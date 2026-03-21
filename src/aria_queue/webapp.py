from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .contracts import load_declaration, preflight, run_ucc, save_declaration
from .core import add_queue_item, get_active_progress, load_queue, load_state, save_state, start_background_process, summarize_queue
from .install import install_all, status_all, uninstall_all


INDEX_HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ariaflow</title>
    <style>
    :root {
      color-scheme: dark;
      --bg: #08111f;
      --panel: rgba(15, 23, 42, 0.88);
      --panel-2: rgba(8, 17, 31, 0.9);
      --line: rgba(148, 163, 184, 0.18);
      --text: #e2e8f0;
      --muted: #94a3b8;
      --accent: #7dd3fc;
      --accent-2: #34d399;
      --warn: #fbbf24;
      --danger: #fb7185;
      --shadow: 0 20px 60px rgba(0, 0, 0, 0.35);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background:
        radial-gradient(circle at top left, rgba(125, 211, 252, 0.14), transparent 32%),
        radial-gradient(circle at top right, rgba(52, 211, 153, 0.12), transparent 28%),
        linear-gradient(180deg, #050b15 0%, var(--bg) 100%);
      min-height: 100vh;
    }
    .wrap { max-width: 1180px; margin: 0 auto; padding: 28px 20px 42px; }
    .hero {
      display: grid;
      grid-template-columns: 1.5fr 1fr;
      gap: 18px;
      align-items: end;
      margin-bottom: 18px;
    }
    .title h1 { margin: 0; font-size: clamp(2rem, 4vw, 3.6rem); letter-spacing: -0.04em; }
    .title p { margin: 10px 0 0; color: var(--muted); max-width: 70ch; line-height: 1.5; }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 18px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(16px);
    }
    .grid { display: grid; grid-template-columns: repeat(12, 1fr); gap: 16px; }
    .span-12 { grid-column: span 12; }
    .span-8 { grid-column: span 8; }
    .span-7 { grid-column: span 7; }
    .span-5 { grid-column: span 5; }
    .span-4 { grid-column: span 4; }
    .span-6 { grid-column: span 6; }
    .summary {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
    }
    .metric {
      background: linear-gradient(180deg, rgba(15, 23, 42, 0.95), rgba(2, 6, 23, 0.85));
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 14px;
      min-height: 92px;
    }
    .metric .label { color: var(--muted); font-size: 0.82rem; text-transform: uppercase; letter-spacing: 0.08em; }
    .metric .value { font-size: 1.75rem; font-weight: 700; margin-top: 8px; letter-spacing: -0.03em; }
    .metric .sub { color: var(--muted); font-size: 0.92rem; margin-top: 6px; }
    .toolbar { display: grid; gap: 12px; }
    .row { display: flex; gap: 10px; flex-wrap: wrap; }
    .row > * { flex: 1 1 160px; }
    input, textarea, button { font: inherit; }
    input, textarea {
      width: 100%;
      border-radius: 12px;
      border: 1px solid var(--line);
      background: var(--panel-2);
      color: var(--text);
      padding: 12px 14px;
      outline: none;
    }
    textarea { min-height: 220px; resize: vertical; line-height: 1.45; }
    input::placeholder, textarea::placeholder { color: #64748b; }
    input:focus, textarea:focus { border-color: rgba(125, 211, 252, 0.65); box-shadow: 0 0 0 3px rgba(125, 211, 252, 0.12); }
    button {
      border: 1px solid transparent;
      border-radius: 12px;
      padding: 11px 14px;
      background: linear-gradient(180deg, #7dd3fc, #38bdf8);
      color: #082f49;
      font-weight: 700;
      cursor: pointer;
    }
    button.secondary {
      background: rgba(15, 23, 42, 0.85);
      color: var(--text);
      border-color: var(--line);
    }
    button:hover { filter: brightness(1.05); }
    .section-title { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 14px; }
    .section-title h2 { margin: 0; font-size: 1.05rem; letter-spacing: -0.02em; }
    .section-title .hint { color: var(--muted); font-size: 0.92rem; }
    .list { display: grid; gap: 10px; }
    .item {
      border: 1px solid var(--line);
      background: rgba(8, 17, 31, 0.65);
      border-radius: 14px;
      padding: 14px;
    }
    .item-top {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      margin-bottom: 8px;
    }
    .item-url {
      font-weight: 600;
      overflow: hidden;
      text-overflow: ellipsis;
      word-break: break-all;
    }
    .meta { display: flex; gap: 8px; flex-wrap: wrap; color: var(--muted); font-size: 0.9rem; }
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 5px 10px;
      border-radius: 999px;
      font-size: 0.82rem;
      border: 1px solid var(--line);
      background: rgba(15, 23, 42, 0.7);
      color: var(--text);
    }
    .badge.good { border-color: rgba(52, 211, 153, 0.4); color: #86efac; }
    .badge.warn { border-color: rgba(251, 191, 36, 0.35); color: #fcd34d; }
    .badge.bad { border-color: rgba(251, 113, 133, 0.35); color: #fda4af; }
    .meter { height: 11px; background: rgba(15, 23, 42, 0.95); border-radius: 999px; overflow: hidden; border: 1px solid var(--line); }
    .meter > div { height: 100%; width: 0%; background: linear-gradient(90deg, var(--accent-2), var(--accent)); transition: width 180ms ease; }
    .statusline { display: flex; justify-content: space-between; gap: 12px; color: var(--muted); font-size: 0.92rem; margin-top: 10px; }
    .statusline strong { color: var(--text); }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
    .declaration { display: grid; gap: 12px; }
    details.debug {
      margin-top: 12px;
      border-top: 1px solid var(--line);
      padding-top: 12px;
    }
    details.debug summary {
      cursor: pointer;
      color: var(--muted);
      font-size: 0.9rem;
      list-style: none;
    }
    details.debug summary::-webkit-details-marker { display: none; }
    .debug-box {
      margin-top: 10px;
      padding: 12px;
      background: rgba(2, 6, 23, 0.65);
      border: 1px solid var(--line);
      border-radius: 12px;
      white-space: pre-wrap;
      word-break: break-word;
      max-height: 280px;
      overflow: auto;
      font-size: 0.9rem;
    }
    .footer { color: var(--muted); font-size: 0.88rem; margin-top: 10px; }
    @media (max-width: 980px) {
      .hero, .summary { grid-template-columns: 1fr; }
      .span-8, .span-7, .span-5, .span-4, .span-6 { grid-column: span 12; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <div class="title">
        <h1>ariaflow</h1>
        <p>Headless queue engine with an optional local dashboard. Add a URL, run one download at a time, and keep the control surface focused on what matters.</p>
      </div>
      <div class="panel">
        <div class="statusline">
          <span>Mode</span>
          <strong id="mode-label">idle</strong>
        </div>
        <div class="statusline">
          <span>Active</span>
          <strong id="active-label" class="mono">none</strong>
        </div>
        <div class="statusline">
          <span>Queue</span>
          <strong id="queue-label">0 items</strong>
        </div>
        <div class="summary" style="margin-top:14px;">
          <div class="metric"><div class="label">Waiting</div><div class="value" id="sum-queued">0</div><div class="sub">queued items</div></div>
          <div class="metric"><div class="label">Done</div><div class="value" id="sum-done">0</div><div class="sub">completed</div></div>
          <div class="metric"><div class="label">Errors</div><div class="value" id="sum-error">0</div><div class="sub">failed items</div></div>
          <div class="metric"><div class="label">Speed</div><div class="value" id="sum-speed">-</div><div class="sub">active transfer</div></div>
        </div>
      </div>
    </div>
    <div class="grid">
      <div class="span-12">
        <div class="panel toolbar">
          <div class="row">
            <input id="url" placeholder="Paste download URL">
            <button onclick="add()">Add to queue</button>
            <button class="secondary" onclick="preflightRun()">Preflight</button>
            <button class="secondary" onclick="runQueue()">Run</button>
            <button class="secondary" onclick="uccRun()">UCC</button>
            <button class="secondary" onclick="pauseQueue()">Pause</button>
            <button class="secondary" onclick="resumeQueue()">Resume</button>
          </div>
        </div>
      </div>
      <div class="span-12">
        <div class="panel">
          <div class="section-title">
            <h2>Queue</h2>
            <div class="hint">One download at a time</div>
          </div>
          <div id="queue" class="list">Loading...</div>
        </div>
      </div>
      <div class="span-7">
        <div class="panel">
          <div class="section-title">
            <h2>Active download</h2>
            <div class="hint">Live progress</div>
          </div>
          <div class="meter"><div id="bar"></div></div>
          <div id="active" style="margin-top:12px;">Idle</div>
        </div>
      </div>
      <div class="span-5">
        <div class="panel">
          <div class="section-title">
            <h2>Lifecycle</h2>
            <div class="hint">Install state and services</div>
          </div>
          <div class="row" style="margin-bottom:12px;">
            <button class="secondary" onclick="loadLifecycle()">Refresh lifecycle</button>
            <button class="secondary" onclick="previewInstall()">Install preview</button>
            <button class="secondary" onclick="previewUninstall()">Uninstall preview</button>
          </div>
          <div id="lifecycle" class="list">Loading...</div>
        </div>
      </div>
      <div class="span-6">
        <div class="panel">
          <div class="section-title">
            <h2>Result</h2>
            <div class="hint">Latest action output</div>
          </div>
          <div id="result" class="mono" style="white-space:pre-wrap;word-break:break-word;color:var(--text)">Idle</div>
          <details class="debug">
            <summary>Debug JSON</summary>
            <div id="result-json" class="debug-box">Idle</div>
          </details>
        </div>
      </div>
      <div class="span-6">
        <div class="panel declaration">
          <div class="section-title">
            <h2>Declaration</h2>
            <div class="hint">UIC settings and policy</div>
          </div>
          <textarea id="declaration" placeholder="Loading declaration..."></textarea>
          <div class="row">
            <button class="secondary" onclick="loadDeclaration()">Load</button>
            <button class="secondary" onclick="saveDeclaration()">Save</button>
          </div>
        </div>
      </div>
    </div>
    <div class="footer">
      Local-only dashboard. Web UI is optional; the engine stays headless.
    </div>
  </div>
  <script>
    let lastStatus = null;
    let lastLifecycle = null;
    let lastResult = null;
    let lastDeclaration = null;

    function badgeClass(status) {
      if (["done", "converged", "ok", "complete"].includes(status)) return "badge good";
      if (["error", "failed", "missing"].includes(status)) return "badge bad";
      if (["paused", "queued", "unchanged", "skipped"].includes(status)) return "badge warn";
      return "badge";
    }
    function renderQueueItem(item) {
      const status = item.status || "unknown";
      const detail = [
        item.created_at ? `Created ${item.created_at}` : null,
        item.post_action_rule ? `Rule ${item.post_action_rule}` : null,
        item.gid ? `GID ${item.gid}` : null,
        item.error_message ? item.error_message : null,
      ].filter(Boolean).join(" · ");
      return `
        <div class="item">
          <div class="item-top">
            <div class="item-url">${item.url || "(no url)"}</div>
            <span class="${badgeClass(status)}">${status}</span>
          </div>
          <div class="meta">
            ${detail ? `<span>${detail}</span>` : ""}
          </div>
        </div>
      `;
    }
    function renderLifecycleItem(name, record) {
      const result = record && record.result ? record.result : {};
      const lines = [];
      if (result.message) lines.push(result.message);
      if (result.reason) lines.push(`Reason: ${result.reason}`);
      if (result.completion) lines.push(`Completion: ${result.completion}`);
      return `
        <div class="item">
          <div class="item-top">
            <div class="item-url">${name}</div>
            <span class="${badgeClass(result.outcome)}">${result.outcome || "unknown"}</span>
          </div>
          <div class="meta">
            <span>${lines.join(" · ") || "No details"}</span>
          </div>
        </div>
      `;
    }
    function renderLifecycleSummary(data) {
      const items = [
        ["ariaflow", data.ariaflow],
        ["aria2", data["aria2-launchd"]],
        ["web", data["ariaflow-serve-launchd"]],
      ].map(([name, record]) => {
        const result = record && record.result ? record.result : {};
        return `
          <div class="item">
            <div class="item-top">
              <div class="item-url">${name}</div>
              <span class="${badgeClass(result.outcome)}">${result.outcome || "unknown"}</span>
            </div>
            <div class="meta">
              <span>${result.message || "No details"}</span>
            </div>
          </div>
        `;
      });
      return items.join("");
    }
    function renderQueueSummary(summary) {
      document.getElementById('sum-queued').textContent = summary?.queued ?? 0;
      document.getElementById('sum-done').textContent = summary?.done ?? 0;
      document.getElementById('sum-error').textContent = summary?.error ?? 0;
    }
    async function refresh() {
      const r = await fetch('/api/status');
      const data = await r.json();
      lastStatus = data;
      document.getElementById('queue').innerHTML = (data.items || []).length ? data.items.map(renderQueueItem).join("") : "<div class='item'>Queue is empty.</div>";
      const active = data.active || {status: 'idle'};
      const speed = active.downloadSpeed || data.state?.download_speed || "-";
      document.getElementById('active').innerHTML = `
        <div class="item">
          <div class="item-top">
            <div class="item-url">${active.url || "No active download"}</div>
            <span class="${badgeClass(active.status)}">${active.status || "idle"}</span>
          </div>
          <div class="meta">
            <span>Progress ${Math.round(Number(active.percent || 0))}%</span>
            ${active.downloadSpeed ? `<span>Speed ${active.downloadSpeed}</span>` : ""}
            ${active.totalLength ? `<span>Total ${active.totalLength}</span>` : ""}
            ${active.completedLength ? `<span>Done ${active.completedLength}</span>` : ""}
          </div>
          <div class="statusline">
            <span>GID <strong>${active.gid || "none"}</strong></span>
            <span>${active.errorMessage || ""}</span>
          </div>
        </div>
      `;
      const percent = active && active.percent != null ? active.percent : 0;
      document.getElementById('bar').style.width = percent + '%';
      document.getElementById('mode-label').textContent = data.state && data.state.paused ? 'paused' : (data.state && data.state.running ? 'running' : 'idle');
      document.getElementById('active-label').textContent = active.url || 'none';
      document.getElementById('queue-label').textContent = `${(data.summary && data.summary.total) || 0} item(s)`;
      document.getElementById('sum-speed').textContent = speed && speed !== "-" ? speed : "-";
      renderQueueSummary(data.summary);
    }
    async function loadLifecycle() {
      const r = await fetch('/api/lifecycle');
      const data = await r.json();
      lastLifecycle = data;
      document.getElementById('lifecycle').innerHTML = renderLifecycleSummary(data);
    }
    async function pauseQueue() {
      const r = await fetch('/api/pause', { method: 'POST' });
      const data = await r.json();
      lastResult = data;
      document.getElementById('result').textContent = data.paused ? "Queue paused" : "Queue not paused";
      document.getElementById('result-json').textContent = JSON.stringify(data, null, 2);
      await refresh();
    }
    async function resumeQueue() {
      const r = await fetch('/api/resume', { method: 'POST' });
      const data = await r.json();
      lastResult = data;
      document.getElementById('result').textContent = data.paused ? "Queue paused" : "Queue resumed";
      document.getElementById('result-json').textContent = JSON.stringify(data, null, 2);
      await refresh();
    }
    async function add() {
      const url = document.getElementById('url').value.trim();
      const r = await fetch('/api/add', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({url}) });
      const data = await r.json();
      lastResult = data;
      document.getElementById('result').textContent = `Queued: ${data.added?.url || url}`;
      document.getElementById('result-json').textContent = JSON.stringify(data, null, 2);
      await refresh();
    }
    async function preflightRun() {
      const r = await fetch('/api/preflight', { method: 'POST' });
      const data = await r.json();
      lastResult = data;
      document.getElementById('result').textContent = data.status === 'pass' ? "Preflight passed" : "Preflight needs attention";
      document.getElementById('result-json').textContent = JSON.stringify(data, null, 2);
    }
    async function runQueue() {
      const r = await fetch('/api/run', { method: 'POST' });
      const data = await r.json();
      lastResult = data;
      document.getElementById('result').textContent = data.started ? "Queue runner started" : "Queue runner already running";
      document.getElementById('result-json').textContent = JSON.stringify(data, null, 2);
    }
    async function uccRun() {
      const r = await fetch('/api/ucc', { method: 'POST' });
      const data = await r.json();
      lastResult = data;
      const outcome = data.result && data.result.outcome ? data.result.outcome : "unknown";
      document.getElementById('result').textContent = `UCC result: ${outcome}`;
      document.getElementById('result-json').textContent = JSON.stringify(data, null, 2);
      await refresh();
    }
    async function previewInstall() {
      const r = await fetch('/api/lifecycle/install', { method: 'POST' });
      lastLifecycle = await r.json();
      document.getElementById('lifecycle').innerHTML = renderLifecycleSummary(lastLifecycle);
    }
    async function previewUninstall() {
      const r = await fetch('/api/lifecycle/uninstall', { method: 'POST' });
      lastLifecycle = await r.json();
      document.getElementById('lifecycle').innerHTML = renderLifecycleSummary(lastLifecycle);
    }
    async function loadDeclaration() {
      const r = await fetch('/api/declaration');
      lastDeclaration = await r.json();
      document.getElementById('declaration').value = JSON.stringify(lastDeclaration, null, 2);
    }
    async function saveDeclaration() {
      const value = document.getElementById('declaration').value;
      const parsed = JSON.parse(value);
      const r = await fetch('/api/declaration', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(parsed) });
      const data = await r.json();
      lastResult = data;
      document.getElementById('result').textContent = "Declaration saved";
      document.getElementById('result-json').textContent = JSON.stringify(data, null, 2);
    }
    refresh();
    setInterval(refresh, 2000);
    loadDeclaration();
    loadLifecycle();
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
            state = load_state()
            items = load_queue()
            payload = {"items": items, "state": state, "summary": summarize_queue(items)}
            active = get_active_progress()
            if active:
                payload["active"] = active
            self._send_json(payload)
            return
        if path == "/api/declaration":
            self._send_json(load_declaration())
            return
        if path == "/api/lifecycle":
            self._send_json(status_all())
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
            self._send_json(start_background_process())
            return

        if path == "/api/ucc":
            self._send_json(run_ucc())
            return

        if path == "/api/declaration":
            declaration = payload if isinstance(payload, dict) else {}
            saved = save_declaration(declaration)
            self._send_json({"saved": True, "declaration": saved})
            return

        if path == "/api/lifecycle/install":
            self._send_json(install_all(dry_run=True, include_web=False))
            return

        if path == "/api/lifecycle/uninstall":
            self._send_json(uninstall_all(dry_run=True, include_web=False))
            return

        if path == "/api/pause":
            state = load_state()
            state["paused"] = True
            save_state(state)
            self._send_json({"paused": True})
            return

        if path == "/api/resume":
            state = load_state()
            state["paused"] = False
            save_state(state)
            self._send_json({"paused": False})
            return

        self._send_json({"error": "not_found"}, status=404)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


def serve(host: str = "127.0.0.1", port: int = 8000) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), AriaFlowHandler)
