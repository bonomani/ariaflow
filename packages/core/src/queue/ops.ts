import { ACTIONS, TARGETS } from "../storage/actions.js";
import { randomUUID } from "node:crypto";
import type { ActionLog } from "../storage/action-log.js";
import type { DeclarationStore } from "../storage/declaration.js";
import type { QueueStore } from "../storage/queue.js";
import type { SessionService } from "../storage/sessions.js";
import { detectDownloadMode, summarizeQueue } from "./policy.js";
import { findLiveItemByUrl } from "./lookup.js";
import { prefValue } from "../contracts/declaration.js";
import { TERMINAL_STATUSES, type ItemStatus, type QueueItemRecord } from "./types.js";

export interface AddInput {
  url: string;
  output?: string | null;
  post_action_rule?: string | null;
  mirrors?: string[] | null;
  torrent_data?: string | null;
  metalink_data?: string | null;
  priority?: number;
  distribute?: boolean;
}

export interface AddResult {
  /** The persisted queue item (deduped to existing if a live URL match was found). */
  item: QueueItemRecord;
  /** True when a live duplicate was found and no new record was created. */
  duplicate: boolean;
}

/**
 * Queue-record orchestration. This layer is RPC-free: it persists the
 * queued record, records the action, and resolves session/preference
 * defaults. Actually handing the item to aria2 is the scheduler's job.
 */
export class QueueOps {
  constructor(
    private readonly queue: QueueStore,
    private readonly sessions: SessionService,
    private readonly declaration: DeclarationStore,
    private readonly actions: ActionLog,
    private readonly now: () => string = () => new Date().toISOString(),
  ) {}

  async add(input: AddInput): Promise<AddResult> {
    const state = await this.sessions.ensure();
    await this.sessions.touch();

    const items = await this.queue.load();
    const before = { summary: summarizeQueue(items) };
    const existing = findLiveItemByUrl(items, input.url);

    if (existing) {
      await this.actions.record({
        action: ACTIONS.queueAdd,
        target: TARGETS.queue,
        outcome: "unchanged",
        reason: "duplicate_url",
        before,
        after: { summary: summarizeQueue(items), item_id: existing.id },
        detail: {
          item_id: existing.id,
          url: input.url,
          status: existing.status,
          gid: existing.gid,
        },
      });
      return { item: existing, duplicate: true };
    }

    const declaration = await this.declaration.load();
    const defaultRule = String(prefValue(declaration, "post_action_rule", "pending"));
    const resolvedOutput = (input.output?.trim() || null) ?? null;
    const resolvedRule = (input.post_action_rule?.trim() || "") || defaultRule;
    const sid = state.session_id;
    const created_at = this.now();
    const mode = detectDownloadMode({
      url: input.url,
      mirrors: input.mirrors ?? null,
      torrentData: input.torrent_data ?? null,
      metalinkData: input.metalink_data ?? null,
    });

    const item: QueueItemRecord = {
      id: randomUUID(),
      url: input.url,
      output: resolvedOutput,
      post_action_rule: resolvedRule,
      status: "queued",
      desired_state: "running",
      priority: input.priority ?? 0,
      mode,
      mirrors: input.mirrors ?? null,
      torrent_data: input.torrent_data ?? null,
      metalink_data: input.metalink_data ?? null,
      created_at,
      session_id: sid,
      session_history: sid
        ? [{ session_id: sid, joined_at: created_at, reason: "created" }]
        : null,
    };
    if (input.distribute) item.distribute = true;

    items.push(item);
    await this.queue.save(items);

    await this.actions.record({
      action: ACTIONS.queueAdd,
      target: TARGETS.queue,
      outcome: "changed",
      reason: "queue_item_created",
      before,
      after: { summary: summarizeQueue(items), item_id: item.id },
      detail: {
        item_id: item.id,
        url: input.url,
        output: item.output,
        post_action_rule: item.post_action_rule,
      },
    });

    return { item, duplicate: false };
  }

  /**
   * Mark an item paused/resumed/etc. without involving aria2 — the RPC
   * side effect is the scheduler/transfers layer's job. Returns the
   * mutated item or null when not found.
   */
  async transitionStatus(
    itemId: string,
    next: ItemStatus,
    timestampField?: keyof QueueItemRecord,
  ): Promise<QueueItemRecord | null> {
    const items = await this.queue.load();
    const item = items.find((i) => i.id === itemId) ?? null;
    if (!item) return null;
    const before = { ...item };
    item.status = next;
    if (timestampField) item[timestampField] = this.now();
    await this.queue.save(items);
    await this.actions.record({
      action: ACTIONS.queueItemTransition,
      target: TARGETS.queueItem,
      outcome: "changed",
      reason: `status:${next}`,
      before: { item: before },
      after: { item: { ...item } },
      detail: { item_id: itemId, status: next },
    });
    return item;
  }

  /**
   * Hard-remove a queue record. Returns the removed item or null.
   * Terminal-status items are still removable; the caller decides.
   */
  async remove(itemId: string): Promise<QueueItemRecord | null> {
    const items = await this.queue.load();
    const idx = items.findIndex((i) => i.id === itemId);
    if (idx < 0) return null;
    const [removed] = items.splice(idx, 1);
    await this.queue.save(items);
    await this.actions.record({
      action: ACTIONS.queueRemove,
      target: TARGETS.queueItem,
      outcome: "changed",
      reason: "manual",
      detail: {
        item_id: itemId,
        was_terminal: TERMINAL_STATUSES.has(String(removed!.status ?? "") as never),
      },
    });
    return removed!;
  }
}
