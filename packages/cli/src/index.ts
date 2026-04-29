#!/usr/bin/env node
import { Command } from "commander";
import {
  cmdAdd,
  cmdBandwidth,
  cmdDashboard,
  cmdDeclaration,
  cmdList,
  cmdPause,
  cmdProbe,
  cmdRemove,
  cmdResume,
  cmdSeedStop,
  cmdServe,
  cmdSetPref,
  cmdStatus,
  cmdWatch,
} from "./commands.js";
import { makeContext } from "./context.js";

const program = new Command();
program
  .name("ariaflow")
  .description("ariaflow-server CLI (TypeScript port)")
  .version("0.0.0");

program
  .command("add")
  .argument("<url>", "URL to download (http/https/ftp/magnet)")
  .option("-o, --output <path>", "output filename (relative)")
  .option("-p, --priority <n>", "priority (integer)", (v) => Number(v))
  .option("--pretty", "human-readable output instead of JSON")
  .action(async (url: string, opts: { output?: string; priority?: number; pretty?: boolean }) => {
    const ctx = makeContext();
    const r = await cmdAdd(ctx, url, opts);
    process.stdout.write(r.stdout);
    process.exit(r.exitCode);
  });

program
  .command("list")
  .option("--pretty", "human-readable output instead of JSON")
  .action(async (opts: { pretty?: boolean }) => {
    const ctx = makeContext();
    const r = await cmdList(ctx, opts);
    process.stdout.write(r.stdout);
    process.exit(r.exitCode);
  });

program
  .command("remove")
  .argument("<id>", "queue item id (UUID)")
  .action(async (id: string) => {
    const ctx = makeContext();
    const r = await cmdRemove(ctx, id);
    process.stdout.write(r.stdout);
    process.exit(r.exitCode);
  });

program
  .command("pause")
  .argument("<id>", "queue item id (UUID)")
  .action(async (id: string) => {
    const ctx = makeContext();
    const r = await cmdPause(ctx, id);
    process.stdout.write(r.stdout);
    process.exit(r.exitCode);
  });

program
  .command("resume")
  .argument("<id>", "queue item id (UUID)")
  .action(async (id: string) => {
    const ctx = makeContext();
    const r = await cmdResume(ctx, id);
    process.stdout.write(r.stdout);
    process.exit(r.exitCode);
  });

program.command("status").action(async () => {
  const ctx = makeContext();
  const r = await cmdStatus(ctx);
  process.stdout.write(r.stdout);
  process.exit(r.exitCode);
});

program.command("bandwidth").description("show bandwidth config + last probe").action(async () => {
  const ctx = makeContext();
  const r = await cmdBandwidth(ctx);
  process.stdout.write(r.stdout);
  process.exit(r.exitCode);
});

program.command("declaration").description("show the UCC declaration").action(async () => {
  const ctx = makeContext();
  const r = await cmdDeclaration(ctx);
  process.stdout.write(r.stdout);
  process.exit(r.exitCode);
});

program
  .command("serve")
  .description("start the HTTP API server")
  .option("--host <h>", "bind host", "127.0.0.1")
  .option("--port <p>", "bind port", (v) => Number(v), 8000)
  .option("--openapi-yaml <path>", "path to openapi.yaml (auto-discovered if omitted)")
  .action(async (opts: { host: string; port: number; openapiYaml?: string }) => {
    const ctx = makeContext();
    const handle = await cmdServe(ctx, {
      host: opts.host,
      port: opts.port,
      ...(opts.openapiYaml ? { openapiYamlPath: opts.openapiYaml } : {}),
    });
    process.stdout.write(`ariaflow-server listening at ${handle.url}\n`);
    const stop = async () => {
      await handle.close();
      process.exit(0);
    };
    process.once("SIGINT", stop);
    process.once("SIGTERM", stop);
  });

program
  .command("watch")
  .description("subscribe to /api/events on a running ariaflow-server")
  .option("--url <u>", "events URL", "http://127.0.0.1:8000/api/events")
  .option("--limit <n>", "exit after N events", (v) => Number(v))
  .action(async (opts: { url: string; limit?: number }) => {
    const ctrl = new AbortController();
    process.once("SIGINT", () => ctrl.abort());
    process.once("SIGTERM", () => ctrl.abort());
    const r = await cmdWatch({
      url: opts.url,
      ...(opts.limit !== undefined ? { limit: opts.limit } : {}),
      signal: ctrl.signal,
    });
    if (!r.ok) process.stdout.write(r.stdout);
    process.exit(r.exitCode);
  });

program
  .command("dashboard")
  .description("combined snapshot of scheduler / queue / bandwidth / declaration")
  .option("--pretty", "human-readable layout instead of JSON")
  .action(async (opts: { pretty?: boolean }) => {
    const ctx = makeContext();
    const r = await cmdDashboard(ctx, opts);
    process.stdout.write(r.stdout);
    process.exit(r.exitCode);
  });

program
  .command("probe")
  .description("run a manual bandwidth probe (networkQuality)")
  .action(async () => {
    const ctx = makeContext();
    const r = await cmdProbe(ctx);
    process.stdout.write(r.stdout);
    process.exit(r.exitCode);
  });

program
  .command("set-pref")
  .description("update a single UCC preference")
  .argument("<name>", "preference name")
  .argument("<value>", "value (booleans/numbers auto-coerced)")
  .action(async (name: string, value: string) => {
    const ctx = makeContext();
    const r = await cmdSetPref(ctx, name, value);
    process.stdout.write(r.stdout);
    process.exit(r.exitCode);
  });

program
  .command("seed-stop")
  .description("stop a distribute-mode seed by infohash")
  .argument("<infohash>", "torrent infohash")
  .action(async (infohash: string) => {
    const ctx = makeContext();
    const r = await cmdSeedStop(ctx, infohash);
    process.stdout.write(r.stdout);
    process.exit(r.exitCode);
  });

program.parseAsync(process.argv);
