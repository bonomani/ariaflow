import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import {
  ACTIONS,
  TARGETS,
  advertiseHttpService,
  aria2AutoStartInstalled,
  Aria2Client,
  callStartScheduler,
  EventBus,
  installAria2Service,
  prefValue,
  uninstallAria2Service,
} from "@ariaflow/core";
import { buildServer } from "@ariaflow/api";
import type { CliContext } from "../context.js";
import { createSchedulerController } from "./_scheduler_controller.js";

interface ServeOptions {
  host?: string;
  port?: number;
  version?: string;
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
  /**
   * BG-45: skip the auto-start reconciliation pass on boot. Used by
   * tests that don't want cmdServe to mutate real launchd / systemd
   * state. Production code never sets this.
   */
  skipAutoStartReconcile?: boolean;
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

  // Walk up from `here` looking for the first package.json. After R-H
  // split commands.ts into commands/, `here` is .../dist/commands/ —
  // two levels deep instead of one. A bounded walk-up handles both
  // shapes (and any future restructure) without hard-coded depths.
  const candidates: string[] = [];
  let dir = here;
  for (let i = 0; i < 5; i++) {
    candidates.push(join(dir, "package.json"));
    const parent = dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  candidates.push(join(repoRoot, "packages/cli/package.json"));

  for (const p of candidates) {
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

  const scheduler = createSchedulerController(ctx, aria2, {
    ...(opts.schedulerIntervalMs !== undefined ? { intervalMs: opts.schedulerIntervalMs } : {}),
  });

  const app = await buildServer({
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
    ...(aria2
      ? { startScheduler: scheduler.launch, stopScheduler: scheduler.stop }
      : {}),
  });
  const requestedPort = opts.port ?? 8000;
  const host = opts.host ?? "127.0.0.1";
  await app.listen({ host, port: requestedPort });
  const addr = app.server.address();
  const port =
    typeof addr === "object" && addr !== null && "port" in addr ? addr.port : requestedPort;

  // BG-45 phase 2: reconcile the aria2 auto-start supervisor (launchd
  // plist / systemd unit) to match the declared preference. Failures
  // are non-fatal — the HTTP listener stays up either way.
  if (!opts.skipAutoStartReconcile) try {
    const declaration = await ctx.declaration.load();
    const want = Boolean(prefValue(declaration, "auto_start_aria2", false));
    const installed = aria2AutoStartInstalled();
    if (want && !installed) {
      const result = await installAria2Service();
      await ctx.actions.record({
        action: ACTIONS.autoStartReconciled,
        target: TARGETS.system,
        outcome: result.ok ? "changed" : "failed",
        reason: "install",
        detail: { target: result.target, ok: result.ok },
      });
    } else if (!want && installed) {
      const result = await uninstallAria2Service();
      await ctx.actions.record({
        action: ACTIONS.autoStartReconciled,
        target: TARGETS.system,
        outcome: result.ok ? "changed" : "failed",
        reason: "uninstall",
        detail: { target: result.target, ok: result.ok },
      });
    }
  } catch (err) {
    await ctx.actions.record({
      action: ACTIONS.autoStartReconciled,
      target: TARGETS.system,
      outcome: "failed",
      reason: "exception",
      detail: { error: err instanceof Error ? err.message : String(err) },
    });
  }

  if (opts.startScheduler && aria2) {
    // BG-40: callStartScheduler stamps the operator intent + handles
    // revert-on-failure, matching /api/scheduler/start semantics so
    // `ariaflow serve --scheduler` reports "starting"/"running"
    // (never "stopped") during the bootstrap window.
    await callStartScheduler(ctx.state, scheduler.launch);
  }

  // BG-18: announce _ariaflow-server._tcp via the local mDNS daemon so
  // dashboards on the same L2 segment auto-discover the backend.
  // Failures are non-fatal — the HTTP listener stays up either way.
  const mdnsHandle = opts.noMdns
    ? null
    : advertiseHttpService({ port, path: "/api" });
  if (mdnsHandle && mdnsHandle.backend) {
    await ctx.actions.record({
      action: ACTIONS.systemBonjourRegister,
      target: TARGETS.system,
      outcome: "changed",
      reason: "registered",
      detail: { backend: mdnsHandle.backend, port, path: "/api" },
    });
  }

  return {
    url: `http://${host}:${port}`,
    port,
    scheduler: scheduler.running(),
    mdns: (mdnsHandle?.backend ?? null) as "dns-sd" | "avahi" | null,
    close: async () => {
      await scheduler.stop();
      await mdnsHandle?.stop();
      await app.close();
    },
    startScheduler: scheduler.launch,
    stopScheduler: scheduler.stop,
  };
}
