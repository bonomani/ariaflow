import {
  bandwidthConfigFrom,
  runBandwidthProbe,
  summarizeQueue,
} from "@ariaflow/core";
import { buildServer, generateOpenApi } from "@ariaflow/api";
import type { CliContext } from "../context.js";
import { json, ok, type CmdResult } from "./_shared.js";

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

export async function cmdProbe(ctx: CliContext): Promise<CmdResult> {
  const declaration = await ctx.declaration.load();
  const config = bandwidthConfigFrom(declaration);
  const probe = await runBandwidthProbe({ config });
  await ctx.state.update((s) => {
    s.last_bandwidth_probe = probe;
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
  const probe = state.last_bandwidth_probe ?? null;
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
