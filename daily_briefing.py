#!/usr/bin/env python3
"""
snEco — Daily Briefing for KAM (v2.73.0 Phase B)

Запускається щодня о 06:00 UTC через GitHub Action.
1. Тягне дані з Cloudflare Worker /api/dashboard/data (counterparties + demands + payments)
2. Розраховує health score per клієнт (та сама логіка що у customer-360.html)
3. Виявляє ACTION ITEMS:
   - 🔴 Overdue AR > 30 днів
   - 🟡 Dormant: gap > 1.5× avg cadence
   - 📞 Next CRM contact today/overdue (з D1, якщо буде backend; v1 — skip)
   - ⚠ Trend 3m < -20% для TOP-50 клієнтів
4. Формує HTML email + надсилає через Resend на vg@sneco.ua + KAM mailing list

ENV:
  WORKER_URL              https://sneco-auth.vg-ab6.workers.dev
  SYNC_API_KEY            secret для Worker (read access via /api/dashboard/data — JWT)
  ADMIN_JWT_TOKEN         JWT з block='dashboard' для read API (видається у Brand Bible Maintenance)
  RESEND_API_KEY          для відправки email
  BRIEFING_TO             comma-separated emails (default: vg@sneco.ua)
"""

import os, sys, json, requests
from datetime import datetime, timedelta, timezone

WORKER  = os.getenv("WORKER_URL", "https://sneco-auth.vg-ab6.workers.dev")
TOKEN   = os.getenv("ADMIN_JWT_TOKEN", "")
RESEND  = os.getenv("RESEND_API_KEY", "")
TO      = [e.strip() for e in os.getenv("BRIEFING_TO", "vg@sneco.ua").split(",") if e.strip()]

if not TOKEN or not RESEND:
    print("❌ ADMIN_JWT_TOKEN + RESEND_API_KEY обов'язкові", file=sys.stderr)
    sys.exit(2)


def fetch(table, limit=50000):
    r = requests.post(
        f"{WORKER}/api/dashboard/data",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"},
        json={"type": table, "limit": limit},
        timeout=60,
    )
    r.raise_for_status()
    return r.json().get("items", [])


