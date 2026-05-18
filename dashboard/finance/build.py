#!/usr/bin/env python3
"""
snEco — P&L Dashboard Builder
Тягне з МойСклад: відвантаження (revenue) + вихідні платежі (витрати по статтях)
за 2026 рік, групує помісячно, генерує self-contained finance.html.

Запуск:
    cd ~/snEco-brand-book
    source .venv/bin/activate
    python3 dashboard/finance/build.py

Що робить:
    1. Тягне entity/organization (всі юр.особи)
    2. Тягне entity/expenseitem (каталог статей витрат)
    3. Тягне entity/demand (відвантаження) за 2026 з expand=organization
    4. Тягне entity/paymentout (вихідні платежі) за 2026 з expand=organization,expenseItem
    5. Зберігає сирі дані у data/raw_*.json (можна перезапустити dashboard без re-fetch)
    6. Агрегує помісячно (revenue + expenses by category) по кожній юр.особі окремо
    7. Генерує finance.html — standalone дашборд, відкриваєш у браузері (file://)

Зауваження:
    - sum у МойСкладі — в КОПІЙКАХ/центах, ділимо на 100 → отримуємо валютні одиниці
    - applicable=false означає документ скасований → ігноруємо
    - Якщо у paymentout не проставлено expenseItem → відносимо до "Без категорії"
    - Валюта — нативна для організації (UA орг = UAH, SK орг = EUR)
"""

import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

# ─── Конфігурація ────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent.parent  # ~/snEco-brand-book/
load_dotenv(ROOT / ".env")

TOKEN = os.getenv("MOYSKLAD_TOKEN")
if not TOKEN:
    print("❌ MOYSKLAD_TOKEN не знайдено у .env", file=sys.stderr)
    sys.exit(1)

BASE_URL = "https://api.moysklad.ru/api/remap/1.2"
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept-Encoding": "gzip",
}

YEAR = 2026
DATE_FROM = f"{YEAR}-01-01 00:00:00"
DATE_TO = f"{YEAR}-12-31 23:59:59"

OUT_DIR = Path(__file__).parent
DATA_DIR = OUT_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

USE_CACHE = "--no-cache" not in sys.argv
SKIP_FETCH = "--skip-fetch" in sys.argv  # build HTML only from cached JSON


# ─── МойСклад API helpers ────────────────────────────────────────────────────

def fetch_all(endpoint: str, expand: str = None, date_filter: bool = True,
              cache_key: str = None) -> list:
    """Тягне всі записи з пагінацією. Кешує у data/raw_<cache_key>.json."""
    cache_path = DATA_DIR / f"raw_{cache_key}.json" if cache_key else None

    if USE_CACHE and cache_path and cache_path.exists():
        print(f"  📦 cache hit: {cache_path.name}")
        return json.loads(cache_path.read_text())

    url = f"{BASE_URL}/{endpoint}"
    rows, offset, limit = [], 0, 1000
    while True:
        params = {"limit": limit, "offset": offset}
        if date_filter:
            params["filter"] = f"moment>={DATE_FROM};moment<={DATE_TO}"
        if expand:
            params["expand"] = expand
        r = requests.get(url, headers=HEADERS, params=params, timeout=60)
        if r.status_code != 200:
            print(f"  ⚠️  {endpoint} HTTP {r.status_code}: {r.text[:200]}")
            break
        d = r.json()
        rows.extend(d.get("rows", []))
        total = d.get("meta", {}).get("size", 0)
        offset += limit
        print(f"  {endpoint}: {min(offset, total)}/{total}")
        if offset >= total:
            break

    if cache_path:
        cache_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2))
        print(f"  💾 cached → {cache_path.name}")
    return rows


def safe_name(obj, default=""):
    if isinstance(obj, dict):
        return obj.get("name", default)
    return default


def extract_id(field):
    """Витягує UUID з meta.href навіть якщо expand не спрацював."""
    if not isinstance(field, dict):
        return None
    if "id" in field:
        return field["id"]
    href = field.get("meta", {}).get("href", "")
    return href.rsplit("/", 1)[-1] if href else None


