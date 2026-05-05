import {
  downloadSha256,
  installAria2Service,
  renderFormula,
  tarballUrl,
  uninstallAria2Service,
  versionFromTag,
  writeFormula,
} from "@ariaflow/core";
import { fail, json, ok, type CmdResult } from "./_shared.js";

interface FormulaOptions {
  tag: string;
  sha256?: string;
  output?: string;
}

/**
 * Render the Homebrew formula for a release tag. The sha256 is
 * fetched by streaming the GitHub release tarball when not provided;
 * pass --sha256 to skip the network round-trip.
 */
export async function cmdFormula(opts: FormulaOptions): Promise<CmdResult> {
  let version: string;
  try {
    version = versionFromTag(opts.tag);
  } catch (err) {
    return fail(`error: ${(err as Error).message}\n`);
  }
  const url = tarballUrl(opts.tag);
  let sha256 = opts.sha256;
  if (!sha256) {
    try {
      sha256 = await downloadSha256(url);
    } catch (err) {
      return fail(`error: failed to fetch ${url}: ${(err as Error).message}\n`, 1);
    }
  }
  const formula = renderFormula({ version, url, sha256 });
  if (opts.output) {
    await writeFormula(opts.output, formula);
  }
  return ok(formula);
}

interface InstallServiceOpts {
  dryRun?: boolean;
  binPath?: string;
}

export async function cmdInstallService(opts: InstallServiceOpts = {}): Promise<CmdResult> {
  try {
    const r = await installAria2Service({
      ...(opts.dryRun ? { dryRun: true } : {}),
      ...(opts.binPath ? { binPath: opts.binPath } : {}),
    });
    return r.ok ? ok(json(r) + "\n") : fail(json(r) + "\n", 1);
  } catch (err) {
    return fail(`error: ${(err as Error).message}\n`, 1);
  }
}

export async function cmdUninstallService(
  opts: { dryRun?: boolean } = {},
): Promise<CmdResult> {
  try {
    const r = await uninstallAria2Service(opts.dryRun ? { dryRun: true } : {});
    return r.ok ? ok(json(r) + "\n") : fail(json(r) + "\n", 1);
  } catch (err) {
    return fail(`error: ${(err as Error).message}\n`, 1);
  }
}
