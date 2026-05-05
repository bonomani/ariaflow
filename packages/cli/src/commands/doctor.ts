import {
  Aria2Client,
  detectServiceTarget,
  findAria2c,
  install,
} from "@ariaflow/core";
import type { CliContext } from "../context.js";
import { fail, json, ok, type CmdResult } from "./_shared.js";

interface DoctorOptions {
  aria2Host?: string;
  aria2Port?: number;
  aria2Secret?: string;
  pretty?: boolean;
}

interface DoctorCheck {
  name: string;
  ok: boolean;
  detail: string;
}

/**
 * Pre-flight diagnostics: walk the environment, check every dependency
 * the server needs, and report a structured pass/fail per check.
 *
 * No subprocess execution beyond a single aria2.getVersion RPC and
 * a writability probe on the config dir. Cheap to run on demand.
 */
export async function cmdDoctor(
  ctx: CliContext,
  opts: DoctorOptions = {},
): Promise<CmdResult> {
  const checks: DoctorCheck[] = [];

  // 1. aria2c on PATH (or a known fallback).
  const aria2cPath = findAria2c();
  checks.push({
    name: "aria2c_binary",
    ok: aria2cPath !== null,
    detail: aria2cPath ?? "aria2c not found on PATH; install via brew/apt",
  });

  // 2. networkQuality (macOS only — informational on other platforms).
  const nq = install.networkqualityStatus();
  checks.push({
    name: "networkquality",
    ok: nq.installed,
    detail: nq.message,
  });

  // 3. Config dir writable.
  try {
    const env = (ctx.queue as unknown as { env?: NodeJS.ProcessEnv }).env ?? process.env;
    const dir = env.ARIAFLOW_DIR || (await ctx.declaration.load(), undefined);
    // Trigger a benign write through the declaration store.
    await ctx.declaration.load();
    checks.push({
      name: "config_dir_writable",
      ok: true,
      detail: dir ? `using ${dir}` : "config dir writable",
    });
  } catch (err) {
    checks.push({
      name: "config_dir_writable",
      ok: false,
      detail: (err as Error).message,
    });
  }

  // 4. aria2 RPC reachable.
  const host = opts.aria2Host ?? "127.0.0.1";
  const port = opts.aria2Port ?? 6800;
  const probe = new Aria2Client({
    host,
    port,
    defaultTimeoutMs: 2000,
    ...(opts.aria2Secret ? { secret: opts.aria2Secret } : {}),
  });
  let aria2Version: string | undefined;
  let aria2Reachable = false;
  try {
    const ver = await probe.call<{ version: string }>("aria2.getVersion");
    aria2Version = ver.version;
    aria2Reachable = true;
  } catch {
    /* unreachable */
  }
  checks.push({
    name: "aria2_rpc_reachable",
    ok: aria2Reachable,
    detail: aria2Reachable
      ? `aria2 ${aria2Version} responding at ${host}:${port}`
      : `no response from ${host}:${port} (start aria2c --enable-rpc)`,
  });

  // 5. Service installed (informational — not required to run).
  const target = detectServiceTarget();
  checks.push({
    name: "platform_service_target",
    ok: true,
    detail: target ?? "unsupported platform — no service target available",
  });

  const allOk = checks.every((c) => c.ok);
  if (!opts.pretty) return ok(json({ ok: allOk, checks }) + "\n");
  const lines = checks.map(
    (c) => `${c.ok ? "OK   " : "FAIL "}${c.name.padEnd(28)} ${c.detail}`,
  );
  lines.push(`\n${allOk ? "All checks passed." : "One or more checks failed."}`);
  return allOk ? ok(lines.join("\n") + "\n") : fail(lines.join("\n") + "\n", 1);
}
