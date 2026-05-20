#!/usr/bin/env python3
"""
snEco · Procurement Sync · production-grade
Тягне з МойСклад → batch POST у Worker /api/dashboard/ingest → D1 tables ms_*.

v4 (2026-05-20): + multi-currency (EUR/USD конверсія). sum_kop тепер ЗАВЖДИ у UAH;
                  оригінал — у *_orig_kop колонках.
v3 (2026-05-20): + second-pass retry для failed positions + tolerant status (< 2% = success).
v2 (2026-05-19): + ThreadPoolExecutor для positions fetch (8x паралельності).

Запуск:
    python3 sync.py                  # incremental (last 7 days)
    python3 sync.py --full           # повний 2026 рік
    python3 sync.py --dry-run        # без write, тільки fetch + print summary

Env (required):
    MOYSKLAD_TOKEN          з .env або GitHub Secret
    SYNC_API_KEY            з .env або GitHub Secret
    WORKER_URL              default https://sneco-auth.vg-ab6.workers.dev
"""

import argparse
import json
import os
import sys
import time
import traceback
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(ROOT / ".env")

WORKER_URL = os.getenv("WORKER_URL", "https://sneco-auth.vg-ab6.workers.dev").rstrip("/")
SYNC_API_KEY = os.getenv("SYNC_API_KEY")
MS_TOKEN = os.getenv("MOYSKLAD_TOKEN")

MS_BASE = "https://api.moysklad.ru/api/remap/1.2"
MS_HEADERS = {
    "Authorization": f"Bearer {MS_TOKEN}" if MS_TOKEN else "",
    "Accept": "application/json;charset=utf-8",
    "Accept-Encoding": "gzip",
}

BATCH_SIZE = 400
MAX_RETRIES = 5
RATE_LIMIT_SLEEP = 0.05
INGEST_TIMEOUT = 60
PARALLEL_WORKERS = 8

STATUS_SUCCESS_THRESHOLD = 0.02
STATUS_PARTIAL_THRESHOLD = 0.20

YEAR = 2026


# ─── Helpers ────────────────────────────────────────────────────────────────

def extract_id(field) -> Optional[str]:
    if not isinstance(field, dict):
        return None
    if "id" in field:
        return field["id"]
    href = field.get("meta", {}).get("href", "")
    if not href:
        return None
    return href.rsplit("/", 1)[-1].split("?")[0]


def safe_name(obj, default="") -> str:
    if isinstance(obj, dict):
        return obj.get("name", default) or default
    return default


def to_kop(value, default=0) -> int:
    if value is None:
        return default
    return int(round(float(value)))


# ─── Multi-currency (v4) ────────────────────────────────────────────────────

def _fetch_currency_map() -> Dict[str, str]:
    """v4: тягне всі currency з МойСклад → href → isoCode (UAH/EUR/USD)."""
    href_map = {}
    try:
        r = requests.get(f"{MS_BASE}/entity/currency",
                         headers=MS_HEADERS,
                         params={"limit": 1000},
                         timeout=30)
        if r.status_code != 200:
            print(f"  ⚠ currency lookup HTTP {r.status_code} → all docs default to UAH", flush=True)
            return href_map
        for row in r.json().get("rows", []):
            href = (row.get("meta") or {}).get("href", "")
            iso = row.get("isoCode") or row.get("name", "")
            if href and iso:
                href_map[href] = iso
    except Exception as e:
        print(f"  ⚠ currency map fetch error: {e}", flush=True)
    print(f"  💱 currency map: {len(href_map)} валют", flush=True)
    return href_map


def _extract_rate(doc: dict, currency_map: Dict[str, str]) -> tuple:
    """v4: повертає (iso_code, rate_to_uah) з MoySklad документа.
    rate.value відсутній або 0 → UAH default (1.0).
    """
    rate_obj = doc.get("rate") or {}
    rate_val = rate_obj.get("value")
    cur_href = ((rate_obj.get("currency") or {}).get("meta") or {}).get("href", "")

    iso = currency_map.get(cur_href, "UAH")
    rate = float(rate_val) if (rate_val and rate_val > 0) else 1.0
    return iso, rate


