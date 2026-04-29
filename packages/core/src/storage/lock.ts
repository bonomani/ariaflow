import { mkdir, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname } from "node:path";
import { AsyncLocalStorage } from "node:async_hooks";
import lockfile from "proper-lockfile";

/**
 * Reentrant async storage lock.
 *
 * Mirrors Python's `storage_locked()`:
 * - exclusive across processes via a sentinel file (proper-lockfile),
 * - reentrant within the same async context: a nested `with()` call from
 *   inside an already-held section runs immediately, without queuing.
 *
 * Concurrent (non-nested) callers are serialized through an internal
 * promise chain so we hold at most one OS-level lock at a time.
 */
export class StorageLock {
  private chain: Promise<unknown> = Promise.resolve();
  private release: (() => Promise<void>) | null = null;
  private readonly als = new AsyncLocalStorage<true>();

  constructor(private readonly sentinelPath: string) {}

  async with<T>(fn: () => Promise<T> | T): Promise<T> {
    if (this.als.getStore()) {
      // Reentrant: already inside a held section in this async context.
      return await fn();
    }
    const next = this.chain.then(() => this.acquireAndRun(fn));
    this.chain = next.catch(() => undefined);
    return next;
  }

  private async acquireAndRun<T>(fn: () => Promise<T> | T): Promise<T> {
    await ensureSentinel(this.sentinelPath);
    this.release = await lockfile.lock(this.sentinelPath, {
      retries: { retries: 50, minTimeout: 20, maxTimeout: 200 },
      stale: 30_000,
    });
    try {
      return await this.als.run(true, async () => fn());
    } finally {
      const release = this.release;
      this.release = null;
      if (release) {
        try {
          await release();
        } catch {
          /* lock already released by stale recovery — ignore */
        }
      }
    }
  }
}

async function ensureSentinel(path: string): Promise<void> {
  await mkdir(dirname(path), { recursive: true });
  if (!existsSync(path)) await writeFile(path, "", { flag: "a" });
}
