from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .contracts import preflight, run_ucc
from .core import add_queue_item, load_queue


INDEX_HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ariaflow</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 0; background: #111827; color: #e5e7eb; }
    .wrap { max-width: 920px; margin: 0 auto; padding: 24px; }
    .card { background: #1f2937; border: 1px solid #374151; border-radius: 14px; padding: 16px; margin: 16px 0; }
    input, button { font: inherit; }
    input { width: 100%; padding: 12px; border-radius: 10px; border: 1px solid #4b5563; background: #111827; color: #e5e7eb; }
    button { padding: 10px 14px; border: 0; border-radius: 10px; background: #22c55e; color: #052e16; font-weight: 700; cursor: pointer; }
    button.secondary { background: #60a5fa; color: #eff6ff; }
    pre { white-space: pre-wrap; word-break: break-word; background: #0b1220; padding: 12px; border-radius: 10px; }
    .row { display: flex; gap: 10px; flex-wrap: wrap; }
    .row > * { flex: 1 1 180px; }
  </style>
</head>
<body>
  <div class="wrap">
    <h1>ariaflow</h1>
    <p>Local queue manager for aria2 with preflight, adaptive bandwidth, and post-action hooks.</p>
    <div class="card">
      <div class="row">
        <input id="url" placeholder="Paste download URL">
        <button onclick="add()">Add</button>
        <button class="secondary" onclick="preflightRun()">Preflight</button>
        <button class="secondary" onclick="runQueue()">Run</button>
      </div>
    </div>
    <div class="card">
      <h2>Queue</h2>
      <pre id="queue">Loading...</pre>
    </div>
    <div class="card">
      <h2>Result</h2>
      <pre id="result">Idle</pre>
    </div>
  </div>
  <script>
    async function refresh() {
      const r = await fetch('/api/status');
      document.getElementById('queue').textContent = JSON.stringify(await r.json(), null, 2);
    }
    async function add() {
      const url = document.getElementById('url').value.trim();
      const r = await fetch('/api/add', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({url}) });
      document.getElementById('result').textContent = JSON.stringify(await r.json(), null, 2);
      await refresh();
    }
    async function preflightRun() {
      const r = await fetch('/api/preflight', { method: 'POST' });
      document.getElementById('result').textContent = JSON.stringify(await r.json(), null, 2);
    }
    async function runQueue() {
      const r = await fetch('/api/run', { method: 'POST' });
      document.getElementById('result').textContent = JSON.stringify(await r.json(), null, 2);
      await refresh();
    }
    refresh();
  </script>
</body>
</html>
"""


class AriaFlowHandler(BaseHTTPRequestHandler):
    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in {"/", "/index.html"}:
            body = INDEX_HTML.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/status":
            self._send_json({"items": load_queue()})
            return
        self._send_json({"error": "not_found"}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        payload = json.loads(raw or "{}")

        if path == "/api/add":
            url = payload.get("url", "").strip()
            if not url:
                self._send_json({"error": "missing_url"}, status=400)
                return
            item = add_queue_item(url)
            self._send_json({"added": item.__dict__})
            return

        if path == "/api/preflight":
            self._send_json(preflight())
            return

        if path == "/api/run":
            self._send_json(run_ucc())
            return

        self._send_json({"error": "not_found"}, status=404)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


def serve(host: str = "127.0.0.1", port: int = 8000) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), AriaFlowHandler)