# ─── МойСклад fetchers ──────────────────────────────────────────────────────

def ms_get(url: str, params: Optional[dict] = None, session: Optional[requests.Session] = None) -> dict:
    s = session or requests
    for attempt in range(MAX_RETRIES):
        try:
            r = s.get(url, headers=MS_HEADERS, params=params, timeout=60)
            if r.status_code == 429:
                wait = 2 ** attempt
                time.sleep(wait)
                continue
            r.raise_for_status()
            time.sleep(RATE_LIMIT_SLEEP)
            return r.json()
        except requests.RequestException as e:
            if attempt == MAX_RETRIES - 1:
                raise
            time.sleep(2 ** attempt)


def ms_fetch_paginated(endpoint: str, extra_params: Optional[dict] = None, session: Optional[requests.Session] = None) -> List[dict]:
    rows, offset, limit = [], 0, 1000
    while True:
        params = {"limit": limit, "offset": offset}
        if extra_params:
            params.update(extra_params)
        d = ms_get(f"{MS_BASE}/{endpoint}", params=params, session=session)
        rows.extend(d.get("rows", []))
        total = d.get("meta", {}).get("size", 0)
        offset += limit
        if offset >= total:
            break
    return rows


def _fetch_processing_positions(pid: str, kind: str, session: requests.Session) -> tuple:
    try:
        positions = ms_fetch_paginated(f"entity/processing/{pid}/{kind}", session=session)
        return (pid, kind, positions, None)
    except Exception as e:
        return (pid, kind, [], str(e))


# ─── Ingest to Worker ───────────────────────────────────────────────────────

def post_batch(entity: str, rows: list) -> dict:
    if not rows:
        return {"inserted": 0}
    url = f"{WORKER_URL}/api/dashboard/ingest"
    payload = {"entity": entity, "rows": rows}
    r = requests.post(
        url,
        json=payload,
        headers={"X-Sync-Key": SYNC_API_KEY, "Origin": "https://dreamcarua.github.io"},
        timeout=INGEST_TIMEOUT,
    )
    if not r.ok:
        sample = rows[0] if rows else None
        print(f"  ⚠ ingest {entity} HTTP {r.status_code}: {r.text[:500]}", file=sys.stderr)
        print(f"     sample row: {json.dumps(sample, ensure_ascii=False)[:400]}", file=sys.stderr)
        r.raise_for_status()
    return r.json()


def post_sync_log(log: dict):
    url = f"{WORKER_URL}/api/dashboard/ingest"
    r = requests.post(
        url,
        json={"sync_log": log},
        headers={"X-Sync-Key": SYNC_API_KEY, "Origin": "https://dreamcarua.github.io"},
        timeout=15,
    )
    if not r.ok:
        print(f"  ⚠ sync_log HTTP {r.status_code}: {r.text[:300]}", file=sys.stderr)


def ingest_batched(entity: str, rows: list, dry_run: bool = False) -> int:
    if dry_run:
        print(f"  [dry-run] would ingest {len(rows)} rows as '{entity}'")
        return len(rows)
    sent = 0
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        resp = post_batch(entity, batch)
        sent += resp.get("inserted", len(batch))
        print(f"    {entity}: {sent}/{len(rows)} ingested", flush=True)
    return sent


# ─── Row builders (v4: multi-currency) ─────────────────────────────────────

