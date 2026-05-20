#!/usr/bin/env python3
"""
snEco — Sync Health Check (daily 08:00 Київ / 05:00 UTC)

Перевіряє статус усіх sync workflows + ms_sync_log у D1 за останню добу.
Якщо щось failed або lag > N годин — шле email на vg@sneco.ua через Resend.

Env (GitHub Secrets):
    GITHUB_TOKEN          — `${{ secrets.GITHUB_TOKEN }}` (через workflow context)
    SYNC_API_KEY          — для Worker /api/dashboard/data
    WORKER_URL            — https://sneco-auth.vg-ab6.workers.dev
    RESEND_API_KEY        — для email

Запуск: щодня о 05:00 UTC через .github/workflows/sync-health-check.yml
"""

import os
import sys
import json
import time
import requests
from datetime import datetime, timezone, timedelta

WORKER_URL = os.getenv("WORKER_URL", "https://sneco-auth.vg-ab6.workers.dev").rstrip("/")
SYNC_API_KEY = os.getenv("SYNC_API_KEY")
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO = "dreamcarua/sneco-brand-book"
ALERT_EMAIL = "vg@sneco.ua"
SENDER_EMAIL = "noreply@sneco.ua"

# Експектації по lag-у (годин) — sync має бути не старіше за це
# Tolerance 26h — flagged тільки якщо sync пропустив цілий день.
# Це робить health check стійким до manual dispatch у будь-який час доби
# (бо o 17:00 Київ останній моя sync о 06:00 вже 11h тому, але це OK — наступний завтра).
EXPECT_LAG_HOURS = {
    "moysklad-sync.yml": 26,        # 06:00 Київ щодня → 26h tolerance = > доби missed
    "procurement-sync.yml": 26,     # 03:00 Київ щодня → 26h tolerance = > доби missed
    "daily-briefing.yml": 26,       # 09:00 Київ щодня → 26h tolerance = > доби missed
}


def gh_api(path):
    """GitHub API request з auth."""
    url = f"https://api.github.com{path}"
    r = requests.get(url, headers={
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }, timeout=30)
    r.raise_for_status()
    return r.json()


def check_workflow(workflow_file, max_age_h):
    """Перевіряє останній run workflow'у. Повертає dict зі статусом."""
    try:
        data = gh_api(f"/repos/{REPO}/actions/workflows/{workflow_file}/runs?per_page=5&exclude_pull_requests=true")
        runs = data.get("workflow_runs", [])
        # Беремо останній run з ЗАВЕРШЕНИМ статусом (skip in_progress)
        completed = [r for r in runs if r.get("status") == "completed"]
        if not completed:
            return {"workflow": workflow_file, "ok": False, "reason": "no completed runs у останніх 5"}
        last = completed[0]
        conclusion = last.get("conclusion", "unknown")
        updated_at = last.get("updated_at", "")
        if updated_at:
            dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            age_h = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
        else:
            age_h = 999
        ok = conclusion == "success" and age_h <= max_age_h
        return {
            "workflow": workflow_file,
            "ok": ok,
            "conclusion": conclusion,
            "age_h": round(age_h, 1),
            "max_age_h": max_age_h,
            "run_url": last.get("html_url", ""),
            "started_at": last.get("created_at", ""),
            "duration_min": round((dt - datetime.fromisoformat(last.get("created_at", "").replace("Z", "+00:00"))).total_seconds()/60, 1) if updated_at else None,
        }
    except Exception as e:
        return {"workflow": workflow_file, "ok": False, "reason": f"GitHub API error: {e}"}


def check_worker_sync_log():
    """Перевіряє останній ms_sync_log у D1 через Worker (X-Sync-Key auth)."""
    try:
        r = requests.post(
            f"{WORKER_URL}/api/dashboard/last-sync",
            headers={"X-Sync-Key": SYNC_API_KEY, "Content-Type": "application/json"},
            json={},
            timeout=30,
        )
        if not r.ok:
            return {"ok": False, "reason": f"Worker HTTP {r.status_code}: {r.text[:200]}"}
        data = r.json()
        # Recent items (5 latest sync_log rows)
        items = data.get("items", [])
        if not items:
            return {"ok": False, "reason": "ms_sync_log порожній"}
        last = items[0]
        finished = last.get("finished_at") or last.get("started_at")
        age_h = 999
        if finished:
            try:
                ts = int(finished) if isinstance(finished, (int, float)) else int(datetime.fromisoformat(str(finished).replace("Z", "+00:00")).timestamp())
                age_h = (time.time() - ts) / 3600
            except (ValueError, TypeError):
                pass
        return {
            "ok": last.get("status") == "success" and age_h <= 12,
            "status": last.get("status"),
            "trigger": last.get("trigger"),
            "age_h": round(age_h, 1),
            "entities": last.get("entities"),
        }
    except Exception as e:
        return {"ok": False, "reason": f"Worker API error: {e}"}


def send_email(subject, html_body):
    """Send email through Resend."""
    if not RESEND_API_KEY:
        print("⚠️ RESEND_API_KEY missing, skipping email", flush=True)
        return False
    r = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
        json={
            "from": f"snEco Sync Monitor <{SENDER_EMAIL}>",
            "to": [ALERT_EMAIL],
            "subject": subject,
            "html": html_body,
        },
        timeout=30,
    )
    if not r.ok:
        print(f"❌ Resend HTTP {r.status_code}: {r.text[:300]}", flush=True)
        return False
    print(f"✅ Email sent to {ALERT_EMAIL}", flush=True)
    return True


