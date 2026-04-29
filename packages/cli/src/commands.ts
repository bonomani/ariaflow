import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { allowedActions, bandwidthConfigFrom, EventBus, summarizeQueue } from "@ariaflow/core";
import { buildServer } from "@ariaflow/api";
import type { CliContext } from "./context.js";

export interface CmdResult {
  ok: boolean;
  exitCode: number;
  stdout: string;
}

const ok = (stdout: string): CmdResult => ({ ok: true, exitCode: 0, stdout });
const fail = (stdout: string, code = 1): CmdResult => ({ ok: false, exitCode: code, stdout });

const json = (v: unknown): string => JSON.stringify(v, null, 2);

export async function cmdAdd(
  ctx: CliContext,
  url: string,
  opts: { output?: string; priority?: number; pretty?: boolean } = {},
): Promise<CmdResult> {
  if (!url) return fail("error: url is required\n");
  const { item, duplicate } = await ctx.queueOps.add({
    url,
    output: opts.output ?? null,
    priority: opts.priority ?? 0,
  });
  const summary = { id: item.id, url: item.url, status: item.status, duplicate };
  if (opts.pretty) {
    return ok(
      `${duplicate ? "duplicate" : "added"} ${item.id}\n  url: ${item.url}\n  status: ${item.status}\n`,
    );
  }
  return ok(json(summary) + "\n");
}

export async function cmdList(
  ctx: CliContext,
  opts: { pretty?: boolean } = {},
): Promise<CmdResult> {
  const items = await ctx.queue.load();
  if (opts.pretty) {
    if (items.length === 0) return ok("(no items)\n");
    const lines = items.map(
      (i) => `${i.id}  ${String(i.status ?? "?").padEnd(10)} ${i.url}`,
    );
    return ok(lines.join("\n") + "\n");
  }
  return ok(
    json({
      summary: summarizeQueue(items),
      items: items.map((i) => ({
        id: i.id,
        url: i.url,
        status: i.status ?? "queued",
        gid: i.gid ?? null,
        actions: allowedActions(String(i.status ?? "")),
      })),
    }) + "\n",
  );
}

export async function cmdRemove(ctx: CliContext, itemId: string): Promise<CmdResult> {
  if (!itemId) return fail("error: id is required\n");
  const removed = await ctx.queueOps.remove(itemId);
  if (!removed) return fail(`error: item ${itemId} not found\n`, 2);
  return ok(json({ removed: removed.id }) + "\n");
}

export async function cmdPause(ctx: CliContext, itemId: string): Promise<CmdResult> {
  if (!itemId) return fail("error: id is required\n");
  const next = await ctx.queueOps.transitionStatus(itemId, "paused", "paused_at");
  if (!next) return fail(`error: item ${itemId} not found\n`, 2);
  return ok(json({ id: next.id, status: next.status, paused_at: next.paused_at }) + "\n");
}

export async function cmdResume(ctx: CliContext, itemId: string): Promise<CmdResult> {
  if (!itemId) return fail("error: id is required\n");
  const next = await ctx.queueOps.transitionStatus(itemId, "queued", "resumed_at");
  if (!next) return fail(`error: item ${itemId} not found\n`, 2);
  return ok(json({ id: next.id, status: next.status, resumed_at: next.resumed_at }) + "\n");
}

export async function cmdBandwidth(ctx: CliContext): Promise<CmdResult> {
  const declaration = await ctx.declaration.load();
  const state = await ctx.state.load();
  const config = bandwidthConfigFrom(declaration);
  return ok(
    json({
      config,
      last_probe: state.last_bandwidth_probe ?? null,
      last_probe_at: state.last_bandwidth_probe_at ?? null,
    }) + "\n",
  );
}

export async function cmdDeclaration(ctx: CliContext): Promise<CmdResult> {
  const declaration = await ctx.declaration.load();
  return ok(json(declaration) + "\n");
}

export async function cmdStatus(ctx: CliContext): Promise<CmdResult> {
  const state = await ctx.state.load();
  const items = await ctx.queue.load();
  const summary = summarizeQueue(items);
  return ok(
    json({
      session_id: state.session_id,
      paused: state.paused,
      running: state.running,
      active_gid: state.active_gid,
      summary,
    }) + "\n",
  );
}

export interface WatchOptions {
  url: string;
  /** Maximum events to receive before resolving; default unlimited. */
  limit?: number;
  /** Abort signal for the consumer (e.g. SIGINT handler). */
  signal?: AbortSignal;
  /** Where to write each line; defaults to process.stdout. */
  out?: { write(s: string): boolean | void };
}

