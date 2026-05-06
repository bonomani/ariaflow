import { homedir } from "node:os";
import { join } from "node:path";

/**
 * BG-58: resolve the platform's standard download folder when the
 * operator hasn't set `download_dir` explicitly.
 *
 * Order:
 *   1. $XDG_DOWNLOAD_DIR (Linux freedesktop spec; honored on every OS
 *      when set, since operators on macOS/Windows occasionally export
 *      it too)
 *   2. ~/Downloads (macOS, Linux fallback, Windows in WSL)
 *
 * Returns null in the headless edge case (no $HOME and no XDG var) so
 * the caller can keep its existing "download_dir_unset" 409 path.
 */
export function resolveDefaultDownloadDir(): string | null {
  const xdg = process.env.XDG_DOWNLOAD_DIR?.trim();
  if (xdg) return xdg;
  const home = homedir();
  if (!home) return null;
  return join(home, "Downloads");
}
