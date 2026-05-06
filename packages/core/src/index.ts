export const VERSION = "0.0.0";

// Storage primitives
export { StorageLock } from "./storage/lock.js";
export {
  configDir,
  queuePath,
  statePath,
  archivePath,
  actionLogPath,
  sessionsLogPath,
  storageLockPath,
} from "./storage/paths.js";
export { readJson, writeJson } from "./storage/json.js";
export { StateStore, toWireState, type ServerState, type WireState } from "./storage/state.js";
export { QueueStore, ArchiveStore } from "./storage/queue.js";
export { ActionLog, type ActionOutcome } from "./storage/action-log.js";
export {
  ACTIONS,
  TARGETS,
  type ActionName,
  type ActionTarget,
} from "./storage/actions.js";
export { EventBus, type EventListener } from "./events/bus.js";
export { DeclarationStore, declarationPath } from "./storage/declaration.js";
export { SessionService } from "./storage/sessions.js";

// Queue
export type {
  QueueItemRecord,
  ItemStatus,
  DownloadMode,
} from "./queue/types.js";
export { ITEM_STATUSES, TERMINAL_STATUSES } from "./queue/types.js";
export { QueueOps, type AddInput, type AddResult } from "./queue/ops.js";
export { allowedActions, detectDownloadMode, summarizeQueue } from "./queue/policy.js";
export { findLiveItemByUrl } from "./queue/lookup.js";

// Contracts
export {
  defaultDeclaration,
  prefValue,
  type Declaration,
  type UicGate,
  type UicPreference,
} from "./contracts/declaration.js";
export {
  evaluatePreflight,
  type PreflightResult,
  type GateSignals,
  type UCCResult,
} from "./contracts/preflight.js";
export { uccEnvelope, type UccEnvelope, type UccResult } from "./contracts/ucc.js";

// aria2
export { Aria2Client, Aria2RpcError, type Aria2ClientOptions } from "./aria2/client.js";
export * as aria2 from "./aria2/methods.js";
export { dispatchDownload, dispatchPrefsFrom, type DispatchPrefs } from "./aria2/dispatch.js";
export { applyBandwidthCap } from "./aria2/cap.js";
export { resolveDefaultDownloadDir } from "./install/download_dir.js";
export { brewOutdatedFormula, type UpdateProbeResult } from "./install/check_update.js";
export { resolvePkgManager } from "./install/pkg_manager.js";
export { buildPostUpgradeRestartSuffix } from "./install/restart_chain.js";
export { verifyExistingTier1 } from "./queue/verify.js";
export { updateOutputPath, markMissingByPath } from "./queue/history_sync.js";
export {
  validateChangeOptions,
  MANAGED_ARIA2_OPTIONS,
  SAFE_ARIA2_OPTIONS,
  type ChangeOptionsValidation,
} from "./aria2/options.js";

// Routes (validators)
export {
  errorPayload,
  validateItemId,
  validateUrl,
  validateOutputPath,
  isValidBase64,
  ALLOWED_URL_SCHEMES,
} from "./routes/helpers.js";
export { parseAddItems, type ParsedAddItem } from "./routes/parse-add.js";

// Bandwidth / scheduler / transfers / reconcile / discovery / bonjour / install
export * as bandwidthUnits from "./bandwidth/units.js";
export { bandwidthConfigFrom, type BandwidthConfig } from "./bandwidth/config.js";
export { runBandwidthProbe, type ResolvedProbe } from "./bandwidth/run.js";
export * as scheduler from "./scheduler/helpers.js";
export {
  deriveSchedulerStatus,
  deriveWaitReason,
  type SchedulerStatus,
  type WaitReason,
  type WaitReasonInputs,
} from "./scheduler/status.js";
export {
  callStartScheduler,
  callStopScheduler,
  type StartResult,
  type StopResult,
} from "./scheduler/intent.js";
export { probeAria2Reachable, probeDiskOk } from "./scheduler/probes.js";
export { getActiveProgress } from "./scheduler/progress.js";
export {
  runSchedulerTick,
  type SchedulerTickDeps,
  type SchedulerTickResult,
} from "./scheduler/tick.js";
export { pollActiveItems, type PollDeps, type PollResult } from "./scheduler/poll.js";
export {
  runRetryPass,
  isRetryReady,
  type RetryDeps,
  type RetryResult,
} from "./scheduler/retry.js";
export {
  runPostAction,
  runPostActionBatch,
  type PostActionDeps,
  type PostActionResult,
} from "./scheduler/post-action.js";
export {
  reconcileLiveQueue,
  type ReconcileLiveDeps,
  type ReconcileLiveOptions,
  type ReconcileLiveResult,
} from "./scheduler/reconcile.js";
export {
  deduplicateActiveTransfers,
  type DeduplicateDeps,
  type DeduplicateResult,
} from "./scheduler/dedup.js";
export {
  runSchedulerLoop,
  type SchedulerLoopDeps,
  type SchedulerLoopIteration,
  type SchedulerLoopOptions,
} from "./scheduler/loop.js";
export {
  buildTransferSummary,
  rankActiveInfos,
  type TransferSummary,
} from "./transfers/progress.js";
export { planCleanup } from "./reconcile/cleanup.js";
export { planAutoCleanup } from "./state/archivable.js";
export { queueItemForActiveInfo } from "./reconcile/match.js";
export * as discovery from "./discovery/parse.js";
export {
  matchesAllowlist,
  matchesContentFilter,
} from "./discovery/filter.js";
export { PeerRegistry, type DiscoveredPeer } from "./discovery/registry.js";
export * as bonjour from "./bonjour/bonjour.js";
export {
  advertiseHttpService,
  type AdvertiseHandle,
  type AdvertiseOptions,
} from "./bonjour/advertise.js";
export * as install from "./install/networkquality.js";
export {
  detectAriaflowManagedBy,
  detectAriaflowInstalledVia,
  detectBinaryInstalledVia,
  detectLaunchdLabel,
  type AriaflowManagedBy,
  type AriaflowInstalledVia,
} from "./install/ariaflow_self.js";
export {
  versionFromTag,
  tarballUrl,
  downloadSha256,
  renderFormula,
  writeFormula,
} from "./install/formula.js";
export {
  ARIA2_LAUNCHD_LABEL,
  ARIA2_SYSTEMD_UNIT,
  buildAria2Plist,
  buildAria2SystemdUnit,
  detectServiceTarget,
  findAria2c,
  aria2AutoStartInstalled,
  installAria2Service,
  planLaunchdInstall,
  planLaunchdUninstall,
  planSystemdInstall,
  planSystemdUninstall,
  runShellPlan,
  uninstallAria2Service,
  type InstallServiceResult,
  type ServiceTarget,
  type ShellExecResult,
} from "./install/services.js";
