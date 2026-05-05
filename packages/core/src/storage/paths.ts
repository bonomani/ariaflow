import { homedir } from "node:os";
import { join } from "node:path";

/**
 * Resolve the on-disk config directory. Honors `ARIAFLOW_DIR`;
 * otherwise defaults to `~/.config/ariaflow-server`.
 */
export function configDir(env: NodeJS.ProcessEnv = process.env): string {
  if (env.ARIAFLOW_DIR) return env.ARIAFLOW_DIR;
  return join(homedir(), ".config", "ariaflow-server");
}

export const queuePath = (env?: NodeJS.ProcessEnv) => join(configDir(env), "queue.json");
export const statePath = (env?: NodeJS.ProcessEnv) => join(configDir(env), "state.json");
export const actionLogPath = (env?: NodeJS.ProcessEnv) => join(configDir(env), "actions.jsonl");
export const archivePath = (env?: NodeJS.ProcessEnv) => join(configDir(env), "archive.json");
export const sessionsLogPath = (env?: NodeJS.ProcessEnv) =>
  join(configDir(env), "sessions.jsonl");
export const storageLockPath = (env?: NodeJS.ProcessEnv) =>
  join(configDir(env), ".storage.lock");
