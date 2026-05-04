interface Aria2RpcResponse<T = unknown> {
  jsonrpc: "2.0";
  id: string;
  result?: T;
  error?: { code: number; message: string };
}

export class Aria2RpcError extends Error {
  constructor(
    message: string,
    public readonly code?: number,
  ) {
    super(message);
    this.name = "Aria2RpcError";
  }
}

export interface Aria2ClientOptions {
  port?: number;
  host?: string;
  defaultTimeoutMs?: number;
  /** Override fetch (for tests). Defaults to globalThis.fetch. */
  fetch?: typeof fetch;
  /** RPC `id` field; defaults to "ariaflow-server". */
  rpcId?: string;
  /** Optional aria2 RPC secret token (passed as `token:<secret>` first param). */
  secret?: string;
}

/**
 * Minimal aria2 JSON-RPC client. Transport-only — high-level wrappers
 * (addUri, tellStatus, etc.) live alongside this class.
 */
export class Aria2Client {
  readonly port: number;
  readonly host: string;
  readonly defaultTimeoutMs: number;
  private readonly fetchImpl: typeof fetch;
  private readonly rpcId: string;
  private readonly secret: string | undefined;

  constructor(opts: Aria2ClientOptions = {}) {
    this.port = opts.port ?? 6800;
    this.host = opts.host ?? "127.0.0.1";
    this.defaultTimeoutMs = opts.defaultTimeoutMs ?? 15_000;
    this.fetchImpl = opts.fetch ?? globalThis.fetch;
    this.rpcId = opts.rpcId ?? "ariaflow-server";
    this.secret = opts.secret;
  }

  get endpoint(): string {
    return `http://${this.host}:${this.port}/jsonrpc`;
  }

  async call<T = unknown>(
    method: string,
    params: unknown[] = [],
    opts: { timeoutMs?: number } = {},
  ): Promise<T> {
    const finalParams = this.secret ? [`token:${this.secret}`, ...params] : params;
    const payload = { jsonrpc: "2.0", id: this.rpcId, method, params: finalParams };

    const ctrl = new AbortController();
    const timeoutMs = opts.timeoutMs ?? this.defaultTimeoutMs;
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    let res: Response;
    try {
      res = await this.fetchImpl(this.endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: ctrl.signal,
      });
    } finally {
      clearTimeout(timer);
    }

    let data: Aria2RpcResponse<T>;
    try {
      data = (await res.json()) as Aria2RpcResponse<T>;
    } catch (e) {
      throw new Aria2RpcError(`aria2 RPC: invalid JSON response (${(e as Error).message})`);
    }

    if (!data || typeof data !== "object" || Array.isArray(data)) {
      throw new Aria2RpcError("aria2 RPC returned non-object");
    }
    if (data.error) {
      throw new Aria2RpcError(
        `aria2 RPC error ${data.error.code}: ${data.error.message}`,
        data.error.code,
      );
    }
    if (!("result" in data)) {
      throw new Aria2RpcError("aria2 RPC response missing 'result'");
    }
    return data.result as T;
  }
}