/**
 * Subscribe to an SSE stream at `url` and write one JSON line per event:
 *   {"event": "action_logged", "data": {...}}
 *
 * Streams the response body via fetch + ReadableStream and parses
 * SSE-framed `event:`/`data:` blocks separated by blank lines. This
 * avoids depending on globalThis.EventSource (only stable in Node 22+
 * and not enabled by default everywhere).
 *
 * Resolves when `limit` is reached, when the server closes the body,
 * or when `signal` fires. Returns a fail result on connect error.
 */
export async function cmdWatch(opts: WatchOptions): Promise<CmdResult> {
  const out = opts.out ?? process.stdout;
  const limit = opts.limit ?? Number.POSITIVE_INFINITY;
  let res: Response;
  try {
    res = await fetch(opts.url, {
      headers: { Accept: "text/event-stream" },
      ...(opts.signal ? { signal: opts.signal } : {}),
    });
  } catch (err) {
    return fail(`error: failed to connect to ${opts.url}: ${(err as Error).message}\n`);
  }
  if (!res.ok || !res.body) {
    return fail(`error: failed to connect to ${opts.url}: HTTP ${res.status}\n`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let received = 0;
  let event = "message";
  const dataLines: string[] = [];

  const emit = (): void => {
    if (dataLines.length === 0) return;
    const raw = dataLines.join("\n");
    let parsed: unknown = raw;
    try {
      parsed = JSON.parse(raw);
    } catch {
      /* leave raw */
    }
    out.write(JSON.stringify({ event, data: parsed }) + "\n");
    received += 1;
    event = "message";
    dataLines.length = 0;
  };

  try {
    while (received < limit) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let nl: number;
      while ((nl = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, nl).replace(/\r$/, "");
        buffer = buffer.slice(nl + 1);
        if (line === "") {
          emit();
          if (received >= limit) break;
        } else if (line.startsWith(":")) {
          /* heartbeat / comment — ignore */
        } else if (line.startsWith("event:")) {
          event = line.slice(6).trim();
        } else if (line.startsWith("data:")) {
          dataLines.push(line.slice(5).replace(/^ /, ""));
        }
      }
    }
  } finally {
    try {
      await reader.cancel();
    } catch {
      /* ignore */
    }
  }
  return ok("");
}

export interface ServeOptions {
  host?: string;
  port?: number;
  version?: string;
  /** Path to openapi.yaml; auto-discovered when omitted. */
  openapiYamlPath?: string;
}

/**
 * Walk up from cwd looking for an openapi.yaml at the repo root. Returns
 * the resolved absolute path or null when not found within 5 levels.
 */
function findOpenApiYaml(start: string = process.cwd()): string | null {
  let dir = start;
  for (let i = 0; i < 5; i++) {
    const candidate = join(dir, "openapi.yaml");
    if (existsSync(candidate)) return candidate;
    const parent = dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return null;
}

export interface ServeHandle {
  url: string;
  port: number;
  close: () => Promise<void>;
}

/**
 * Boot the Fastify server with the CLI's storage stack. Returns a
 * handle the caller can close — the bin uses this to wire SIGINT.
 *
 * NOTE: this does NOT call process.exit; the listening loop keeps the
 * process alive on its own once Fastify starts.
 */
export async function cmdServe(
  ctx: CliContext,
  opts: ServeOptions = {},
): Promise<ServeHandle> {
  const eventBus = new EventBus();
  const yamlPath = opts.openapiYamlPath ?? findOpenApiYaml();
  const app = buildServer({
    queueOps: ctx.queueOps,
    queueStore: ctx.queue,
    archiveStore: ctx.archive,
    declarationStore: ctx.declaration,
    stateStore: ctx.state,
    sessionService: ctx.sessions,
    actionLog: ctx.actions,
    eventBus,
    ...(opts.version !== undefined ? { version: opts.version } : {}),
    ...(yamlPath ? { openapiYamlPath: yamlPath } : {}),
  });
  const requestedPort = opts.port ?? 8000;
  const host = opts.host ?? "127.0.0.1";
  await app.listen({ host, port: requestedPort });
  // When port=0 was passed, ask Fastify for the bound port so the URL
  // we hand back actually reaches the listener.
  const addr = app.server.address();
  const port =
    typeof addr === "object" && addr !== null && "port" in addr ? addr.port : requestedPort;
  return {
    url: `http://${host}:${port}`,
    port,
    close: async () => {
      await app.close();
    },
  };
}
