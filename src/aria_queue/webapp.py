from __future__ import annotations

import json
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .api import (
    add_queue_item,
    active_gids,
    active_status,
    auto_preflight_on_run,
    aria_status,
    current_bandwidth,
    current_global_options,
    get_active_progress,
    homebrew_install_ariaflow,
    homebrew_uninstall_ariaflow,
    install_aria2_launchd,
    is_macos,
    load_action_log,
    load_declaration,
    load_queue,
    load_state,
    pause_active_transfer,
    preflight,
    record_action,
    resume_active_transfer,
    run_ucc,
    save_declaration,
    save_state,
    start_background_process,
    start_new_state_session,
    status_all,
    stop_background_process,
    summarize_queue,
    uninstall_aria2_launchd,
    ucc_record,
)
from .core import format_bytes, format_mbps, format_rate


STATUS_CACHE: dict[str, object] = {"ts": 0.0, "payload": None}
STATUS_CACHE_TTL = 2.0


def _session_fields() -> dict[str, object]:
    state = load_state()
    return {
        "session_id": state.get("session_id"),
        "session_started_at": state.get("session_started_at"),
        "session_last_seen_at": state.get("session_last_seen_at"),
        "session_closed_at": state.get("session_closed_at"),
        "session_closed_reason": state.get("session_closed_reason"),
    }


def _lifecycle_payload() -> dict[str, object]:
    lifecycle = status_all()
    lifecycle.update(_session_fields())
    return lifecycle


