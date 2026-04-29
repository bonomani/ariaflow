import { readJson, writeJson } from "./json.js";
import { archivePath, queuePath } from "./paths.js";
import type { StorageLock } from "./lock.js";
import type { QueueItemRecord } from "../queue/types.js";

interface QueueFile {
  items: QueueItemRecord[];
  [k: string]: unknown;
}

const emptyQueue = (): QueueFile => ({ items: [] });

export class QueueStore {
  constructor(
    private readonly lock: StorageLock,
    private readonly env: NodeJS.ProcessEnv = process.env,
  ) {}

  load(): Promise<QueueItemRecord[]> {
    return this.lock.with(async () => {
      const data = await readJson<QueueFile>(queuePath(this.env), emptyQueue());
      return Array.isArray(data.items) ? data.items : [];
    });
  }

  save(items: QueueItemRecord[]): Promise<void> {
    return this.lock.with(() => writeJson(queuePath(this.env), { items }));
  }
}

export class ArchiveStore {
  constructor(
    private readonly lock: StorageLock,
    private readonly env: NodeJS.ProcessEnv = process.env,
  ) {}

  load(): Promise<QueueItemRecord[]> {
    return this.lock.with(async () => {
      const data = await readJson<QueueFile>(archivePath(this.env), emptyQueue());
      return Array.isArray(data.items) ? data.items : [];
    });
  }

  save(items: QueueItemRecord[]): Promise<void> {
    return this.lock.with(() => writeJson(archivePath(this.env), { items }));
  }

  async append(item: QueueItemRecord): Promise<void> {
    return this.lock.with(async () => {
      const existing = await this.load();
      const stamped = { ...item, archived_at: new Date().toISOString() };
      await writeJson(archivePath(this.env), { items: [...existing, stamped] });
    });
  }
}
