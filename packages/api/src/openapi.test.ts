import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  ActionLog,
  ArchiveStore,
  DeclarationStore,
  QueueOps,
  QueueStore,
  SessionService,
  StateStore,
  StorageLock,
  storageLockPath,
} from "@ariaflow/core";
import { buildServer } from "./server.js";
import { generateOpenApi } from "./openapi.js";

let dir: string;
let app: ReturnType<typeof buildServer>;

beforeEach(async () => {
  dir = mkdtempSync(join(tmpdir(), "ariaflow-oa-"));
  const env = { ARIAFLOW_DIR: dir };
  const lock = new StorageLock(storageLockPath(env));
  const state = new StateStore(lock, env);
  const queue = new QueueStore(lock, env);
  const archive = new ArchiveStore(lock, env);
  const actions = new ActionLog(lock, state, env);
  const sessions = new SessionService(lock, state, queue, archive, env);
  const declaration = new DeclarationStore(lock, env);
  const queueOps = new QueueOps(queue, sessions, declaration, actions);
  app = buildServer({
    queueOps,
    queueStore: queue,
    declarationStore: declaration,
    stateStore: state,
    sessionService: sessions,
    actionLog: actions,
    cwd: dir,
  });
  await app.ready();
});

afterEach(async () => {
  await app.close();
  rmSync(dir, { recursive: true, force: true });
});

describe("generateOpenApi", () => {
  it("emits a 3.0.3 doc with our routes mapped to tags", () => {
    const doc = generateOpenApi(app, { title: "ariaflow", version: "0.1.0" });
    expect(doc.openapi).toBe("3.0.3");
    expect(doc.info).toEqual({ title: "ariaflow", version: "0.1.0" });
    expect(doc.paths["/api/downloads"]).toBeTruthy();
    expect(doc.paths["/api/downloads"]!.post).toBeTruthy();
    expect(doc.paths["/api/declaration"]).toBeTruthy();
  });

  it("converts Fastify :id syntax to OpenAPI {id}", () => {
    const doc = generateOpenApi(app);
    const keys = Object.keys(doc.paths);
    expect(keys.some((k) => k.includes("{id}"))).toBe(true);
    expect(keys.some((k) => k.includes(":id"))).toBe(false);
  });

  it("tags by longest-matching prefix", () => {
    const doc = generateOpenApi(app);
    const downloads = doc.paths["/api/downloads"]!.get!;
    expect(downloads.tags).toEqual(["Queue"]);
    const sessionsCurrent = doc.paths["/api/sessions/current"]!.get!;
    expect(sessionsCurrent.tags).toEqual(["Sessions"]);
    const decl = doc.paths["/api/declaration"]!.get!;
    expect(decl.tags).toEqual(["Config"]);
  });
});
