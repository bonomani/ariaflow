import { copyFile, mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname } from "node:path";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/**
 * Read JSON from `path`. Falls back to `defaultValue` when the file is
 * missing or unparseable. On a parse error the file is preserved at
 * `<path>.corrupt.bak` (best-effort) before returning the default.
 *
 * One short retry tolerates a concurrent write that hasn't yet
 * completed its atomic rename.
 */
export async function readJson<T>(path: string, defaultValue: T): Promise<T> {
  if (!existsSync(path)) return defaultValue;
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const txt = await readFile(path, "utf8");
      return JSON.parse(txt) as T;
    } catch (e) {
      if (attempt === 0 && e instanceof SyntaxError) {
        await sleep(50);
        continue;
      }
      try {
        await copyFile(path, `${path}.corrupt.bak`);
      } catch {
        /* best-effort */
      }
      return defaultValue;
    }
  }
  return defaultValue;
}

/**
 * Atomically write JSON to `path` (write to `<path>.tmp`, then rename).
 * Creates parent directories as needed. Output is indent-2, sort-keys
 * to match the Python writer.
 */
export async function writeJson(path: string, value: unknown): Promise<void> {
  await mkdir(dirname(path), { recursive: true });
  const tmp = `${path}.tmp`;
  await writeFile(tmp, stringifySorted(value) + "\n", "utf8");
  await rename(tmp, path);
}

function stringifySorted(value: unknown): string {
  return JSON.stringify(value, replacerSortKeys(), 2);
}

function replacerSortKeys() {
  // Sort object keys recursively for deterministic output.
  return function (this: unknown, _key: string, val: unknown): unknown {
    if (val && typeof val === "object" && !Array.isArray(val)) {
      const sorted: Record<string, unknown> = {};
      for (const k of Object.keys(val).sort()) {
        sorted[k] = (val as Record<string, unknown>)[k];
      }
      return sorted;
    }
    return val;
  };
}
