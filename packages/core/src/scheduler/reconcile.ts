import { randomUUID } from "node:crypto";
import type { Aria2Client } from "../aria2/client.js";
import { tellActive, type Aria2Status } from "../aria2/methods.js";
import {
  activeItemUrl,
  mergeActiveStatus,
} from "../reconcile/merge.js";
import { queueItemForActiveInfo } from "../reconcile/match.js";
import type { ActionLog } from "../storage/action-log.js";
import type { QueueStore } from "../storage/queue.js";
import type { ServerState, StateStore } from "../storage/state.js";
import { summarizeQueue } from "../queue/policy.js";
import type { QueueItemRecord } from "../queue/types.js";

export interface ReconcileLiveDeps {
  queueStore: QueueStore;
  stateStore: StateStore;
  actionLog: ActionLog;
  aria2: Aria2Client;
}

export interface ReconcileLiveOptions {
  /** Adopt aria2 GIDs that don't match any queue row (default true). */
  adoptMissing?: boolean;
}

export interface ReconcileLiveResult {
  changed: boolean;
  recovered: number;
  active_count: number;
  items: QueueItemRecord[];
}

const stampNow = (): string => new Date().toISOString();

/**
 * Walk aria2's active list, match each GID to a queue row, and merge
 * live state back:
 *
 *   - GID matches a row: refresh status / live_status / url; if the row
 *     belongs to a stale session, stamp recovery_session_id +
 *     recovered_at + recovered=true and bump it into the current
 *     session.
 *   - GID matches nothing AND adoptMissing: synthesize a new queue
 *     row using the GID's URL (or the GID itself when no URL is
 *     surfaced), tag it as recovered.
 *   - GID matches nothing AND adoptMissing=false: leave it alone.
 *
 * Records a "reconcile" action when anything changed; returns the
 * full mutation summary.
 */
export async function reconcileLiveQueue(
  deps: ReconcileLiveDeps,
  opts: ReconcileLiveOptions = {},
): Promise<ReconcileLiveResult> {
  const adoptMissing = opts.adoptMissing ?? true;
  const state = await deps.stateStore.load();
  const items = await deps.queueStore.load();
  const beforeSummary = summarizeQueue(items);

  let activeInfos: Aria2Status[];
  try {
    activeInfos = await tellActive(deps.aria2);
  } catch {
    // aria2 unreachable — nothing to reconcile against.
    return { changed: false, recovered: 0, active_count: 0, items };
  }

  const now = stampNow();
  let changed = false;
  let recovered = 0;
  const sessionId = state.session_id;

  for (const info of activeInfos) {
    const gid = String(info.gid ?? "");
    if (!gid) continue;
    const url = activeItemUrl(info);

    let item = queueItemForActiveInfo(
      info as { gid?: unknown; files?: unknown },
      items,
      sessionId,
    );

    if (!item && adoptMissing) {
      const adopted: QueueItemRecord = {
        id: randomUUID(),
        url: url ?? gid,
        status: mergeActiveStatus(info.status ?? null),
        created_at: now,
        gid,
        session_id: sessionId,
        recovery_session_id: sessionId,
        recovered_at: now,
        live_status: String(info.status ?? "active"),
      };
      (adopted as Record<string, unknown>).recovered = true;
      items.push(adopted);
      changed = true;
      recovered += 1;
      continue;
    }
    if (!item) continue;

    if (item.gid !== gid) {
      item.gid = gid;
      changed = true;
    }
    const liveStatus = String(info.status ?? "");
    const merged = mergeActiveStatus(info.status ?? null);
    if (item.status !== merged) {
      item.status = merged;
      changed = true;
    }
    if (url && (!item.url || item.url !== url)) {
      item.url = url;
      changed = true;
    }
    if (liveStatus) item.live_status = liveStatus;

    const rec = item as Record<string, unknown>;
    if (sessionId && item.session_id !== sessionId) {
      rec.recovered = true;
      rec.recovery_session_id = sessionId;
      rec.recovered_at = now;
      item.session_id = sessionId;
      changed = true;
      recovered += 1;
    } else if (liveStatus === "active" && (item.status === "paused" || item.status === "queued")) {
      rec.recovered = true;
      rec.recovery_session_id = sessionId;
      rec.recovered_at = now;
      item.session_id = sessionId;
      changed = true;
      recovered += 1;
    }
  }

  if (changed) {
    await deps.queueStore.save(items);
    await deps.actionLog.record({
      action: "reconcile",
      target: "queue",
      outcome: "changed",
      reason: "live_state_merged",
      before: { summary: beforeSummary },
      after: {
        summary: summarizeQueue(items),
        recovered,
        active: activeInfos.map((i) => String(i.gid ?? "")).filter(Boolean),
      },
      detail: {
        recovered,
        active_count: activeInfos.length,
        adopt_missing: adoptMissing,
      },
    });
  }

  return {
    changed,
    recovered,
    active_count: activeInfos.length,
    items,
  };
}