def build_email_html(results, worker_log, all_ok):
    """Build HTML email body."""
    status_color = "#96C11F" if all_ok else "#E84040"
    status_text = "✅ ВСІ SYNC ОК" if all_ok else "⚠ ПРОБЛЕМИ З SYNC"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    rows = ""
    for r in results:
        icon = "✅" if r.get("ok") else "❌"
        wf = r["workflow"]
        if r.get("ok"):
            details = f"{r['conclusion']} · {r['age_h']} год тому"
        else:
            details = r.get("reason") or f"{r.get('conclusion','?')} · {r.get('age_h','?')} год (max {r.get('max_age_h','?')}h)"
        link = f'<a href="{r.get("run_url","#")}" style="color:#FEBF27">{wf}</a>' if r.get("run_url") else wf
        rows += f'<tr><td style="padding:8px 12px;border-bottom:1px solid #eee">{icon}</td><td style="padding:8px 12px;border-bottom:1px solid #eee">{link}</td><td style="padding:8px 12px;border-bottom:1px solid #eee;color:#666">{details}</td></tr>'

    worker_section = ""
    if worker_log:
        wok = "✅" if worker_log.get("ok") else "⚠"
        worker_section = f'''
        <h3 style="margin:24px 0 10px;color:#333">D1 ms_sync_log (Worker view)</h3>
        <table style="width:100%;border-collapse:collapse;font-size:13px">
          <tr><td style="padding:8px 12px;background:#fafaf6">Last status</td><td style="padding:8px 12px">{wok} {worker_log.get("status","?")} · trigger: {worker_log.get("trigger","?")} · {worker_log.get("age_h","?")} год тому</td></tr>
          <tr><td style="padding:8px 12px;background:#fafaf6">Entities</td><td style="padding:8px 12px;font-family:monospace;font-size:11px;color:#666">{json.dumps(worker_log.get("entities") or {}, ensure_ascii=False)[:300]}</td></tr>
        </table>
        '''

    return f'''<!DOCTYPE html>
<html><body style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;background:#F4F4EF;padding:20px;color:#1E1E1E">
  <div style="max-width:600px;margin:0 auto;background:#fff;border-radius:12px;padding:28px;box-shadow:0 2px 8px rgba(0,0,0,.05)">
    <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:.2em;margin-bottom:8px">snEco · Sync Monitor</div>
    <h1 style="font-size:24px;font-weight:800;margin:0 0 16px;color:{status_color}">{status_text}</h1>
    <div style="font-size:13px;color:#666;margin-bottom:20px">Перевірка о {now}</div>

    <table style="width:100%;border-collapse:collapse;font-size:13px">
      <thead>
        <tr style="background:#fafaf6">
          <th style="padding:10px 12px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:#555;border-bottom:2px solid #ddd">✓</th>
          <th style="padding:10px 12px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:#555;border-bottom:2px solid #ddd">Workflow</th>
          <th style="padding:10px 12px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:#555;border-bottom:2px solid #ddd">Status</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>

    {worker_section}

    <div style="margin-top:24px;padding-top:20px;border-top:1px solid #eee;font-size:11px;color:#888">
      Перевіряє: <a href="https://github.com/{REPO}/actions" style="color:#FEBF27">GitHub Actions</a> + Worker last-sync.<br>
      Шле тільки коли ⚠ або раз на день при ✅.<br>
      Перевір дашборди: <a href="https://brand.sneco.ua/dashboard/customer-360/customer-360.html" style="color:#FEBF27">Customer 360</a> ·
      <a href="https://brand.sneco.ua/dashboard/finance/finance.html" style="color:#FEBF27">Finance</a> ·
      <a href="https://brand.sneco.ua/dashboard/procurement/" style="color:#FEBF27">Procurement</a>
    </div>
  </div>
</body></html>'''


def main():
    if not GITHUB_TOKEN:
        print("❌ GITHUB_TOKEN missing", file=sys.stderr); sys.exit(2)

    print(f"🔍 Sync Health Check · {datetime.now(timezone.utc).isoformat()}", flush=True)
    print(f"   Repo: {REPO}", flush=True)
    print(f"   Workflows перевіряємо: {list(EXPECT_LAG_HOURS.keys())}", flush=True)

    results = []
    for wf, max_h in EXPECT_LAG_HOURS.items():
        r = check_workflow(wf, max_h)
        results.append(r)
        icon = "✅" if r.get("ok") else "❌"
        print(f"   {icon} {wf}: {r}", flush=True)

    worker_log = None
    if SYNC_API_KEY:
        worker_log = check_worker_sync_log()
        print(f"   📊 Worker last-sync: {worker_log}", flush=True)

    all_ok = all(r.get("ok") for r in results)
    is_friday = datetime.now(timezone.utc).weekday() == 4  # Friday — weekly summary
    should_email = not all_ok or is_friday

    if should_email:
        subject = f"{'⚠' if not all_ok else '✅'} snEco Sync Monitor · {'PROBLEMS' if not all_ok else 'Weekly summary'}"
        html = build_email_html(results, worker_log, all_ok)
        send_email(subject, html)
    else:
        print("✅ All sync OK + not Friday → email skipped", flush=True)

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
