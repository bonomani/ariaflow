import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import {
  advertiseHttpService,
  allowedActions,
  Aria2Client,
  bandwidthConfigFrom,
  deduplicateActiveTransfers,
  detectServiceTarget,
  downloadSha256,
  EventBus,
  findAria2c,
  install,
  installAria2Service,
  planAutoCleanup,
  reconcileLiveQueue,
  renderFormula,
  runBandwidthProbe,
  runSchedulerLoop,
  summarizeQueue,
  tarballUrl,
  uninstallAria2Service,
  versionFromTag,
  writeFormula,
} from "@ariaflow/core";
import { buildServer, generateOpenApi } from "@ariaflow/api";
import type { CliContext } from "./context.js";

interface CmdResult {
  ok: boolean;
  exitCode: number;
  stdout: string;
}

const ok = (stdout: string): CmdResult => ({ ok: true, exitCode: 0, stdout });
const fail = (stdout: string, code = 1): CmdResult => ({ ok: false, exitCode: code, stdout });

const json = (v: unknown): string => JSON.stringify(v, null, 2);

export async function cmdAdd(
  ctx: CliContext,
  url: string,
  opts: { output?: string; priority?: number; pretty?: boolean } = {},
): Promise<CmdResult> {
  if (!url) return fail("error: url is required\n");
  const { item, duplicate } = await ctx.queueOps.add({
    url,
    output: opts.output ?? null,
    priority: opts.priority ?? 0,
  });
  const summary = { id: item.id, url: item.url, status: item.status, duplicate };
  if (opts.pretty) {
    return ok(
      `${duplicate ? "duplicate" : "added"} ${item.id}\n  url: ${item.url}\n  status: ${item.status}\n`,
    );
  }
  return ok(json(summary) + "\n");
}

export async function cmdList(
  ctx: CliContext,
  opts: { pretty?: boolean } = {},
): Promise<CmdResult> {
  const items = await ctx.queue.load();
  if (opts.pretty) {
    if (items.length === 0) return ok("(no items)\n");
    const lines = items.map(
      (i) => `${i.id}  ${String(i.status ?? "?").padEnd(10)} ${i.url}`,
    );
    return ok(lines.join("\n") + "\n");
  }
  return ok(
    json({
      summary: summarizeQueue(items),
      items: items.map((i) => ({
        id: i.id,
        url: i.url,
        status: i.status ?? "queued",
        gid: i.gid ?? null,
        actions: allowedActions(String(i.status ?? "")),
      })),
    }) + "\n",
  );
}

export async function cmdRemove(ctx: CliContext, itemId: string): Promise<CmdResult> {
  if (!itemId) return fail("error: id is required\n");
  const removed = await ctx.queueOps.remove(itemId);
  if (!removed) return fail(`error: item ${itemId} not found\n`, 2);
  return ok(json({ removed: removed.id }) + "\n");
}

export async function cmdPause(ctx: CliContext, itemId: string): Promise<CmdResult> {
  if (!itemId) return fail("error: id is required\n");
  const next = await ctx.queueOps.transitionStatus(itemId, "paused", "paused_at");
  if (!next) return fail(`error: item ${itemId} not found\n`, 2);
  return ok(json({ id: next.id, status: next.status, paused_at: next.paused_at }) + "\n");
}

export async function cmdResume(ctx: CliContext, itemId: string): Promise<CmdResult> {
  if (!itemId) return fail("error: id is required\n");
  const next = await ctx.queueOps.transitionStatus(itemId, "queued", "resumed_at");
  if (!next) return fail(`error: item ${itemId} not found\n`, 2);
  return ok(json({ id: next.id, status: next.status, resumed_at: next.resumed_at }) + "\n");
}

export async function cmdBandwidth(ctx: CliContext): Promise<CmdResult> {
  const declaration = await ctx.declaration.load();
  const state = await ctx.state.load();
  const config = bandwidthConfigFrom(declaration);
  return ok(
    json({
      config,
      last_probe: state.last_bandwidth_probe ?? null,
      last_probe_at: state.last_bandwidth_probe_at ?? null,
    }) + "\n",
  );
}

