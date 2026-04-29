export interface UccEnvelopeInput {
  target: string;
  observed: boolean;
  outcome: string;
  completion?: string | null;
  reason?: string;
  detail?: string | null;
  commands?: string[] | null;
}

export interface UccResult {
  observation: "ok" | "failed";
  outcome: string;
  reason: string;
  target: string;
  completion?: string;
  message?: string;
  commands?: string[];
}

export interface UccEnvelope {
  meta: { contract: "UCC"; version: "2.0"; target: string };
  result: UccResult;
}

/**
 * Build the canonical UCC v2.0 response envelope.
 * Mirrors src/ariaflow_server/ucc.py::ucc_envelope.
 */
export function uccEnvelope(input: UccEnvelopeInput): UccEnvelope {
  const result: UccResult = {
    observation: input.observed ? "ok" : "failed",
    outcome: input.outcome,
    reason: input.reason ?? "aggregate",
    target: input.target,
  };
  if (input.completion !== undefined && input.completion !== null) {
    result.completion = input.completion;
  }
  if (input.detail !== undefined && input.detail !== null) {
    result.message = input.detail;
  }
  if (input.commands !== undefined && input.commands !== null) {
    result.commands = input.commands;
  }
  return {
    meta: { contract: "UCC", version: "2.0", target: input.target },
    result,
  };
}

/** Alias preserved for parity with the Python module. */
export const uccRecord = uccEnvelope;
