import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import {
  advertiseHttpService,
  Aria2Client,
  bandwidthConfigFrom,
  callStartScheduler,
  deduplicateActiveTransfers,
  EventBus,
  reconcileLiveQueue,
  runBandwidthProbe,
  runSchedulerLoop,
} from "@ariaflow/core";
import { buildServer } from "@ariaflow/api";
import type { CliContext } from "../context.js";

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
    const initialCap = Number(state.last_bandwidth_probe?.cap_bytes_per_sec ?? 0) || 0;
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
            s.last_bandwidth_probe = fresh;
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
    // BG-40: callStartScheduler stamps the operator intent + handles
    // revert-on-failure, matching /api/scheduler/start semantics so
    // `ariaflow serve --scheduler` reports "starting"/"running"
    // (never "stopped") during the bootstrap window.
    await callStartScheduler(ctx.state, launchScheduler);
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