def month_key(moment_str: str) -> str:
    """'2026-03-15 14:30:00.000' → '2026-03'."""
    return moment_str[:7]


# ─── Fetch all needed data ──────────────────────────────────────────────────

def main():
    print(f"🔌 Connecting to MoySklad API…")

    if not SKIP_FETCH:
        print(f"\n[1/4] Organizations…")
        orgs = fetch_all("entity/organization", date_filter=False,
                         cache_key="organizations")
        print(f"      → {len(orgs)} orgs")
        for o in orgs:
            print(f"        • {o['name']} (id={o['id'][:8]}…)")

        print(f"\n[2/4] Expense items (статті витрат)…")
        expense_items = fetch_all("entity/expenseitem", date_filter=False,
                                  cache_key="expense_items")
        print(f"      → {len(expense_items)} categories")

        print(f"\n[3/4] Demand (відвантаження) {YEAR}…")
        demands = fetch_all("entity/demand",
                            expand="organization,agent",
                            cache_key="demands")
        print(f"      → {len(demands)} demands")

        print(f"\n[4/4] PaymentOut (вихідні платежі) {YEAR}…")
        payments_out = fetch_all("entity/paymentout",
                                 expand="organization,expenseItem,agent",
                                 cache_key="payments_out")
        print(f"      → {len(payments_out)} payments")
    else:
        print("📦 Skipping fetch, using cached data…")
        orgs = json.loads((DATA_DIR / "raw_organizations.json").read_text())
        expense_items = json.loads((DATA_DIR / "raw_expense_items.json").read_text())
        demands = json.loads((DATA_DIR / "raw_demands.json").read_text())
        payments_out = json.loads((DATA_DIR / "raw_payments_out.json").read_text())

    # ─── Aggregate ──────────────────────────────────────────────────────────

    print(f"\n🧮 Aggregating…")

    # Lookup tables — expand= не завжди працює, тому будуємо самі з каталогів
    org_name_by_id = {o["id"]: o["name"] for o in orgs}
    expense_name_by_id = {e["id"]: e["name"] for e in expense_items}

    # Build month list: 2026-01 .. current month
    today = datetime.now()
    if today.year == YEAR:
        last_month = today.month
    elif today.year > YEAR:
        last_month = 12
    else:
        last_month = 1
    months = [f"{YEAR}-{m:02d}" for m in range(1, last_month + 1)]

    # Revenue per (org, month)
    revenue = defaultdict(lambda: defaultdict(float))  # org → month → sum
    revenue_count = defaultdict(lambda: defaultdict(int))
    for d in demands:
        if not d.get("applicable", True):
            continue
        org_id = extract_id(d.get("organization")) or "unknown"
        mk = month_key(d.get("moment", ""))
        if mk[:4] != str(YEAR):
            continue
        revenue[org_id][mk] += d.get("sum", 0) / 100.0
        revenue_count[org_id][mk] += 1

    # Expenses per (org, month, category)
    expenses = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    expense_count = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for p in payments_out:
        if not p.get("applicable", True):
            continue
        org_id = extract_id(p.get("organization")) or "unknown"
        mk = month_key(p.get("moment", ""))
        if mk[:4] != str(YEAR):
            continue
        # expenseItem name: try expand first, fall back to catalog lookup by id
        ei_field = p.get("expenseItem")
        cat = None
        if isinstance(ei_field, dict):
            cat = ei_field.get("name") or expense_name_by_id.get(extract_id(ei_field))
        if not cat:
            cat = "(Без категорії)"
        expenses[org_id][mk][cat] += p.get("sum", 0) / 100.0
        expense_count[org_id][mk][cat] += 1

    # ─── Build aggregated dataset ───────────────────────────────────────────

    dataset = {
        "year": YEAR,
        "months": months,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "currency_note": "Кожна організація — у своїй нативній валюті (UA=UAH, SK=EUR)",
        "organizations": [],
    }

    # Sort orgs by total revenue descending
    # Collect all org_ids seen in either revenue or expenses
    seen_org_ids = set(revenue.keys()) | set(expenses.keys())
    org_totals = []
    for org_id in seen_org_ids:
        name = org_name_by_id.get(org_id, f"(unknown {org_id[:8]})")
        total_rev = sum(revenue[org_id].values())
        total_exp = sum(sum(m.values()) for m in expenses[org_id].values())
        if total_rev == 0 and total_exp == 0:
            continue
        org_totals.append((org_id, name, total_rev, total_exp))
    org_totals.sort(key=lambda x: -x[2])

    for org_id, name, total_rev, total_exp in org_totals:
        # Collect all categories used in this org
        cats = set()
        for m in months:
            cats.update(expenses[org_id][m].keys())
        # Sort categories by total spend desc
        cat_totals = [(c, sum(expenses[org_id][m].get(c, 0) for m in months)) for c in cats]
        cat_totals.sort(key=lambda x: -x[1])
        sorted_cats = [c for c, _ in cat_totals]

        monthly = []
        for m in months:
            rev = revenue[org_id].get(m, 0.0)
            row = {
                "month": m,
                "revenue": round(rev, 2),
                "revenue_docs": revenue_count[org_id].get(m, 0),
                "expenses_by_cat": {c: round(expenses[org_id][m].get(c, 0), 2)
                                    for c in sorted_cats},
                "expense_docs": sum(expense_count[org_id][m].values()),
            }
            row["total_expense"] = round(sum(row["expenses_by_cat"].values()), 2)
            row["net"] = round(rev - row["total_expense"], 2)
            monthly.append(row)

        dataset["organizations"].append({
            "id": org_id,
            "name": name,
            "total_revenue": round(total_rev, 2),
            "total_expense": round(total_exp, 2),
            "net": round(total_rev - total_exp, 2),
            "categories": sorted_cats,
            "category_totals": {c: round(t, 2) for c, t in cat_totals},
            "monthly": monthly,
        })

    # ─── Consolidated view: всі юр.особи разом ──────────────────────────────

    if len(dataset["organizations"]) > 1:
        all_cats_totals = defaultdict(float)
        for o in dataset["organizations"]:
            for c, t in o["category_totals"].items():
                all_cats_totals[c] += t
        sorted_all_cats = sorted(all_cats_totals.items(), key=lambda x: -x[1])
        sorted_cat_names = [c for c, _ in sorted_all_cats]

        total_rev_all = sum(o["total_revenue"] for o in dataset["organizations"])
        total_exp_all = sum(o["total_expense"] for o in dataset["organizations"])

        monthly_all = []
        for mi, m in enumerate(months):
            rev_m = sum(o["monthly"][mi]["revenue"] for o in dataset["organizations"])
            exp_m = sum(o["monthly"][mi]["total_expense"] for o in dataset["organizations"])
            cats_m = {
                c: round(sum(o["monthly"][mi]["expenses_by_cat"].get(c, 0)
                             for o in dataset["organizations"]), 2)
                for c in sorted_cat_names
            }
            monthly_all.append({
                "month": m,
                "revenue": round(rev_m, 2),
                "revenue_docs": sum(o["monthly"][mi]["revenue_docs"]
                                    for o in dataset["organizations"]),
                "expenses_by_cat": cats_m,
                "expense_docs": sum(o["monthly"][mi]["expense_docs"]
                                    for o in dataset["organizations"]),
                "total_expense": round(exp_m, 2),
                "net": round(rev_m - exp_m, 2),
            })

        aggregate = {
            "id": "__all__",
            "name": f"Всі юр.особи ({len(dataset['organizations'])})",
            "is_aggregate": True,
            "note": ("Сума по всіх юр.особах у UAH. УВАГА: внутрішньогрупові потоки "
                     "(Перемещение, Вивод Средств, На Абрис, на Пет Корп) можуть "
                     "подвійно відображатися — як виплата у однієї юр.особи і як "
                     "надходження в іншої. Для чистого консолідованого P&L їх треба "
                     "елімінувати — це наступний крок."),
            "total_revenue": round(total_rev_all, 2),
            "total_expense": round(total_exp_all, 2),
            "net": round(total_rev_all - total_exp_all, 2),
            "categories": sorted_cat_names,
            "category_totals": {c: round(t, 2) for c, t in sorted_all_cats},
            "monthly": monthly_all,
        }
        dataset["organizations"].insert(0, aggregate)

    # Write aggregated JSON
    agg_path = OUT_DIR / "data.json"
    agg_path.write_text(json.dumps(dataset, ensure_ascii=False, indent=2))
    print(f"  💾 aggregated → {agg_path.relative_to(ROOT)}")

    # ─── Generate HTML ──────────────────────────────────────────────────────

    html = build_html(dataset)
    # Local POC output — prod finance.html живе окремо як static OTP-gated fetcher
    html_path = OUT_DIR / "local-preview.html"
    html_path.write_text(html)
    print(f"  📄 local preview → {html_path.relative_to(ROOT)}")

    print(f"\n✅ Готово!")
    print(f"\nВідкрий у браузері:")
    print(f"  open {html_path}")
    print(f"\nЯкщо треба пересобрати тільки HTML без re-fetch:")
    print(f"  python3 {Path(__file__).relative_to(ROOT)} --skip-fetch")
    print(f"\nЯкщо треба свіжі дані з МойСкладу:")
    print(f"  python3 {Path(__file__).relative_to(ROOT)} --no-cache")


