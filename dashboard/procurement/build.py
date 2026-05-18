#!/usr/bin/env python3
"""
snEco — Procurement / Planning Dashboard

Аналізує processing-операції за 2026: скільки свіжого сиру спожито,
скільки сушеного сиру вироблено, скільки упаковки і гофротари витрачено,
скільки готових пачок зібрано (по смаках), і скільки днів вистачить
поточних залишків при поточному темпі споживання.

Запуск:
    cd ~/snEco-brand-book
    source .venv/bin/activate
    python3 dashboard/procurement/build.py            # повний цикл
    python3 dashboard/procurement/build.py --skip-fetch  # тільки агрегація+HTML
    python3 dashboard/procurement/build.py --no-cache    # форсувати re-fetch
"""

import json
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

# ─── Setup ───────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(ROOT / ".env")
TOKEN = os.getenv("MOYSKLAD_TOKEN")
if not TOKEN:
    print("❌ MOYSKLAD_TOKEN not in .env", file=sys.stderr)
    sys.exit(1)

BASE = "https://api.moysklad.ru/api/remap/1.2"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Accept-Encoding": "gzip"}

YEAR = 2026
DATE_FROM = f"{YEAR}-01-01 00:00:00"
DATE_TO = f"{YEAR}-12-31 23:59:59"

OUT = Path(__file__).parent
DATA = OUT / "data"
DATA.mkdir(exist_ok=True)

USE_CACHE = "--no-cache" not in sys.argv
SKIP_FETCH = "--skip-fetch" in sys.argv


# ─── Utils ───────────────────────────────────────────────────────────────────

def extract_id(field):
    if not isinstance(field, dict):
        return None
    if "id" in field:
        return field["id"]
    href = field.get("meta", {}).get("href", "")
    if not href:
        return None
    last = href.rsplit("/", 1)[-1]
    return last.split("?")[0]  # strip ?expand=… or other query string


def month_key(moment_str):
    return moment_str[:7]


def fetch_paginated(endpoint, params=None, date_filter=False, expand=None, cache_key=None):
    """Generic paginated list fetcher with caching."""
    cache_path = DATA / f"raw_{cache_key}.json" if cache_key else None
    if USE_CACHE and cache_path and cache_path.exists():
        print(f"  📦 cache: {cache_path.name}")
        return json.loads(cache_path.read_text())

    rows, offset = [], 0
    while True:
        p = {"limit": 1000, "offset": offset}
        if date_filter:
            p["filter"] = f"moment>={DATE_FROM};moment<={DATE_TO}"
        if expand:
            p["expand"] = expand
        if params:
            p.update(params)
        r = requests.get(f"{BASE}/{endpoint}", headers=HEADERS, params=p, timeout=120)
        if r.status_code != 200:
            print(f"  ⚠️  {endpoint} HTTP {r.status_code}: {r.text[:200]}")
            break
        d = r.json()
        rows.extend(d.get("rows", []))
        total = d.get("meta", {}).get("size", 0)
        offset += 1000
        print(f"  {endpoint}: {min(offset, total)}/{total}")
        if offset >= total:
            break
    if cache_path:
        cache_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2))
        print(f"  💾 cached → {cache_path.name}")
    return rows


def fetch_processing_positions(processings):
    """Fetch /materials and /products for each processing. Resumable + cached."""
    cache_path = DATA / "raw_positions.json"
    cache = {}
    if cache_path.exists() and USE_CACHE:
        cache = json.loads(cache_path.read_text())
        print(f"  📦 positions cache: {len(cache)} processings already cached")

    todo = [p for p in processings if p["id"] not in cache]
    if not todo:
        print(f"  ✅ all {len(processings)} processings have positions cached")
        return cache

    print(f"  ⏳ fetching positions for {len(todo)} processings "
          f"(≈{len(todo)*2}/45 req/sec = ~{len(todo)*2/45:.0f}s)…")
    start = time.time()
    saved_count = 0
    for i, p in enumerate(todo, 1):
        pid = p["id"]
        result = {"materials": [], "products": []}
        for kind in ("materials", "products"):
            url = f"{BASE}/entity/processing/{pid}/{kind}"
            try:
                # /materials and /products are paginated too — though usually <100 items
                all_rows = []
                offset = 0
                while True:
                    r = requests.get(url, headers=HEADERS,
                                     params={"limit": 1000, "offset": offset},
                                     timeout=60)
                    if r.status_code != 200:
                        print(f"     ⚠️  {pid[:8]} {kind} HTTP {r.status_code}")
                        break
                    d = r.json()
                    all_rows.extend(d.get("rows", []))
                    total = d.get("meta", {}).get("size", 0)
                    offset += 1000
                    if offset >= total:
                        break
                result[kind] = all_rows
            except requests.RequestException as e:
                print(f"     ⚠️  {pid[:8]} {kind}: {e}")
        cache[pid] = result

        if i % 50 == 0 or i == len(todo):
            elapsed = time.time() - start
            rate = i / elapsed if elapsed else 0
            eta = (len(todo) - i) / rate if rate else 0
            print(f"     {i}/{len(todo)} ({rate:.1f}/s, ETA {eta:.0f}s)")

        # save periodically so interruptions don't lose progress
        if i % 100 == 0:
            cache_path.write_text(json.dumps(cache, ensure_ascii=False))
            saved_count = i

    cache_path.write_text(json.dumps(cache, ensure_ascii=False))
    print(f"  💾 positions cached → raw_positions.json ({len(cache)} ops)")
    return cache


