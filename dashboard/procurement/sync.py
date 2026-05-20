#!/usr/bin/env python3
"""
snEco · Procurement Sync · production-grade
Тягне з МойСклад → batch POST у Worker /api/dashboard/ingest → D1 tables proc_*.

v2 (2026-05-19): + ThreadPoolExecutor для positions fetch (8x паралельності).
Раніше: ~50 хв на 2288 processings. Тепер: ~5-8 хв.

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
RATE_LIMIT_SLEEP = 0.05   # secs between МС requests (зменшено з 0.1 — є retry для 429)
INGEST_TIMEOUT = 60
PARALLEL_WORKERS = 8       # v2: parallel positions fetch

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


# ─── МойСклад fetchers ──────────────────────────────────────────────────────

def ms_get(url: str, params: Optional[dict] = None, session: Optional[requests.Session] = None) -> dict:
    """Single GET with retry/backoff. v2: optional session для connection reuse."""
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
    """v2: worker для ThreadPoolExecutor. Returns (pid, kind, positions, error)."""
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


# ─── Row builders ───────────────────────────────────────────────────────────

def build_processing_row(p: dict) -> dict:
    return {
        "id": p["id"],
        "ms_moment": p.get("moment"),
        "name": p.get("name"),
        "organization_id": extract_id(p.get("organization")),
        "organization": safe_name(p.get("organization")),
        "processing_plan_id": extract_id(p.get("processingPlan")),
        "processing_plan_name": safe_name(p.get("processingPlan")),
        "quantity": p.get("quantity", 0),
        "processing_sum_kop": to_kop(p.get("processingSum", 0)),
        "applicable": 1 if p.get("applicable", True) else 0,
        "updated_at": p.get("updated"),
        "raw_json": json.dumps(p, ensure_ascii=False),
    }


def build_position_rows(processing_id: str, positions: list, side: str) -> list:
    rows = []
    for pos in positions:
        pos_id = pos.get("id") or extract_id(pos.get("meta", {})) or ""
        rows.append({
            "id": f"{processing_id}:{side}:{pos_id}" if pos_id else f"{processing_id}:{side}:{len(rows)}",
            "processing_id": processing_id,
            "position_id": pos_id,
            "assortment_id": extract_id(pos.get("assortment")) or "",
            "quantity": pos.get("quantity", 0),
            "price_kop": to_kop(pos.get("price", 0)),
            "raw_json": json.dumps(pos, ensure_ascii=False),
        })
    return rows


def build_stock_row(s: dict, snapshot_at: str) -> dict:
    aid = extract_id(s)
    folder = s.get("folder") or {}
    uom = s.get("uom") or {}
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
        "price_kop": to_kop(s.get("price", 0)),
        "sale_price_kop": to_kop(s.get("salePrice", 0)),
        "stock_days": s.get("stockDays", 0),
        "snapshot_at": snapshot_at,
        "raw_json": json.dumps(s, ensure_ascii=False),
    }


# ─── Main sync ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true",
                        help="Full year 2026 (default: last 7 days)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch + print, do not POST to Worker")
    parser.add_argument("--trigger", default="manual",
                        choices=["manual", "cron", "webhook"])
    args = parser.parse_args()

    if not MS_TOKEN:
        print("❌ MOYSKLAD_TOKEN missing", file=sys.stderr); sys.exit(2)
    if not SYNC_API_KEY and not args.dry_run:
        print("❌ SYNC_API_KEY missing", file=sys.stderr); sys.exit(2)

    started = int(time.time())
    started_iso = datetime.now(timezone.utc).isoformat()
    print(f"🚀 Procurement sync · {started_iso} · {'FULL' if args.full else 'incremental(7d)'}{' · DRY-RUN' if args.dry_run else ''}", flush=True)

    if args.full:
        date_from = f"{YEAR}-01-01 00:00:00"
        date_to = f"{YEAR}-12-31 23:59:59"
    else:
        d_from = datetime.now() - timedelta(days=7)
        date_from = d_from.strftime("%Y-%m-%d 00:00:00")
        date_to = datetime.now().strftime("%Y-%m-%d 23:59:59")

    # ─── 1. Processings ────────────────────────────────────────────────────
    print(f"\n[1/4] Processings ({date_from} → {date_to})…", flush=True)
    processings = ms_fetch_paginated(
        "entity/processing",
        {"filter": f"moment>={date_from};moment<={date_to}"}
    )
    print(f"      → {len(processings)} processings", flush=True)

    proc_rows = [build_processing_row(p) for p in processings]

    # ─── 2. Positions (parallel) ───────────────────────────────────────────
    print(f"\n[2/4] Positions for {len(processings)} processings (parallel × {PARALLEL_WORKERS})…", flush=True)
    mat_rows, prod_rows = [], []
    pos_errors = []

    if processings:
        with ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as executor:
            session = requests.Session()
            tasks = []
            for p in processings:
                pid = p["id"]
                tasks.append(executor.submit(_fetch_processing_positions, pid, "materials", session))
                tasks.append(executor.submit(_fetch_processing_positions, pid, "products", session))

            done_count = 0
            total_tasks = len(tasks)
            t_phase = time.time()
            for future in as_completed(tasks):
                pid, kind, positions, err = future.result()
                if err:
                    pos_errors.append(f"{pid[:8]} {kind}: {err}")
                else:
                    target = mat_rows if kind == "materials" else prod_rows
                    target.extend(build_position_rows(pid, positions, kind[:-1]))
                done_count += 1
                if done_count % 100 == 0 or done_count == total_tasks:
                    elapsed = time.time() - t_phase
                    rate = done_count / elapsed if elapsed else 0
                    eta = (total_tasks - done_count) / rate if rate else 0
                    print(f"      {done_count}/{total_tasks} ({rate:.1f}/s, ETA {eta:.0f}s)", flush=True)
            session.close()

    print(f"      → {len(mat_rows)} material positions, {len(prod_rows)} product positions, {len(pos_errors)} errors", flush=True)

    # ─── 3. Stock snapshot ──────────────────────────────────────────────────
    print(f"\n[3/4] Stock report…", flush=True)
    stock_raw = ms_fetch_paginated("report/stock/all")
    snapshot_iso = datetime.now(timezone.utc).isoformat()
    stock_rows = [build_stock_row(s, snapshot_iso) for s in stock_raw]
    print(f"      → {len(stock_rows)} stock items", flush=True)

    # ─── 4. Ingest into Worker ──────────────────────────────────────────────
    print(f"\n[4/4] Ingesting to Worker…", flush=True)
    counts = {}
    errors = list(pos_errors)
    try:
        counts["processings"] = ingest_batched("processings", proc_rows, args.dry_run)
    except Exception as e:
        errors.append(f"processings: {e}")
    try:
        counts["processing_materials"] = ingest_batched("processing_materials", mat_rows, args.dry_run)
    except Exception as e:
        errors.append(f"processing_materials: {e}")
    try:
        counts["processing_products"] = ingest_batched("processing_products", prod_rows, args.dry_run)
    except Exception as e:
        errors.append(f"processing_products: {e}")
    try:
        counts["stocks"] = ingest_batched("stocks", stock_rows, args.dry_run)
    except Exception as e:
        errors.append(f"stocks: {e}")

    finished = int(time.time())
    duration = (finished - started) * 1000
    status = "success" if not errors else ("partial" if any(counts.values()) else "failed")

    log = {
        "started_at": started_iso,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "trigger": args.trigger,
        "status": status,
        "entities": counts,  # v2: name matches Worker (раніше було entities_json)
        "errors": errors if errors else None,
        "duration_ms": duration,
    }
    if not args.dry_run:
        try:
            post_sync_log(log)
            print(f"📝 sync_log → ms_sync_log", flush=True)
        except Exception as e:
            print(f"⚠ failed to write sync_log: {e}")

    total = sum(counts.values())
    print(f"\n🎯 Done · {total} rows · {len(errors)} errors · {duration/1000:.1f}s · status={status}", flush=True)
    sys.exit(0 if status == "success" else 1)


if __name__ == "__main__":
    main()
