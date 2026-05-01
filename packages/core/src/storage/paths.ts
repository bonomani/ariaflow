import { existsSync, renameSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

/**
 * Resolve the on-disk config directory.
 *
 * Honors `ARIAFLOW_DIR` / `ARIA_QUEUE_DIR` env vars; otherwise defaults
 * to `~/.config/ariaflow-server`. Migrates the legacy `aria-queue`
 * directory in-place if present.
 */
export function configDir(env: NodeJS.ProcessEnv = process.env): string {
  const explicit = env.ARIAFLOW_DIR || env.ARIA_QUEUE_DIR;
  if (explicit) return explicit;
  const home = homedir();
  const next = join(home, ".config", "ariaflow-server");
  const old = join(home, ".config", "aria-queue");
  if (!existsSync(next) && existsSync(old)) {
    try {
      renameSync(old, next);
    } catch {
      return old;
    }
  }
  return next;
}

export const queuePath = (env?: NodeJS.ProcessEnv) => join(configDir(env), "queue.json");
export const statePath = (env?: NodeJS.ProcessEnv) => join(configDir(env), "state.json");
export const actionLogPath = (env?: NodeJS.ProcessEnv) => join(configDir(env), "actions.jsonl");
export const archivePath = (env?: NodeJS.ProcessEnv) => join(configDir(env), "archive.json");
export const sessionsLogPath = (env?: NodeJS.ProcessEnv) =>
  join(configDir(env), "sessions.jsonl");
export const storageLockPath = (env?: NodeJS.ProcessEnv) =>
  join(configDir(env), ".storage.lock");
