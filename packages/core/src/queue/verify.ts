import { statSync } from "node:fs";
import { basename, isAbsolute, join } from "node:path";

/**
 * BG-55: Tier 1 (`local_only`) verification.
 * Returns the absolute path that exists on disk (if any) for the URL's
 * basename under download_dir. Returns null when the gate doesn't fire
 * (strategy off / no download_dir / file absent / can't stat).
 *
 * Lives in its own module so a future Tier 2 (HEAD probe) implementation
 * can plug in alongside without rewiring `queue/ops.ts`.
 */
export function verifyExistingTier1(
  url: string,
  downloadDir: string,
  output: string | null,
): string | null {
  if (!downloadDir) return null;
  let expectedName: string | null = null;
  if (output && output.trim()) {
    const trimmed = output.trim();
    expectedName = basename(trimmed) === trimmed ? trimmed : null;
  }
  if (!expectedName) {
    try {
      const u = new URL(url);
      expectedName = basename(u.pathname) || null;
    } catch {
      return null;
    }
  }
  if (!expectedName) return null;
  const path = isAbsolute(expectedName) ? expectedName : join(downloadDir, expectedName);
  try {
    const st = statSync(path);
    if (st.isFile()) return path;
  } catch {
    /* ENOENT or perms — no file */
  }
  return null;
}
