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
