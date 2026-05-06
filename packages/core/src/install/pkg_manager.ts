import { statSync } from "node:fs";
import { delimiter, join } from "node:path";

/**
 * BG-60: resolve a package manager command (`brew`, `pipx`, `npm`, ...)
 * to an absolute path. Bare-name spawns work under a login shell but
 * fail under launchd / systemd-user, where PATH is minimal. Order:
 *
 *   1. $PATH lookup (succeeds under any shell-derived env)
 *   2. Known install prefixes (Homebrew Apple Silicon / Intel / Linuxbrew,
 *      pipx default `~/.local/bin`)
 *   3. Fall through with the bare name — spawn will ENOENT and the
 *      caller's existing catch handles it.
 */
export function resolvePkgManager(name: string): string {
  const path = process.env.PATH ?? "";
  for (const dir of path.split(delimiter)) {
    if (!dir) continue;
    const candidate = join(dir, name);
    try {
      if (statSync(candidate).isFile()) return candidate;
    } catch {
      /* not in this dir */
    }
  }
  const home = process.env.HOME ?? "";
  const candidates = [
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "/home/linuxbrew/.linuxbrew/bin",
    home ? join(home, ".local", "bin") : null,
  ].filter((d): d is string => d !== null);
  for (const dir of candidates) {
    const candidate = join(dir, name);
    try {
      if (statSync(candidate).isFile()) return candidate;
    } catch {
      /* not here */
    }
  }
  return name;
}