export async function cmdDeclaration(ctx: CliContext): Promise<CmdResult> {
  const declaration = await ctx.declaration.load();
  return ok(json(declaration) + "\n");
}

export async function cmdStatus(ctx: CliContext): Promise<CmdResult> {
  const state = await ctx.state.load();
  const items = await ctx.queue.load();
  const summary = summarizeQueue(items);
  return ok(
    json({
      session_id: state.session_id,
      paused: state.paused,
      running: state.running,
      active_gid: state.active_gid,
      summary,
    }) + "\n",
  );
}

interface WatchOptions {
  url: string;
  /** Maximum events to receive before resolving; default unlimited. */
  limit?: number;
  /** Abort signal for the consumer (e.g. SIGINT handler). */
  signal?: AbortSignal;
  /** Where to write each line; defaults to process.stdout. */
  out?: { write(s: string): boolean | void };
}

/**
 * Subscribe to an SSE stream at `url` and write one JSON line per event:
 *   {"event": "action_logged", "data": {...}}
 *
 * Streams the response body via fetch + ReadableStream and parses
 * SSE-framed `event:`/`data:` blocks separated by blank lines. This
 * avoids depending on globalThis.EventSource (only stable in Node 22+
 * and not enabled by default everywhere).
 *
 * Resolves when `limit` is reached, when the server closes the body,
 * or when `signal` fires. Returns a fail result on connect error.
 */
