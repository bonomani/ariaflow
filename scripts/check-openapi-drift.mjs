#!/usr/bin/env node
// Compare the live Fastify routes (built via @ariaflow/api/buildServer)
// against the canonical openapi.yaml at the repo root. Exit non-zero
// with a human-readable drift report on any path or method mismatch.
//
// Usage: node scripts/check-openapi-drift.mjs [path/to/openapi.yaml]

import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "..");
const yamlPath = process.argv[2] ? resolve(process.argv[2]) : join(repoRoot, "openapi.yaml");

// Use relative file:// imports into the built dist so the script runs
// without pnpm workspace resolution (CI containers that don't run
// `pnpm install` first still work as long as `pnpm build` ran).
const coreDistUrl = pathToFileURL(resolve(repoRoot, "packages/core/dist/index.js")).href;
const apiDistUrl = pathToFileURL(resolve(repoRoot, "packages/api/dist/index.js")).href;
const {
  ActionLog,
  ArchiveStore,
  DeclarationStore,
  QueueOps,
  QueueStore,
  SessionService,
  StateStore,
  StorageLock,
  storageLockPath,
} = await import(coreDistUrl);
const { buildServer, diffOpenApi, formatDriftReport, generateOpenApi, loadOpenApiYaml } =
  await import(apiDistUrl);

const dir = mkdtempSync(join(tmpdir(), "ariaflow-drift-"));
try {
  const env = { ARIAFLOW_DIR: dir };
  const lock = new StorageLock(storageLockPath(env));
  const state = new StateStore(lock, env);
  const queue = new QueueStore(lock, env);
  const archive = new ArchiveStore(lock, env);
  const actions = new ActionLog(lock, state, env);
  const sessions = new SessionService(lock, state, queue, archive, env);
  const declaration = new DeclarationStore(lock, env);
  const queueOps = new QueueOps(queue, sessions, declaration, actions);

  const app = buildServer({
    queueOps,
    queueStore: queue,
    declarationStore: declaration,
    stateStore: state,
    sessionService: sessions,
    actionLog: actions,
  });
  await app.ready();

  const live = generateOpenApi(app);
  const expected = await loadOpenApiYaml(yamlPath);
  const report = diffOpenApi(live, expected);

  await app.close();

  if (report.ok) {
    process.stdout.write(`OpenAPI drift: OK (${Object.keys(live.paths).length} paths)\n`);
    process.exit(0);
  }
  process.stdout.write(`OpenAPI drift detected (vs ${yamlPath}):\n`);
  process.stdout.write(formatDriftReport(report));
  process.exit(1);
} finally {
  rmSync(dir, { recursive: true, force: true });
}
