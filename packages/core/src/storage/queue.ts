import { readJson, writeJson } from "./json.js";
import { archivePath, queuePath } from "./paths.js";
import type { StorageLock } from "./lock.js";
import type { QueueItem } from "../state/archivable.js";

interface QueueFile {
  items: QueueItem[];
  [k: string]: unknown;
}

const EMPTY_QUEUE: QueueFile = { items: [] };

export class QueueStore {
  constructor(
    private readonly lock: StorageLock,
    private readonly env: NodeJS.ProcessEnv = process.env,
  ) {}

  load(): Promise<QueueItem[]> {
    return this.lock.with(async () => {
      const data = await readJson<QueueFile>(queuePath(this.env), EMPTY_QUEUE);
      return Array.isArray(data.items) ? data.items : [];
    });
  }

  save(items: QueueItem[]): Promise<void> {
    return this.lock.with(() => writeJson(queuePath(this.env), { items }));
  }
}

export class ArchiveStore {
  constructor(
    private readonly lock: StorageLock,
    private readonly env: NodeJS.ProcessEnv = process.env,
  ) {}

  load(): Promise<QueueItem[]> {
    return this.lock.with(async () => {
      const data = await readJson<QueueFile>(archivePath(this.env), EMPTY_QUEUE);
      return Array.isArray(data.items) ? data.items : [];
    });
  }

  save(items: QueueItem[]): Promise<void> {
    return this.lock.with(() => writeJson(archivePath(this.env), { items }));
  }

  async append(item: QueueItem): Promise<void> {
    return this.lock.with(async () => {
      const existing = await this.load();
      const stamped = { ...item, archived_at: new Date().toISOString() };
      await writeJson(archivePath(this.env), { items: [...existing, stamped] });
    });
  }
}