# ─── Categorization ─────────────────────────────────────────────────────────

def categorize_products(products):
    """Returns dict: product_id → category code or None."""
    cat = {}
    for p in products:
        path = (p.get("pathName") or "")
        if path.startswith("Сырье для производства/СВЕЖИЙ сыр"):
            cat[p["id"]] = "fresh_cheese"
        elif path.startswith("Сырье для производства/СУШЕНЫЙ сыр"):
            cat[p["id"]] = "dried_cheese"
        elif "Сырье для производства/Упаковка/Гофротара" in path:
            cat[p["id"]] = "cardboard"
        elif path.startswith("Сырье для производства/Упаковка"):
            cat[p["id"]] = "packaging"
        elif path.startswith("Продукция/ПАЧКИ"):
            cat[p["id"]] = "final_package"
        else:
            cat[p["id"]] = None
    return cat


# ─── Flavor extraction (для готових пачок) ──────────────────────────────────

FLAVORS = [
    ("Cheddar", ["чеддер", "cheddar"]),
    ("Gouda", ["гауда", "gouda"]),
    ("Parmesan", ["пармезан", "parmesan", "primaggio", "прімаджіо", "примаджио"]),
    ("Mozzarella", ["моцарелла", "mozzarella"]),
    ("Suluguni", ["сулугуни", "сулугуні", "suluguni"]),
    ("Emmental", ["эмменталь", "емменталь", "emmental"]),
    ("Blue Royale", ["blue royale", "blue", "блю"]),
    ("Fitness/Superfood", ["фитнес", "фітнес", "fitness", "superfood", "суперфуд"]),
    ("Cosmic/Kids", ["cosmic", "космік", "космик", "kids"]),
    ("Гойя", ["гойя"]),
]


def detect_flavor(name):
    n = name.lower()
    for label, keywords in FLAVORS:
        if any(kw in n for kw in keywords):
            return label
    return "Інше"


# ─── Aggregation ────────────────────────────────────────────────────────────

