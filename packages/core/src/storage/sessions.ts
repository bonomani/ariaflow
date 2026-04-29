import { appendFile, readFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { randomUUID } from "node:crypto";
import { sessionsLogPath } from "./paths.js";
import type { StorageLock } from "./lock.js";
import type { ServerState, StateStore } from "./state.js";
import type { ArchiveStore, QueueStore } from "./queue.js";
import type { QueueItem } from "../state/archivable.js";

export interface SessionHistoryEntry {
  session_id: string;
  started_at: string | null;
  closed_at: string | null;
  closed_reason: string | null;
  items_total: number;
  items_done: number;
  items_error: number;
  items_queued: number;
  timestamp: string;
}

export interface SessionStats {
  session_id: string | null;
  started_at: string | null;
  items_total: number;
  items_active: number;
  items_archived: number;
  items_done: number;
  items_error: number;
  items_queued: number;
  items_downloading: number;
  items_paused: number;
  bytes_completed: number;
}

const ASM_CR4_ACTIVE = new Set(["active", "waiting"]);

export class SessionService {
  private bus: { publish(event: string, data: unknown): void } | undefined;

  constructor(
    private readonly lock: StorageLock,
    private readonly state: StateStore,
    private readonly queue: QueueStore,
    private readonly archive: ArchiveStore,
    private readonly env: NodeJS.ProcessEnv = process.env,
    private readonly now: () => string = () => new Date().toISOString(),
  ) {}

  /** Attach an event bus so lifecycle transitions are published. */
  setBus(bus: { publish(event: string, data: unknown): void }): void {
    this.bus = bus;
  }

  clearBus(): void {
    this.bus = undefined;
  }

  /** Open a session if none is active; idempotent within an open session. */
  ensure(): Promise<ServerState> {
    return this.lock.with(async () => {
      let opened = false;
      const next = await this.state.update((s) => {
        if (!s.session_id || s.session_closed_at) {
          s.session_id = randomUUID();
          const now = this.now();
          s.session_started_at = now;
          s.session_last_seen_at = now;
          s.session_closed_at = null;
          s.session_closed_reason = null;
          opened = true;
        }
      });
      if (opened) {
        this.bus?.publish("session_started", {
          session_id: next.session_id,
          started_at: next.session_started_at,
        });
      }
      return next;
    });
  }

  /** Touch session_last_seen_at if a session is open. */
  touch(): Promise<ServerState> {
    return this.lock.with(() =>
      this.state.update((s) => {
        if (s.session_id) s.session_last_seen_at = this.now();
      }),
    );
  }

  /**
   * Close the session. ASM CR-4: refuses while jobs are still active/waiting;
   * caller must pause/cancel them first (see startNew() for the rollover path).
   */
  close(reason = "closed"): Promise<ServerState> {
    return this.lock.with(async () => {
      const items = await this.queue.load();
      const active = items.filter((i) => ASM_CR4_ACTIVE.has(String(i.status ?? "")));
      if (active.length > 0) {
        throw new Error(
          `ASM CR-4: cannot close session with ${active.length} active/waiting job(s); pause or cancel them first`,
        );
      }
      const before = await this.state.load();
      const next = await this.state.update((s) => {
        if (s.session_id && !s.session_closed_at) {
          const now = this.now();
          s.session_closed_at = now;
          s.session_closed_reason = reason;
          s.session_last_seen_at = now;
        }
      });
      await this.appendSessionHistory(next, items);
      if (before.session_id && !before.session_closed_at && next.session_closed_at) {
        this.bus?.publish("session_closed", {
          session_id: next.session_id,
          closed_at: next.session_closed_at,
          reason: next.session_closed_reason,
        });
      }
      return next;
    });
  }

  /**
   * ASM CR-4 rollover: pause active/waiting items in queue.json, close the
   * session, then open a fresh one. The state-record pause is intentional —
   * aria2 itself isn't paused here; the next session resumes via the scheduler.
   */
  startNew(reason = "manual_new_session"): Promise<ServerState> {
    return this.lock.with(async () => {
      const items = await this.queue.load();
      let mutated = false;
      for (const it of items) {
        if (ASM_CR4_ACTIVE.has(String(it.status ?? ""))) {
          it.status = "paused";
          mutated = true;
        }
      }
      if (mutated) await this.queue.save(items);
      await this.close(reason);
      return this.state.update((s) => {
        const now = this.now();
        s.session_id = randomUUID();
        s.session_started_at = now;
        s.session_last_seen_at = now;
        s.session_closed_at = null;
        s.session_closed_reason = null;
      });
    });
  }

  async loadHistory(limit = 50): Promise<SessionHistoryEntry[]> {
    return this.lock.with(async () => {
      const path = sessionsLogPath(this.env);
      if (!existsSync(path)) return [];
      const lines = (await readFile(path, "utf8")).split("\n");
      const out: SessionHistoryEntry[] = [];
      for (const line of lines.slice(-limit)) {
        const t = line.trim();
        if (!t) continue;
        try {
          out.push(JSON.parse(t) as SessionHistoryEntry);
        } catch {
          /* ignore corrupt line */
        }
      }
      return out;
    });
  }

  async stats(sessionId?: string | null): Promise<SessionStats> {
    return this.lock.with(async () => {
      const s = await this.state.load();
      const sid = sessionId ?? s.session_id;
      const items = await this.queue.load();
      const archived = await this.archive.load();
      const inSession = (i: QueueItem) => i.session_id === sid;
      const active = items.filter(inSession);
      const arch = archived.filter(inSession);
      const all = [...active, ...arch];
      const count = (pred: (i: QueueItem) => boolean) => all.filter(pred).length;
      return {
        session_id: sid ?? null,
        started_at: sid === s.session_id ? s.session_started_at : null,
        items_total: all.length,
        items_active: active.length,
        items_archived: arch.length,
        items_done: count((i) => i.status === "complete"),
        items_error: count((i) => i.status === "error" || i.status === "failed"),
        items_queued: count((i) => i.status === "queued"),
        items_downloading: count((i) => i.status === "active"),
        items_paused: count((i) => i.status === "paused"),
        bytes_completed: all.reduce((n, i) => n + Number(i.completed_length ?? 0), 0),
      };
    });
  }

  private async appendSessionHistory(state: ServerState, items: QueueItem[]): Promise<void> {
    const sid = state.session_id;
    if (!sid) return;
    const sessionItems = items.filter((i) => i.session_id === sid);
    const entry: SessionHistoryEntry = {
      session_id: sid,
      started_at: state.session_started_at,
      closed_at: state.session_closed_at,
      closed_reason: state.session_closed_reason,
      items_total: sessionItems.length,
      items_done: sessionItems.filter((i) => i.status === "complete").length,
      items_error: sessionItems.filter((i) => i.status === "error" || i.status === "failed").length,
      items_queued: sessionItems.filter((i) => i.status === "queued").length,
      timestamp: this.now(),
    };
    const sorted: Record<string, unknown> = {};
    for (const k of Object.keys(entry).sort()) sorted[k] = (entry as unknown as Record<string, unknown>)[k];
    await appendFile(sessionsLogPath(this.env), JSON.stringify(sorted) + "\n", "utf8");
  }
}
