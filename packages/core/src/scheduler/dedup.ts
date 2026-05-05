import { ACTIONS, TARGETS } from "../storage/actions.js";
import type { Aria2Client } from "../aria2/client.js";
import { pause, remove, tellActive, type Aria2Status } from "../aria2/methods.js";
import { activeItemUrl } from "../reconcile/merge.js";
import { rankActiveInfos } from "../transfers/progress.js";
import { dedupActiveTransferAction } from "../transfers/helpers.js";
import type { ActionLog } from "../storage/action-log.js";
import type { DeclarationStore } from "../storage/declaration.js";

export interface DeduplicateDeps {
  declarationStore: DeclarationStore;
  actionLog: ActionLog;
  aria2: Aria2Client;
}

export interface DeduplicateResult {
  changed: boolean;
  /** GIDs the keeper-tier — one per URL group. */
  kept: string[];
  /** GIDs the duplicate-tier — paused or removed depending on policy. */
  paused: string[];
  /** The action applied to duplicates: "remove" | "pause" | "ignore". */
  action: "remove" | "pause" | "ignore";
}

/**
 * Walk aria2.tellActive, group jobs by source URL (or GID when no URL),
 * pick the most-progressed job per URL as the keeper, and apply the
 * configured `duplicate_active_transfer_action` to the rest:
 *   - "remove": aria2.remove(gid)
 *   - "pause":  aria2.pause(gid)
 *   - "ignore": no-op (still returns the kept list)
 *
 * The keeper is chosen by rankActiveInfos — descending by
 * [percent, completed, speed]. RPC failures on the duplicate side
 * don't abort the pass; the next iteration retries.
 *
 * Records a "deduplicate" action when anything changed.
 */
export async function deduplicateActiveTransfers(
  deps: DeduplicateDeps,
): Promise<DeduplicateResult> {
  let active: Aria2Status[];
  try {
    active = await tellActive(deps.aria2);
  } catch {
    return { changed: false, kept: [], paused: [], action: "ignore" };
  }
  if (active.length < 2) {
    return { changed: false, kept: [], paused: [], action: "ignore" };
  }

  const declaration = await deps.declarationStore.load();
  const action = dedupActiveTransferAction(declaration);
  if (action === "ignore") {
    return {
      changed: false,
      kept: active.map((i) => String(i.gid ?? "")).filter(Boolean),
      paused: [],
      action,
    };
  }

  const groups = new Map<string, Aria2Status[]>();
  for (const info of active) {
    const url = activeItemUrl(info) || String(info.gid ?? "");
    if (!url) continue;
    const arr = groups.get(url) ?? [];
    arr.push(info);
    groups.set(url, arr);
  }

  const kept: string[] = [];
  const paused: string[] = [];
  let changed = false;
  for (const jobs of groups.values()) {
    if (jobs.length < 2) continue;
    const ranked = rankActiveInfos(jobs);
    const keeper = ranked[0]!;
    const keeperGid = String(keeper.gid ?? "");
    if (keeperGid) kept.push(keeperGid);
    for (const duplicate of ranked.slice(1)) {
      const gid = String(duplicate.gid ?? "");
      if (!gid) continue;
      try {
        if (action === "remove") await remove(deps.aria2, gid);
        else await pause(deps.aria2, gid);
        paused.push(gid);
        changed = true;
      } catch {
        /* swallow — next pass retries */
      }
    }
  }

  if (changed) {
    await deps.actionLog.record({
      action: ACTIONS.queueDeduplicate,
      target: TARGETS.activeTransfer,
      outcome: "changed",
      reason: "duplicate_active_transfer",
      before: { active: active.map((i) => i.gid).filter(Boolean) },
      after: { kept, paused, action },
      detail: { kept, paused, group_count: groups.size, action },
    });
  }

  return { changed, kept, paused, action };
}
