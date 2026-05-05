import type { Aria2Client } from "../aria2/client.js";
import { tellActive, tellStatus, type Aria2Status } from "../aria2/methods.js";
import type { ActionLog } from "../storage/action-log.js";
import type { QueueStore } from "../storage/queue.js";
import { mergeActiveStatus } from "../reconcile/merge.js";
import type { ItemStatus, QueueItemRecord } from "../queue/types.js";

export interface PollDeps {
  queueStore: QueueStore;
  actionLog: ActionLog;
  aria2: Aria2Client;
  /**
   * BG-28(a): when supplied, poll keeps state.active_gid / active_url
   * coherent — points it at the still-running active item, or clears
   * both when nothing is in flight.
   */
  stateStore?: import("../storage/state.js").StateStore;
}

export interface PollResult {
  /** Per-gid live status snapshots from aria2.tellActive. */
  active: Aria2Status[];
  /** Items that just finished (status -> "complete"). */
  completed: Array<{ id: string; gid: string }>;
  /** Items that just errored (status -> "error", error_code/message stamped). */
  errored: Array<{ id: string; gid: string; error_code?: string; error_message?: string }>;
  /** Items whose live_status changed without a queue-status transition. */
  updated: Array<{ id: string; gid: string; status: string }>;
}

const stampNow = (): string => new Date().toISOString();

/**
 * One polling pass: snapshot aria2.tellActive, then for each queue
 * item that has a gid:
 *   - if the gid shows up in the active list, copy live fields
 *     (downloadSpeed, completedLength, totalLength, status->live_status)
 *     onto the row;
 *   - else fall back to aria2.tellStatus(gid) so completed/errored
 *     items the aria2 daemon already moved off the active tier still
 *     get reconciled here;
 *   - on live status "complete" or "error" or "removed", flip the
 *     queue row's persisted status accordingly and stamp completed_at /
 *     error_at / removed_at;
 *   - record a "transition" action per state change.
 *
 * Composes existing helpers and stays free of session / bandwidth
 * concerns.
 */
export async function pollActiveItems(deps: PollDeps): Promise<PollResult> {
  const items = await deps.queueStore.load();
  const tracked = items.filter((i) => typeof i.gid === "string" && i.gid);
  if (tracked.length === 0) {
    return { active: [], completed: [], errored: [], updated: [] };
  }

  const active = await tellActive(deps.aria2);
  const byGid = new Map<string, Aria2Status>();
  for (const a of active) byGid.set(a.gid, a);

  const completed: PollResult["completed"] = [];
  const errored: PollResult["errored"] = [];
  const updated: PollResult["updated"] = [];
  let dirty = false;

  for (const item of tracked) {
    const gid = item.gid as string;
    let info = byGid.get(gid);
    if (!info) {
      try {
        info = await tellStatus(deps.aria2, gid);
      } catch {
        continue; // RPC failed — leave the row alone for the next tick
      }
    }
    const live = mergeActiveStatus(info.status ?? null);
    const before: QueueItemRecord = { ...item };

    // BG-28(b): mirror aria2's tellStatus camelCase keys onto the row
    // (the dashboard reads `item.downloadSpeed` etc directly from
    // /api/status.items[]). Snake-case aliases stay for any internal
    // caller that depended on them. Mutations here mark the row dirty
    // so the queue store actually persists the refresh.
    const setField = (key: string, value: unknown): void => {
      if (value === undefined) return;
      if (item[key] !== value) {
        item[key] = value;
        dirty = true;
      }
    };
    const infoRec = info as Record<string, unknown>;
    setField("downloadSpeed", info.downloadSpeed);
    setField("uploadSpeed", info.uploadSpeed);
    setField("completedLength", info.completedLength);
    setField("totalLength", info.totalLength);
    setField("connections", infoRec.connections);
    setField("numSeeders", infoRec.numSeeders);
    setField("download_speed", info.downloadSpeed);
    setField("completed_length", info.completedLength);
    setField("total_length", info.totalLength);
    item.live_status = live;

    if (live === "complete") {
      if (item.status !== "complete") {
        item.status = "complete";
        item.completed_at = stampNow();
        completed.push({ id: item.id, gid });
        dirty = true;
        await deps.actionLog.record({
          action: "transition",
          target: "queue_item",
          outcome: "changed",
          reason: "status:complete",
          before: { item: before },
          after: { item: { ...item } },
          detail: { item_id: item.id, gid },
        });
      }
    } else if (live === "error") {
      if (item.status !== "error") {
        item.status = "error";
        item.error_at = stampNow();
        if (typeof info.errorCode === "string") item.error_code = info.errorCode;
        if (typeof info.errorMessage === "string") item.error_message = info.errorMessage;
        errored.push({
          id: item.id,
          gid,
          ...(typeof info.errorCode === "string" ? { error_code: info.errorCode } : {}),
          ...(typeof info.errorMessage === "string"
            ? { error_message: info.errorMessage }
            : {}),
        });
        dirty = true;
        await deps.actionLog.record({
          action: "transition",
          target: "queue_item",
          outcome: "changed",
          reason: "status:error",
          before: { item: before },
          after: { item: { ...item } },
          detail: { item_id: item.id, gid },
        });
      }
    } else if (live === "removed") {
      // BG-30/BG-33: canonical "removed" (aria2-native vocabulary).
      if (item.status !== "removed") {
        item.status = "removed" as ItemStatus;
        item.removed_at = stampNow();
        dirty = true;
        await deps.actionLog.record({
          action: "transition",
          target: "queue_item",
          outcome: "changed",
          reason: "status:removed",
          before: { item: before },
          after: { item: { ...item } },
          detail: { item_id: item.id, gid },
        });
      }
    } else if (live === "waiting") {
      // BG-30 #1: persist aria2's waiting state (was only kept on
      // live_status). summarizeQueue can now bucket it.
      if (item.status !== "waiting" && item.status !== "paused") {
        item.status = "waiting" as ItemStatus;
        dirty = true;
        await deps.actionLog.record({
          action: "transition",
          target: "queue_item",
          outcome: "changed",
          reason: "status:waiting",
          before: { item: before },
          after: { item: { ...item } },
          detail: { item_id: item.id, gid },
        });
      }
      if (before.live_status !== live) {
        updated.push({ id: item.id, gid, status: live });
        dirty = true;
      }
    } else {
      // Non-terminal live status: just update the live_status field if it
      // changed. Don't touch the queue row's status.
      if (before.live_status !== live) {
        updated.push({ id: item.id, gid, status: live });
        dirty = true;
      }
    }
  }

  if (dirty) await deps.queueStore.save(items);

  // BG-28(a): keep state.active_gid / active_url honest. Prefer an
  // item still in aria2's active tier; otherwise clear both so the
  // dashboard doesn't keep spotlighting a dead gid.
  if (deps.stateStore) {
    const liveActive = items.find(
      (i) =>
        typeof i.gid === "string" &&
        i.gid &&
        i.status === "active" &&
        byGid.has(i.gid as string),
    );
    const cur = await deps.stateStore.load();
    const nextGid = liveActive ? (liveActive.gid as string) : null;
    const nextUrl = liveActive ? liveActive.url ?? null : null;
    if (cur.active_gid !== nextGid || cur.active_url !== nextUrl) {
      await deps.stateStore.update((s) => {
        s.active_gid = nextGid;
        s.active_url = nextUrl;
      });
    }
  }

  return { active, completed, errored, updated };
}
