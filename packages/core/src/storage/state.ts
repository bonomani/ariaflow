import { readJson, writeJson } from "./json.js";
import { statePath } from "./paths.js";
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
};

export class StateStore {
  constructor(
    private readonly lock: StorageLock,
    private readonly env: NodeJS.ProcessEnv = process.env,
  ) {}

  load(): Promise<ServerState> {
    return this.lock.with(() => readJson(statePath(this.env), { ...DEFAULT_STATE }));
  }

  /** Bump _rev and persist atomically. Returns the saved state. */
  async save(state: ServerState): Promise<ServerState> {
    return this.lock.with(async () => {
      const next = { ...state, _rev: Number(state._rev ?? 0) + 1 };
      await writeJson(statePath(this.env), next);
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
      return stamped;
    });
  }
}