def build_processing_row(p: dict, currency_map: dict) -> dict:
    """v4: + currency, rate_to_uah, processing_sum_orig_kop."""
    iso, rate = _extract_rate(p, currency_map)
    sum_orig_kop = to_kop(p.get("processingSum", 0))    # у валюті документа
    sum_uah_kop = int(round(sum_orig_kop * rate))        # нормалізовано в UAH
    return {
        "id": p["id"],
        "ms_moment": p.get("moment"),
        "name": p.get("name"),
        "organization_id": extract_id(p.get("organization")),
        "organization": safe_name(p.get("organization")),
        "processing_plan_id": extract_id(p.get("processingPlan")),
        "processing_plan_name": safe_name(p.get("processingPlan")),
        "quantity": p.get("quantity", 0),
        "processing_sum_kop": sum_uah_kop,
        "applicable": 1 if p.get("applicable", True) else 0,
        "updated_at": p.get("updated"),
        # v4: multi-currency
        "currency": iso,
        "rate_to_uah": rate,
        "processing_sum_orig_kop": sum_orig_kop,
        "raw_json": json.dumps(p, ensure_ascii=False),
    }


def build_position_rows(processing_id: str, positions: list, side: str,
                         parent_currency: str = "UAH", parent_rate: float = 1.0) -> list:
    """v4: + parent's currency/rate (positions не мають власної). price_uah = price_orig × rate."""
    rows = []
    for pos in positions:
        pos_id = pos.get("id") or extract_id(pos.get("meta", {})) or ""
        price_orig_kop = to_kop(pos.get("price", 0))
        price_uah_kop = int(round(price_orig_kop * parent_rate))
        rows.append({
            "id": f"{processing_id}:{side}:{pos_id}" if pos_id else f"{processing_id}:{side}:{len(rows)}",
            "processing_id": processing_id,
            "position_id": pos_id,
            "assortment_id": extract_id(pos.get("assortment")) or "",
            "quantity": pos.get("quantity", 0),
            "price_kop": price_uah_kop,
            # v4: multi-currency (inherited from parent)
            "currency": parent_currency,
            "rate_to_uah": parent_rate,
            "price_orig_kop": price_orig_kop,
            "raw_json": json.dumps(pos, ensure_ascii=False),
        })
    return rows


def build_stock_row(s: dict, snapshot_at: str, currency_map: dict) -> dict:
    """v4: + currency, rate_to_uah, price_orig_kop, sale_price_orig_kop.
    Stock items зазвичай не мають власної валюти (assortment level),
    тому фолбек на UAH/1.0 якщо немає rate."""
    iso, rate = _extract_rate(s, currency_map)
    aid = extract_id(s)
    folder = s.get("folder") or {}
    uom = s.get("uom") or {}
    price_orig_kop = to_kop(s.get("price", 0))
    sale_price_orig_kop = to_kop(s.get("salePrice", 0))
    return {
        "assortment_id": aid or "",
        "name": s.get("name"),
        "code": s.get("code"),
        "article": s.get("article"),
        "folder_name": folder.get("name"),
        "folder_path": (folder.get("pathName") or "") + ("/" + folder.get("name", "") if folder.get("name") else ""),
        "uom_name": uom.get("name"),
        "stock": s.get("stock", 0),
        "in_transit": s.get("inTransit", 0),
        "reserve": s.get("reserve", 0),
        "quantity": s.get("quantity", 0),
        "price_kop": int(round(price_orig_kop * rate)),
        "sale_price_kop": int(round(sale_price_orig_kop * rate)),
        "stock_days": s.get("stockDays", 0),
        "snapshot_at": snapshot_at,
        # v4: multi-currency
        "currency": iso,
        "rate_to_uah": rate,
        "price_orig_kop": price_orig_kop,
        "sale_price_orig_kop": sale_price_orig_kop,
        "raw_json": json.dumps(s, ensure_ascii=False),
    }


# ─── Main sync ──────────────────────────────────────────────────────────────

