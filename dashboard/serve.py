#!/usr/bin/env python3
"""
snEco — Local dashboard server.

Запускає HTTP сервер на http://localhost:8765/ що:
  • Віддає всі дашборди (finance, procurement, …)
  • Має /api/refresh/<name> щоб кнопка "Оновити дані" викликала build.py
  • Має /api/status/<name> щоб кнопка опитувала прогрес

Запуск:
    cd ~/snEco-brand-book
    source .venv/bin/activate
    python3 dashboard/serve.py
"""

import json
import os
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

PORT = int(os.environ.get("SNECO_DASHBOARD_PORT", "8765"))
ROOT = Path(__file__).resolve().parent  # ~/snEco-brand-book/dashboard/

DASHBOARDS = {
    "finance": {
        "label": "P&L Dashboard (local preview)",
        "emoji": "💰",
        "html": ROOT / "finance" / "local-preview.html",
        "build": ROOT / "finance" / "build.py",
        "eta_sec": 30,
    },
    "procurement": {
        "label": "Procurement Planning (local preview)",
        "emoji": "📦",
        "html": ROOT / "procurement" / "local-preview.html",
        "build": ROOT / "procurement" / "build.py",
        "eta_sec": 180,
    },
}

# refresh state: name → {running, log_tail, error, started_at, ended_at}
_state = {n: {"running": False, "log_tail": "", "error": None,
              "started_at": 0, "ended_at": 0} for n in DASHBOARDS}
_state_lock = threading.Lock()


def run_refresh(name):
    cfg = DASHBOARDS[name]
    with _state_lock:
        if _state[name]["running"]:
            return
        _state[name] = {"running": True, "log_tail": "", "error": None,
                        "started_at": time.time(), "ended_at": 0}

    cmd = [sys.executable, str(cfg["build"]), "--no-cache"]
    print(f"[refresh:{name}] starting: {' '.join(cmd)}")
    try:
        # Stream output, keep last ~20 lines in state
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, cwd=str(ROOT.parent),
        )
        lines = []
        for line in proc.stdout:
            print(f"[refresh:{name}] {line.rstrip()}")
            lines.append(line.rstrip())
            with _state_lock:
                _state[name]["log_tail"] = "\n".join(lines[-25:])
        proc.wait(timeout=15)
        if proc.returncode != 0:
            with _state_lock:
                _state[name]["error"] = f"build.py exited with code {proc.returncode}"
    except subprocess.TimeoutExpired:
        with _state_lock:
            _state[name]["error"] = "build process didn't terminate cleanly"
        proc.kill()
    except Exception as e:
        with _state_lock:
            _state[name]["error"] = str(e)
    finally:
        with _state_lock:
            _state[name]["running"] = False
            _state[name]["ended_at"] = time.time()
        print(f"[refresh:{name}] done")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a, **kw):  # silence default logging
        pass

    # ── helpers ─────────────────────────────────────────────────────────────

    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html, status=200):
        body = html.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_404(self, msg="Not Found"):
        self._send_html(f"<h1>404</h1><p>{msg}</p>", status=404)

    # ── routes ──────────────────────────────────────────────────────────────

    def do_GET(self):
        path = self.path.split("?", 1)[0].rstrip("/")
        if path == "" or path == "/index.html":
            return self._send_html(self._index_html())

        # /api/status/<name>
        if path.startswith("/api/status/"):
            name = path[len("/api/status/"):]
            if name not in DASHBOARDS:
                return self._send_404("unknown dashboard")
            with _state_lock:
                s = dict(_state[name])
            return self._send_json(s)

        # /finance, /procurement, etc.
        for name, cfg in DASHBOARDS.items():
            if path == f"/{name}":
                try:
                    html = cfg["html"].read_text()
                except FileNotFoundError:
                    return self._send_html(
                        f"<h1>{cfg['emoji']} {cfg['label']}</h1>"
                        f"<p>HTML ще не згенеровано. Запусти спочатку:</p>"
                        f"<pre>python3 dashboard/{name}/build.py</pre>",
                        status=404)
                return self._send_html(html)

        return self._send_404()

    def do_POST(self):
        path = self.path.rstrip("/")
        if path.startswith("/api/refresh/"):
            name = path[len("/api/refresh/"):]
            if name not in DASHBOARDS:
                return self._send_404("unknown dashboard")
            with _state_lock:
                if _state[name]["running"]:
                    return self._send_json({"status": "already_running"}, status=409)
            t = threading.Thread(target=run_refresh, args=(name,), daemon=True)
            t.start()
            return self._send_json({"status": "started"}, status=202)
        return self._send_404()

    # ── index page ──────────────────────────────────────────────────────────

    def _index_html(self):
        cards = "".join(
            f'<a class="card" href="/{name}"><div class="emoji">{cfg["emoji"]}</div>'
            f'<div><div class="label">{cfg["label"]}</div>'
            f'<div class="path">localhost:{PORT}/{name}</div></div></a>'
            for name, cfg in DASHBOARDS.items()
        )
        return f"""<!DOCTYPE html><html lang="uk"><head><meta charset="utf-8">
<title>snEco · Dashboards</title>
<style>
body{{font-family:-apple-system,sans-serif;background:#F4F4EF;padding:48px 24px;max-width:720px;margin:0 auto;color:#1E1E1E}}
h1{{font-size:22px;font-weight:700;margin-bottom:6px}}
.subtitle{{color:#8a8a8a;font-size:13px;margin-bottom:24px}}
.card{{display:flex;align-items:center;gap:16px;background:#fff;border:1px solid #E5E5DC;
  border-radius:12px;padding:18px 22px;margin-bottom:12px;text-decoration:none;color:inherit;
  transition:border-color .15s}}
.card:hover{{border-color:#FEBF27}}
.emoji{{font-size:28px}}
.label{{font-size:16px;font-weight:600}}
.path{{font-size:12px;color:#8a8a8a;margin-top:2px;font-family:ui-monospace,monospace}}
.footer{{margin-top:32px;font-size:12px;color:#8a8a8a;line-height:1.6}}
code{{background:#eee;padding:2px 6px;border-radius:4px;font-size:12px}}
</style></head><body>
<h1>snEco · Dashboards</h1>
<div class="subtitle">Локальний сервер на http://localhost:{PORT}/ · {time.strftime("%H:%M, %d.%m.%Y")}</div>
{cards}
<div class="footer">
Кнопка <strong>Оновити дані</strong> у кожному дашборді викликає <code>build.py --no-cache</code>.
Зупинити сервер: Ctrl-C у Terminal.
</div></body></html>"""


def main():
    addr = ("127.0.0.1", PORT)
    httpd = HTTPServer(addr, Handler)
    url = f"http://localhost:{PORT}/"
    print("═" * 60)
    print(f"  snEco · Dashboard server")
    print(f"  {url}")
    print(f"  Ctrl-C to stop")
    print("═" * 60)
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