INDEX_HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ariaflow</title>
    <style>
    :root {
      color-scheme: light dark;
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
    :root[data-theme="light"] {
      color-scheme: light;
      --bg: #f5f7fb;
      --panel: rgba(255, 255, 255, 0.88);
      --panel-2: rgba(248, 250, 252, 0.92);
      --line: rgba(15, 23, 42, 0.12);
      --text: #0f172a;
      --muted: #475569;
      --shadow: 0 20px 60px rgba(15, 23, 42, 0.08);
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
    .wrap { max-width: 1180px; margin: 0 auto; padding: 20px 20px 32px; }
    .hero {
      display: grid;
      grid-template-columns: minmax(0, 0.82fr) minmax(0, 1.18fr);
      gap: 10px;
      align-items: end;
      margin-bottom: 10px;
    }
    .title h1 { margin: 0; font-size: clamp(1.45rem, 2.4vw, 2.1rem); letter-spacing: -0.04em; }
    .title p { margin: 4px 0 0; color: var(--muted); max-width: 44ch; line-height: 1.35; font-size: 0.88rem; }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 14px;
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
      gap: 10px;
    }
    .metric {
      background: linear-gradient(180deg, rgba(15, 23, 42, 0.95), rgba(2, 6, 23, 0.85));
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 11px 12px;
      min-height: 76px;
    }
    .metric .label { color: var(--muted); font-size: 0.74rem; text-transform: uppercase; letter-spacing: 0.08em; }
    .metric .value { font-size: 1.45rem; font-weight: 700; margin-top: 4px; letter-spacing: -0.03em; }
    .metric .sub { color: var(--muted); font-size: 0.82rem; margin-top: 3px; }
    .topline {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-bottom: 8px;
      color: var(--muted);
      font-size: 0.88rem;
    }
    .topline strong { color: var(--text); }
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
    .item.compact {
      padding: 12px 14px;
      display: grid;
      gap: 8px;
    }
    .item.compact.active-item {
      border-color: rgba(125, 211, 252, 0.35);
      box-shadow: inset 0 0 0 1px rgba(125, 211, 252, 0.12);
      background: rgba(8, 17, 31, 0.82);
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
    .transfer {
      display: grid;
      gap: 12px;
    }
    .transfer-head {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: flex-start;
    }
    .transfer-name {
      font-size: 1.08rem;
      font-weight: 700;
      letter-spacing: -0.02em;
      word-break: break-all;
    }
    .transfer-sub {
      color: var(--muted);
      font-size: 0.9rem;
      margin-top: 4px;
      word-break: break-all;
    }
    .action-strip {
      display: inline-flex;
      gap: 8px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }
    .icon-btn {
      padding: 8px 10px;
      min-width: 38px;
      border-radius: 999px;
      line-height: 1;
    }
    .sr-only {
      position: absolute;
      width: 1px;
      height: 1px;
      padding: 0;
      margin: -1px;
      overflow: hidden;
      clip: rect(0, 0, 0, 0);
      white-space: nowrap;
      border: 0;
    }
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
    .chips { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 12px; }
    .chip {
      padding: 8px 12px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: rgba(8, 17, 31, 0.7);
      color: var(--text);
      font-size: 0.88rem;
    }
    .chip strong { color: #fff; }
    .nav {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin: 0 0 18px;
    }
    .nav .spacer {
      flex: 1 1 auto;
    }
    .nav a {
      text-decoration: none;
      color: var(--text);
      padding: 8px 12px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: rgba(8, 17, 31, 0.55);
    }
    .nav a.active {
      background: linear-gradient(180deg, #7dd3fc, #38bdf8);
      color: #082f49;
      border-color: transparent;
      font-weight: 700;
    }
    .nav button {
      padding: 8px 12px;
      border-radius: 999px;
      min-width: 110px;
    }
    .refresh-control {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 8px 12px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: rgba(15, 23, 42, 0.85);
      color: var(--text);
      font-size: 0.9rem;
    }
    .refresh-control select {
      border: 0;
      background: transparent;
      color: inherit;
      font: inherit;
      outline: none;
      appearance: none;
      cursor: pointer;
    }
    .page-only { display: none; }
    body.page-dashboard .show-dashboard,
    body.page-bandwidth .show-bandwidth,
    body.page-lifecycle .show-lifecycle,
    body.page-options .show-options,
    body.page-log .show-log { display: block; }
    @media (max-width: 980px) {
      .hero, .summary { grid-template-columns: 1fr; }
      .hero { align-items: start; }
      .span-8, .span-7, .span-5, .span-4, .span-6 { grid-column: span 12; }
    }
  </style>
</head>
<body data-page="dashboard">
  <div class="wrap">
    <div class="nav">
      <a href="/" data-page="dashboard">Dashboard</a>
      <a href="/bandwidth" data-page="bandwidth">Bandwidth</a>
      <a href="/lifecycle" data-page="lifecycle">Service Status</a>
      <a href="/options" data-page="options">Options</a>
      <a href="/log" data-page="log">Log</a>
      <div class="spacer"></div>
      <label class="refresh-control" for="refresh-interval">
        Refresh
        <select id="refresh-interval" onchange="setRefreshInterval(this.value)">
          <option value="1500">1.5s</option>
          <option value="3000">3s</option>
          <option value="5000">5s</option>
          <option value="10000" selected>10s</option>
          <option value="30000">30s</option>
          <option value="0">Off</option>
        </select>
      </label>
      <button class="secondary" id="theme-btn" onclick="toggleTheme()">Theme</button>
    </div>
    <div class="hero">
      <div class="title">
        <h1>ariaflow</h1>
        <p>Headless queue engine with a local dashboard.</p>
      </div>
      <div class="panel">
        <div class="topline">
          <span>Mode: <strong id="mode-label">idle</strong></span>
          <span>Job: <strong id="active-label" class="mono">none</strong></span>
          <span>Speed: <strong id="sum-speed">-</strong></span>
        </div>
        <div class="chips">
          <div class="chip">Runner <strong id="chip-runner">idle</strong></div>
          <div class="chip">Cap <strong id="chip-cap">-</strong></div>
          <div class="chip">Last issue <strong id="chip-error">none</strong></div>
        <div class="chip">Run <strong id="chip-session">-</strong></div>
        </div>
        <div class="summary" style="margin-top:10px;">
          <div class="metric"><div class="label">Waiting</div><div class="value" id="sum-queued">0</div><div class="sub">queued jobs</div></div>
          <div class="metric"><div class="label">Done</div><div class="value" id="sum-done">0</div><div class="sub">completed</div></div>
          <div class="metric"><div class="label">Errors</div><div class="value" id="sum-error">0</div><div class="sub">failed jobs</div></div>
        </div>
      </div>
    </div>
    <div class="grid">
      <div class="span-12 show-dashboard page-only">
        <div class="panel toolbar">
          <div class="row">
            <textarea id="url" rows="3" placeholder="Paste one or more URLs, one per line"></textarea>
            <button onclick="add()">Add to queue</button>
          </div>
        </div>
      </div>
      <div class="span-12 show-dashboard page-only">
        <div class="panel toolbar">
          <div class="section-title" style="margin-bottom:0;">
            <h2>Controls</h2>
            <div class="hint">Global engine actions</div>
          </div>
          <div class="row">
            <button class="secondary" onclick="preflightRun()">Preflight</button>
            <button class="secondary" id="runner-btn" onclick="toggleRunner()">Start engine</button>
            <button class="secondary" id="toggle-btn" onclick="toggleQueue()">Pause</button>
            <button class="secondary" onclick="newSession()">Start new run</button>
          </div>
          <label class="refresh-control" style="justify-self:start; margin-top:-2px;">
            <input type="checkbox" id="auto-preflight" onchange="setAutoPreflightPreference(this.checked)">
            Run preflight before start
          </label>
        </div>
      </div>
      <div class="span-12 show-dashboard page-only">
        <div class="panel">
          <div class="section-title">
            <h2>Queue</h2>
            <div class="hint">Multiple jobs supported; live transfer shown in the row</div>
          </div>
          <div id="queue" class="list">Loading...</div>
        </div>
      </div>
      <div class="span-5 show-bandwidth page-only">
        <div class="panel">
          <div class="section-title">
            <h2>Bandwidth</h2>
            <div class="hint">Probe and cap</div>
          </div>
          <div class="list" style="margin-bottom:12px;">
            <div class="item">
              <div class="item-top"><div class="item-url">Probe result</div><span class="badge" id="bw-source">-</span></div>
              <div class="meta"><span id="bw-down">No probe yet</span></div>
            </div>
            <div class="item">
              <div class="item-top"><div class="item-url">Current cap</div><span class="badge" id="bw-cap">-</span></div>
              <div class="meta"><span id="bw-global">Global option not loaded</span></div>
            </div>
            <div class="item">
              <div class="item-top"><div class="item-url">Live download</div><span class="badge" id="bw-live">idle</span></div>
              <div class="meta"><span id="bw-live-detail">No active transfer</span></div>
            </div>
            <div class="item">
              <div class="item-top"><div class="item-url">Probe details</div><span class="badge" id="bw-probe-mode">-</span></div>
              <div class="meta"><span id="bw-probe-detail">No probe yet</span></div>
            </div>
          </div>
        </div>
      </div>
      <div class="span-6 show-lifecycle page-only">
        <div class="panel">
          <div class="section-title">
            <h2>Service Status</h2>
            <div class="hint">Installed, current, autostart, and updater state</div>
          </div>
          <div class="row" style="margin-bottom:12px;">
            <button class="secondary" onclick="loadLifecycle()">Refresh service status</button>
          </div>
          <div class="item" style="margin-bottom:12px;">
            <div class="item-top">
              <div class="item-url">Update policy</div>
              <span class="badge">Homebrew tap</span>
            </div>
            <div class="meta"><span>ariaflow updates are applied through the Homebrew tap, not in-place by the running app.</span></div>
          </div>
          <div id="lifecycle" class="list">Loading...</div>
        </div>
      </div>
      <div class="span-6 show-options page-only">
        <div class="panel">
          <div class="section-title">
            <h2>Options</h2>
            <div class="hint">Operator policies and toggles</div>
          </div>
          <div class="list" id="options-panel">Loading...</div>
        </div>
      </div>
      <div class="span-6 show-log page-only">
        <div class="panel">
          <div class="section-title">
            <h2>Log</h2>
            <div class="hint">Action history and UCC trace</div>
          </div>
          <div class="row" style="margin-bottom:12px;">
            <button class="secondary" onclick="uccRun()">Run contract</button>
            <button class="secondary" onclick="preflightRun()">Preflight</button>
          </div>
          <div id="contract-trace" class="list">Idle</div>
          <div class="section-title" style="margin-top:14px;">
            <h2>Preflight</h2>
            <div class="hint">Pass, warnings, and failures</div>
          </div>
          <div id="preflight" class="list">Idle</div>
          <div id="result" class="mono" style="white-space:pre-wrap;word-break:break-word;color:var(--text);margin-top:12px;">Idle</div>
          <details class="debug">
            <summary>Action JSON</summary>
            <div id="result-json" class="debug-box">Idle</div>
          </details>
        </div>
      </div>
      <div class="span-6 show-log page-only">
        <div class="panel">
          <div class="section-title">
            <h2>Action history</h2>
            <div class="hint">Normalized event log</div>
          </div>
          <div class="row" style="margin-bottom:12px;">
            <select id="action-filter" onchange="refreshActionLog()">
              <option value="all">All actions</option>
              <option value="add">Add</option>
              <option value="preflight">Preflight</option>
              <option value="run">Run</option>
              <option value="stop">Stop</option>
              <option value="ucc">UCC</option>
              <option value="probe">Probe</option>
              <option value="pause">Pause</option>
              <option value="resume">Resume</option>
              <option value="poll">Poll</option>
              <option value="complete">Complete</option>
              <option value="error">Error</option>
            </select>
            <select id="target-filter" onchange="refreshActionLog()">
              <option value="all">All targets</option>
              <option value="bandwidth">Bandwidth</option>
              <option value="queue">Queue</option>
              <option value="queue_item">Queue job</option>
              <option value="active_transfer">Active transfer</option>
              <option value="system">System</option>
            </select>
            <select id="session-filter" onchange="refreshActionLog()">
              <option value="all">All sessions</option>
              <option value="current" selected>Current run</option>
            </select>
          </div>
          <div id="action-log" class="list">Loading...</div>
        </div>
      </div>
      <div class="span-6 show-log page-only">
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
    let refreshTimer = null;
    let refreshInterval = 10000;
    let backendGlobalOptions = {};
    let lastDeclaration = null;
    const path = window.location.pathname.replace(/[/]+$/, "");
    const page = path === "/bandwidth" ? "bandwidth" : path === "/lifecycle" ? "lifecycle" : path === "/log" ? "log" : "dashboard";

    function applyPage() {
      document.body.classList.add(`page-${page}`);
      document.querySelectorAll('.nav a').forEach((link) => {
        link.classList.toggle('active', link.dataset.page === page);
      });
      if (page === 'dashboard') {
        document.querySelectorAll('.show-dashboard').forEach((el) => el.style.display = '');
      } else if (page === 'bandwidth') {
        document.querySelectorAll('.show-bandwidth').forEach((el) => el.style.display = '');
      } else if (page === 'lifecycle') {
        document.querySelectorAll('.show-lifecycle').forEach((el) => el.style.display = '');
      } else if (page === 'log') {
        document.querySelectorAll('.show-log').forEach((el) => el.style.display = '');
      }
    }

    function applyTheme(theme) {
      const root = document.documentElement;
      const saved = theme || 'system';
      const next = saved === 'system'
        ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
        : saved;
      root.dataset.theme = next;
      localStorage.setItem('ariaflow.theme', saved);
      const btn = document.getElementById('theme-btn');
      if (btn) btn.textContent = saved === 'system' ? 'Theme: system' : `Theme: ${saved}`;
    }

    function initTheme() {
      const saved = localStorage.getItem('ariaflow.theme') || 'system';
      applyTheme(saved);
      const mq = window.matchMedia('(prefers-color-scheme: dark)');
      const sync = () => {
        if ((localStorage.getItem('ariaflow.theme') || 'system') === 'system') {
          applyTheme('system');
        }
      };
      if (mq.addEventListener) mq.addEventListener('change', sync);
      else if (mq.addListener) mq.addListener(sync);
    }

    function toggleTheme() {
      const current = localStorage.getItem('ariaflow.theme') || 'system';
      const next = current === 'system' ? 'dark' : current === 'dark' ? 'light' : 'system';
      applyTheme(next);
    }
    function syncRefreshControl() {
      const el = document.getElementById('refresh-interval');
      if (!el) return;
      const backendValue = backendGlobalOptions["ariaflow-refresh-interval"];
      const value = String(Number(backendValue || refreshInterval || 10000) || 10000);
      if (el.value !== value) el.value = value;
    }
    function getDeclarationPreference(name) {
      const prefs = lastDeclaration?.uic?.preferences || [];
      const pref = prefs.find((item) => item.name === name);
      return pref ? pref.value : undefined;
    }
    function renderOptionCard(title, value, hint, widget) {
      return `
        <div class="item">
          <div class="item-top">
            <div class="item-url">${title}</div>
            ${widget || `<span class="badge">${value ?? '-'}</span>`}
          </div>
          <div class="meta"><span>${hint}</span></div>
        </div>
      `;
    }
    function renderOptionsPanel(declaration) {
      const prefs = declaration?.uic?.preferences || [];
      const autoPreflight = prefs.find((item) => item.name === 'auto_preflight_on_run');
      const dedup = prefs.find((item) => item.name === 'duplicate_active_transfer_action');
      const concurrency = prefs.find((item) => item.name === 'max_simultaneous_downloads');
      const postAction = prefs.find((item) => item.name === 'post_action_rule');
      return [
        renderOptionCard(
          'Auto preflight',
          autoPreflight?.value ? 'enabled' : 'disabled',
          'Run UIC preflight automatically before starting the queue.',
          `<label class="refresh-control"><input type="checkbox" ${autoPreflight?.value ? 'checked' : ''} onchange="setAutoPreflightPreference(this.checked)">Toggle</label>`
        ),
        renderOptionCard(
          'Duplicate active transfer',
          dedup?.value || 'pause',
          'When aria2 exposes duplicate active jobs for the same URL, choose the action.',
          `<select onchange="setDuplicateAction(this.value)">
            <option value="pause" ${dedup?.value === 'pause' ? 'selected' : ''}>Pause duplicates</option>
            <option value="remove" ${dedup?.value === 'remove' ? 'selected' : ''}>Remove duplicates</option>
            <option value="ignore" ${dedup?.value === 'ignore' ? 'selected' : ''}>Ignore duplicates</option>
          </select>`
        ),
        renderOptionCard(
          'Simultaneous downloads',
          Number(concurrency?.value || 0) === 0 ? 'unlimited' : `${concurrency?.value || 0} jobs`,
          'Limit how many downloads ariaflow may keep active at once. Use 0 for no limit.',
          `<label class="refresh-control" style="justify-content:flex-start;">
            <span>Max</span>
            <input type="number" min="0" step="1" value="${Number(concurrency?.value || 0)}" oninput="setSimultaneousLimit(this.value)" style="width:110px; padding:0 8px; height:32px;">
            <span>jobs</span>
          </label>`
        ),
        renderOptionCard(
          'Post-action rule',
          postAction?.value || 'pending',
          'Placeholder policy used after a download finishes.',
          `<select onchange="setPostActionRule(this.value)">
            <option value="pending" ${postAction?.value === 'pending' ? 'selected' : ''}>Pending</option>
          </select>`
        ),
      ].join('');
    }
    async function setAutoPreflightPreference(enabled) {
      const r = await fetch('/api/declaration');
      const data = await r.json();
      const prefs = Array.isArray(data?.uic?.preferences) ? data.uic.preferences : [];
      const idx = prefs.findIndex((item) => item.name === 'auto_preflight_on_run');
      const next = { name: 'auto_preflight_on_run', value: !!enabled, options: [true, false], rationale: 'default off' };
      if (idx >= 0) prefs[idx] = next;
      else prefs.push(next);
      data.uic = data.uic || {};
      data.uic.preferences = prefs;
      const save = await fetch('/api/declaration', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(data) });
      lastDeclaration = await save.json();
      const options = document.getElementById('options-panel');
      if (options) options.innerHTML = renderOptionsPanel(lastDeclaration);
    }
    async function setDuplicateAction(value) {
      const r = await fetch('/api/declaration');
      const data = await r.json();
      const prefs = Array.isArray(data?.uic?.preferences) ? data.uic.preferences : [];
      const idx = prefs.findIndex((item) => item.name === 'duplicate_active_transfer_action');
      const next = { name: 'duplicate_active_transfer_action', value: value, options: ['pause', 'remove', 'ignore'], rationale: 'default dedup policy' };
      if (idx >= 0) prefs[idx] = next;
      else prefs.push(next);
      data.uic = data.uic || {};
      data.uic.preferences = prefs;
      const save = await fetch('/api/declaration', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(data) });
      lastDeclaration = await save.json();
      const options = document.getElementById('options-panel');
      if (options) options.innerHTML = renderOptionsPanel(lastDeclaration);
    }
    async function setSimultaneousLimit(value) {
      const r = await fetch('/api/declaration');
      const data = await r.json();
      const prefs = Array.isArray(data?.uic?.preferences) ? data.uic.preferences : [];
      const idx = prefs.findIndex((item) => item.name === 'max_simultaneous_downloads');
      const limit = Math.max(0, parseInt(value, 10) || 0);
      const next = { name: 'max_simultaneous_downloads', value: limit, options: [0], rationale: '0 means unlimited' };
      if (idx >= 0) prefs[idx] = next;
      else prefs.push(next);
      data.uic = data.uic || {};
      data.uic.preferences = prefs;
      const save = await fetch('/api/declaration', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(data) });
      lastDeclaration = await save.json();
      const options = document.getElementById('options-panel');
      if (options) options.innerHTML = renderOptionsPanel(lastDeclaration);
    }
    async function setPostActionRule(value) {
      const r = await fetch('/api/declaration');
      const data = await r.json();
      const prefs = Array.isArray(data?.uic?.preferences) ? data.uic.preferences : [];
      const idx = prefs.findIndex((item) => item.name === 'post_action_rule');
      const next = { name: 'post_action_rule', value: value, options: ['pending'], rationale: 'default placeholder' };
      if (idx >= 0) prefs[idx] = next;
      else prefs.push(next);
      data.uic = data.uic || {};
      data.uic.preferences = prefs;
      const save = await fetch('/api/declaration', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(data) });
      lastDeclaration = await save.json();
      const options = document.getElementById('options-panel');
      if (options) options.innerHTML = renderOptionsPanel(lastDeclaration);
    }
    function setRefreshInterval(value) {
      refreshInterval = Number(value) || 0;
      localStorage.setItem('ariaflow.refresh_interval', String(refreshInterval));
      if (refreshTimer) {
        clearInterval(refreshTimer);
        refreshTimer = null;
      }
      if (refreshInterval > 0) {
        refreshTimer = setInterval(refresh, refreshInterval);
      }
    }

    function badgeClass(status) {
      if (["done", "converged", "ok", "complete"].includes(status)) return "badge good";
      if (["error", "failed", "missing"].includes(status)) return "badge bad";
      if (["paused", "queued", "unchanged", "skipped"].includes(status)) return "badge warn";
      return "badge";
    }
    function formatBytes(value) {
      if (value == null) return "-";
      let size = Number(value);
      const units = ["B", "KiB", "MiB", "GiB", "TiB"];
      for (const unit of units) {
        if (Math.abs(size) < 1024 || unit === units[units.length - 1]) {
          return unit === "B" ? `${Math.round(size)} ${unit}` : `${size.toFixed(1)} ${unit}`;
        }
        size /= 1024;
      }
      return `${size.toFixed(1)} TiB`;
    }
    function formatRate(value) {
      if (value == null) return "-";
      return `${formatBytes(value)}/s`;
    }
    function formatMbps(value) {
      if (value == null) return "-";
      return `${value} Mbps`;
    }
    function humanCap(value) {
      if (value == null) return "-";
      const text = String(value).trim();
      if (!text || text === "0" || text === "0M" || text === "0 Mbps" || text === "0 Mbps/s") return "unlimited";
      return text;
    }
    function activeStateLabel(active, state) {
      if (state?.paused && active?.recovered) return "paused";
      if (state?.paused) return "paused";
      if (active?.recovered) return active.status ? active.status : "recovered";
      if (active?.status) return active.status;
      if (state?.running) return "running";
      return "idle";
    }
    function activeDisplayName(active, items) {
      const match = (items || []).find((item) => active?.gid && item.gid === active.gid);
      const url = active?.url || match?.url || "";
      const name = shortName(url || active?.gid || "none");
      return { name, url };
    }
    function summarizeActiveItem(active, state, items) {
      const display = activeDisplayName(active, items);
      const name = display.name;
      if (state?.paused && active?.recovered) return name;
      if (active?.recovered) return name;
      if (active?.status && active?.status !== "idle") return `${active.status} · ${name}`;
      if (state?.running) return name;
      return "none";
    }
    function sessionLabel(state) {
      if (state?.session_id && !state?.session_closed_at) return `current ${String(state.session_id).slice(0, 8)}`;
      if (state?.session_id && state?.session_closed_at) return `closed ${String(state.session_id).slice(0, 8)}`;
      return "-";
    }
    function enrichQueueItems(items, active, state) {
      const liveItems = Array.isArray(active) ? active : (active ? [active] : []);
      return (items || []).map((item) => {
        const matches = liveItems.find((live) => live && (item.gid === live.gid || (state?.active_gid && item.gid === state.active_gid) || (item.url && live.url && item.url === live.url)));
        if (!matches) return item;
        const total = Number(matches.totalLength || item.totalLength || 0);
        const done = Number(matches.completedLength || item.completedLength || 0);
        const computedPercent = total > 0 ? (done / total) * 100 : null;
        const live = {
          percent: matches.percent != null ? matches.percent : computedPercent,
          downloadSpeed: matches.downloadSpeed,
          totalLength: matches.totalLength,
          completedLength: matches.completedLength,
          errorMessage: matches.errorMessage,
          recovered: matches.recovered,
          recovery_session_id: matches.recovery_session_id,
          recovered_at: matches.recovered_at,
          url: matches.url,
          status: matches.status,
          gid: matches.gid,
        };
        return { ...item, live, url: item.url || live.url };
      });
    }
    function renderQueueItem(item) {
      const status = item.status || "unknown";
      const detail = [
        item.created_at ? `Created ${item.created_at}` : null,
        item.post_action_rule ? `Rule ${item.post_action_rule}` : null,
        item.gid ? `GID ${item.gid}` : null,
        item.error_message ? item.error_message : null,
      ].filter(Boolean).join(" · ");
      const live = item.live || {};
      const shortUrl = shortName(item.output || item.url || live.url || '(no url)');
      const activeish = ["downloading", "paused", "recovered"].includes(status) || item.recovered;
      const liveStatus = live.status || null;
      const speed = live.downloadSpeed || item.downloadSpeed;
      const totalLength = live.totalLength || item.totalLength;
      const completedLength = live.completedLength || item.completedLength;
      const progress = live.percent != null ? live.percent : item.percent;
      const computedProgress = progress != null
        ? progress
        : (Number(totalLength || 0) > 0 ? (Number(completedLength || 0) / Number(totalLength || 1)) * 100 : 0);
      const displayUrl = item.url || live.url || "";
      const ariaBadge = liveStatus ? `<span class="badge ${badgeClass(liveStatus)}">aria2: ${liveStatus}</span>` : "";
      const pauseLabel = status === 'paused' ? 'Resume queue' : 'Pause queue';
      const pauseButton = activeish
        ? `<button class="secondary icon-btn" onclick="toggleQueue()" title="${pauseLabel}" aria-label="${pauseLabel}">${status === 'paused' ? '▶' : '⏸'}<span class="sr-only">${pauseLabel}</span></button>`
        : "";
      const actionButtons = activeish ? `
        <div class="action-strip">
          ${pauseButton}
          <button class="secondary icon-btn" onclick="preflightRun()" title="Run preflight" aria-label="Run preflight">✓<span class="sr-only">Run preflight</span></button>
          <button class="secondary icon-btn" onclick="runQueue()" title="Start run" aria-label="Start run">⟳<span class="sr-only">Start run</span></button>
        </div>
      ` : "";
      const activePanel = activeish ? `
        <div class="meter"><div style="width:${Math.round(Number(computedProgress || 0))}%"></div></div>
        <div class="statusline">
          <span>${Math.round(Number(computedProgress || 0))}% done</span>
          <span>${speed ? formatRate(speed) : "waiting"}</span>
        </div>
        <div class="meta">
          ${totalLength ? `<span>Total ${formatBytes(totalLength)}</span>` : ""}
          ${completedLength ? `<span>Done ${formatBytes(completedLength)}</span>` : ""}
          ${item.gid ? `<span>GID ${item.gid}</span>` : ""}
          ${item.recovered ? `<span class="badge warn">${item.recovery_session_id ? 'recovered · recovery run' : 'recovered'}</span>` : ""}
          ${item.recovered_at ? `<span>Recovered ${item.recovered_at}</span>` : ""}
          ${item.error_message ? `<span class="mono">${item.error_message}</span>` : ""}
        </div>
      ` : "";
      const stateLabel = liveStatus ? `${status} · aria2:${liveStatus}` : status;
      return `
        <div class="item compact ${activeish ? 'active-item' : ''}">
        <div class="item-top">
          <div class="item-url">${shortUrl}</div>
          <span class="${badgeClass(status)}">${stateLabel}</span>
        </div>
        <div class="meta">
          ${ariaBadge}
          ${displayUrl ? `<span title="${displayUrl}">${displayUrl}</span>` : ""}
          ${detail ? `<span class="mono">${detail}</span>` : ""}
        </div>
          ${actionButtons}
          ${activePanel}
        </div>
      `;
    }
    function shortName(value) {
      if (!value) return "(no name)";
      try {
        const url = new URL(value);
        const parts = url.pathname.split("/").filter(Boolean);
        return parts.length ? parts[parts.length - 1] : url.hostname;
      } catch (err) {
        const parts = value.split("/").filter(Boolean);
        return parts.length ? parts[parts.length - 1] : value;
      }
    }
    function activeTransfer(items, active, state) {
      const liveItems = Array.isArray(items) ? items : [];
      return liveItems.find((item) => item && (item.gid === active?.gid || (state?.active_gid && item.gid === state.active_gid) || (active?.url && item.url && active.url === item.url)))
        || active
        || null;
    }
    function lifecycleStateLabel(name, record) {
      const result = record && record.result ? record.result : {};
      const reason = result.reason || "";
      if (name === "ariaflow") {
        if (reason === "match") return "installed · current";
        if (reason === "missing") return "absent";
        return result.outcome || "unknown";
      }
      if (name === "aria2") {
        if (reason === "match") return "installed · current";
        if (reason === "missing") return "absent";
        return result.outcome || "unknown";
      }
      if (name === "networkquality") {
        if (reason === "ready") return "installed · usable";
        if (reason === "timeout") return "installed · slow";
        if (reason === "no_output") return "installed · no parse";
        if (reason === "missing") return "absent";
        if (reason === "error") return "installed · error";
        return result.outcome || "unknown";
      }
      if (reason === "match") return "loaded";
      if (reason === "missing") return "not loaded";
      return result.outcome || "unknown";
    }
    function renderLifecycleItem(name, record, actions = []) {
      const result = record && record.result ? record.result : {};
      const lines = [];
      if (result.message) lines.push(result.message);
      if (result.reason) lines.push(`Reason: ${result.reason}`);
      if (result.completion) lines.push(`Completion: ${result.completion}`);
      const buttons = actions.length ? `
        <div class="action-strip" style="justify-content:flex-start; margin-top:8px;">
          ${actions.map((action) => `<button class="secondary icon-btn" onclick="lifecycleAction('${action.target}','${action.action}')" title="${action.label}">${action.label}</button>`).join("")}
        </div>
      ` : "";
      return `
        <div class="item">
          <div class="item-top">
            <div class="item-url">${name}</div>
            <span class="${badgeClass(result.outcome)}">${lifecycleStateLabel(name, record)}</span>
          </div>
          <div class="meta">
            <span>${lines.join(" · ") || "No details"}</span>
          </div>
          ${buttons}
        </div>
      `;
    }
    function renderLifecycleSummary(data) {
      const rows = [
        {
          name: "ariaflow",
          record: data.ariaflow,
          actions: [
            { target: "ariaflow", action: "install", label: "Install / Update" },
            { target: "ariaflow", action: "uninstall", label: "Remove" },
          ],
        },
        {
          name: "aria2",
          record: data.aria2,
          actions: [],
        },
        {
          name: "networkquality",
          record: data.networkquality,
          actions: [],
        },
        {
          name: "aria2 auto-start",
          record: data["aria2-launchd"],
          actions: [
            { target: "aria2-launchd", action: "install", label: "Load" },
            { target: "aria2-launchd", action: "uninstall", label: "Unload" },
          ],
        },
      ];
      const session = data?.session_id ? `
        <div class="item" style="margin-bottom:12px;">
          <div class="item-top">
            <div class="item-url">Run</div>
            <span class="badge ${data.session_closed_at ? 'warn' : 'good'}">${data.session_closed_at ? 'closed' : 'current'}</span>
          </div>
          <div class="meta"><span class="mono">${data.session_id}</span></div>
          <div class="meta">
            <span>${data.session_started_at ? `Started ${data.session_started_at}` : 'Start time unknown'}</span>
            <span>${data.session_last_seen_at ? `Last seen ${data.session_last_seen_at}` : 'Last seen unknown'}</span>
            ${data.session_closed_at ? `<span>Closed ${data.session_closed_at}${data.session_closed_reason ? ` · ${data.session_closed_reason}` : ''}</span>` : ""}
          </div>
        </div>
      ` : "";
      return `${session}${rows.map((row) => renderLifecycleItem(row.name, row.record, row.actions)).join("")}`;
    }
    function renderQueueSummary(summary) {
      document.getElementById('sum-queued').textContent = summary?.queued ?? 0;
      document.getElementById('sum-done').textContent = summary?.done ?? 0;
      document.getElementById('sum-error').textContent = summary?.error ?? 0;
    }
    function renderPreflight(data) {
      const gates = (data.gates || []).map((gate) => `
        <div class="item">
          <div class="item-top">
            <div class="item-url">${gate.name}</div>
            <span class="${gate.satisfied ? 'badge good' : 'badge bad'}">${gate.satisfied ? 'ready' : 'blocked'}</span>
          </div>
          <div class="meta"><span>${gate.class || 'gate'} · ${gate.blocking || 'unknown'}</span></div>
        </div>
      `).join("");
      const warnings = (data.warnings || []).map((warning) => `
        <div class="item">
          <div class="item-top">
            <div class="item-url">${warning.name}</div>
            <span class="badge warn">warning</span>
          </div>
          <div class="meta"><span>${warning.message}</span></div>
        </div>
      `).join("");
      const failures = (data.hard_failures || []).map((failure) => `
        <div class="item">
          <div class="item-top">
            <div class="item-url">${failure}</div>
            <span class="badge bad">blocked</span>
          </div>
        </div>
      `).join("");
      return `
        ${gates || "<div class='item'>No gates defined.</div>"}
        ${warnings ? `<div class='item'><div class='item-url' style='margin-bottom:8px;'>Warnings</div>${warnings}</div>` : ""}
        ${failures ? `<div class='item'><div class='item-url' style='margin-bottom:8px;'>Hard failures</div>${failures}</div>` : ""}
      `;
    }
    function renderContractTrace(data) {
      if (!data) return "Idle";
      const result = data.result || {};
      const preflight = data.preflight || {};
      const lines = [
        `Contract: ${data.meta?.contract || "unknown"} v${data.meta?.version || "-"}`,
        `Outcome: ${result.outcome || "unknown"}`,
        `Observation: ${result.observation || "unknown"}`,
        result.message ? `Message: ${result.message}` : null,
        result.reason ? `Reason: ${result.reason}` : null,
        preflight.status ? `Preflight: ${preflight.status}` : null,
      ].filter(Boolean);
      return `
        <div class="item">
          <div class="item-top">
            <div class="item-url">UCC execution</div>
            <span class="${badgeClass(result.outcome)}">${result.outcome || "unknown"}</span>
          </div>
          <div class="meta"><span>${lines.join(" · ")}</span></div>
        </div>
      `;
    }
    function renderActionLog(entries) {
      if (!entries || !entries.length) return "<div class='item'>No action log yet.</div>";
      const currentFilter = document.getElementById('action-filter')?.value || 'all';
      const currentTarget = document.getElementById('target-filter')?.value || 'all';
      const currentSession = document.getElementById('session-filter')?.value || 'all';
      const sessionId = lastStatus?.state?.session_id || lastLifecycle?.session_id || lastDeclaration?.session_id || null;
      return entries
        .filter((entry) => currentFilter === 'all' ? true : (entry.action || 'unknown') === currentFilter)
        .filter((entry) => currentTarget === 'all' ? true : (entry.target || 'unknown') === currentTarget)
        .filter((entry) => currentSession === 'all' ? true : (currentSession === 'current' ? (sessionId ? entry.session_id === sessionId : false) : true))
        .slice()
        .reverse()
        .map((entry) => {
        const status = entry.outcome || entry.status || "unknown";
        const lines = [
          entry.timestamp ? `At ${entry.timestamp}` : null,
          entry.session_id ? `Session: ${entry.session_id}` : null,
          entry.action ? `Action: ${entry.action}` : null,
          entry.target ? `Target: ${entry.target}` : null,
          entry.reason ? `Reason: ${entry.reason}` : null,
          entry.detail ? `Detail: ${JSON.stringify(entry.detail)}` : null,
          entry.observed_before ? `Before: ${JSON.stringify(entry.observed_before)}` : null,
          entry.observed_after ? `After: ${JSON.stringify(entry.observed_after)}` : null,
          entry.message ? `Message: ${entry.message}` : null,
        ].filter(Boolean).join(" · ");
        return `
          <div class="item">
            <div class="item-top">
              <div class="item-url">${entry.action || "event"}</div>
              <span class="${badgeClass(status)}">${status}</span>
            </div>
            <div class="meta"><span>${lines || "No details"}</span></div>
          </div>
        `;
      }).join("");
    }
    let refreshInFlight = false;
    async function refresh() {
      if (refreshInFlight) return;
      refreshInFlight = true;
      try {
        const r = await fetch('/api/status');
        const data = await r.json();
        lastStatus = data;
        backendGlobalOptions = data.aria2_global_options || {};
        const state = data.state || {};
        const active = data.active || {status: 'idle'};
        const actives = Array.isArray(data.actives) ? data.actives : (data.active ? [data.active] : []);
        const liveActive = activeTransfer(actives, active, state);
        const speed = liveActive?.downloadSpeed || active.downloadSpeed || data.state?.download_speed || null;
        const items = enrichQueueItems(data.items || [], actives, state);
        document.getElementById('queue').innerHTML = items.length ? items.map(renderQueueItem).join("") : "<div class='item'>Queue is empty.</div>";
        document.getElementById('chip-error').textContent = state.last_error || data.bandwidth?.reason || 'none';
        document.getElementById('chip-cap').textContent = data.bandwidth?.cap_mbps ? humanCap(formatMbps(data.bandwidth.cap_mbps)) : humanCap(data.bandwidth?.limit || data.bandwidth_global?.limit || '-');
        document.getElementById('chip-runner').textContent = data.state && data.state.running ? 'running' : 'idle';
        document.getElementById('chip-session').textContent = sessionLabel(state);
        const toggleButton = document.getElementById('toggle-btn');
        if (toggleButton) toggleButton.textContent = data.state && data.state.paused ? 'Resume' : 'Pause';
        const runnerButton = document.getElementById('runner-btn');
        if (runnerButton) runnerButton.textContent = data.state && data.state.running ? 'Stop engine' : 'Start engine';
        document.getElementById('mode-label').textContent = activeStateLabel(liveActive, state);
        document.getElementById('active-label').textContent = summarizeActiveItem(liveActive, state, items);
        document.getElementById('sum-speed').textContent = speed ? formatRate(speed) : "idle";
        renderQueueSummary(data.summary);
        document.getElementById('bw-source').textContent = data.bandwidth?.source || '-';
        document.getElementById('bw-down').textContent = data.bandwidth?.source === 'networkquality'
          ? `Downlink ${formatMbps(data.bandwidth.downlink_mbps)}${data.bandwidth.partial ? ' (partial capture)' : ''}`
          : `No networkquality probe available${data.bandwidth?.reason ? ` · ${data.bandwidth.reason}` : ''}`;
        document.getElementById('bw-cap').textContent = data.bandwidth?.cap_mbps ? humanCap(formatMbps(data.bandwidth.cap_mbps)) : humanCap(data.bandwidth?.limit || '-');
        document.getElementById('bw-global').textContent = data.bandwidth_global?.limit ? `Global limit ${data.bandwidth_global.limit}` : 'Global option unavailable';
        document.getElementById('bw-live').textContent = activeStateLabel(liveActive, state);
        document.getElementById('bw-live-detail').textContent = liveActive?.downloadSpeed
          ? `Speed ${formatRate(liveActive.downloadSpeed)}${liveActive.completedLength ? ` · ${formatBytes(liveActive.completedLength)}/${formatBytes(liveActive.totalLength || 0)}` : ''}`
          : 'No active transfer';
        document.getElementById('bw-probe-mode').textContent = data.bandwidth?.source || '-';
        document.getElementById('bw-probe-detail').textContent = data.bandwidth?.source === 'networkquality'
          ? `Measured ${formatMbps(data.bandwidth.downlink_mbps)} and capped at ${formatMbps(data.bandwidth.cap_mbps)}${data.bandwidth.partial ? ' from partial output' : ''}`
          : 'Using default floor because no probe was available';
        syncRefreshControl();
      } finally {
        refreshInFlight = false;
      }
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
      document.getElementById('result').textContent = data.paused ? "Queue paused" : "Pause requested";
      document.getElementById('result-json').textContent = JSON.stringify(data, null, 2);
      await refresh();
    }
    async function resumeQueue() {
      const r = await fetch('/api/resume', { method: 'POST' });
      const data = await r.json();
      lastResult = data;
      document.getElementById('result').textContent = data.resumed ? "Queue resumed" : "Resume requested";
      document.getElementById('result-json').textContent = JSON.stringify(data, null, 2);
      await refresh();
    }
    async function toggleQueue() {
      const paused = lastStatus?.state?.paused;
      return paused ? resumeQueue() : pauseQueue();
    }
    async function add() {
      const raw = document.getElementById('url').value.trim();
      const urls = raw.split(/\\r?\\n/).map((line) => line.trim()).filter(Boolean);
      const payload = urls.length > 1 ? { urls } : { url: urls[0] || "" };
      const r = await fetch('/api/add', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload) });
      const data = await r.json();
      lastResult = data;
      const queued = Array.isArray(data.added) ? data.added.length : (data.added ? 1 : 0);
      document.getElementById('result').textContent = queued > 1
        ? `Queued ${queued} items`
        : `Queued: ${data.added?.url || urls[0] || raw}`;
      document.getElementById('result-json').textContent = JSON.stringify(data, null, 2);
      await refresh();
    }
    async function preflightRun() {
      const r = await fetch('/api/preflight', { method: 'POST' });
      const data = await r.json();
      lastResult = data;
      document.getElementById('result').textContent = data.status === 'pass' ? "Preflight passed" : "Preflight needs attention";
      document.getElementById('result-json').textContent = JSON.stringify(data, null, 2);
      document.getElementById('preflight').innerHTML = renderPreflight(data);
      await refresh();
    }
    async function runQueue() {
      const autoPreflight = document.getElementById('auto-preflight')?.checked;
      const r = await fetch('/api/run', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({auto_preflight_on_run: !!autoPreflight}) });
      const data = await r.json();
      lastResult = data;
      document.getElementById('result').textContent = data.started ? "Queue runner started" : data.stopped ? "Queue runner stopped" : "Queue runner already running";
      document.getElementById('result-json').textContent = JSON.stringify(data, null, 2);
      await refresh();
    }
    async function toggleRunner() {
      return runQueue();
    }
    async function uccRun() {
      const r = await fetch('/api/ucc', { method: 'POST' });
      const data = await r.json();
      lastResult = data;
      const outcome = data.result && data.result.outcome ? data.result.outcome : "unknown";
      document.getElementById('result').textContent = `UCC result: ${outcome}`;
      document.getElementById('result-json').textContent = JSON.stringify(data, null, 2);
      const trace = document.getElementById('contract-trace');
      if (trace) trace.innerHTML = renderContractTrace(data);
      const actionLog = document.getElementById('action-log');
      if (actionLog && lastStatus) actionLog.innerHTML = renderActionLog(lastStatus.action_log || []);
      await refresh();
    }
    async function lifecycleAction(target, action) {
      const r = await fetch('/api/lifecycle/action', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ target, action }),
      });
      const data = await r.json();
      const lifecycle = data.lifecycle || data;
      lastLifecycle = lifecycle;
      document.getElementById('lifecycle').innerHTML = renderLifecycleSummary(lifecycle);
      document.getElementById('result').textContent = `${target} ${action} requested`;
      document.getElementById('result-json').textContent = JSON.stringify(data, null, 2);
    }
    async function newSession() {
      const r = await fetch('/api/session', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ action: 'new' }),
      });
      const data = await r.json();
      lastResult = data;
      document.getElementById('result').textContent = data.ok ? 'New session started' : 'Session change requested';
      document.getElementById('result-json').textContent = JSON.stringify(data, null, 2);
      await refresh();
      if (page === 'lifecycle') loadLifecycle();
      if (page === 'log') refreshActionLog();
    }
    async function loadDeclaration() {
      const r = await fetch('/api/declaration');
      lastDeclaration = await r.json();
      const declarationBox = document.getElementById('declaration');
      if (declarationBox) declarationBox.value = JSON.stringify(lastDeclaration, null, 2);
      const checkbox = document.getElementById('auto-preflight');
      if (checkbox) checkbox.checked = !!getDeclarationPreference('auto_preflight_on_run');
      const options = document.getElementById('options-panel');
      if (options) options.innerHTML = renderOptionsPanel(lastDeclaration);
      const limit = document.querySelector('input[oninput="setSimultaneousLimit(this.value)"]');
      if (limit) limit.value = String(getDeclarationPreference('max_simultaneous_downloads') ?? 0);
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
    async function refreshActionLog() {
      if (page !== 'log') return;
      const sessionFilter = document.getElementById('session-filter');
      if (sessionFilter && !sessionFilter.value) sessionFilter.value = 'current';
      const r = await fetch('/api/log?limit=120');
      const data = await r.json();
      const actionLog = document.getElementById('action-log');
      if (actionLog) actionLog.innerHTML = renderActionLog(data.items || []);
    }
    document.getElementById('action-filter')?.addEventListener('change', refreshActionLog);
    document.getElementById('session-filter')?.addEventListener('change', refreshActionLog);
    initTheme();
    refresh();
    setRefreshInterval(10000);
    if (page === 'lifecycle') loadLifecycle();
    if (page === 'options') loadDeclaration();
    if (page === 'log') {
      loadDeclaration();
      refreshActionLog();
    }
    if (page === 'dashboard') {
      loadDeclaration().catch(() => {});
    }
    applyPage();
  </script>
</body>
</html>
"""


class AriaFlowHandler(BaseHTTPRequestHandler):
    def _invalidate_status_cache(self) -> None:
        STATUS_CACHE["ts"] = 0.0
        STATUS_CACHE["payload"] = None

    @staticmethod
    def _derive_active_item(items: list[dict]) -> dict | None:
        for item in items:
            if not isinstance(item, dict):
                continue
            status = str(item.get("status") or "").lower()
            live_status = str(item.get("live_status") or "").lower()
            if status in {"downloading", "paused", "recovered"} or live_status in {"active", "paused"}:
                active = {
                    "gid": item.get("gid"),
                    "url": item.get("url"),
                    "status": item.get("status") or item.get("live_status") or "active",
                    "errorCode": item.get("error_code"),
                    "errorMessage": item.get("error_message"),
                    "downloadSpeed": item.get("downloadSpeed") or item.get("download_speed"),
                    "completedLength": item.get("completedLength") or item.get("completed_length"),
                    "totalLength": item.get("totalLength") or item.get("total_length"),
                    "files": item.get("files"),
                    "percent": item.get("percent"),
                }
                return active
        return None

    def _status_payload(self, force: bool = False) -> dict:
        now = time.time()
        cached = STATUS_CACHE.get("payload")
        if not force and cached is not None and now - float(STATUS_CACHE.get("ts", 0.0)) < STATUS_CACHE_TTL:
            return cached  # type: ignore[return-value]

        state = load_state()
        items = load_queue()
        bandwidth = current_bandwidth(timeout=3)
        payload = {
            "items": items,
            "state": state,
            "summary": summarize_queue(items),
            "aria2": aria_status(timeout=3),
            "bandwidth": bandwidth,
            "bandwidth_global": bandwidth,
            "aria2_global_options": current_global_options(timeout=3),
        }
        active = active_status(timeout=3)
        if not active:
            active = self._derive_active_item(items)
        if active:
            payload["active"] = active
        actives = active_gids(timeout=3)
        if not actives and active:
            actives = [active]
        if actives:
            payload["actives"] = actives
        STATUS_CACHE["ts"] = now
        STATUS_CACHE["payload"] = payload
        return payload

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/status":
            self._send_json(self._status_payload())
            return
        if path == "/api/log":
            limit = 120
            query = dict(part.split("=", 1) if "=" in part else (part, "") for part in parsed.query.split("&") if part)
            try:
                limit = max(1, min(500, int(query.get("limit", "120"))))
            except ValueError:
                limit = 120
            self._send_json({"items": load_action_log(limit=limit)})
            return
        if path == "/api/declaration":
            self._send_json(load_declaration())
            return
        if path == "/api/options":
            self._send_json(load_declaration())
            return
        if path == "/api/lifecycle":
            self._send_json(_lifecycle_payload())
            return
        self._send_json({"error": "not_found"}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        payload = json.loads(raw or "{}")

        if path == "/api/add":
            raw_urls = payload.get("urls")
            if isinstance(raw_urls, list):
                urls = [str(url).strip() for url in raw_urls if str(url).strip()]
            else:
                raw_url = str(payload.get("url", "")).strip()
                urls = [line.strip() for line in raw_url.splitlines() if line.strip()]
            if not urls:
                self._send_json({"error": "missing_url"}, status=400)
                return
            added = [add_queue_item(url).__dict__ for url in urls]
            self._invalidate_status_cache()
            self._send_json({"added": added[0] if len(added) == 1 else added})
            return

        if path == "/api/preflight":
            before = {"state": load_state(), "queue": summarize_queue(load_queue())}
            result = preflight()
            result["aria2"] = aria_status()
            result["bandwidth"] = current_bandwidth()
            record_action(
                action="preflight",
                target="system",
                outcome="converged" if result.get("status") == "pass" else "blocked",
                reason=result.get("status", "unknown"),
                before=before,
                after={"state": load_state(), "queue": summarize_queue(load_queue()), "preflight": result},
                detail=result,
            )
            self._invalidate_status_cache()
            self._send_json(result)
            return

        if path == "/api/run":
            before = {"state": load_state(), "queue": summarize_queue(load_queue())}
            state = load_state()
            if state.get("running"):
                result = stop_background_process()
            else:
                if auto_preflight_on_run():
                    preflight_result = preflight()
                    record_action(
                        action="preflight",
                        target="system",
                        outcome="converged" if preflight_result.get("status") == "pass" else "blocked",
                        reason=preflight_result.get("status", "unknown"),
                        before=before,
                        after={"state": load_state(), "queue": summarize_queue(load_queue()), "preflight": preflight_result},
                        detail=preflight_result,
                    )
                    if preflight_result.get("exit_code") != 0:
                        self._invalidate_status_cache()
                        self._send_json({
                            "started": False,
                            "stopped": False,
                            "reason": "preflight_blocked",
                            "preflight": preflight_result,
                            "auto_preflight_on_run": True,
                        })
                        return
                result = start_background_process()
            record_action(
                action="run",
                target="queue",
                outcome="changed" if result.get("started") or result.get("stopped") else "unchanged",
                reason=result.get("reason", "unknown"),
                before=before,
                after={"state": load_state(), "queue": summarize_queue(load_queue()), "runner": result},
                detail=result,
            )
            self._invalidate_status_cache()
            self._send_json(result)
            return

        if path == "/api/ucc":
            before = {"state": load_state(), "queue": summarize_queue(load_queue())}
            result = run_ucc()
            record_action(
                action="ucc",
                target="queue",
                outcome=result.get("result", {}).get("outcome", "unknown"),
                observation=result.get("result", {}).get("observation", "unknown"),
                reason=result.get("result", {}).get("reason", "unknown"),
                before=before,
                after={"state": load_state(), "queue": summarize_queue(load_queue()), "ucc": result},
                detail=result,
            )
            self._invalidate_status_cache()
            self._send_json(result)
            return

        if path == "/api/declaration":
            declaration = payload if isinstance(payload, dict) else {}
            saved = save_declaration(declaration)
            self._invalidate_status_cache()
            self._send_json({"saved": True, "declaration": saved})
            return

        if path == "/api/lifecycle/action":
            if not is_macos():
                self._send_json({"error": "macos_only"}, status=400)
                return
            target = str(payload.get("target", "")).strip()
            action = str(payload.get("action", "")).strip()
            before = {"lifecycle": status_all()}
            try:
                if target == "ariaflow" and action == "install":
                    commands = homebrew_install_ariaflow(dry_run=False)
                    result = {
                        "ariaflow": ucc_record(
                            target="ariaflow",
                            observed=True,
                            outcome="changed",
                            completion="complete",
                            reason="install",
                            detail="ariaflow package installed or updated",
                            commands=commands,
                        )
                    }
                elif target == "ariaflow" and action == "uninstall":
                    commands = homebrew_uninstall_ariaflow(dry_run=False)
                    result = {
                        "ariaflow": ucc_record(
                            target="ariaflow",
                            observed=True,
                            outcome="changed",
                            completion="complete",
                            reason="uninstall",
                            detail="ariaflow package removed",
                            commands=commands,
                        )
                    }
                elif target == "aria2-launchd" and action == "install":
                    commands = install_aria2_launchd(dry_run=False)
                    result = {
                        "aria2-launchd": ucc_record(
                            target="aria2-launchd",
                            observed=True,
                            outcome="changed",
                            completion="complete",
                            reason="install",
                            detail="aria2 launchd service installed or queued for installation",
                            commands=commands,
                        )
                    }
                elif target == "aria2-launchd" and action == "uninstall":
                    commands = uninstall_aria2_launchd(dry_run=False)
                    result = {
                        "aria2-launchd": ucc_record(
                            target="aria2-launchd",
                            observed=True,
                            outcome="changed",
                            completion="complete",
                            reason="uninstall",
                            detail="aria2 launchd removed or queued for removal",
                            commands=commands,
                        )
                    }
                else:
                    self._send_json({"error": "unsupported_action", "target": target, "action": action}, status=400)
                    return
            except Exception as exc:
                record_action(
                    action="lifecycle_action",
                    target=target or "system",
                    outcome="failed",
                    reason="exception",
                    before=before,
                    after={"lifecycle": status_all(), "target": target, "action": action},
                    detail={"error": str(exc), "target": target, "action": action},
                )
                self._invalidate_status_cache()
                self._send_json({"error": "lifecycle_action_failed", "message": str(exc)}, status=500)
                return
            record_action(
                action="lifecycle_action",
                target=target or "system",
                outcome="changed",
                reason=action or "lifecycle_action",
                before=before,
                after={"lifecycle": status_all(), "target": target, "action": action, "result": result},
                detail={"target": target, "action": action, "result": result},
            )
            self._invalidate_status_cache()
            self._send_json({"ok": True, "target": target, "action": action, "lifecycle": _lifecycle_payload(), "result": result})
            return

        if path == "/api/session":
            action = str(payload.get("action", "")).strip()
            if action != "new":
                self._send_json({"error": "unsupported_action", "action": action}, status=400)
                return
            before = {"state": load_state(), "queue": summarize_queue(load_queue())}
            state = start_new_state_session(reason="manual_new_session")
            self._invalidate_status_cache()
            after = {"state": load_state(), "queue": summarize_queue(load_queue())}
            result = {"ok": True, "session": state}
            record_action(
                action="session",
                target="system",
                outcome="changed",
                reason="new_session",
                before=before,
                after=after,
                detail={"session_id": state.get("session_id"), "session_started_at": state.get("session_started_at")},
            )
            self._send_json(result)
            return

        if path == "/api/pause":
            result = pause_active_transfer()
            self._invalidate_status_cache()
            self._send_json(result)
            return

        if path == "/api/resume":
            result = resume_active_transfer()
            self._invalidate_status_cache()
            self._send_json(result)
            return

        self._send_json({"error": "not_found"}, status=404)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


def serve(host: str = "127.0.0.1", port: int = 8000) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), AriaFlowHandler)