def aggregate(processings, positions_cache, products, cat_map):
    """Returns dict with monthly stats and lifetime totals."""
    product_by_id = {p["id"]: p for p in products}

    # months covered
    today = datetime.now()
    if today.year == YEAR:
        last_month = today.month
    elif today.year > YEAR:
        last_month = 12
    else:
        last_month = 1
    months = [f"{YEAR}-{m:02d}" for m in range(1, last_month + 1)]

    # per-month aggregations
    fresh_consumed = defaultdict(lambda: defaultdict(float))    # month → fresh_product_id → kg
    dried_produced = defaultdict(lambda: defaultdict(float))    # month → dried_product_id → kg
    pack_consumed = defaultdict(lambda: defaultdict(float))     # month → pack_product_id → шт
    card_consumed = defaultdict(lambda: defaultdict(float))     # month → card_product_id → шт
    final_produced_by_flavor = defaultdict(lambda: defaultdict(float))  # month → flavor → шт
    final_produced_by_sku = defaultdict(lambda: defaultdict(float))     # month → final_id → шт
    final_kg_by_flavor = defaultdict(lambda: defaultdict(float))         # month → flavor → kg

    # lifetime totals (for forecast)
    lifetime_consumed = defaultdict(float)  # product_id → total qty since Jan 1 2026

    n_ops_processed = 0
    n_ops_skipped = 0

    for proc in processings:
        if not proc.get("applicable", True):
            n_ops_skipped += 1
            continue
        mk = month_key(proc.get("moment", ""))
        if mk[:4] != str(YEAR):
            n_ops_skipped += 1
            continue
        pos = positions_cache.get(proc["id"])
        if not pos:
            n_ops_skipped += 1
            continue
        n_ops_processed += 1

        for mat in pos.get("materials", []):
            assortment_id = extract_id(mat.get("assortment"))
            qty = mat.get("quantity", 0)
            cat = cat_map.get(assortment_id)
            if cat == "fresh_cheese":
                fresh_consumed[mk][assortment_id] += qty
            elif cat == "dried_cheese":
                # dried cheese ALSO appears as material in 2nd-step packaging
                # we track separately as "dried_consumed_in_packaging"
                pass  # not strictly needed for forecast, skip for now
            elif cat == "packaging":
                pack_consumed[mk][assortment_id] += qty
            elif cat == "cardboard":
                card_consumed[mk][assortment_id] += qty
            lifetime_consumed[assortment_id] += qty

        for prod in pos.get("products", []):
            assortment_id = extract_id(prod.get("assortment"))
            qty = prod.get("quantity", 0)
            cat = cat_map.get(assortment_id)
            if cat == "dried_cheese":
                dried_produced[mk][assortment_id] += qty
            elif cat == "final_package":
                final_produced_by_sku[mk][assortment_id] += qty
                p = product_by_id.get(assortment_id, {})
                flavor = detect_flavor(p.get("name", ""))
                final_produced_by_flavor[mk][flavor] += qty
                weight = p.get("weight") or 0
                final_kg_by_flavor[mk][flavor] += qty * weight

    print(f"  Processed: {n_ops_processed} ops, skipped: {n_ops_skipped}")

    return {
        "months": months,
        "fresh_consumed": dict(fresh_consumed),
        "dried_produced": dict(dried_produced),
        "pack_consumed": dict(pack_consumed),
        "card_consumed": dict(card_consumed),
        "final_produced_by_sku": dict(final_produced_by_sku),
        "final_produced_by_flavor": dict(final_produced_by_flavor),
        "final_kg_by_flavor": dict(final_kg_by_flavor),
        "lifetime_consumed": dict(lifetime_consumed),
        "n_ops_processed": n_ops_processed,
    }


# ─── Forecast: days of supply ───────────────────────────────────────────────

def compute_forecast(stock, lifetime_consumed, cat_map, products):
    """Returns list of {product_id, name, category, stock, daily_avg, days_left}."""
    product_by_id = {p["id"]: p for p in products}

    # current day count in 2026
    today = datetime.now()
    if today.year == YEAR:
        days_elapsed = today.timetuple().tm_yday
    elif today.year > YEAR:
        days_elapsed = 365
    else:
        return []

    # Stock report has assortment href; extract product id (strip query string)
    stock_by_id = {}
    for s in stock:
        pid = extract_id(s)  # uses meta.href and strips ?expand=…
        if not pid:
            continue
        stock_by_id[pid] = s.get("stock", 0)

    rows = []
    for pid, total_consumed in lifetime_consumed.items():
        cat = cat_map.get(pid)
        if cat not in ("fresh_cheese", "packaging", "cardboard"):
            continue
        p = product_by_id.get(pid, {})
        if not p:
            continue
        current_stock = stock_by_id.get(pid, 0)
        daily_avg = total_consumed / days_elapsed if days_elapsed else 0
        days_left = current_stock / daily_avg if daily_avg > 0 else None
        rows.append({
            "id": pid,
            "name": p.get("name", "?"),
            "category": cat,
            "uom": "кг" if cat == "fresh_cheese" else "шт",
            "stock": round(current_stock, 2),
            "total_consumed": round(total_consumed, 2),
            "daily_avg": round(daily_avg, 3),
            "days_left": round(days_left, 1) if days_left is not None else None,
        })

    # sort: most critical (lowest days) first, items with daily_avg=0 to bottom
    rows.sort(key=lambda r: (r["days_left"] is None, r["days_left"] if r["days_left"] is not None else 9999))
    return rows


# ─── Build dataset ──────────────────────────────────────────────────────────