def fetch_positions_parallel(processings: List[dict], currency_map: dict) -> tuple:
    """v4: positions inherit parent's currency/rate."""
    mat_rows, prod_rows = [], []
    failed_tasks = []
    total_tasks = len(processings) * 2

    if not processings:
        return mat_rows, prod_rows, [], 0, 0

    # Build parent_id → (currency, rate) map для inheritance
    parent_currency = {}
    parent_rate = {}
    for p in processings:
        iso, rate = _extract_rate(p, currency_map)
        parent_currency[p["id"]] = iso
        parent_rate[p["id"]] = rate

    # ─── Pass 1: parallel ───
    print(f"      Pass 1 — parallel × {PARALLEL_WORKERS}…", flush=True)
    with ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as executor:
        session = requests.Session()
        tasks = []
        for p in processings:
            pid = p["id"]
            tasks.append(executor.submit(_fetch_processing_positions, pid, "materials", session))
            tasks.append(executor.submit(_fetch_processing_positions, pid, "products", session))

        done_count = 0
        t_phase = time.time()
        for future in as_completed(tasks):
            pid, kind, positions, err = future.result()
            if err:
                failed_tasks.append((pid, kind))
            else:
                target = mat_rows if kind == "materials" else prod_rows
                target.extend(build_position_rows(
                    pid, positions, kind[:-1],
                    parent_currency=parent_currency.get(pid, "UAH"),
                    parent_rate=parent_rate.get(pid, 1.0),
                ))
            done_count += 1
            if done_count % 100 == 0 or done_count == total_tasks:
                elapsed = time.time() - t_phase
                rate_per_sec = done_count / elapsed if elapsed else 0
                eta = (total_tasks - done_count) / rate_per_sec if rate_per_sec else 0
                print(f"      {done_count}/{total_tasks} ({rate_per_sec:.1f}/s, ETA {eta:.0f}s)", flush=True)
        session.close()

    print(f"      Pass 1 done: {total_tasks - len(failed_tasks)}/{total_tasks} ok, {len(failed_tasks)} failed", flush=True)

    # ─── Pass 2: sequential retry ───
    recovered = 0
    if failed_tasks:
        print(f"      Pass 2 — sequential retry для {len(failed_tasks)} failed…", flush=True)
        session = requests.Session()
        still_failed = []
        for pid, kind in failed_tasks:
            time.sleep(0.5)
            pid2, kind2, positions, err = _fetch_processing_positions(pid, kind, session)
            if err:
                still_failed.append((pid, kind))
            else:
                target = mat_rows if kind == "materials" else prod_rows
                target.extend(build_position_rows(
                    pid, positions, kind[:-1],
                    parent_currency=parent_currency.get(pid, "UAH"),
                    parent_rate=parent_rate.get(pid, 1.0),
                ))
                recovered += 1
        session.close()
        print(f"      Pass 2 done: recovered {recovered}/{len(failed_tasks)}, still failed: {len(still_failed)}", flush=True)
        failed_tasks = still_failed

    return mat_rows, prod_rows, failed_tasks, total_tasks, recovered


