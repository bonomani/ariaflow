#!/usr/bin/env node
import { Command } from "commander";
import { cmdAdd, cmdList, cmdRemove, cmdStatus } from "./commands.js";
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

program.command("status").action(async () => {
  const ctx = makeContext();
  const r = await cmdStatus(ctx);
  process.stdout.write(r.stdout);
  process.exit(r.exitCode);
});

program.parseAsync(process.argv);
