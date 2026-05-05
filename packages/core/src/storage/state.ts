import { readJson, writeJson } from "./json.js";
import { statePath } from "./paths.js";
import type { ResolvedProbe } from "../bandwidth/run.js";
import type { StorageLock } from "./lock.js";

export interface ServerState {
  paused: boolean;
  active_gid: string | null;
  active_url: string | null;
  running: boolean;
  session_id: string | null;
  session_started_at: string | null;
  session_last_seen_at: string | null;
  session_closed_at: string | null;
  session_closed_reason: string | null;
  /**
   * BG-40: operator-declared scheduler intent. "running" means the
   * operator has hit /start (or /resume's auto-start path); "stopped"
   * means /stop was hit or the loop has never started. Distinct from
   * `running` (which the loop itself flips to reflect actual dispatch
   * progress) — the difference is what lets us tell `stopped` apart
   * from `starting` in the derived status enum.
   */
  scheduler_intent?: "stopped" | "running";
  /** Last bandwidth probe result; null/undefined before the first probe. */
  last_bandwidth_probe?: ResolvedProbe | null;
  /** Epoch seconds when `last_bandwidth_probe` was stamped. */
  last_bandwidth_probe_at?: number | null;
  _rev?: number;
  [k: string]: unknown;
}

const DEFAULT_STATE: ServerState = {
  paused: false,
  active_gid: null,
  active_url: null,
  running: false,
  session_id: null,
  session_started_at: null,
  session_last_seen_at: null,
  session_closed_at: null,
  session_closed_reason: null,
  scheduler_intent: "stopped",
};

interface StateBus {
  publish(event: string, data: unknown): void;
}

/**
 * BG-33: `state.paused` is internal-only — every wire surface (the
 * /api/status response, /api/events SSE frames) must expose
 * `dispatch_paused` instead. Strips `paused` from the published frame
 * and adds the canonical alias.
 */
function publishStateChange(bus: StateBus, state: ServerState): void {
  const { paused, ...rest } = state;
  bus.publish("state_changed", { ...rest, dispatch_paused: Boolean(paused) });
}

export class StateStore {
  private bus: StateBus | undefined;

  constructor(
    private readonly lock: StorageLock,
    private readonly env: NodeJS.ProcessEnv = process.env,
  ) {}

  /**
   * R-T: attach an event bus so each successful save() / update() also
   * publishes "state_changed" carrying the (sanitized) next state.
   * Mirrors ActionLog.setBus / SessionService.setBus. The /api/events
   * SSE stream ships state_changed under the "items" + "scheduler"
   * topics (per event-topics.ts).
   */
  setBus(bus: StateBus): void {
    this.bus = bus;
  }

  /** Detach any previously-attached event bus. */
  clearBus(): void {
    this.bus = undefined;
  }

  load(): Promise<ServerState> {
    return this.lock.with(() => readJson(statePath(this.env), { ...DEFAULT_STATE }));
  }

  /** Bump _rev and persist atomically. Returns the saved state. */
  async save(state: ServerState): Promise<ServerState> {
    return this.lock.with(async () => {
      const next = { ...state, _rev: Number(state._rev ?? 0) + 1 };
      await writeJson(statePath(this.env), next);
      if (this.bus) publishStateChange(this.bus, next);
      return next;
    });
  }

  /** Read-modify-write convenience. The mutator may return the next state, or mutate in place. */
  async update(mutate: (s: ServerState) => ServerState | void | Promise<ServerState | void>): Promise<ServerState> {
    return this.lock.with(async () => {
      const current = await readJson<ServerState>(statePath(this.env), { ...DEFAULT_STATE });
      const result = await mutate(current);
      const next = (result ?? current) as ServerState;
      const stamped = { ...next, _rev: Number(next._rev ?? 0) + 1 };
      await writeJson(statePath(this.env), stamped);
      if (this.bus) publishStateChange(this.bus, stamped);
      return stamped;
    });
  }
}
