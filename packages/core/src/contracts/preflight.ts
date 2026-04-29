import type { Declaration, UicGate, UicPreference } from "./declaration.js";

export interface GateSignals {
  aria2_available: boolean;
  queue_readable: boolean;
  paused?: boolean;
}

export interface GateResult {
  name: string;
  satisfied: boolean;
  blocking: string;
  class: string;
}

export interface PreflightResult {
  contract: string;
  version: string;
  gates: GateResult[];
  preferences: UicPreference[];
  policies: unknown[];
  warnings: { name: string; message: string }[];
  hard_failures: string[];
  status: "pass" | "fail";
  exit_code: 0 | 1;
}

/**
 * Pure preflight evaluator. Caller resolves environmental signals
 * (aria2 availability, queue readability, paused state) and passes them in.
 */
export function evaluatePreflight(
  declaration: Declaration,
  signals: GateSignals,
): PreflightResult {
  const gates: GateResult[] = [];
  const failures: string[] = [];
  const warnings: { name: string; message: string }[] = [];

  for (const gate of declaration.uic?.gates ?? []) {
    const satisfied = resolveGate(gate, signals, warnings);
    gates.push({
      name: gate.name,
      satisfied,
      blocking: gate.blocking ?? "hard",
      class: gate.class ?? "readiness",
    });
    if (!satisfied && (gate.blocking ?? "hard") === "hard") failures.push(gate.name);
  }

  return {
    contract: declaration.meta?.contract ?? "UCC",
    version: declaration.meta?.version ?? "2.0",
    gates,
    preferences: declaration.uic?.preferences ?? [],
    policies: declaration.uic?.policies ?? [],
    warnings,
    hard_failures: failures,
    status: failures.length === 0 ? "pass" : "fail",
    exit_code: failures.length === 0 ? 0 : 1,
  };
}

function resolveGate(
  gate: UicGate,
  signals: GateSignals,
  warnings: { name: string; message: string }[],
): boolean {
  switch (gate.name) {
    case "aria2_available":
      return signals.aria2_available;
    case "queue_readable":
      return signals.queue_readable;
    case "paused": {
      const ok = !signals.paused;
      if (!ok) warnings.push({ name: gate.name, message: "queue is paused" });
      return ok;
    }
    default:
      return true;
  }
}

export interface UCCResult {
  observation: string;
  outcome: string;
  completion?: string | null;
  failure_class?: string | null;
  inhibitor?: string | null;
  partial?: boolean | null;
  message?: string;
  reason?: string;
  observed_before?: Record<string, unknown> | null;
  observed_after?: Record<string, unknown> | null;
  diff?: Record<string, unknown> | null;
}

/**
 * Strip null/empty fields from a UCCResult, mirroring the Python
 * `UCCResult.to_dict()` cleanup.
 */
export function uccResultToDict(r: UCCResult): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(r)) {
    if (v === null || v === undefined) continue;
    if (v === "") continue;
    out[k] = v;
  }
  return out;
}
