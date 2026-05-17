#!/usr/bin/env python3
"""
snEco — МойСклад Data Sync v2
Вивантажує всі ключові дані з МойСклад API і зберігає в Excel-файли.
Запуск: python3 moysklad_sync.py

Надійність даних:
  ✅ ТОЧНІ:     demands (відвантаження), payments (оплати)
  ⚠️ НЕПОВНІ:  supply, processing, processingPlan (собівартість, виробництво)
  ✅ ДОВІРЛИВІ: counterparties, products, customerorders, salesreturn

Вимоги: pip install requests pandas openpyxl python-dotenv
"""

import os
import sys
import json
import requests
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

# Force unbuffered stdout — critical for GitHub Actions where tee buffers print()
# Without this, our progress / SYNC_MODE logs only appear at the end of the run.
try:
    sys.stdout.reconfigure(line_buffering=True, write_through=True)
    sys.stderr.reconfigure(line_buffering=True, write_through=True)
except Exception:
    pass

# ── Конфігурація ──────────────────────────────────────────────────────────────

load_dotenv(Path(__file__).parent / ".env")

TOKEN       = os.getenv("MOYSKLAD_TOKEN")
BASE_URL    = "https://api.moysklad.ru/api/remap/1.2"

# === Incremental sync mode (v2.57) ===========================================
# SYNC_MODE=incremental (default for cron) → читаємо cursor з Worker last-sync,
# беремо лише дані які з'явилися/змінились ПІСЛЯ останнього успішного sync.
# Очікувана економія часу: 90-95% (з 16 хв → ~30-90 секунд).
#
# SYNC_MODE=full → fallback на DATA_WINDOW_DAYS (default 30) — для manual
# workflow_dispatch коли треба повний reload (наприклад після schema зміни).
# ============================================================================
SYNC_MODE   = os.getenv("SYNC_MODE", "incremental").lower()
WORKER_URL  = os.getenv("WORKER_URL", "https://sneco-auth.vg-ab6.workers.dev")
WINDOW_DAYS = int(os.getenv("DATA_WINDOW_DAYS", "30"))
SAFETY_OVERLAP_HOURS = 1   # 1 година overlap на випадок clock drift / late writes

def _get_incremental_cursor():
    """Повертає datetime останнього успішного sync, або None якщо не вдалося."""
    try:
        r = requests.post(
            f"{WORKER_URL}/api/dashboard/last-sync",
            headers={"Content-Type": "application/json"},
            json={}, timeout=10,
        )
        if not r.ok:
            return None
        items = r.json().get("items", [])
        # Шукаємо найновіший SUCCESS run з валідним finished_at
        ok = next(
            (x for x in items if x.get("status") == "success" and x.get("finished_at")),
            None,
        )
        return datetime.fromtimestamp(ok["finished_at"]) if ok else None
    except Exception as e:
        print(f"  ⚠️  Cursor fetch failed: {e}")
        return None

_START_DATE_OVERRIDE = os.getenv("DATA_START_DATE", "").strip()
if SYNC_MODE == "full":
    if _START_DATE_OVERRIDE:
        try:
            _sync_from = datetime.fromisoformat(_START_DATE_OVERRIDE)
            _master_from = _sync_from
            print(f"🔄 SYNC_MODE=full → DATA_START_DATE={_START_DATE_OVERRIDE} ({_sync_from.isoformat()})", flush=True)
        except ValueError:
            print(f"⚠️  DATA_START_DATE='{_START_DATE_OVERRIDE}' invalid ISO, fallback to window_days={WINDOW_DAYS}", flush=True)
            _sync_from = datetime.now() - timedelta(days=WINDOW_DAYS)
            _master_from = datetime.now() - timedelta(days=WINDOW_DAYS)
    else:
        _sync_from = datetime.now() - timedelta(days=WINDOW_DAYS)
        _master_from = datetime.now() - timedelta(days=WINDOW_DAYS)
        print(f"🔄 SYNC_MODE=full → window: last {WINDOW_DAYS} days from {_sync_from.isoformat()}", flush=True)
else:
    _cursor = _get_incremental_cursor()
    if _cursor:
        _sync_from = _cursor - timedelta(hours=SAFETY_OVERLAP_HOURS)
        # Master entities (products/counterparties/processingplans) — 7-day overlap для безпеки
        # на випадок late updates / clock drift / випадково deleted-but-restored entities
        _master_from = _cursor - timedelta(days=7)
        print(f"⚡ SYNC_MODE=incremental → cursor {_cursor.isoformat()}", flush=True)
        print(f"   Transactional from: {_sync_from.isoformat()} (overlap {SAFETY_OVERLAP_HOURS}h)", flush=True)
        print(f"   Master from:        {_master_from.isoformat()} (overlap 7d)", flush=True)
    else:
        _sync_from = datetime.now() - timedelta(days=WINDOW_DAYS)
        _master_from = datetime.now() - timedelta(days=WINDOW_DAYS)
        print(f"⚠️  No prior sync cursor → fallback: last {WINDOW_DAYS} days from {_sync_from.isoformat()}", flush=True)