def main():
    print("📊 Daily briefing — fetching D1...")
    cps      = fetch("counterparties")
    demands  = fetch("demands")
    payments = fetch("payments")
    print(f"  CP: {len(cps)} · demands: {len(demands)} · payments: {len(payments)}")

    # Build agent index
    cp_by_key = {}
    for c in cps:
        k = c.get("id") or c.get("name")
        if k: cp_by_key[k] = c

    # Aggregate per agent
    today = datetime.now(timezone.utc).date()
    cutoff_30 = (today - timedelta(days=30)).isoformat()
    cutoff_60 = (today - timedelta(days=60)).isoformat()
    dems_by_agent = {}
    for d in demands:
        k = d.get("agent_id") or d.get("agent")
        if not k: continue
        dems_by_agent.setdefault(k, []).append(d)

    # Action items
    overdue_clients   = []   # AR > 30d
    critical_overdue  = []   # AR > 60d
    dormant_topclients = []  # TOP-50 by revenue, gap > 1.5× cadence
    trending_down     = []   # TOP-50, trend3m < -20%

    # First — rank clients by revenue
    rev_per_agent = {}
    for k, dems in dems_by_agent.items():
        rev_per_agent[k] = sum((d.get("sum_kop", 0) or 0) / 100 for d in dems)
    top50 = sorted(rev_per_agent.items(), key=lambda x: -x[1])[:50]
    top50_keys = {k for k, _ in top50}

    for k, dems in dems_by_agent.items():
        cp = cp_by_key.get(k) or {"name": k, "id": None}
        dems_sorted = sorted(dems, key=lambda d: d.get("ms_moment", ""))
        # AR per demand
        overdue_sum = 0
        crit_overdue_sum = 0
        for d in dems_sorted:
            balance_uah = round((((d.get("sum_kop", 0) or 0) - (d.get("payed_sum_kop", 0) or 0)) / 100))
            if balance_uah <= 0: continue
            dt = (d.get("ms_moment", "") or "")[:10]
            if dt and dt <= cutoff_30:
                overdue_sum += balance_uah
            if dt and dt <= cutoff_60:
                crit_overdue_sum += balance_uah
        if crit_overdue_sum > 1000:
            critical_overdue.append({"cp": cp, "sum": crit_overdue_sum})
        elif overdue_sum > 1000:
            overdue_clients.append({"cp": cp, "sum": overdue_sum})

        # Cadence + dormant
        if k in top50_keys and len(dems_sorted) >= 3:
            dates = [datetime.fromisoformat(d.get("ms_moment", "")[:10]) for d in dems_sorted if d.get("ms_moment")]
            if dates:
                gaps = [(dates[i] - dates[i-1]).days for i in range(1, len(dates))]
                avg_cadence = sum(gaps) / len(gaps) if gaps else None
                last_date = dates[-1]
                days_since = (datetime.combine(today, datetime.min.time()) - last_date).days
                if avg_cadence and days_since > avg_cadence * 1.5:
                    dormant_topclients.append({
                        "cp": cp, "days_since": days_since,
                        "avg_cadence": int(avg_cadence), "rev": rev_per_agent[k],
                    })

        # Trend 3 months
        if k in top50_keys and len(dems_sorted) >= 6:
            by_month = {}
            for d in dems_sorted:
                ym = (d.get("ms_moment", "") or "")[:7]
                by_month[ym] = by_month.get(ym, 0) + (d.get("sum_kop", 0) or 0) / 100
            months = sorted(by_month.keys())
            if len(months) >= 6:
                last3 = sum(by_month[m] for m in months[-3:])
                prev3 = sum(by_month[m] for m in months[-6:-3])
                if prev3 > 0:
                    delta_pct = round((last3 - prev3) / prev3 * 100)
                    if delta_pct < -20:
                        trending_down.append({
                            "cp": cp, "delta": delta_pct,
                            "last3": last3, "prev3": prev3,
                        })

    # Sort
    critical_overdue.sort(key=lambda x: -x["sum"])
    overdue_clients.sort(key=lambda x: -x["sum"])
    dormant_topclients.sort(key=lambda x: -x["rev"])
    trending_down.sort(key=lambda x: x["delta"])

    # Format HTML
    today_str = today.strftime("%d.%m.%Y")
    sections_html = []

    def cp_link(cp):
        nm = cp.get("name", "—")
        return f'<a href="https://brand.sneco.ua/dashboard/customer-360/customer-360.html" style="color:#1d5fa6;text-decoration:none">{nm}</a>'

    def fmt_n(n):
        n = int(n)
        if abs(n) >= 1_000_000: return f"{n/1_000_000:.1f}M"
        if abs(n) >= 1_000: return f"{n/1_000:.0f}K"
        return str(n)

    if critical_overdue:
        rows = "\n".join(
            f'<tr><td style="padding:6px 10px"><b>{cp_link(x["cp"])}</b></td>'
            f'<td style="padding:6px 10px;text-align:right;color:#a00;font-weight:700">{fmt_n(x["sum"])} ₴</td></tr>'
            for x in critical_overdue[:10]
        )
        sections_html.append(f"""
        <h3 style="color:#a00;margin-top:20px">🔴 КРИТИЧНО — overdue &gt; 60 днів ({len(critical_overdue)} клієнтів)</h3>
        <table style="width:100%;border-collapse:collapse;font-size:13px">{rows}</table>
        <p style="font-size:12px;color:#666">Σ {fmt_n(sum(x['sum'] for x in critical_overdue))} ₴ — терміново дзвонити сьогодні</p>
        """)

    if overdue_clients:
        rows = "\n".join(
            f'<tr><td style="padding:6px 10px"><b>{cp_link(x["cp"])}</b></td>'
            f'<td style="padding:6px 10px;text-align:right;color:#996600;font-weight:600">{fmt_n(x["sum"])} ₴</td></tr>'
            for x in overdue_clients[:10]
        )
        sections_html.append(f"""
        <h3 style="color:#996600;margin-top:20px">🟡 Overdue 30-60 днів ({len(overdue_clients)} клієнтів)</h3>
        <table style="width:100%;border-collapse:collapse;font-size:13px">{rows}</table>
        """)

    if dormant_topclients:
        rows = "\n".join(
            f'<tr><td style="padding:6px 10px"><b>{cp_link(x["cp"])}</b></td>'
            f'<td style="padding:6px 10px;text-align:right;color:#555">{x["days_since"]} дн (норма {x["avg_cadence"]})</td>'
            f'<td style="padding:6px 10px;text-align:right;color:#666">{fmt_n(x["rev"])} ₴ LTV</td></tr>'
            for x in dormant_topclients[:10]
        )
        sections_html.append(f"""
        <h3 style="color:#1d5fa6;margin-top:20px">📞 Dormant ТОП-50 — час реактивації ({len(dormant_topclients)})</h3>
        <table style="width:100%;border-collapse:collapse;font-size:13px">{rows}</table>
        """)

    if trending_down:
        rows = "\n".join(
            f'<tr><td style="padding:6px 10px"><b>{cp_link(x["cp"])}</b></td>'
            f'<td style="padding:6px 10px;text-align:right;color:#a00;font-weight:700">{x["delta"]}%</td>'
            f'<td style="padding:6px 10px;text-align:right;color:#666">{fmt_n(x["last3"])} vs {fmt_n(x["prev3"])}</td></tr>'
            for x in trending_down[:10]
        )
        sections_html.append(f"""
        <h3 style="color:#a00;margin-top:20px">📉 ТОП-50 з негативним 3-міс трендом ({len(trending_down)})</h3>
        <table style="width:100%;border-collapse:collapse;font-size:13px">{rows}</table>
        """)

    body = "\n".join(sections_html) if sections_html else "<p style='color:#4a7000;font-weight:600'>✅ Усе спокійно — критичних action items немає.</p>"

    html = f"""<!DOCTYPE html>
<html><body style="font-family:-apple-system,Helvetica,Arial,sans-serif;background:#f3f3f0;padding:20px;color:#1E1E1E">
<div style="max-width:680px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.05)">
  <div style="background:#1E1E1E;padding:22px 28px">
    <div style="color:#FEBF27;font-size:20px;font-weight:800;letter-spacing:-.3px">snEco · Daily Briefing</div>
    <div style="color:rgba(255,255,255,.7);font-size:12px;margin-top:4px">{today_str} · KAM action items</div>
  </div>
  <div style="padding:22px 28px">
    {body}
    <hr style="margin:24px 0;border:0;border-top:1px solid #eee">
    <p style="font-size:11px;color:#999">
      Згенеровано автоматично з Customer 360 dashboard.<br>
      Деталі на: <a href="https://brand.sneco.ua/dashboard/customer-360/customer-360.html" style="color:#1d5fa6">brand.sneco.ua/dashboard/customer-360</a>
    </p>
  </div>
</div>
</body></html>"""

    # Send via Resend
    r = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {RESEND}", "Content-Type": "application/json"},
        json={
            "from": "noreply@sneco.ua",
            "to": TO,
            "subject": f"snEco Daily · {today_str} · {len(critical_overdue) + len(overdue_clients) + len(dormant_topclients) + len(trending_down)} action items",
            "html": html,
        },
        timeout=30,
    )
    if r.ok:
        print(f"✅ Briefing sent → {', '.join(TO)}")
    else:
        print(f"❌ Resend {r.status_code}: {r.text[:300]}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