# ─── HTML generator ──────────────────────────────────────────────────────────

def build_html(dataset: dict) -> str:
    data_json = json.dumps(dataset, ensure_ascii=False)
    months_count = len(dataset["months"])
    orgs_count = len(dataset["organizations"])
    return f"""<!DOCTYPE html>
<html lang="uk">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>snEco — P&amp;L Dashboard {dataset["year"]}</title>
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
header h1{{font-size:18px;font-weight:700;letter-spacing:.2px}}
header .meta{{font-size:12px;color:var(--muted)}}
.tabs{{display:flex;gap:6px;padding:14px 24px 0;border-bottom:1px solid var(--border);
  background:#fff;flex-wrap:wrap}}
.tab{{padding:9px 16px;border:1px solid var(--border);border-bottom:none;
  border-radius:8px 8px 0 0;background:#fafaf6;cursor:pointer;font-weight:500;
  font-size:13px;color:#555}}
.tab.active{{background:#fff;color:var(--d);border-color:var(--border);
  position:relative;top:1px}}
main{{padding:20px 24px 60px;max-width:1600px;margin:0 auto}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));
  gap:14px;margin-bottom:22px}}
.kpi{{background:var(--card);border:1px solid var(--border);border-radius:10px;
  padding:14px 16px}}
.kpi .label{{font-size:11px;color:var(--muted);text-transform:uppercase;
  letter-spacing:.6px;margin-bottom:6px}}
.kpi .value{{font-size:22px;font-weight:700}}
.kpi .sub{{font-size:11px;color:var(--muted);margin-top:4px}}
.kpi.green .value{{color:var(--g)}}
.kpi.red .value{{color:var(--red)}}
.section{{background:var(--card);border:1px solid var(--border);border-radius:10px;
  padding:18px 20px;margin-bottom:22px}}
.section h2{{font-size:14px;margin-bottom:14px;font-weight:700;
  letter-spacing:.3px;text-transform:uppercase;color:#444}}
.chart-wrap{{position:relative;height:380px}}
table{{width:100%;border-collapse:collapse;font-size:12px;font-variant-numeric:tabular-nums}}
th,td{{padding:8px 10px;border-bottom:1px solid var(--border);text-align:right;
  white-space:nowrap}}
th:first-child,td:first-child{{text-align:left;font-weight:500;max-width:280px;
  overflow:hidden;text-overflow:ellipsis}}
thead th{{background:#fafaf6;font-weight:600;color:#555;font-size:11px;
  text-transform:uppercase;letter-spacing:.4px;border-bottom:2px solid var(--border);
  position:sticky;top:0}}
.row-revenue td{{background:#fef9e9;font-weight:700;border-bottom:2px solid var(--y)}}
.row-total td{{background:#f4f4ef;font-weight:700;border-top:2px solid var(--border)}}
.row-net td{{background:#f0f7e6;font-weight:700;border-top:2px solid var(--g);
  color:var(--g)}}
.row-net.negative td{{background:#fdecec;color:var(--red);border-top-color:var(--red)}}
.pct{{display:inline-block;color:var(--muted);font-size:11px;margin-left:4px}}
.empty{{color:#bbb}}
.empty-state{{text-align:center;padding:60px 20px;color:var(--muted)}}
.scroll-x{{overflow-x:auto}}
.legend-cat{{display:inline-block;width:10px;height:10px;border-radius:2px;
  margin-right:6px;vertical-align:middle}}
.note{{background:#fef9e9;border:1px solid #f1d883;border-left:4px solid var(--y);
  padding:11px 14px;border-radius:6px;font-size:12px;color:#7a5e10;
  margin-bottom:18px;line-height:1.5}}
.note strong{{color:#5c4500}}
.tab.aggregate{{background:#fef9e9;border-color:#f1d883;font-weight:700}}
.tab.aggregate.active{{background:#fff5d1}}
.header-actions{{display:flex;align-items:flex-end;gap:14px;flex-direction:column}}
.refresh-btn{{background:var(--y);border:none;border-radius:8px;padding:8px 14px;
  font-size:13px;font-weight:600;cursor:pointer;display:inline-flex;align-items:center;
  gap:6px;color:#1E1E1E;font-family:inherit;transition:filter .15s}}
.refresh-btn:hover{{filter:brightness(.95)}}
.refresh-btn .icon{{display:inline-block;font-weight:700}}
.refresh-btn.loading{{background:#fef9e9;cursor:wait;opacity:.85}}
.refresh-btn.loading .icon{{animation:spin 1s linear infinite}}
@keyframes spin{{from{{transform:rotate(0)}}to{{transform:rotate(360deg)}}}}
.refresh-status{{font-size:11px;color:var(--muted);margin-top:2px;max-width:340px;
  text-align:right;font-variant-numeric:tabular-nums}}
.refresh-status.error{{color:var(--red)}}
</style>
</head>
<body>

<header>
  <div>
    <h1>snEco · P&amp;L Dashboard {dataset["year"]}</h1>
    <div class="meta">Згенеровано: {dataset["generated_at"]} · {orgs_count} орг · {months_count} міс · {dataset["currency_note"]}</div>
  </div>
  <div class="header-actions">
    <button class="refresh-btn" id="refreshBtn" onclick="refreshData()">
      <span class="icon">↻</span>
      <span class="label">Оновити дані</span>
    </button>
    <div class="refresh-status" id="refreshStatus">POC v0.1 · дані з МойСклад API</div>
  </div>
</header>

<div class="tabs" id="tabs"></div>

<main id="main"></main>

<script>
const DATA = {data_json};

const fmt = (n) => n == null ? '—' :
  n.toLocaleString('uk-UA', {{maximumFractionDigits:0, minimumFractionDigits:0}});
const pct = (n, base) => base > 0 ? (n / base * 100).toFixed(1) + '%' : '—';

// Stable color palette
const PALETTE = ['#FEBF27','#96C11F','#3B82F6','#E84040','#8B5CF6','#F59E0B',
                 '#10B981','#EC4899','#06B6D4','#EF4444','#84CC16','#A855F7',
                 '#0EA5E9','#F97316','#14B8A6','#D946EF','#22C55E','#FB7185'];
const colorFor = (i) => PALETTE[i % PALETTE.length];

let currentOrgIdx = 0;
let chartInstance = null;

function renderTabs() {{
  const tabs = document.getElementById('tabs');
  tabs.innerHTML = '';
  DATA.organizations.forEach((o, i) => {{
    const t = document.createElement('div');
    let cls = 'tab';
    if (i === currentOrgIdx) cls += ' active';
    if (o.is_aggregate) cls += ' aggregate';
    t.className = cls;
    t.textContent = o.name;
    t.onclick = () => {{ currentOrgIdx = i; renderTabs(); renderOrg(); }};
    tabs.appendChild(t);
  }});
}}

function renderOrg() {{
  const main = document.getElementById('main');
  const org = DATA.organizations[currentOrgIdx];
  if (!org) {{
    main.innerHTML = '<div class="empty-state">Немає даних для відображення.</div>';
    return;
  }}
  const months = DATA.months;
  const cats = org.categories;

  const monthsWithData = org.monthly.filter(m => m.revenue > 0 || m.total_expense > 0).length;
  const avgMonthlyRev = monthsWithData > 0 ? org.total_revenue / monthsWithData : 0;
  const netMargin = org.total_revenue > 0 ? (org.net / org.total_revenue * 100) : 0;

  const noteHtml = org.note ? `<div class="note"><strong>⚠ Консолідований view:</strong> ${{org.note}}</div>` : '';

  main.innerHTML = `
    ${{noteHtml}}
    <div class="kpis">
      <div class="kpi">
        <div class="label">Загальна виручка ${{DATA.year}}</div>
        <div class="value">${{fmt(org.total_revenue)}}</div>
        <div class="sub">${{monthsWithData}} місяців з даними</div>
      </div>
      <div class="kpi">
        <div class="label">Загальні витрати</div>
        <div class="value">${{fmt(org.total_expense)}}</div>
        <div class="sub">${{pct(org.total_expense, org.total_revenue)}} від виручки</div>
      </div>
      <div class="kpi ${{org.net >= 0 ? 'green' : 'red'}}">
        <div class="label">Net (виручка − витрати)</div>
        <div class="value">${{fmt(org.net)}}</div>
        <div class="sub">${{netMargin.toFixed(1)}}% маржа</div>
      </div>
      <div class="kpi">
        <div class="label">Середня виручка / міс</div>
        <div class="value">${{fmt(avgMonthlyRev)}}</div>
        <div class="sub">по місяцях з даними</div>
      </div>
    </div>

    <div class="section">
      <h2>Витрати як % від виручки помісячно</h2>
      <div class="chart-wrap"><canvas id="chartMonthly"></canvas></div>
    </div>

    <div class="section">
      <h2>Помісячна розбивка</h2>
      <div class="scroll-x">
        <table id="tablePnl"></table>
      </div>
    </div>
  `;

  drawChart(org, months, cats);
  drawTable(org, months, cats);
}}

function drawChart(org, months, cats) {{
  const ctx = document.getElementById('chartMonthly').getContext('2d');
  if (chartInstance) chartInstance.destroy();

  // Build dataset per category: y = % of revenue that month
  const catDatasets = cats.map((c, i) => ({{
    label: c,
    data: months.map((m, mi) => {{
      const row = org.monthly[mi];
      if (row.revenue <= 0) return 0;
      return +(((row.expenses_by_cat[c] || 0) / row.revenue) * 100).toFixed(2);
    }}),
    backgroundColor: colorFor(i),
    stack: 'stack1',
  }}));

  // Add "Net margin" as positive remainder if profitable, else red overshoot
  const netData = months.map((m, mi) => {{
    const row = org.monthly[mi];
    if (row.revenue <= 0) return 0;
    return +(((row.revenue - row.total_expense) / row.revenue) * 100).toFixed(2);
  }});

  catDatasets.push({{
    label: 'Net margin',
    data: netData,
    backgroundColor: '#1E1E1E',
    borderColor: '#1E1E1E',
    type: 'line',
    yAxisID: 'y',
    tension: 0.3,
    pointRadius: 4,
    pointHoverRadius: 6,
    fill: false,
    order: -1,
  }});

  chartInstance = new Chart(ctx, {{
    type: 'bar',
    data: {{
      labels: months.map(m => m.slice(5) + '.' + m.slice(2,4)),
      datasets: catDatasets,
    }},
    options: {{
      maintainAspectRatio: false,
      responsive: true,
      scales: {{
        y: {{
          stacked: true,
          ticks: {{ callback: v => v + '%' }},
          title: {{ display: true, text: '% від виручки місяця' }},
        }},
        x: {{ stacked: true }},
      }},
      plugins: {{
        legend: {{
          position: 'bottom',
          labels: {{ boxWidth: 12, padding: 8, font: {{ size: 11 }} }},
        }},
        tooltip: {{
          callbacks: {{
            label: (c) => `${{c.dataset.label}}: ${{c.parsed.y.toFixed(1)}}%`,
          }},
        }},
      }},
    }},
  }});
}}

function drawTable(org, months, cats) {{
  const table = document.getElementById('tablePnl');
  const monthHeaders = months.map(m => `<th>${{m.slice(5)}}.${{m.slice(2,4)}}</th>`).join('');

  // Revenue row
  let html = `<thead><tr><th>Стаття</th>${{monthHeaders}}<th>Всього</th></tr></thead><tbody>`;
  const revCells = org.monthly.map(r => `<td>${{r.revenue > 0 ? fmt(r.revenue) : '<span class="empty">—</span>'}}</td>`).join('');
  html += `<tr class="row-revenue"><td>Відвантаження (виручка) — 100%</td>${{revCells}}<td>${{fmt(org.total_revenue)}}</td></tr>`;

  // Categories
  cats.forEach((c, i) => {{
    const cells = org.monthly.map(r => {{
      const v = r.expenses_by_cat[c] || 0;
      const p = r.revenue > 0 ? (v / r.revenue * 100) : null;
      if (v === 0) return '<td><span class="empty">—</span></td>';
      return `<td>${{fmt(v)}}<span class="pct">${{p != null ? p.toFixed(1)+'%' : ''}}</span></td>`;
    }}).join('');
    const total = org.category_totals[c] || 0;
    const totalPct = org.total_revenue > 0 ? (total / org.total_revenue * 100).toFixed(1) + '%' : '—';
    html += `<tr><td><span class="legend-cat" style="background:${{colorFor(i)}}"></span>${{c}}</td>${{cells}}<td>${{fmt(total)}}<span class="pct">${{totalPct}}</span></td></tr>`;
  }});

  // Total expenses
  const expCells = org.monthly.map(r => {{
    const p = r.revenue > 0 ? (r.total_expense / r.revenue * 100).toFixed(1) + '%' : '—';
    return `<td>${{r.total_expense > 0 ? fmt(r.total_expense) : '<span class="empty">—</span>'}}<span class="pct">${{r.total_expense > 0 ? p : ''}}</span></td>`;
  }}).join('');
  html += `<tr class="row-total"><td>Всього витрати</td>${{expCells}}<td>${{fmt(org.total_expense)}}<span class="pct">${{pct(org.total_expense, org.total_revenue)}}</span></td></tr>`;

  // Net
  const netCells = org.monthly.map(r => `<td>${{fmt(r.net)}}</td>`).join('');
  const netClass = org.net >= 0 ? '' : 'negative';
  html += `<tr class="row-net ${{netClass}}"><td>Net (виручка − витрати)</td>${{netCells}}<td>${{fmt(org.net)}}</td></tr>`;

  html += '</tbody>';
  table.innerHTML = html;
}}

// init
if (DATA.organizations.length === 0) {{
  document.getElementById('main').innerHTML = '<div class="empty-state">Дані за ' + DATA.year + ' рік відсутні у МойСкладі.<br>Перевір DATE_FROM / DATE_TO у build.py та статус документів (applicable).</div>';
}} else {{
  renderTabs();
  renderOrg();
}}

// ─── Refresh data button ────────────────────────────────────────────────────
const DASHBOARD_NAME = 'finance';
const ETA_SEC = 30;

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
  const originalStatus = status.textContent;
  btn.classList.add('loading');
  btn.disabled = true;
  status.classList.remove('error');
  btn.querySelector('.label').textContent = 'Тягне з МойСкладу…';
  status.textContent = `очікувано ~${{ETA_SEC}}s`;

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


if __name__ == "__main__":
    main()
