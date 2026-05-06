import type { QueueItemRecord } from "./types.js";

/**
 * BG-56: rewrite `output_path` on every queue row that points at `from`
 * to point at `to`. Used after rename/move on the file ops route. Returns
 * true when at least one row was touched (caller should persist).
 */
export function updateOutputPath(
  items: QueueItemRecord[],
  from: string,
  to: string,
): boolean {
  let touched = false;
  for (const it of items) {
    if (it.output_path === from) {
      it.output_path = to;
      touched = true;
    }
  }
  return touched;
}

/**
 * BG-56: flag every queue row whose `output_path` is in `paths` as
 * absent on disk. Used after delete + the orphaned-reconcile cleanup
 * recipe. Returns true when at least one row was touched.
 */
export function markMissingByPath(
  items: QueueItemRecord[],
  paths: ReadonlySet<string>,
): boolean {
  let touched = false;
  for (const it of items) {
    if (it.output_path && paths.has(it.output_path)) {
      it.file_present_on_disk = false;
      touched = true;
    }
  }
  return touched;
}