DATE_FROM = _sync_from.strftime("%Y-%m-%d %H:%M:%S")
DATE_FROM_MASTER = _master_from.strftime("%Y-%m-%d %H:%M:%S")

OUTPUT_DIR  = Path(__file__).parent / "data"
OUTPUT_DIR.mkdir(exist_ok=True)

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Accept-Encoding": "gzip",
}

# ── Утиліти ───────────────────────────────────────────────────────────────────

def fetch_all(endpoint: str, params: dict = None, date_filter: bool = True, expand: str = None,
              filter_field: str = "moment") -> list:
    """Тягне всі записи з пагінацією.

    Args:
        date_filter: якщо True — додає filter за `filter_field` >= DATE_FROM (transactional)
                     або DATE_FROM_MASTER (для master entities з filter_field='updated').
        filter_field: 'moment' (default, для transactional) або 'updated' (для master entities).
                      'updated' працює для всіх MoySklad entities + дозволяє incremental sync
                      master entities (products/counterparties/processingplan/processing).
    """
    url = f"{BASE_URL}/{endpoint}"
    all_rows, offset, limit = [], 0, 1000
    base_params = {"limit": limit}
    if date_filter:
        # Master entities (filter_field='updated') використовують 7-day overlap
        from_str = DATE_FROM_MASTER if filter_field == "updated" else DATE_FROM
        base_params["filter"] = f"{filter_field}>={from_str}"
    if expand:
        base_params["expand"] = expand
    if params:
        base_params.update(params)
    t0 = datetime.now()
    while True:
        base_params["offset"] = offset
        resp = requests.get(url, headers=HEADERS, params=base_params)
        if resp.status_code != 200:
            print(f"  ⚠️  {endpoint} → HTTP {resp.status_code}: {resp.text[:200]}", flush=True)
            break
        data  = resp.json()
        rows  = data.get("rows", [])
        total = data.get("meta", {}).get("size", 0)
        all_rows.extend(rows)
        offset += limit
        print(f"  {endpoint}: {min(offset, total)}/{total}", flush=True)
        if offset >= total:
            break
    elapsed = (datetime.now() - t0).total_seconds()
    if elapsed > 5:
        print(f"    ⏱  {endpoint} took {elapsed:.1f}s · {len(all_rows)} rows", flush=True)
    return all_rows


def fetch_report(endpoint: str, extra_params: dict = None) -> list:
    """Тягне звітні дані (momentFrom/momentTo)."""
    url = f"{BASE_URL}/{endpoint}"
    all_rows, offset, limit = [], 0, 1000
    base_params = {"limit": limit, "momentFrom": DATE_FROM}
    if extra_params:
        base_params.update(extra_params)
    while True:
        base_params["offset"] = offset
        resp = requests.get(url, headers=HEADERS, params=base_params)
        if resp.status_code != 200:
            print(f"  ⚠️  {endpoint} → HTTP {resp.status_code}: {resp.text[:200]}")
            break
        data  = resp.json()
        rows  = data.get("rows", [])
        total = data.get("meta", {}).get("size", 0)
        all_rows.extend(rows)
        offset += limit
        print(f"  {endpoint}: {min(offset, total)}/{total}")
        if offset >= total:
            break
    return all_rows


def safe(val, key="name"):
    if isinstance(val, dict):
        return val.get(key, "")
    return val or ""


def save_excel(df: pd.DataFrame, name: str, reliable: bool = True):
    """Upsert: мержить нові дані з існуючим файлом по колонці 'id' (якщо є)."""
    path = OUTPUT_DIR / f"{name}.xlsx"
    flag = "✅" if reliable else "⚠️ "

    if path.exists() and "id" in df.columns:
        try:
            existing = pd.read_excel(path)
            if "id" in existing.columns:
                # Видаляємо з існуючих ті рядки, що є в нових (оновлені записи)
                existing = existing[~existing["id"].isin(df["id"])]
                # Додаємо нові/оновлені рядки та сортуємо
                merged = pd.concat([existing, df], ignore_index=True)
                if "Дата" in merged.columns:
                    merged = merged.sort_values("Дата").reset_index(drop=True)
                df = merged
                print(f"  {flag} data/{name}.xlsx  ({len(df)} рядків, upsert)")
            else:
                df.to_excel(path, index=False)
                print(f"  {flag} data/{name}.xlsx  ({len(df)} рядків)")
        except Exception as e:
            print(f"  ⚠️  Не вдалось прочитати {name}.xlsx, перезаписую: {e}")
            df.to_excel(path, index=False)
            print(f"  {flag} data/{name}.xlsx  ({len(df)} рядків)")
    else:
        df.to_excel(path, index=False)
        print(f"  {flag} data/{name}.xlsx  ({len(df)} рядків)")

    df.to_excel(path, index=False)


