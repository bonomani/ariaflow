from __future__ import annotations

import json
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .contracts import load_declaration, preflight, run_ucc, save_declaration
from .core import (
    add_queue_item,
    active_status,
    load_action_log,
    aria_status,
    current_bandwidth,
    format_bytes,
    format_mbps,
    format_rate,
    get_active_progress,
    load_queue,
    load_state,
    pause_active_transfer,
    record_action,
    resume_active_transfer,
    save_state,
    start_background_process,
    summarize_queue,
)
from .install import install_all, status_all, uninstall_all


STATUS_CACHE: dict[str, object] = {"ts": 0.0, "payload": None}
STATUS_CACHE_TTL = 2.0


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
    .item.compact {
      padding: 12px 14px;
      display: grid;
      gap: 8px;
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
    .page-only { display: none; }
    body.page-dashboard .show-dashboard,
    body.page-bandwidth .show-bandwidth,
    body.page-lifecycle .show-lifecycle,
    body.page-log .show-log { display: block; }
    @media (max-width: 980px) {
      .hero, .summary { grid-template-columns: 1fr; }
      .span-8, .span-7, .span-5, .span-4, .span-6 { grid-column: span 12; }
    }
  </style>
</head>
<body data-page="dashboard">
  <div class="wrap">
    <div class="nav">
      <a href="/" data-page="dashboard">Dashboard</a>
      <a href="/bandwidth" data-page="bandwidth">Bandwidth</a>
      <a href="/lifecycle" data-page="lifecycle">Lifecycle</a>
      <a href="/log" data-page="log">Log</a>
    </div>
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
        <div class="chips">
          <div class="chip">aria2 <strong id="chip-aria2">unknown</strong></div>
          <div class="chip">Cap <strong id="chip-cap">-</strong></div>
          <div class="chip">Speed <strong id="chip-speed">-</strong></div>
          <div class="chip">Last error <strong id="chip-error">none</strong></div>
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
      <div class="span-12 show-dashboard page-only">
        <div class="panel toolbar">
          <div class="row">
            <input id="url" placeholder="Paste download URL">
            <button onclick="add()">Add to queue</button>
            <button class="secondary" onclick="preflightRun()">Preflight</button>
            <button class="secondary" onclick="runQueue()">Run</button>
            <button class="secondary" id="toggle-btn" onclick="toggleQueue()">Pause</button>
          </div>
        </div>
      </div>
      <div class="span-12 show-dashboard page-only">
        <div class="panel">
          <div class="section-title">
            <h2>Queue</h2>
            <div class="hint">One download at a time</div>
          </div>
          <div id="queue" class="list">Loading...</div>
        </div>
      </div>
      <div class="span-7 show-dashboard page-only">
        <div class="panel">
          <div class="section-title">
            <h2>Active download</h2>
            <div class="hint">Live progress</div>
          </div>
          <div id="active" class="transfer">Idle</div>
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
              <option value="ucc">UCC</option>
              <option value="probe">Probe</option>
              <option value="pause">Pause</option>
              <option value="resume">Resume</option>
              <option value="poll">Poll</option>
              <option value="complete">Complete</option>
              <option value="error">Error</option>
              <option value="lifecycle_install_preview">Install preview</option>
              <option value="lifecycle_uninstall_preview">Uninstall preview</option>
            </select>
            <select id="target-filter" onchange="refreshActionLog()">
              <option value="all">All targets</option>
              <option value="bandwidth">Bandwidth</option>
              <option value="queue">Queue</option>
              <option value="queue_item">Queue item</option>
              <option value="active_transfer">Active transfer</option>
              <option value="system">System</option>
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
    let lastDeclaration = null;
    const path = window.location.pathname.replace(/\/+$/, "");
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
    function renderQueueItem(item) {
      const status = item.status || "unknown";
      const detail = [
        item.created_at ? `Created ${item.created_at}` : null,
        item.post_action_rule ? `Rule ${item.post_action_rule}` : null,
        item.gid ? `GID ${item.gid}` : null,
        item.error_message ? item.error_message : null,
      ].filter(Boolean).join(" · ");
      const shortUrl = item.output || (item.url ? item.url.split('/').pop() : '(no url)');
      return `
        <div class="item compact">
          <div class="item-top">
            <div class="item-url">${shortUrl}</div>
            <span class="${badgeClass(status)}">${status}</span>
          </div>
          <div class="meta">
            ${item.url ? `<span title="${item.url}">${item.url}</span>` : ""}
            ${detail ? `<span class="mono">${detail}</span>` : ""}
          </div>
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
      return entries
        .filter((entry) => currentFilter === 'all' ? true : (entry.action || 'unknown') === currentFilter)
        .filter((entry) => currentTarget === 'all' ? true : (entry.target || 'unknown') === currentTarget)
        .slice()
        .reverse()
        .map((entry) => {
        const status = entry.outcome || entry.status || "unknown";
        const lines = [
          entry.timestamp ? `At ${entry.timestamp}` : null,
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
        document.getElementById('queue').innerHTML = (data.items || []).length ? data.items.map(renderQueueItem).join("") : "<div class='item'>Queue is empty.</div>";
        const active = data.active || {status: 'idle'};
        const speed = active.downloadSpeed || data.state?.download_speed || "-";
        const state = data.state || {};
        document.getElementById('chip-error').textContent = state.last_error || 'none';
        document.getElementById('chip-speed').textContent = formatRate(active.downloadSpeed || null);
        document.getElementById('chip-cap').textContent = data.bandwidth?.cap_mbps ? formatMbps(data.bandwidth.cap_mbps) : (data.bandwidth?.limit || '-');
        document.getElementById('chip-aria2').textContent = data.aria2?.reachable ? `v${data.aria2.version}` : 'offline';
        const toggleButton = document.getElementById('toggle-btn');
        if (toggleButton) toggleButton.textContent = data.state && data.state.paused ? 'Resume' : 'Pause';
        const activeName = shortName(active.url || active.gid || "No active download");
        const activePauseButton = state.paused
          ? `<button class="secondary icon-btn" onclick="toggleQueue()" title="Resume">▶</button>`
          : `<button class="secondary icon-btn" onclick="toggleQueue()" title="Pause">⏸</button>`;
        const activeRecoveryBadge = active.recovered ? `<span class="badge warn">recovered</span>` : "";
        document.getElementById('active').innerHTML = `
          <div class="transfer-head">
            <div>
              <div class="transfer-name">${activeName} ${activeRecoveryBadge}</div>
              <div class="transfer-sub">${active.url || "No active download"}</div>
            </div>
            <div class="action-strip">
              ${activePauseButton}
              <button class="secondary icon-btn" onclick="preflightRun()" title="Preflight">✓</button>
              <button class="secondary icon-btn" onclick="runQueue()" title="Run">⟳</button>
            </div>
          </div>
          <div class="meter"><div id="bar"></div></div>
          <div class="statusline">
            <span>${Math.round(Number(active.percent || 0))}% done</span>
            <span>${active.downloadSpeed ? formatRate(active.downloadSpeed) : "waiting"}</span>
          </div>
          <div class="meta">
            ${active.totalLength ? `<span>Total ${formatBytes(active.totalLength)}</span>` : ""}
            ${active.completedLength ? `<span>Done ${formatBytes(active.completedLength)}</span>` : ""}
            ${active.gid ? `<span>GID ${active.gid}</span>` : ""}
            ${active.errorMessage ? `<span class="mono">${active.errorMessage}</span>` : ""}
          </div>
        `;
        const percent = active && active.percent != null ? active.percent : 0;
        document.getElementById('bar').style.width = percent + '%';
        document.getElementById('mode-label').textContent = data.state && data.state.paused ? 'paused' : (data.state && data.state.running ? 'running' : 'idle');
        document.getElementById('active-label').textContent = active.url || 'none';
        document.getElementById('queue-label').textContent = `${(data.summary && data.summary.total) || 0} item(s)`;
        document.getElementById('sum-speed').textContent = speed && speed !== "-" ? speed : "-";
        renderQueueSummary(data.summary);
        document.getElementById('bw-source').textContent = data.bandwidth?.source || '-';
        document.getElementById('bw-down').textContent = data.bandwidth?.source === 'networkquality'
          ? `Downlink ${formatMbps(data.bandwidth.downlink_mbps)}${data.bandwidth.partial ? ' (partial capture)' : ''}`
          : 'No networkquality probe available';
        document.getElementById('bw-cap').textContent = data.bandwidth?.cap_mbps ? formatMbps(data.bandwidth.cap_mbps) : '-';
        document.getElementById('bw-global').textContent = data.bandwidth_global?.limit ? `Global limit ${data.bandwidth_global.limit}` : 'Global option unavailable';
        document.getElementById('bw-live').textContent = active.status || 'idle';
        document.getElementById('bw-live-detail').textContent = active.downloadSpeed
          ? `Speed ${formatRate(active.downloadSpeed)}${active.completedLength ? ` · ${formatBytes(active.completedLength)}/${formatBytes(active.totalLength || 0)}` : ''}`
          : 'No active transfer';
        document.getElementById('bw-probe-mode').textContent = data.bandwidth?.source || '-';
        document.getElementById('bw-probe-detail').textContent = data.bandwidth?.source === 'networkquality'
          ? `Measured ${formatMbps(data.bandwidth.downlink_mbps)} and capped at ${formatMbps(data.bandwidth.cap_mbps)}${data.bandwidth.partial ? ' from partial output' : ''}`
          : 'Using default floor because no probe was available';
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
      document.getElementById('preflight').innerHTML = renderPreflight(data);
      await refresh();
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
      const trace = document.getElementById('contract-trace');
      if (trace) trace.innerHTML = renderContractTrace(data);
      const actionLog = document.getElementById('action-log');
      if (actionLog && lastStatus) actionLog.innerHTML = renderActionLog(lastStatus.action_log || []);
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
    async function refreshActionLog() {
      if (page !== 'log') return;
      const r = await fetch('/api/log');
      const data = await r.json();
      const actionLog = document.getElementById('action-log');
      if (actionLog) actionLog.innerHTML = renderActionLog(data.items || []);
    }
    document.getElementById('action-filter')?.addEventListener('change', refreshActionLog);
    refresh();
    setInterval(refresh, 2000);
    loadDeclaration();
    loadLifecycle();
    if (page === 'log') refreshActionLog();
    applyPage();
  </script>
</body>
</html>
"""


class AriaFlowHandler(BaseHTTPRequestHandler):
    def _invalidate_status_cache(self) -> None:
        STATUS_CACHE["ts"] = 0.0
        STATUS_CACHE["payload"] = None

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
        }
        active = active_status(timeout=3)
        if active:
            payload["active"] = active
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
        path = urlparse(self.path).path
        if path in {"/", "/index.html", "/bandwidth", "/lifecycle", "/log"}:
            body = INDEX_HTML.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/status":
            self._send_json(self._status_payload())
            return
        if path == "/api/log":
            self._send_json({"items": load_action_log()})
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
            self._invalidate_status_cache()
            self._send_json({"added": item.__dict__})
            return

        if path == "/api/preflight":
            before = {"state": load_state(), "queue": summarize_queue(load_queue())}
            result = preflight()
            result["aria2"] = aria_status()
            result["bandwidth"] = current_bandwidth()
            result["action_log"] = load_action_log()
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
            result = start_background_process()
            record_action(
                action="run",
                target="queue",
                outcome="changed" if result.get("started") else "unchanged",
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

        if path == "/api/lifecycle/install":
            before = {"lifecycle": status_all()}
            result = install_all(dry_run=True, include_web=False)
            record_action(
                action="lifecycle_install_preview",
                target="system",
                outcome="converged",
                reason="preview",
                before=before,
                after={"lifecycle": status_all(), "preview": result},
                detail=result,
            )
            self._invalidate_status_cache()
            self._send_json(result)
            return

        if path == "/api/lifecycle/uninstall":
            before = {"lifecycle": status_all()}
            result = uninstall_all(dry_run=True, include_web=False)
            record_action(
                action="lifecycle_uninstall_preview",
                target="system",
                outcome="converged",
                reason="preview",
                before=before,
                after={"lifecycle": status_all(), "preview": result},
                detail=result,
            )
            self._invalidate_status_cache()
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
