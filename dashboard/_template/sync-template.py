#!/usr/bin/env python3
"""
sync-template.py — снеко-стандарт для GitHub Actions cron sync.

Викачує дані з МойСклад (або іншого джерела) → batch POST до Worker /api/dashboard/ingest.

Перед використанням:
1. Скопіюй у dashboard/<your-domain>/sync.py
2. Заміни <DOMAIN>, <BLOCK_NAME>, <TABLE_PREFIX>
3. Заповни ENTITIES і логіку трансформації
4. Перевір локально: `python sync.py --dry-run`
5. Зайди у repo Settings → Secrets → перевір що MOYSKLAD_TOKEN + SYNC_API_KEY є
"""

import os
import sys
import time
import json
import argparse
from datetime import datetime, timezone
from typing import Any, Dict, List

import requests
from dotenv import load_dotenv

# ─── Config ───────────────────────────────────────────────────────────────────
load_dotenv()

WORKER_URL       = os.getenv('WORKER_URL', 'https://sneco-auth.vg-ab6.workers.dev')
SYNC_API_KEY     = os.getenv('SYNC_API_KEY')
MOYSKLAD_TOKEN   = os.getenv('MOYSKLAD_TOKEN')
BLOCK_NAME       = '<BLOCK_NAME>'   # e.g. 'payroll-dashboard'
TABLE_PREFIX     = '<TABLE_PREFIX>' # e.g. 'pay'

if not SYNC_API_KEY:
    print('❌ SYNC_API_KEY missing in .env or env vars', file=sys.stderr)
    sys.exit(1)
if not MOYSKLAD_TOKEN:
    print('❌ MOYSKLAD_TOKEN missing', file=sys.stderr)
    sys.exit(1)

MS_BASE = 'https://api.moysklad.ru/api/remap/1.2'
MS_HEADERS = {
    'Authorization': f'Bearer {MOYSKLAD_TOKEN}',
    'Accept': 'application/json;charset=utf-8',
    'Accept-Encoding': 'gzip',
}

# Які entity витягуємо з МойСклад → у яку D1-таблицю писати
# Приклад для payroll: employees → pay_employees, pay_calculations → pay_pays
ENTITIES = [
    # ('moysklad_endpoint', 'd1_table_name', extract_fn)
    # ('entity/employee',    f'{TABLE_PREFIX}_employees', extract_employees),
    # ('entity/processingplan', f'{TABLE_PREFIX}_processes', extract_processes),
]

BATCH_SIZE = 500  # rows per /api/dashboard/ingest POST


# ─── МойСклад fetcher with retry ──────────────────────────────────────────────
def ms_fetch(path: str, params: Dict[str, Any] = None, max_retries: int = 5) -> List[Dict[str, Any]]:
    """Page through МойСклад endpoint, returning all rows."""
    all_rows = []
    offset = 0
    limit = 1000
    while True:
        p = {'limit': limit, 'offset': offset}
        if params:
            p.update(params)
        url = f'{MS_BASE}/{path}'
        for attempt in range(max_retries):
            try:
                r = requests.get(url, headers=MS_HEADERS, params=p, timeout=60)
                if r.status_code == 429:
                    wait = 2 ** attempt
                    print(f'  ⚠ rate-limited, sleeping {wait}s')
                    time.sleep(wait); continue
                r.raise_for_status()
                break
            except requests.HTTPError as e:
                if attempt == max_retries - 1:
                    raise
                print(f'  ⚠ {e}, retry {attempt+1}/{max_retries}')
                time.sleep(2 ** attempt)
        data = r.json()
        rows = data.get('rows', [])
        if not rows:
            break
        all_rows.extend(rows)
        if len(rows) < limit:
            break
        offset += limit
        print(f'  fetched {len(all_rows)} from {path}')
    return all_rows


# ─── Worker ingest ────────────────────────────────────────────────────────────
def ingest_batch(table: str, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """POST rows to Worker /api/dashboard/ingest."""
    if not rows:
        return {'inserted': 0}
    r = requests.post(
        f'{WORKER_URL}/api/dashboard/ingest',
        headers={
            'Authorization': f'Bearer {SYNC_API_KEY}',
            'Content-Type': 'application/json',
        },
        json={'block': BLOCK_NAME, 'table': table, 'rows': rows},
        timeout=120,
    )
    if not r.ok:
        print(f'❌ ingest failed: {r.status_code} {r.text[:200]}', file=sys.stderr)
        r.raise_for_status()
    return r.json()


def chunked(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i+size]


# ─── Domain-specific extractors (REPLACE with your logic) ─────────────────────
# def extract_employees(row: Dict[str, Any]) -> Dict[str, Any]:
#     """Map МойСклад employee → row for pay_employees table."""
#     return {
#         'id':        row.get('id'),
#         'name':      row.get('name'),
#         'email':     row.get('email'),
#         'department': row.get('group', {}).get('meta', {}).get('href', '').split('/')[-1],
#         'archived':  bool(row.get('archived')),
#         'updated':   row.get('updated'),
#     }


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', help='Fetch but do not POST')
    args = parser.parse_args()

    started = datetime.now(timezone.utc).isoformat()
    print(f'🟢 sync.py started at {started}')
    print(f'   block={BLOCK_NAME} prefix={TABLE_PREFIX}')

    summary = {}

    for ms_path, d1_table, extract_fn in ENTITIES:
        print(f'\n📥 {ms_path} → {d1_table}')
        raw = ms_fetch(ms_path)
        rows = [extract_fn(r) for r in raw]
        print(f'   transformed {len(rows)} rows')

        if args.dry_run:
            print(f'   [dry-run] skipping ingest')
            summary[d1_table] = len(rows)
            continue

        inserted = 0
        for batch in chunked(rows, BATCH_SIZE):
            res = ingest_batch(d1_table, batch)
            inserted += res.get('inserted', len(batch))
        print(f'   ✓ inserted {inserted} into {d1_table}')
        summary[d1_table] = inserted

    print('\n═══════════════════════════════════════════════')
    print('Summary:')
    for t, n in summary.items():
        print(f'  {t}: {n}')
    print('═══════════════════════════════════════════════')

    # Write to last-sync metadata
    if not args.dry_run:
        try:
            requests.post(
                f'{WORKER_URL}/api/dashboard/ingest',
                headers={'Authorization': f'Bearer {SYNC_API_KEY}', 'Content-Type': 'application/json'},
                json={
                    'block': BLOCK_NAME,
                    'table': f'{TABLE_PREFIX}_sync_log',
                    'rows': [{
                        'started_at': started,
                        'finished_at': datetime.now(timezone.utc).isoformat(),
                        'summary_json': json.dumps(summary),
                        'success': True,
                    }],
                },
                timeout=30,
            )
        except Exception as e:
            print(f'⚠ failed to write sync log: {e}')


if __name__ == '__main__':
    main()