def build_dataset(products, processings, positions_cache, stock):
    cat_map = categorize_products(products)
    product_by_id = {p["id"]: p for p in products}

    agg = aggregate(processings, positions_cache, products, cat_map)
    forecast = compute_forecast(stock, agg["lifetime_consumed"], cat_map, products)

    # For monthly chart: roll up to category-level totals
    months = agg["months"]

    def total_per_month(by_month_by_id):
        return {m: round(sum(by_month_by_id.get(m, {}).values()), 2) for m in months}

    summary = {
        "year": YEAR,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "months": months,
        "n_ops": agg["n_ops_processed"],
        # Headline monthly series
        "fresh_cheese_kg_by_month": total_per_month(agg["fresh_consumed"]),
        "dried_cheese_kg_by_month": total_per_month(agg["dried_produced"]),
        "packaging_pcs_by_month": total_per_month(agg["pack_consumed"]),
        "cardboard_pcs_by_month": total_per_month(agg["card_consumed"]),
        "final_pkg_pcs_by_month": total_per_month(agg["final_produced_by_sku"]),
        "final_pkg_kg_by_month": {m: round(sum(agg["final_kg_by_flavor"].get(m, {}).values()), 2) for m in months},
        # Per-flavor breakdown of final packages
        "final_by_flavor": {
            "labels": sorted({fl for m in months for fl in agg["final_produced_by_flavor"].get(m, {})}),
            "pcs_by_month": {m: agg["final_produced_by_flavor"].get(m, {}) for m in months},
            "kg_by_month": {m: agg["final_kg_by_flavor"].get(m, {}) for m in months},
        },
        # Per-product detail for fresh cheese and dried cheese
        "fresh_cheese_detail": _per_product_detail(agg["fresh_consumed"], product_by_id, months),
        "dried_cheese_detail": _per_product_detail(agg["dried_produced"], product_by_id, months),
        # Forecast
        "forecast": forecast,
    }
    return summary


def _per_product_detail(by_month_by_id, product_by_id, months):
    # build {label, monthly: {m: qty}, total}
    by_id_total = defaultdict(float)
    for m in months:
        for pid, qty in by_month_by_id.get(m, {}).items():
            by_id_total[pid] += qty
    items = []
    for pid, total in sorted(by_id_total.items(), key=lambda x: -x[1]):
        p = product_by_id.get(pid, {})
        items.append({
            "id": pid,
            "name": p.get("name", "?"),
            "total": round(total, 2),
            "monthly": {m: round(by_month_by_id.get(m, {}).get(pid, 0), 2) for m in months},
        })
    return items


# ─── HTML ────────────────────────────────────────────────────────────────────

