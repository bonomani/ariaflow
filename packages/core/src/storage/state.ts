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
 * BG-33 + BG-40: produce the canonical wire shape for a ServerState.
 * Apply at any boundary that ships state to a remote consumer (HTTP
 * response body, SSE event, etc.).
 *
 * Picks declared fields explicitly so:
 *   - The internal-only `paused` and `scheduler_intent` stay off the
 *     wire (canonical names are `dispatch_paused` / `scheduler_status`,
 *     surfaced separately by callers).
 *   - Stale legacy keys riding through the `[k: string]: unknown`
 *     index signature in old state.json files (e.g. `last_error`,
 *     `stop_requested` from retired code paths) don't leak either.
 */
export interface WireState {
  _rev: number;
  active_gid: string | null;
  active_url: string | null;
  running: boolean;
  dispatch_paused: boolean;
  session_id: string | null;
  session_started_at: string | null;
  session_last_seen_at: string | null;
  session_closed_at: string | null;
  session_closed_reason: string | null;
  last_bandwidth_probe: ServerState["last_bandwidth_probe"];
  last_bandwidth_probe_at: number | null;
}

export function toWireState(state: ServerState): WireState {
  return {
    _rev: Number(state._rev ?? 0),
    active_gid: state.active_gid,
    active_url: state.active_url,
    running: Boolean(state.running),
    dispatch_paused: Boolean(state.paused),
    session_id: state.session_id,
    session_started_at: state.session_started_at,
    session_last_seen_at: state.session_last_seen_at,
    session_closed_at: state.session_closed_at,
    session_closed_reason: state.session_closed_reason,
    last_bandwidth_probe: state.last_bandwidth_probe ?? null,
    last_bandwidth_probe_at: state.last_bandwidth_probe_at ?? null,
  };
}

function publishStateChange(bus: StateBus, state: ServerState): void {
  bus.publish("state_changed", toWireState(state));
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
