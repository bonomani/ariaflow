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
let app: Awaited<ReturnType<typeof buildServer>>;

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
  app = await buildServer({
    queueOps,
    queueStore: queue,
    declarationStore: declaration,
    stateStore: state,
    sessionService: sessions,
    actionLog: actions,
    cwd: dir,
    version: "0.1.0",
  });
  await app.ready();
});

afterEach(async () => {
  await app.close();
  rmSync(dir, { recursive: true, force: true });
});

describe("generateOpenApi (R-J: backed by @fastify/swagger)", () => {
  it("emits a 3.0 doc with info populated from buildServer deps.version", () => {
    const doc = generateOpenApi(app);
    expect(doc.openapi).toMatch(/^3\.0/);
    expect(doc.info.title).toBe("Ariaflow API");
    expect(doc.info.version).toBe("0.1.0");
  });

  it("includes the routes registered by buildServer", () => {
    const doc = generateOpenApi(app);
    expect(doc.paths["/api/downloads"]).toBeTruthy();
    expect(doc.paths["/api/declaration"]).toBeTruthy();
    expect(doc.paths["/api/scheduler"]).toBeTruthy();
  });

  it("converts Fastify :id syntax to OpenAPI {id}", () => {
    const doc = generateOpenApi(app);
    const keys = Object.keys(doc.paths);
    expect(keys.some((k) => k.includes("{id}"))).toBe(true);
    expect(keys.some((k) => k.includes(":id"))).toBe(false);
  });
});
