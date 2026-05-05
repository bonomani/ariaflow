import { appendFile, readFile, stat, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { actionLogPath } from "./paths.js";
import type { StorageLock } from "./lock.js";
import type { StateStore } from "./state.js";

const MAX_LINES = 10_000;
const KEEP_LINES = 5_000;
const ROTATE_SIZE_BYTES = 512 * 1024;

/**
 * Closed set of audit-log outcomes. `changed`/`unchanged` describe a
 * successful mutation that did or did not move state; `failed` is a
 * caught exception; `converged` is for idempotent reconciliation runs
 * that ended in the desired state; `blocked` is for refusals that
 * weren't exceptions (preflight failed, supervisor unknown, etc.);
 * `error` is for the action-log writer's own failure path.
 */
export type ActionOutcome =
  | "changed"
  | "unchanged"
  | "failed"
  | "converged"
  | "blocked"
  | "error";

interface ActionLogEntry {
  action: string;
  target: string;
  outcome: ActionOutcome;
  observation?: string;
  reason?: string;
  timestamp?: string;
  session_id?: string;
  observed_before?: Record<string, unknown>;
  observed_after?: Record<string, unknown>;
  detail?: Record<string, unknown>;
  [k: string]: unknown;
}

interface RecordActionInput {
  action: string;
  target: string;
  outcome: ActionOutcome;
  observation?: string;
  reason?: string;
  before?: Record<string, unknown>;
  after?: Record<string, unknown>;
  detail?: Record<string, unknown>;
}

const sortedJsonLine = (entry: ActionLogEntry): string => {
  const sorted: Record<string, unknown> = {};
  for (const k of Object.keys(entry).sort()) sorted[k] = (entry as Record<string, unknown>)[k];
  return JSON.stringify(sorted) + "\n";
};

async function rotateIfLarge(path: string): Promise<void> {
  if (!existsSync(path)) return;
  const size = (await stat(path)).size;
  if (size < ROTATE_SIZE_BYTES) return;
  const lines = (await readFile(path, "utf8")).split("\n");
  if (lines.length <= MAX_LINES) return;
  await writeFile(path, lines.slice(-KEEP_LINES).join("\n") + "\n", "utf8");
}

export class ActionLog {
  private bus: { publish(event: string, data: unknown): void } | undefined;

  constructor(
    private readonly lock: StorageLock,
    private readonly state: StateStore,
    private readonly env: NodeJS.ProcessEnv = process.env,
  ) {}

  /** Attach an event bus so each append() also publishes "action_logged". */
  setBus(bus: { publish(event: string, data: unknown): void }): void {
    this.bus = bus;
  }

  /** Low-level append. Stamps timestamp + session_id if not already set. */
  async append(entry: ActionLogEntry): Promise<ActionLogEntry> {
    return this.lock.with(async () => {
      const path = actionLogPath(this.env);
      const payload: ActionLogEntry = { ...entry };
      payload.timestamp ??= new Date().toISOString();
      const current = await this.state.load();
      if (current.session_id) {
        payload.session_id ??= current.session_id;
        // Touch session_last_seen_at to mirror Python behavior.
        await this.state.update((s) => {
          s.session_last_seen_at = payload.timestamp ?? null;
        });
      }
      await appendFile(path, sortedJsonLine(payload), "utf8");
      await rotateIfLarge(path);
      // Publish outside the lock-critical fs work but inside the lock-with
      // callback is fine — the bus is in-memory and synchronous.
      this.bus?.publish("action_logged", payload);
      return payload;
    });
  }

  /** High-level convenience for recording an action. */
  record(input: RecordActionInput): Promise<ActionLogEntry> {
    const entry: ActionLogEntry = {
      action: input.action,
      target: input.target,
      outcome: input.outcome,
      observation: input.observation ?? "ok",
      reason: input.reason ?? "aggregate",
    };
    if (input.before !== undefined) entry.observed_before = input.before;
    if (input.after !== undefined) entry.observed_after = input.after;
    if (input.detail !== undefined) entry.detail = input.detail;
    return this.append(entry);
  }

  async load(limit = 200): Promise<ActionLogEntry[]> {
    return this.lock.with(async () => {
      const path = actionLogPath(this.env);
      if (!existsSync(path)) return [];
      const lines = (await readFile(path, "utf8")).split("\n");
      const out: ActionLogEntry[] = [];
      for (const line of lines.slice(-limit)) {
        const trimmed = line.trim();
        if (!trimmed) continue;
        try {
          out.push(JSON.parse(trimmed) as ActionLogEntry);
        } catch {
          out.push({
            action: "invalid",
            target: "log",
            outcome: "error",
            error: "invalid_log_entry",
            raw: trimmed,
          });
        }
      }
      return out;
    });
  }
}
