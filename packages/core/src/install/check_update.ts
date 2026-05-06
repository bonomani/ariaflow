import { spawn } from "node:child_process";

export interface UpdateProbeResult {
  /** True when the package manager has a newer version available. */
  available: boolean;
  /** Currently-installed version per the package manager (null when not parseable). */
  current_version: string | null;
  /** Newest available version per the package manager (null when none / not parseable). */
  latest_version: string | null;
  /** Diagnostic when the probe failed to produce a verdict. */
  message?: string;
}

/**
 * BG-59: probe `brew outdated --json=v2` for a given Homebrew formula.
 * Read-only; never dispatches an upgrade. v2 output shape:
 *   { formulae: [{ name, installed_versions: [...], current_version, ... }] }
 * `current_version` in v2 output means *the new version brew has*, and
 * `installed_versions` is the array currently on disk — surfaced through
 * `current_version` (installed) and `latest_version` (newest brew has).
 *
 * Returns `available: false` on any non-zero exit / parse failure so a
 * missing brew binary doesn't break the caller.
 */
export function brewOutdatedFormula(formula: string): Promise<UpdateProbeResult> {
  return new Promise((resolve) => {
    const proc = spawn("brew", ["outdated", "--json=v2", formula], {
      stdio: ["ignore", "pipe", "ignore"],
    });
    const chunks: Buffer[] = [];
    proc.stdout?.on("data", (c: Buffer) => chunks.push(c));
    proc.on("error", () =>
      resolve({
        available: false,
        current_version: null,
        latest_version: null,
        message: "brew not on PATH",
      }),
    );
    proc.on("close", () => {
      try {
        const raw = Buffer.concat(chunks).toString("utf8");
        const parsed = JSON.parse(raw) as {
          formulae?: Array<{
            current_version?: string;
            installed_versions?: string[];
          }>;
        };
        const row = parsed.formulae?.[0];
        if (!row) {
          resolve({ available: false, current_version: null, latest_version: null });
          return;
        }
        const installed = row.installed_versions?.[0] ?? null;
        const latest = row.current_version ?? null;
        resolve({
          available: true,
          current_version: installed,
          latest_version: latest,
        });
      } catch {
        resolve({
          available: false,
          current_version: null,
          latest_version: null,
          message: "unparseable brew output",
        });
      }
    });
  });
}
