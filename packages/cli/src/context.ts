import {
  ActionLog,
  ArchiveStore,
  DeclarationStore,
  QueueOps,
  QueueStore,
  SessionService,
  StateStore,
  StorageLock,
  storageLockPath,
} from "@ariaflow/core";

export interface CliContext {
  queue: QueueStore;
  archive: ArchiveStore;
  state: StateStore;
  declaration: DeclarationStore;
  sessions: SessionService;
  actions: ActionLog;
  queueOps: QueueOps;
}

/**
 * Build the storage stack the CLI works against. All commands share
 * one StorageLock so concurrent invocations within a single process
 * (e.g. tests) are serialized.
 */
export function makeContext(env: NodeJS.ProcessEnv = process.env): CliContext {
  const lock = new StorageLock(storageLockPath(env));
  const state = new StateStore(lock, env);
  const queue = new QueueStore(lock, env);
  const archive = new ArchiveStore(lock, env);
  const actions = new ActionLog(lock, state, env);
  const sessions = new SessionService(lock, state, queue, archive, env);
  const declaration = new DeclarationStore(lock, env);
  const queueOps = new QueueOps(queue, sessions, declaration, actions);
  return { queue, archive, state, declaration, sessions, actions, queueOps };
}