def build_html(d):
    data_json = json.dumps(d, ensure_ascii=False)
    return f"""<!DOCTYPE html>
<html lang="uk">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>snEco — Procurement Planning {d["year"]}</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
:root{{
  --y:#FEBF27;--g:#96C11F;--d:#1E1E1E;--bg:#F4F4EF;--card:#fff;
  --muted:#8a8a8a;--border:#E5E5DC;--red:#E84040;--blue:#3B82F6;
}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  background:var(--bg);color:var(--d);font-size:14px;min-height:100vh}}
header{{background:#fff;border-bottom:1px solid var(--border);padding:18px 24px;
  display:flex;align-items:center;justify-content:space-between;gap:24px}}
header h1{{font-size:18px;font-weight:700}}
header .meta{{font-size:12px;color:var(--muted)}}
main{{padding:20px 24px 60px;max-width:1600px;margin:0 auto}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));
  gap:14px;margin-bottom:22px}}
.kpi{{background:var(--card);border:1px solid var(--border);border-radius:10px;
  padding:14px 16px}}
.kpi .label{{font-size:11px;color:var(--muted);text-transform:uppercase;
  letter-spacing:.6px;margin-bottom:6px}}
.kpi .value{{font-size:22px;font-weight:700}}
.kpi .sub{{font-size:11px;color:var(--muted);margin-top:4px}}
.section{{background:var(--card);border:1px solid var(--border);border-radius:10px;
  padding:18px 20px;margin-bottom:22px}}
.section h2{{font-size:14px;margin-bottom:14px;font-weight:700;
  letter-spacing:.3px;text-transform:uppercase;color:#444}}
.section h2 .note{{font-weight:400;color:var(--muted);font-size:12px;
  text-transform:none;letter-spacing:0;margin-left:8px}}
.chart-wrap{{position:relative;height:380px}}
.chart-wrap.small{{height:280px}}
table{{width:100%;border-collapse:collapse;font-size:12px;font-variant-numeric:tabular-nums}}
th,td{{padding:8px 10px;border-bottom:1px solid var(--border);text-align:right;white-space:nowrap}}
th:first-child,td:first-child{{text-align:left;font-weight:500}}
thead th{{background:#fafaf6;font-weight:600;color:#555;font-size:11px;
  text-transform:uppercase;letter-spacing:.4px}}
.row-total td{{background:#fef9e9;font-weight:700;border-top:2px solid var(--y)}}
.scroll-x{{overflow-x:auto}}
.bad{{background:#fdecec !important;color:var(--red);font-weight:600}}
.warn{{background:#fef9e9 !important;color:#c69510;font-weight:600}}
.ok{{background:#f0f7e6 !important;color:var(--g);font-weight:600}}
.muted{{color:var(--muted)}}
.tabs{{display:flex;gap:6px;padding:14px 24px 0;border-bottom:1px solid var(--border);
  background:#fff;flex-wrap:wrap}}
.tab{{padding:9px 16px;border:1px solid var(--border);border-bottom:none;
  border-radius:8px 8px 0 0;background:#fafaf6;cursor:pointer;font-weight:500;
  font-size:13px;color:#555}}
.tab.active{{background:#fff;color:var(--d);position:relative;top:1px}}
.header-actions{{display:flex;align-items:flex-end;gap:4px;flex-direction:column}}
.refresh-btn{{background:var(--y);border:none;border-radius:8px;padding:8px 14px;
  font-size:13px;font-weight:600;cursor:pointer;display:inline-flex;align-items:center;
  gap:6px;color:#1E1E1E;font-family:inherit;transition:filter .15s}}
.refresh-btn:hover{{filter:brightness(.95)}}
.refresh-btn .icon{{display:inline-block;font-weight:700}}
.refresh-btn.loading{{background:#fef9e9;cursor:wait;opacity:.85}}
.refresh-btn.loading .icon{{animation:spin 1s linear infinite}}
@keyframes spin{{from{{transform:rotate(0)}}to{{transform:rotate(360deg)}}}}
.refresh-status{{font-size:11px;color:var(--muted);margin-top:2px;max-width:380px;
  text-align:right;font-variant-numeric:tabular-nums;line-height:1.4}}
.refresh-status.error{{color:var(--red)}}
</style>
</head>
<body>

<header>
  <div>
    <h1>snEco · Procurement Planning {d["year"]}</h1>
    <div class="meta">Згенеровано: {d["generated_at"]} · {d["n_ops"]} processing-операцій · {len(d["months"])} міс</div>
  </div>
  <div class="header-actions">
    <button class="refresh-btn" id="refreshBtn" onclick="refreshData()">
      <span class="icon">↻</span>
      <span class="label">Оновити дані</span>
    </button>
    <div class="refresh-status" id="refreshStatus">POC v0.1 · ~3 хв на full refresh</div>
  </div>
</header>

<main id="main"></main>

<script>
const DATA = {data_json};
const fmt = (n, dec=0) => n == null ? '—' : Number(n).toLocaleString('uk-UA', {{maximumFractionDigits: dec, minimumFractionDigits: dec}});
const PALETTE = ['#FEBF27','#96C11F','#3B82F6','#E84040','#8B5CF6','#F59E0B',
                 '#10B981','#EC4899','#06B6D4','#EF4444','#84CC16','#A855F7'];
const color = (i) => PALETTE[i % PALETTE.length];

function totalsRow(series) {{
  return DATA.months.reduce((acc, m) => acc + (series[m] || 0), 0);
}}

function renderKpis() {{
  const freshTotal = totalsRow(DATA.fresh_cheese_kg_by_month);
  const driedTotal = totalsRow(DATA.dried_cheese_kg_by_month);
  const packTotal = totalsRow(DATA.packaging_pcs_by_month);
  const cardTotal = totalsRow(DATA.cardboard_pcs_by_month);
  const finalPcs = totalsRow(DATA.final_pkg_pcs_by_month);
  const finalKg = totalsRow(DATA.final_pkg_kg_by_month);
  const yieldRatio = freshTotal > 0 ? (driedTotal / freshTotal * 100) : 0;
  const lossInDrying = freshTotal > 0 ? ((freshTotal - driedTotal) / freshTotal * 100) : 0;

  return `
    <div class="kpis">
      <div class="kpi">
        <div class="label">Свіжий сир спожито</div>
        <div class="value">${{fmt(freshTotal, 1)}} кг</div>
        <div class="sub">матеріал для сушки</div>
      </div>
      <div class="kpi">
        <div class="label">Сушений сир вироблено</div>
        <div class="value">${{fmt(driedTotal, 1)}} кг</div>
        <div class="sub">з свіжого через VacWave</div>
      </div>
      <div class="kpi">
        <div class="label">Вихід сушки</div>
        <div class="value">${{yieldRatio.toFixed(1)}}%</div>
        <div class="sub">втрати при сушці: ${{lossInDrying.toFixed(1)}}%</div>
      </div>
      <div class="kpi">
        <div class="label">Готових пачок зібрано</div>
        <div class="value">${{fmt(finalPcs)}} шт</div>
        <div class="sub">≈ ${{fmt(finalKg, 1)}} кг готової продукції</div>
      </div>
      <div class="kpi">
        <div class="label">Упаковки спожито</div>
        <div class="value">${{fmt(packTotal)}} шт</div>
      </div>
      <div class="kpi">
        <div class="label">Гофротари спожито</div>
        <div class="value">${{fmt(cardTotal)}} шт</div>
      </div>
    </div>
  `;
}}

function renderBalanceTable() {{
  const months = DATA.months;
  const monthHdrs = months.map(m => `<th>${{m.slice(5)}}.${{m.slice(2,4)}}</th>`).join('');
  const row = (label, series, unit, dec=0) => {{
    const cells = months.map(m => `<td>${{(series[m]||0) > 0 ? fmt(series[m], dec) : '<span class="muted">—</span>'}}</td>`).join('');
    const tot = totalsRow(series);
    return `<tr><td>${{label}}</td>${{cells}}<td><b>${{fmt(tot, dec)}}</b> <span class="muted">${{unit}}</span></td></tr>`;
  }};
  return `
    <div class="section">
      <h2>Виробничий баланс помісячно <span class="note">input vs output</span></h2>
      <div class="scroll-x"><table>
        <thead><tr><th>Показник</th>${{monthHdrs}}<th>За рік</th></tr></thead>
        <tbody>
          ${{row('Свіжий сир спожито (кг)', DATA.fresh_cheese_kg_by_month, 'кг', 1)}}
          ${{row('Сушений сир вироблено (кг)', DATA.dried_cheese_kg_by_month, 'кг', 1)}}
          ${{row('Упаковка спожита (шт)', DATA.packaging_pcs_by_month, 'шт')}}
          ${{row('Гофротара спожита (шт)', DATA.cardboard_pcs_by_month, 'шт')}}
          ${{row('Готових пачок зібрано (шт)', DATA.final_pkg_pcs_by_month, 'шт')}}
          ${{row('Готових пачок (кг)', DATA.final_pkg_kg_by_month, 'кг', 1)}}
        </tbody>
      </table></div>
    </div>
  `;
}}

function renderForecast() {{
  if (!DATA.forecast.length) return '';
  const rowClass = (d) => {{
    if (d == null) return '';
    if (d < 14) return 'bad';
    if (d < 30) return 'warn';
    return 'ok';
  }};
  const catLabel = {{fresh_cheese: 'Свіжий сир', packaging: 'Упаковка', cardboard: 'Гофротара'}};
  const rows = DATA.forecast.map(r => `
    <tr>
      <td><span class="muted">${{catLabel[r.category]||r.category}}</span> · ${{r.name}}</td>
      <td>${{fmt(r.stock, r.uom==='кг'?1:0)}} <span class="muted">${{r.uom}}</span></td>
      <td>${{fmt(r.total_consumed, r.uom==='кг'?1:0)}}</td>
      <td>${{fmt(r.daily_avg, 3)}}</td>
      <td class="${{rowClass(r.days_left)}}">${{r.days_left == null ? '∞' : fmt(r.days_left, 1) + ' дн'}}</td>
    </tr>
  `).join('');
  return `
    <div class="section">
      <h2>Прогноз закінчення сировини <span class="note">stock ÷ середньоденне споживання за {YEAR} = днів вистачить</span></h2>
      <div class="scroll-x"><table>
        <thead><tr><th>Матеріал</th><th>Залишок</th><th>Спожито YTD</th><th>Середньо/день</th><th>Днів вистачить</th></tr></thead>
        <tbody>${{rows}}</tbody>
      </table></div>
      <div style="margin-top:10px;font-size:12px;color:var(--muted)">
        <span class="bad" style="padding:2px 8px;border-radius:3px;">&lt; 14 дн</span> критично ·
        <span class="warn" style="padding:2px 8px;border-radius:3px;">14–30 дн</span> запланувати ·
        <span class="ok" style="padding:2px 8px;border-radius:3px;">&gt; 30 дн</span> ок
      </div>
    </div>
  `;
}}

function renderFlavorChart() {{
  const flavors = DATA.final_by_flavor.labels;
  const months = DATA.months;
  return `
    <div class="section">
      <h2>Готові пачки по смаках (штуки)</h2>
      <div class="chart-wrap"><canvas id="chartFlavorPcs"></canvas></div>
    </div>
    <div class="section">
      <h2>Готові пачки по смаках (кг готової продукції)</h2>
      <div class="chart-wrap"><canvas id="chartFlavorKg"></canvas></div>
    </div>
  `;
}}

function drawFlavorCharts() {{
  const months = DATA.months;
  const labels = months.map(m => m.slice(5) + '.' + m.slice(2,4));
  const flavors = DATA.final_by_flavor.labels;

  // pcs
  new Chart(document.getElementById('chartFlavorPcs'), {{
    type: 'bar',
    data: {{
      labels,
      datasets: flavors.map((f, i) => ({{
        label: f,
        data: months.map(m => DATA.final_by_flavor.pcs_by_month[m]?.[f] || 0),
        backgroundColor: color(i),
        stack: 's',
      }})),
    }},
    options: {{
      maintainAspectRatio: false, responsive: true,
      scales: {{ x: {{stacked: true}}, y: {{stacked: true, title: {{display:true, text:'шт'}}}} }},
      plugins: {{ legend: {{position: 'bottom', labels: {{boxWidth: 12, padding: 8, font: {{size: 11}}}}}} }},
    }},
  }});

  // kg
  new Chart(document.getElementById('chartFlavorKg'), {{
    type: 'bar',
    data: {{
      labels,
      datasets: flavors.map((f, i) => ({{
        label: f,
        data: months.map(m => DATA.final_by_flavor.kg_by_month[m]?.[f] || 0),
        backgroundColor: color(i),
        stack: 's',
      }})),
    }},
    options: {{
      maintainAspectRatio: false, responsive: true,
      scales: {{ x: {{stacked: true}}, y: {{stacked: true, title: {{display:true, text:'кг'}}}} }},
      plugins: {{ legend: {{position: 'bottom', labels: {{boxWidth: 12, padding: 8, font: {{size: 11}}}}}} }},
    }},
  }});
}}

function renderDetail() {{
  const months = DATA.months;
  const monthHdrs = months.map(m => `<th>${{m.slice(5)}}.${{m.slice(2,4)}}</th>`).join('');

  const detailTable = (items, unit, dec=1) => {{
    if (!items.length) return '<div class="muted">немає даних</div>';
    const rows = items.map(it => {{
      const cells = months.map(m => `<td>${{(it.monthly[m]||0) > 0 ? fmt(it.monthly[m], dec) : '<span class="muted">—</span>'}}</td>`).join('');
      return `<tr><td>${{it.name}}</td>${{cells}}<td><b>${{fmt(it.total, dec)}}</b></td></tr>`;
    }}).join('');
    return `<div class="scroll-x"><table>
      <thead><tr><th>Сорт</th>${{monthHdrs}}<th>Всього (${{unit}})</th></tr></thead>
      <tbody>${{rows}}</tbody>
    </table></div>`;
  }};

  return `
    <div class="section">
      <h2>Свіжий сир — деталізація по сортах (кг)</h2>
      ${{detailTable(DATA.fresh_cheese_detail, 'кг', 1)}}
    </div>
    <div class="section">
      <h2>Сушений сир — деталізація по сортах (кг)</h2>
      ${{detailTable(DATA.dried_cheese_detail, 'кг', 1)}}
    </div>
  `;
}}

document.getElementById('main').innerHTML =
  renderKpis() + renderBalanceTable() + renderForecast() +
  renderFlavorChart() + renderDetail();

drawFlavorCharts();

// ─── Refresh data button ────────────────────────────────────────────────────
const DASHBOARD_NAME = 'procurement';
const ETA_SEC = 180;

async function refreshData() {{
  if (location.protocol === 'file:') {{
    alert('Кнопка працює тільки коли дашборд відкрито через локальний сервер.\\n\\n' +
          'У Terminal:\\n  cd ~/snEco-brand-book\\n  source .venv/bin/activate\\n  python3 dashboard/serve.py\\n\\n' +
          'Потім відкрий http://localhost:8765/' + DASHBOARD_NAME);
    return;
  }}
  const btn = document.getElementById('refreshBtn');
  const status = document.getElementById('refreshStatus');
  const originalLabel = btn.querySelector('.label').textContent;
  btn.classList.add('loading');
  btn.disabled = true;
  status.classList.remove('error');
  btn.querySelector('.label').textContent = 'Тягне з МойСкладу…';
  status.textContent = `очікувано ~${{ETA_SEC}}s (1144 операцій)`;

  try {{
    const startResp = await fetch(`/api/refresh/${{DASHBOARD_NAME}}`, {{method: 'POST'}});
    if (startResp.status === 409) {{
      status.textContent = 'Refresh вже виконується — приєднуюсь…';
    }} else if (startResp.status !== 202) {{
      throw new Error('HTTP ' + startResp.status);
    }}
    const startTime = Date.now();
    while (true) {{
      await new Promise(r => setTimeout(r, 1500));
      const s = await fetch(`/api/status/${{DASHBOARD_NAME}}`).then(r => r.json());
      const elapsed = Math.floor((Date.now() - startTime) / 1000);
      if (s.running) {{
        const tail = s.log_tail ? s.log_tail.split('\\n').slice(-1)[0].slice(0, 70).trim() : '';
        status.textContent = `${{elapsed}}s · ${{tail || 'тягне…'}}`;
        continue;
      }}
      if (s.error) {{
        btn.classList.remove('loading');
        btn.disabled = false;
        btn.querySelector('.label').textContent = originalLabel;
        status.textContent = 'Помилка: ' + s.error;
        status.classList.add('error');
        return;
      }}
      btn.querySelector('.label').textContent = 'Готово, перезавантажую…';
      setTimeout(() => location.reload(), 400);
      return;
    }}
  }} catch (e) {{
    btn.classList.remove('loading');
    btn.disabled = false;
    btn.querySelector('.label').textContent = originalLabel;
    status.textContent = 'Помилка: ' + e.message;
    status.classList.add('error');
  }}
}}
</script>
</body>
</html>
"""