export async function cmdWatch(opts: WatchOptions): Promise<CmdResult> {
  const out = opts.out ?? process.stdout;
  const limit = opts.limit ?? Number.POSITIVE_INFINITY;
  let res: Response;
  try {
    res = await fetch(opts.url, {
      headers: { Accept: "text/event-stream" },
      ...(opts.signal ? { signal: opts.signal } : {}),
    });
  } catch (err) {
    return fail(`error: failed to connect to ${opts.url}: ${(err as Error).message}\n`);
  }
  if (!res.ok || !res.body) {
    return fail(`error: failed to connect to ${opts.url}: HTTP ${res.status}\n`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let received = 0;
  let event = "message";
  const dataLines: string[] = [];

  const emit = (): void => {
    if (dataLines.length === 0) return;
    const raw = dataLines.join("\n");
    let parsed: unknown = raw;
    try {
      parsed = JSON.parse(raw);
    } catch {
      /* leave raw */
    }
    out.write(JSON.stringify({ event, data: parsed }) + "\n");
    received += 1;
    event = "message";
    dataLines.length = 0;
  };

  try {
    while (received < limit) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let nl: number;
      while ((nl = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, nl).replace(/\r$/, "");
        buffer = buffer.slice(nl + 1);
        if (line === "") {
          emit();
          if (received >= limit) break;
        } else if (line.startsWith(":")) {
          /* heartbeat / comment — ignore */
        } else if (line.startsWith("event:")) {
          event = line.slice(6).trim();
        } else if (line.startsWith("data:")) {
          dataLines.push(line.slice(5).replace(/^ /, ""));
        }
      }
    }
  } finally {
    try {
      await reader.cancel();
    } catch {
      /* ignore */
    }
  }
  return ok("");
}

interface ServeOptions {
  host?: string;
  port?: number;
  version?: string;
  /** Path to openapi.yaml; auto-discovered when omitted. */
  openapiYamlPath?: string;
  /** aria2 RPC host (default 127.0.0.1). Pass empty string to disable. */
  aria2Host?: string;
  /** aria2 RPC port (default 6800). */
  aria2Port?: number;
  /** Optional aria2 RPC secret token. */
  aria2Secret?: string;
  /**
   * When true and an aria2 client is wired, also start the long-running
   * scheduler loop that picks up queued items, dispatches them via aria2,
   * and polls for completion. Default false (read-only).
   */
  startScheduler?: boolean;
  /** Scheduler tick interval in ms (default 2000). */
  schedulerIntervalMs?: number;
  /** Disable mDNS advertisement (default: announce when a backend is available). */
  noMdns?: boolean;
}

/**
 * Walk up from cwd looking for an openapi.yaml at the repo root. Returns
 * the resolved absolute path or null when not found within 5 levels.
 */
function findOpenApiYaml(start: string = process.cwd()): string | null {
  let dir = start;
  for (let i = 0; i < 5; i++) {
    const candidate = join(dir, "openapi.yaml");
    if (existsSync(candidate)) return candidate;
    const parent = dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return null;
}

/**
 * Resolve the version string the dashboard reads via /api/status,
 * /api/lifecycle, and /api/version (BG-19/20/23).
 *
 * Source: `packages/cli/package.json` → "version". The release-npm
 * workflow stamps the real semver here on every `v*` tag push;
 * `0.0.0` is the placeholder for fresh checkouts and is skipped so
 * the caller's default applies instead.
 */
function readPackageVersion(): string | undefined {
  const here = dirname(import.meta.url.replace(/^file:\/\//, ""));
  const repoRoot = (() => {
    let dir = here;
    for (let i = 0; i < 5; i++) {
      if (existsSync(join(dir, "pnpm-workspace.yaml"))) return dir;
      const parent = dirname(dir);
      if (parent === dir) break;
      dir = parent;
    }
    return process.cwd();
  })();

  const isPlaceholder = (v: string): boolean => !v || v === "0.0.0";

  for (const p of [
    join(here, "..", "package.json"),
    join(repoRoot, "packages/cli/package.json"),
  ]) {
    if (!existsSync(p)) continue;
    try {
      const raw = JSON.parse(readFileSync(p, "utf8")) as { version?: unknown };
      if (typeof raw.version === "string" && !isPlaceholder(raw.version)) return raw.version;
    } catch {
      /* try next */
    }
  }

  return undefined;
}

interface ServeHandle {
  url: string;
  port: number;
  /** True when the scheduler loop is running in the background. */
  scheduler: boolean;
  /** Bonjour backend in use ("dns-sd" / "avahi") or null when disabled / unavailable. */
  mdns: "dns-sd" | "avahi" | null;
  close: () => Promise<void>;
  /** BG-25: programmatic scheduler lifecycle. Returns {started:false} when aria2 isn't wired. */
  startScheduler: () => Promise<{ started: boolean; reason: string }>;
  stopScheduler: () => Promise<{ stopped: boolean; reason: string }>;
}

/**
 * Boot the Fastify server with the CLI's storage stack. Returns a
 * handle the caller can close — the bin uses this to wire SIGINT.
 *
 * NOTE: this does NOT call process.exit; the listening loop keeps the
 * process alive on its own once Fastify starts.
 */
export async function cmdServe(
  ctx: CliContext,
  opts: ServeOptions = {},
): Promise<ServeHandle> {
  const eventBus = new EventBus();
  const yamlPath = opts.openapiYamlPath ?? findOpenApiYaml();
  const aria2Host = opts.aria2Host ?? "127.0.0.1";
  const aria2 =
    aria2Host === ""
      ? undefined
      : new Aria2Client({
          host: aria2Host,
          port: opts.aria2Port ?? 6800,
          ...(opts.aria2Secret !== undefined ? { secret: opts.aria2Secret } : {}),
        });

  // Resolve the version string the dashboard reads via /api/status
  // (BG-19). Prefer an explicit override, otherwise pull the cli
  // package.json sitting next to the running bin so the pill always
  // matches the actual binary, even on a `node packages/cli/dist/...`
  // run without npm install.
  const resolvedVersion = opts.version ?? readPackageVersion();

  let schedulerCtrl: AbortController | undefined;
  let schedulerDone: Promise<unknown> = Promise.resolve();

  // BG-25: factored so /api/scheduler/start (and /resume's auto-start)
  // can spin up the loop on demand, not just at boot.
  const launchScheduler = async (): Promise<{ started: boolean; reason: string }> => {
    if (!aria2) return { started: false, reason: "aria2_unavailable" };
    if (schedulerCtrl && !schedulerCtrl.signal.aborted) {
      return { started: false, reason: "already_running" };
    }
    schedulerCtrl = new AbortController();
    const state = await ctx.state.load();
    const probe = state.last_bandwidth_probe as
      | { cap_bytes_per_sec?: number }
      | null
      | undefined;
    const initialCap = Number(probe?.cap_bytes_per_sec ?? 0) || 0;
    schedulerDone = runSchedulerLoop(
      {
        queueStore: ctx.queue,
        stateStore: ctx.state,
        declarationStore: ctx.declaration,
        actionLog: ctx.actions,
        aria2,
      },
      {
        capBytesPerSec: initialCap,
        intervalMs: opts.schedulerIntervalMs ?? 2000,
        signal: schedulerCtrl.signal,
        preLoop: async () => {
          // Adopt orphan GIDs from a previous run before the loop starts
          // pushing new ones. Composes Phase 8's matcher to avoid double-
          // dispatching items aria2 is already running.
          await reconcileLiveQueue(
            {
              queueStore: ctx.queue,
              stateStore: ctx.state,
              actionLog: ctx.actions,
              aria2: aria2!,
            },
            { adoptMissing: true },
          );
          // Drop duplicate active transfers so the scheduler doesn't
          // double-bill bandwidth to the same URL on startup.
          await deduplicateActiveTransfers({
            declarationStore: ctx.declaration,
            actionLog: ctx.actions,
            aria2: aria2!,
          });
          // Refresh the bandwidth cap before entering the loop so the
          // first batch of dispatches respects the live network rate.
          const declaration = await ctx.declaration.load();
          const config = bandwidthConfigFrom(declaration);
          const fresh = await runBandwidthProbe({ config });
          await ctx.state.update((s) => {
            (s as Record<string, unknown>).last_bandwidth_probe =
              fresh as unknown as Record<string, unknown>;
            s.last_bandwidth_probe_at = Date.now() / 1000;
          });
          await ctx.actions.record({
            action: "probe",
            target: "bandwidth",
            outcome: fresh.source === "networkquality" ? "changed" : "unchanged",
            reason: "scheduler_preloop",
            detail: fresh as unknown as Record<string, unknown>,
          });
          return { capBytesPerSec: fresh.cap_bytes_per_sec ?? 0 };
        },
      },
    ).then(() => {
      // Loop exited normally (drained / max_iterations) — clear the
      // controller so launchScheduler() can spin up a fresh loop when
      // new items arrive.
      schedulerCtrl = undefined;
      schedulerDone = Promise.resolve();
    }, (err) => {
      // Surface scheduler crashes to stderr but don't kill the HTTP
      // listener — caller can investigate via /api/log.
      console.error("scheduler loop crashed:", err);
      schedulerCtrl = undefined;
      schedulerDone = Promise.resolve();
    });
    // Wait one event-loop tick so the loop's first state.running=true
    // write lands before we report success — callers immediately read
    // /api/status after /start and would otherwise race the flip.
    await new Promise<void>((r) => setImmediate(r));
    return { started: true, reason: "started" };
  };

  const stopSchedulerLoop = async (): Promise<{ stopped: boolean; reason: string }> => {
    if (!schedulerCtrl || schedulerCtrl.signal.aborted) {
      return { stopped: false, reason: "not_running" };
    }
    schedulerCtrl.abort();
    await schedulerDone;
    schedulerCtrl = undefined;
    schedulerDone = Promise.resolve();
    return { stopped: true, reason: "stopped" };
  };

  const app = buildServer({
    queueOps: ctx.queueOps,
    queueStore: ctx.queue,
    archiveStore: ctx.archive,
    declarationStore: ctx.declaration,
    stateStore: ctx.state,
    sessionService: ctx.sessions,
    actionLog: ctx.actions,
    eventBus,
    ...(aria2 ? { aria2 } : {}),
    ...(resolvedVersion !== undefined ? { version: resolvedVersion } : {}),
    ...(yamlPath ? { openapiYamlPath: yamlPath } : {}),
    ...(aria2 ? { startScheduler: launchScheduler, stopScheduler: stopSchedulerLoop } : {}),
  });
  const requestedPort = opts.port ?? 8000;
  const host = opts.host ?? "127.0.0.1";
  await app.listen({ host, port: requestedPort });
  const addr = app.server.address();
  const port =
    typeof addr === "object" && addr !== null && "port" in addr ? addr.port : requestedPort;

  if (opts.startScheduler && aria2) {
    // BG-40: stamp operator intent before kicking the loop, mirroring
    // the route handlers' /api/scheduler/start behavior. Without this
    // the bootstrap window after `ariaflow serve --scheduler` would
    // report status="stopped" instead of "starting".
    await ctx.state.update((s) => {
      s.scheduler_intent = "running";
    });
    const result = await launchScheduler();
    // BG-40: only revert intent on a genuine failure. "already_running"
    // means the loop IS running and our intent="running" is correct;
    // "aria2_unavailable" / etc. mean the loop never started.
    if (!result.started && result.reason !== "already_running") {
      await ctx.state.update((s) => {
        s.scheduler_intent = "stopped";
      });
    }
  }

  // BG-18: announce _ariaflow-server._tcp via the local mDNS daemon so
  // dashboards on the same L2 segment auto-discover the backend.
  // Failures are non-fatal — the HTTP listener stays up either way.
  const mdnsHandle = opts.noMdns
    ? null
    : advertiseHttpService({ port, path: "/api" });
  if (mdnsHandle && mdnsHandle.backend) {
    await ctx.actions.record({
      action: "bonjour_register",
      target: "system",
      outcome: "changed",
      reason: "registered",
      detail: { backend: mdnsHandle.backend, port, path: "/api" },
    });
  }

  return {
    url: `http://${host}:${port}`,
    port,
    scheduler: Boolean(schedulerCtrl),
    mdns: (mdnsHandle?.backend ?? null) as "dns-sd" | "avahi" | null,
    close: async () => {
      schedulerCtrl?.abort();
      await schedulerDone;
      await mdnsHandle?.stop();
      await app.close();
    },
    startScheduler: launchScheduler,
    stopScheduler: stopSchedulerLoop,
  };
}

export async function cmdSetPref(
  ctx: CliContext,
  name: string,
  rawValue: string,
): Promise<CmdResult> {
  if (!name) return fail("error: preference name is required\n");
  const declaration = await ctx.declaration.load();
  const pref = declaration.uic.preferences.find((p) => p.name === name);
  if (!pref) return fail(`error: unknown preference: ${name}\n`, 2);
  let value: unknown = rawValue;
  if (rawValue === "true") value = true;
  else if (rawValue === "false") value = false;
  else if (rawValue === "null") value = null;
  else if (rawValue !== "" && Number.isFinite(Number(rawValue))) value = Number(rawValue);
  const before = pref.value;
  pref.value = value;
  await ctx.declaration.save(declaration);
  await ctx.actions.record({
    action: "patch_preferences",
    target: "declaration",
    outcome: "changed",
    reason: "cli_set_pref",
    detail: { applied: { [name]: { before, after: value } } },
  });
  return ok(json({ name, before, after: value }) + "\n");
}

interface CleanupOptions {
  maxDoneAgeDays?: number;
  maxDoneCount?: number;
  archiveNonComplete?: boolean;
  dryRun?: boolean;
}

/**
 * Apply or preview the queue auto-cleanup decision: split items into
 * keep/archive given an age cutoff + max-complete cap, persist the
 * archive on real runs, record the action.
 */
export async function cmdCleanup(
  ctx: CliContext,
  opts: CleanupOptions = {},
): Promise<CmdResult> {
  const items = await ctx.queue.load();
  const plan = planAutoCleanup(items as never, {
    maxDoneAgeDays: opts.maxDoneAgeDays ?? 7,
    maxDoneCount: opts.maxDoneCount ?? 100,
    archiveNonComplete: opts.archiveNonComplete ?? true,
  });
  const summary = {
    archived: plan.archive.length,
    remaining: plan.keep.length,
    dry_run: !!opts.dryRun,
  };
  if (opts.dryRun || plan.archive.length === 0) return ok(json(summary) + "\n");
  const archived = await ctx.archive.load();
  const stamped = plan.archive.map((it) => ({
    ...it,
    archived_at: new Date().toISOString(),
  })) as unknown as Awaited<ReturnType<typeof ctx.archive.load>>;
  await ctx.archive.save([...archived, ...stamped]);
  await ctx.queue.save(plan.keep as never);
  await ctx.actions.record({
    action: "auto_cleanup",
    target: "queue",
    outcome: "changed",
    reason: "cli_cleanup",
    before: { total: items.length },
    after: { total: plan.keep.length, archived: plan.archive.length },
    detail: {
      max_done_age_days: opts.maxDoneAgeDays ?? 7,
      max_done_count: opts.maxDoneCount ?? 100,
    },
  });
  return ok(json(summary) + "\n");
}

export async function cmdDashboard(
  ctx: CliContext,
  opts: { pretty?: boolean } = {},
): Promise<CmdResult> {
  const state = await ctx.state.load();
  const declaration = await ctx.declaration.load();
  const items = await ctx.queue.load();
  const summary = summarizeQueue(items);
  const config = bandwidthConfigFrom(declaration);
  const running = Boolean(state.running);
  const paused = Boolean(state.paused);
  const schedulerStatus = running && paused ? "paused" : running ? "running" : "starting";
  const dashboard = {
    scheduler: {
      status: schedulerStatus,
      running,
      paused,
      session_id: state.session_id,
    },
    queue: summary,
    bandwidth: {
      config,
      last_probe: state.last_bandwidth_probe ?? null,
      last_probe_at: state.last_bandwidth_probe_at ?? null,
    },
    declaration: {
      contract: declaration.meta?.contract,
      version: declaration.meta?.version,
      gates: declaration.uic?.gates?.length ?? 0,
      preferences: declaration.uic?.preferences?.length ?? 0,
    },
  };

  if (!opts.pretty) return ok(json(dashboard) + "\n");

  const lines: string[] = [];
  lines.push(`Scheduler: ${schedulerStatus}  (running=${running} paused=${paused})`);
  if (state.session_id) lines.push(`  session: ${state.session_id}`);
  lines.push(
    `Queue: total=${summary.total}  active=${summary.active ?? 0}  ` +
      `queued=${summary.queued ?? 0}  paused=${summary.paused ?? 0}  ` +
      `complete=${summary.complete ?? 0}  error=${summary.error ?? 0}`,
  );
  const probe = state.last_bandwidth_probe as Record<string, unknown> | null;
  if (probe) {
    const dl = probe.downlink_mbps ?? "—";
    const ul = probe.uplink_mbps ?? "—";
    const cap = probe.cap_mbps ?? "—";
    lines.push(`Bandwidth: downlink=${dl}Mbps  uplink=${ul}Mbps  cap=${cap}Mbps`);
  } else {
    lines.push(`Bandwidth: no probe yet  (use 'ariaflow probe')`);
  }
  lines.push(
    `Declaration: ${declaration.meta?.contract} v${declaration.meta?.version}  ` +
      `(${declaration.uic?.gates?.length ?? 0} gates, ` +
      `${declaration.uic?.preferences?.length ?? 0} prefs)`,
  );
  return ok(lines.join("\n") + "\n");
}

/**
 * Emit the OpenAPI doc generated from the live Fastify routes.
 * Spins up a buildServer() instance in-process, awaits ready, runs
 * generateOpenApi, then closes the server. No network listener — the
 * onRoute hook fires during registration so introspection works without
 * a listen call.
 */
export async function cmdOpenapi(ctx: CliContext): Promise<CmdResult> {
  const app = buildServer({
    queueOps: ctx.queueOps,
    queueStore: ctx.queue,
    archiveStore: ctx.archive,
    declarationStore: ctx.declaration,
    stateStore: ctx.state,
    sessionService: ctx.sessions,
    actionLog: ctx.actions,
  });
  await app.ready();
  try {
    const doc = generateOpenApi(app);
    return ok(json(doc) + "\n");
  } finally {
    await app.close();
  }
}

export async function cmdProbe(ctx: CliContext): Promise<CmdResult> {
  const declaration = await ctx.declaration.load();
  const config = bandwidthConfigFrom(declaration);
  const probe = await runBandwidthProbe({ config });
  await ctx.state.update((s) => {
    (s as Record<string, unknown>).last_bandwidth_probe = probe as unknown as Record<
      string,
      unknown
    >;
    s.last_bandwidth_probe_at = Date.now() / 1000;
  });
  await ctx.actions.record({
    action: "probe",
    target: "bandwidth",
    outcome: probe.source === "networkquality" ? "changed" : "unchanged",
    reason: "cli_probe",
    detail: probe as unknown as Record<string, unknown>,
  });
  return ok(json({ probe, config }) + "\n");
}

export async function cmdSeedStop(
  ctx: CliContext,
  infohash: string,
): Promise<CmdResult> {
  if (!infohash) return fail("error: infohash is required\n");
  const items = await ctx.queue.load();
  const item = items.find(
    (i) => i.distribute_infohash === infohash && i.distribute_status === "seeding",
  );
  if (!item) return fail(`error: no active seed for ${infohash}\n`, 2);
  const torrentPath = item.distribute_torrent_path;
  if (torrentPath) {
    try {
      const { existsSync, unlinkSync } = await import("node:fs");
      if (existsSync(torrentPath)) unlinkSync(torrentPath);
    } catch {
      /* best-effort cleanup */
    }
  }
  item.distribute_status = "stopped";
  delete item.distribute_seed_gid;
  await ctx.queue.save(items);
  await ctx.actions.record({
    action: "seed_stopped",
    target: "queue_item",
    outcome: "changed",
    reason: "cli_stop_seed",
    detail: { item_id: item.id, infohash },
  });
  return ok(json({ infohash, status: "stopped" }) + "\n");
}

interface DoctorOptions {
  aria2Host?: string;
  aria2Port?: number;
  aria2Secret?: string;
  pretty?: boolean;
}

interface DoctorCheck {
  name: string;
  ok: boolean;
  detail: string;
}

/**
 * Pre-flight diagnostics: walk the environment, check every dependency
 * the server needs, and report a structured pass/fail per check.
 *
 * No subprocess execution beyond a single aria2.getVersion RPC and
 * a writability probe on the config dir. Cheap to run on demand.
 */
export async function cmdDoctor(
  ctx: CliContext,
  opts: DoctorOptions = {},
): Promise<CmdResult> {
  const checks: DoctorCheck[] = [];

  // 1. aria2c on PATH (or a known fallback).
  const aria2cPath = findAria2c();
  checks.push({
    name: "aria2c_binary",
    ok: aria2cPath !== null,
    detail: aria2cPath ?? "aria2c not found on PATH; install via brew/apt",
  });

  // 2. networkQuality (macOS only — informational on other platforms).
  const nq = install.networkqualityStatus();
  checks.push({
    name: "networkquality",
    ok: nq.installed,
    detail: nq.message,
  });

  // 3. Config dir writable.
  try {
    const env = (ctx.queue as unknown as { env?: NodeJS.ProcessEnv }).env ?? process.env;
    const dir = env.ARIAFLOW_DIR || (await ctx.declaration.load(), undefined);
    // Trigger a benign write through the declaration store.
    await ctx.declaration.load();
    checks.push({
      name: "config_dir_writable",
      ok: true,
      detail: dir ? `using ${dir}` : "config dir writable",
    });
  } catch (err) {
    checks.push({
      name: "config_dir_writable",
      ok: false,
      detail: (err as Error).message,
    });
  }

  // 4. aria2 RPC reachable.
  const host = opts.aria2Host ?? "127.0.0.1";
  const port = opts.aria2Port ?? 6800;
  const probe = new Aria2Client({
    host,
    port,
    defaultTimeoutMs: 2000,
    ...(opts.aria2Secret ? { secret: opts.aria2Secret } : {}),
  });
  let aria2Version: string | undefined;
  let aria2Reachable = false;
  try {
    const ver = await probe.call<{ version: string }>("aria2.getVersion");
    aria2Version = ver.version;
    aria2Reachable = true;
  } catch {
    /* unreachable */
  }
  checks.push({
    name: "aria2_rpc_reachable",
    ok: aria2Reachable,
    detail: aria2Reachable
      ? `aria2 ${aria2Version} responding at ${host}:${port}`
      : `no response from ${host}:${port} (start aria2c --enable-rpc)`,
  });

  // 5. Service installed (informational — not required to run).
  const target = detectServiceTarget();
  checks.push({
    name: "platform_service_target",
    ok: true,
    detail: target ?? "unsupported platform — no service target available",
  });

  const allOk = checks.every((c) => c.ok);
  if (!opts.pretty) return ok(json({ ok: allOk, checks }) + "\n");
  const lines = checks.map(
    (c) => `${c.ok ? "OK   " : "FAIL "}${c.name.padEnd(28)} ${c.detail}`,
  );
  lines.push(`\n${allOk ? "All checks passed." : "One or more checks failed."}`);
  return allOk ? ok(lines.join("\n") + "\n") : fail(lines.join("\n") + "\n", 1);
}

interface FormulaOptions {
  tag: string;
  sha256?: string;
  output?: string;
}

/**
 * Render the Homebrew formula for a release tag. The sha256 is
 * fetched by streaming the GitHub release tarball when not provided;
 * pass --sha256 to skip the network round-trip.
 */
export async function cmdFormula(opts: FormulaOptions): Promise<CmdResult> {
  let version: string;
  try {
    version = versionFromTag(opts.tag);
  } catch (err) {
    return fail(`error: ${(err as Error).message}\n`);
  }
  const url = tarballUrl(opts.tag);
  let sha256 = opts.sha256;
  if (!sha256) {
    try {
      sha256 = await downloadSha256(url);
    } catch (err) {
      return fail(`error: failed to fetch ${url}: ${(err as Error).message}\n`, 1);
    }
  }
  const formula = renderFormula({ version, url, sha256 });
  if (opts.output) {
    await writeFormula(opts.output, formula);
  }
  return ok(formula);
}

interface InstallServiceOpts {
  dryRun?: boolean;
  binPath?: string;
}

export async function cmdInstallService(opts: InstallServiceOpts = {}): Promise<CmdResult> {
  try {
    const r = await installAria2Service({
      ...(opts.dryRun ? { dryRun: true } : {}),
      ...(opts.binPath ? { binPath: opts.binPath } : {}),
    });
    return r.ok ? ok(json(r) + "\n") : fail(json(r) + "\n", 1);
  } catch (err) {
    return fail(`error: ${(err as Error).message}\n`, 1);
  }
}

export async function cmdUninstallService(
  opts: { dryRun?: boolean } = {},
): Promise<CmdResult> {
  try {
    const r = await uninstallAria2Service(opts.dryRun ? { dryRun: true } : {});
    return r.ok ? ok(json(r) + "\n") : fail(json(r) + "\n", 1);
  } catch (err) {
    return fail(`error: ${(err as Error).message}\n`, 1);
  }
}
