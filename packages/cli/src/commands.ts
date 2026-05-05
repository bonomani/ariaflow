// Barrel file. Each cmd lives in its own per-concern module under
// commands/. Keep this list in sync with cli/src/index.ts and the
// public-surface tests.
export type { CmdResult } from "./commands/_shared.js";

export {
  cmdAdd,
  cmdCleanup,
  cmdList,
  cmdPause,
  cmdRemove,
  cmdResume,
  cmdSeedStop,
} from "./commands/queue.js";

export {
  cmdBandwidth,
  cmdDashboard,
  cmdDeclaration,
  cmdOpenapi,
  cmdProbe,
  cmdStatus,
} from "./commands/inspect.js";

export { cmdWatch } from "./commands/watch.js";

export { cmdServe } from "./commands/serve.js";

export { cmdSetPref } from "./commands/config.js";

export { cmdDoctor } from "./commands/doctor.js";

export {
  cmdFormula,
  cmdInstallService,
  cmdUninstallService,
} from "./commands/install.js";