# ─── Main orchestration ─────────────────────────────────────────────────────

def main():
    print("🔌 Loading catalogs…")

    if SKIP_FETCH:
        print("  📦 --skip-fetch: using cached data")
        folders     = json.loads((DATA / "raw_folders.json").read_text())
        products    = json.loads((DATA / "raw_products.json").read_text())
        stock       = json.loads((DATA / "raw_stock.json").read_text())
        processings = json.loads((DATA / "raw_processings.json").read_text())
        positions   = json.loads((DATA / "raw_positions.json").read_text())
    else:
        folders     = fetch_paginated("entity/productfolder", cache_key="folders")
        products    = fetch_paginated("entity/product", cache_key="products")
        stock       = fetch_paginated("report/stock/all", cache_key="stock")
        processings = fetch_paginated("entity/processing", date_filter=True,
                                       expand="materials,products,organization",
                                       cache_key="processings")
        print(f"\n[positions] Fetching materials/products for each processing…")
        positions = fetch_processing_positions(processings)

    print(f"\n🧮 Aggregating ({len(processings)} ops, {len(products)} products)…")
    dataset = build_dataset(products, processings, positions, stock)

    (OUT / "data.json").write_text(json.dumps(dataset, ensure_ascii=False, indent=2))
    print(f"  💾 data.json")

    html = build_html(dataset)
    # Local POC output — prod procurement.html живе окремо як static OTP-gated fetcher
    (OUT / "local-preview.html").write_text(html)
    print(f"  📄 local-preview.html")

    print(f"\n✅ Готово! Відкрий у браузері:")
    print(f"  open {OUT}/local-preview.html")
    print(f"\nДля повторного запуску без re-fetch:")
    print(f"  python3 dashboard/procurement/build.py --skip-fetch")


if __name__ == "__main__":
    main()
