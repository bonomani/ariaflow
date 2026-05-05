export interface CmdResult {
  ok: boolean;
  exitCode: number;
  stdout: string;
}

export const ok = (stdout: string): CmdResult => ({ ok: true, exitCode: 0, stdout });
export const fail = (stdout: string, code = 1): CmdResult => ({
  ok: false,
  exitCode: code,
  stdout,
});

export const json = (v: unknown): string => JSON.stringify(v, null, 2);

/**
 * Reject a missing required positional arg with a uniform error
 * message. Returns null on success (caller continues), or a fail
 * CmdResult to return immediately.
 */
export function requireArg(name: string, value: string | undefined): CmdResult | null {
  return value ? null : fail(`error: ${name} is required\n`);
}
