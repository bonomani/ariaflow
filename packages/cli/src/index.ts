#!/usr/bin/env node
import { Command } from "commander";
import {
  cmdAdd,
  cmdBandwidth,
  cmdCleanup,
  cmdDashboard,
  cmdDeclaration,
  cmdDoctor,
  cmdFormula,
  cmdInstallService,
  cmdList,
  cmdOpenapi,
  cmdPause,
  cmdProbe,
  cmdRemove,
  cmdResume,
  cmdSeedStop,
  cmdServe,
  cmdSetPref,
  cmdStatus,
  cmdUninstallService,
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
  .option("--aria2-host <h>", "aria2 RPC host", "127.0.0.1")
  .option("--aria2-port <p>", "aria2 RPC port", (v) => Number(v), 6800)
  .option("--aria2-secret <s>", "aria2 RPC secret token")
  .option("--no-aria2", "disable the aria2 client (read-only API)")
  .option(
    "--scheduler",
    "run the scheduler loop in-process (dispatches queued items to aria2)",
  )
  .option(
    "--scheduler-interval <ms>",
    "scheduler tick interval in ms",
    (v) => Number(v),
    2000,
  )
  .option("--no-mdns", "disable mDNS announcement of _ariaflow-server._tcp")
  .action(
    async (opts: {
      host: string;
      port: number;
      openapiYaml?: string;
      aria2: boolean;
      aria2Host: string;
      aria2Port: number;
      aria2Secret?: string;
      scheduler?: boolean;
      schedulerInterval: number;
      mdns: boolean;
    }) => {
      const ctx = makeContext();
      const handle = await cmdServe(ctx, {
        host: opts.host,
        port: opts.port,
        ...(opts.openapiYaml ? { openapiYamlPath: opts.openapiYaml } : {}),
        // commander sets opts.aria2=false when --no-aria2 was passed.
        aria2Host: opts.aria2 === false ? "" : opts.aria2Host,
        aria2Port: opts.aria2Port,
        ...(opts.aria2Secret ? { aria2Secret: opts.aria2Secret } : {}),
        startScheduler: Boolean(opts.scheduler),
        schedulerIntervalMs: opts.schedulerInterval,
        noMdns: opts.mdns === false,
      });
      const trail =
        (handle.scheduler ? "  (scheduler running)" : "") +
        (handle.mdns ? `  (mDNS via ${handle.mdns})` : "");
      process.stdout.write(`ariaflow-server listening at ${handle.url}${trail}\n`);
      const stop = async () => {
        await handle.close();
        process.exit(0);
      };
      process.once("SIGINT", stop);
      process.once("SIGTERM", stop);
    },
  );

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
  .command("cleanup")
  .description("archive stale terminal queue items")
  .option("--max-done-age-days <n>", "age cutoff in days", (v) => Number(v), 7)
  .option("--max-done-count <n>", "max retained complete items", (v) => Number(v), 100)
  .option("--dry-run", "preview the split without persisting")
  .action(
    async (opts: { maxDoneAgeDays: number; maxDoneCount: number; dryRun?: boolean }) => {
      const ctx = makeContext();
      const r = await cmdCleanup(ctx, {
        maxDoneAgeDays: opts.maxDoneAgeDays,
        maxDoneCount: opts.maxDoneCount,
        ...(opts.dryRun ? { dryRun: true } : {}),
      });
      process.stdout.write(r.stdout);
      process.exit(r.exitCode);
    },
  );

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
  .command("doctor")
  .description("pre-flight diagnostics for aria2c, networkQuality, RPC, config dir")
  .option("--pretty", "human-readable layout instead of JSON")
  .option("--aria2-host <h>", "aria2 RPC host", "127.0.0.1")
  .option("--aria2-port <p>", "aria2 RPC port", (v) => Number(v), 6800)
  .option("--aria2-secret <s>", "aria2 RPC secret token")
  .action(
    async (opts: {
      pretty?: boolean;
      aria2Host: string;
      aria2Port: number;
      aria2Secret?: string;
    }) => {
      const ctx = makeContext();
      const r = await cmdDoctor(ctx, {
        ...(opts.pretty ? { pretty: true } : {}),
        aria2Host: opts.aria2Host,
        aria2Port: opts.aria2Port,
        ...(opts.aria2Secret ? { aria2Secret: opts.aria2Secret } : {}),
      });
      process.stdout.write(r.stdout);
      process.exit(r.exitCode);
    },
  );

program
  .command("formula")
  .description("render the Homebrew formula for a release tag")
  .requiredOption("--tag <vX.Y.Z>", "stable release tag")
  .option("--flavor <ts|python>", "which formula to emit", "ts")
  .option("--sha256 <hex>", "precomputed sha256 (skips the network fetch)")
  .option("--output <path>", "write the formula to this path in addition to stdout")
  .action(
    async (opts: { tag: string; flavor: string; sha256?: string; output?: string }) => {
      const flavor = opts.flavor === "python" ? "python" : "ts";
      const r = await cmdFormula({
        tag: opts.tag,
        flavor,
        ...(opts.sha256 ? { sha256: opts.sha256 } : {}),
        ...(opts.output ? { output: opts.output } : {}),
      });
      process.stdout.write(r.stdout);
      process.exit(r.exitCode);
    },
  );

program
  .command("openapi")
  .description("emit the generated OpenAPI 3.0 doc from the live routes")
  .action(async () => {
    const ctx = makeContext();
    const r = await cmdOpenapi(ctx);
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

program
  .command("install-service")
  .description("install the platform-appropriate aria2 service (launchd / systemd)")
  .option("--dry-run", "print the shell plan without executing it")
  .option("--bin-path <path>", "path to aria2c (auto-discovered if omitted)")
  .action(async (opts: { dryRun?: boolean; binPath?: string }) => {
    const r = await cmdInstallService({
      ...(opts.dryRun ? { dryRun: true } : {}),
      ...(opts.binPath ? { binPath: opts.binPath } : {}),
    });
    process.stdout.write(r.stdout);
    process.exit(r.exitCode);
  });

program
  .command("uninstall-service")
  .description("remove the platform aria2 service")
  .option("--dry-run", "print the shell plan without executing it")
  .action(async (opts: { dryRun?: boolean }) => {
    const r = await cmdUninstallService(opts.dryRun ? { dryRun: true } : {});
    process.stdout.write(r.stdout);
    process.exit(r.exitCode);
  });

program.parseAsync(process.argv);
