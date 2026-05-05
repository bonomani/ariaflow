import { allowedActions, planAutoCleanup, summarizeQueue } from "@ariaflow/core";
import type { CliContext } from "../context.js";
import { fail, json, ok, type CmdResult } from "./_shared.js";

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
