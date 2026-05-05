/**
 * Centralized vocabulary for the audit log. Every `actionLog.record({...})`
 * call should source its `action` + `target` from these enums so a typo
 * surfaces at compile time rather than as a silently-divergent log entry.
 *
 * Values are kept as plain string literals (not symbols / branded types)
 * so existing JSONL log files keep parsing the same way.
 */

export const ACTIONS = {
  // scheduler lifecycle (route-driven, target=scheduler)
  schedulerStart: "start",
  schedulerStop: "stop",
  schedulerPause: "pause",
  schedulerResume: "resume",
  schedulerPreflight: "preflight",
  schedulerUcc: "ucc",
  // scheduler loop internals (target=scheduler)
  schedulerPre: "scheduler_pre",
  schedulerStopped: "scheduler_stopped",
  // queue mutations (target=queue)
  queueAdd: "add",
  queueRemove: "remove",
  queueAutoCleanup: "auto_cleanup",
  queueReconcile: "reconcile",
  queueDeduplicate: "deduplicate",
  queueRetry: "retry",
  queueRetryScheduled: "retry_scheduled",
  queueRetryExhausted: "retry_exhausted",
  queueSetPriority: "set_priority",
  queueSelectFiles: "select_files",
  queueSeedStopped: "seed_stopped",
  queueDistributeStarted: "distribute_started",
  // queue-item lifecycle (target=queue_item; tick + poll). Note that
  // "start" is overloaded with schedulerStart — the disambiguator is
  // the `target` field (scheduler vs queue_item).
  queueItemStart: "start",
  queueItemStartFailed: "start_failed",
  queueItemTransition: "transition",
  // bandwidth
  bandwidthProbe: "probe",
  // declaration
  declarationPatch: "patch_preferences",
  // aria2 RPC
  aria2ChangeOptions: "change_options",
  // system
  systemBonjourRegister: "bonjour_register",
  systemLifecycle: "lifecycle_action",
} as const;

export type ActionName = (typeof ACTIONS)[keyof typeof ACTIONS];

export const TARGETS = {
  scheduler: "scheduler",
  queue: "queue",
  queueItem: "queue_item",
  activeTransfer: "active_transfer",
  bandwidth: "bandwidth",
  system: "system",
  declaration: "declaration",
  aria2: "aria2",
} as const;

export type ActionTarget = (typeof TARGETS)[keyof typeof TARGETS];