def determine_status(failed_count: int, total_tasks: int, ingest_errors: list) -> tuple:
    if ingest_errors:
        return ("failed", 100.0)
    if total_tasks == 0:
        return ("success", 0.0)
    loss_pct = (failed_count / total_tasks) * 100
    if failed_count == 0 or (loss_pct / 100) < STATUS_SUCCESS_THRESHOLD:
        return ("success", loss_pct)
    elif (loss_pct / 100) < STATUS_PARTIAL_THRESHOLD:
        return ("partial", loss_pct)
    else:
        return ("failed", loss_pct)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--trigger", default="manual", choices=["manual", "cron", "webhook"])
    args = parser.parse_args()

    if not MS_TOKEN:
        print("❌ MOYSKLAD_TOKEN missing", file=sys.stderr); sys.exit(2)
    if not SYNC_API_KEY and not args.dry_run:
        print("❌ SYNC_API_KEY missing", file=sys.stderr); sys.exit(2)

    started = int(time.time())
    started_iso = datetime.now(timezone.utc).isoformat()
    print(f"🚀 Procurement sync v4 (multi-currency) · {started_iso} · {'FULL' if args.full else 'incremental(7d)'}{' · DRY-RUN' if args.dry_run else ''}", flush=True)

    # v4: currency map ОБОВ'ЯЗКОВО на старті
    currency_map = _fetch_currency_map()

    if args.full:
        date_from = f"{YEAR}-01-01 00:00:00"
        date_to = f"{YEAR}-12-31 23:59:59"
    else:
        d_from = datetime.now() - timedelta(days=7)
        date_from = d_from.strftime("%Y-%m-%d 00:00:00")
        date_to = datetime.now().strftime("%Y-%m-%d 23:59:59")

    print(f"\n[1/4] Processings ({date_from} → {date_to})…", flush=True)
    processings = ms_fetch_paginated(
        "entity/processing",
        {"filter": f"moment>={date_from};moment<={date_to}"}
    )
    print(f"      → {len(processings)} processings", flush=True)

    # v4: build_processing_row тепер потребує currency_map
    proc_rows = [build_processing_row(p, currency_map) for p in processings]

    print(f"\n[2/4] Positions for {len(processings)} processings…", flush=True)
    mat_rows, prod_rows, failed_tasks, total_tasks, recovered = fetch_positions_parallel(processings, currency_map)

    loss_pct = (len(failed_tasks) / total_tasks * 100) if total_tasks else 0
    print(f"      → {len(mat_rows)} material positions, {len(prod_rows)} product positions", flush=True)
    print(f"      → {len(failed_tasks)} STILL failed after retry ({loss_pct:.2f}% loss), recovered {recovered}", flush=True)

    print(f"\n[3/4] Stock report…", flush=True)
    stock_raw = ms_fetch_paginated("report/stock/all")
    snapshot_iso = datetime.now(timezone.utc).isoformat()
    # v4: build_stock_row теж тепер потребує currency_map
    stock_rows = [build_stock_row(s, snapshot_iso, currency_map) for s in stock_raw]
    print(f"      → {len(stock_rows)} stock items", flush=True)

    print(f"\n[4/4] Ingesting to Worker…", flush=True)
    counts = {}
    ingest_errors = []
    try:
        counts["processings"] = ingest_batched("processings", proc_rows, args.dry_run)
    except Exception as e:
        ingest_errors.append(f"processings: {e}")
    try:
        counts["processing_materials"] = ingest_batched("processing_materials", mat_rows, args.dry_run)
    except Exception as e:
        ingest_errors.append(f"processing_materials: {e}")
    try:
        counts["processing_products"] = ingest_batched("processing_products", prod_rows, args.dry_run)
    except Exception as e:
        ingest_errors.append(f"processing_products: {e}")
    try:
        counts["stocks"] = ingest_batched("stocks", stock_rows, args.dry_run)
    except Exception as e:
        ingest_errors.append(f"stocks: {e}")

    finished = int(time.time())
    duration = (finished - started) * 1000

    status, loss_pct_final = determine_status(len(failed_tasks), total_tasks, ingest_errors)

    all_errors = []
    if failed_tasks:
        all_errors.extend([f"position fetch: {pid[:8]} {kind}" for pid, kind in failed_tasks[:10]])
        if len(failed_tasks) > 10:
            all_errors.append(f"... +{len(failed_tasks)-10} more")
    all_errors.extend(ingest_errors)

    log = {
        "started_at": started_iso,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "trigger": args.trigger,
        "status": status,
        "entities": counts,
        "errors": all_errors if all_errors else None,
        "duration_ms": duration,
        "loss_pct": round(loss_pct_final, 2),
        "recovered_count": recovered,
    }
    if not args.dry_run:
        try:
            post_sync_log(log)
            print(f"📝 sync_log → ms_sync_log", flush=True)
        except Exception as e:
            print(f"⚠ failed to write sync_log: {e}")

    total = sum(counts.values())
    print(f"\n🎯 Done · {total} rows · {len(failed_tasks)} failed pos ({loss_pct_final:.2f}%) · {len(ingest_errors)} ingest errors · {duration/1000:.1f}s · status={status}", flush=True)

    sys.exit(0 if status in ("success", "partial") else 1)


if __name__ == "__main__":
    main()