# ── Парсери ───────────────────────────────────────────────────────────────────

def parse_demands(rows):
    records = []
    for r in rows:
        base = {
            "id":               r.get("id"),
            "Дата":             r.get("moment", "")[:10],
            "Номер":            r.get("name"),
            "Контрагент":       safe(r.get("agent")),
            "Контрагент ID":    _extract_id(r.get("agent")),
            "Організація":      safe(r.get("organization")),
            "Склад":            safe(r.get("store")),
            "Сума, грн":        r.get("sum", 0) / 100,
            "ПДВ, грн":         r.get("vatSum", 0) / 100,
            "Знижка, грн":      r.get("discountSum", 0) / 100,
            "Оплачено, грн":    r.get("payedSum", 0) / 100,
            "Стан":             safe(r.get("state")),
            "Проект":           safe(r.get("project")),
            "Канал збуту":      safe(r.get("salesChannel")),
            "Коментар":         r.get("description", ""),
        }
        positions = r.get("positions", {})
        pos_rows  = positions.get("rows", []) if isinstance(positions, dict) else []
        if pos_rows:
            for p in pos_rows:
                rec = base.copy()
                rec["Товар"]            = safe(p.get("assortment"))
                rec["Кількість"]        = p.get("quantity", 0)
                rec["Ціна, грн"]        = p.get("price", 0) / 100
                rec["Сума позиції, грн"]= p.get("sum", 0) / 100
                rec["Знижка %"]         = p.get("discount", 0)
                records.append(rec)
        else:
            records.append(base)
    return records


def parse_customerorders(rows):
    records = []
    for r in rows:
        base = {
            "id":                   r.get("id"),
            "Дата":                 r.get("moment", "")[:10],
            "Номер":                r.get("name"),
            "Контрагент":           safe(r.get("agent")),
            "Контрагент ID":        _extract_id(r.get("agent")),
            "Організація":          safe(r.get("organization")),
            "Сума, грн":            r.get("sum", 0) / 100,
            "Оплачено, грн":        r.get("payedSum", 0) / 100,
            "Відвантажено, грн":    r.get("shippedSum", 0) / 100,
            "Стан":                 safe(r.get("state")),
            "Проект":               safe(r.get("project")),
            "Канал збуту":          safe(r.get("salesChannel")),
            "Коментар":             r.get("description", ""),
        }
        positions = r.get("positions", {})
        pos_rows  = positions.get("rows", []) if isinstance(positions, dict) else []
        if pos_rows:
            for p in pos_rows:
                rec = base.copy()
                rec["Товар"]     = safe(p.get("assortment"))
                rec["Кількість"] = p.get("quantity", 0)
                rec["Ціна, грн"] = p.get("price", 0) / 100
                records.append(rec)
        else:
            records.append(base)
    return records


def parse_salesreturns(rows):
    records = []
    for r in rows:
        base = {
            "id":           r.get("id"),
            "Дата":         r.get("moment", "")[:10],
            "Номер":        r.get("name"),
            "Контрагент":   safe(r.get("agent")),
            "Контрагент ID": _extract_id(r.get("agent")),
            "Склад":        safe(r.get("store")),
            "Сума, грн":    r.get("sum", 0) / 100,
            "Стан":         safe(r.get("state")),
            "Коментар":     r.get("description", ""),
        }
        positions = r.get("positions", {})
        pos_rows  = positions.get("rows", []) if isinstance(positions, dict) else []
        if pos_rows:
            for p in pos_rows:
                rec = base.copy()
                rec["Товар"]     = safe(p.get("assortment"))
                rec["Кількість"] = p.get("quantity", 0)
                rec["Ціна, грн"] = p.get("price", 0) / 100
                records.append(rec)
        else:
            records.append(base)
    return records


def parse_counterparties(rows):
    return [{
        "id":                   r.get("id"),
        "Назва":                r.get("name"),
        "Повна назва":          r.get("legalTitle", "") or r.get("name", ""),
        "Тип":                  r.get("companyType"),
        "Код":                  r.get("code"),
        "ЄДРПОУ/ІНН":          r.get("inn"),
        "Телефон":              r.get("phone"),
        "Факс":                 r.get("fax", ""),
        "Email":                r.get("email"),
        "Юр.адреса":            r.get("legalAddress", ""),
        "Юр.адреса коментар":   r.get("legalAddressFull", "")
                                or r.get("legalAddress", ""),
        "Факт.адреса":          r.get("actualAddress", ""),
        "Теги":                 ", ".join(r.get("tags", [])),
        "Баланс, грн":          (r.get("balance", 0) / 100) if r.get("balance") else 0,
        "Борг прострочений":    (r.get("overdueDebt", 0) / 100) if r.get("overdueDebt") else 0,
        "Статус":               safe(r.get("state")),
        "Коментар":             r.get("description", ""),
    } for r in rows]


SEE_NEXT_FILE_NOTE = "This is just placeholder; never executed"
