import { fail, ok, type CmdResult } from "./_shared.js";

interface WatchOptions {
  url: string;
  /** Maximum events to receive before resolving; default unlimited. */
  limit?: number;
  /** Abort signal for the consumer (e.g. SIGINT handler). */
  signal?: AbortSignal;
  /** Where to write each line; defaults to process.stdout. */
  out?: { write(s: string): boolean | void };
}

/**
 * Subscribe to an SSE stream at `url` and write one JSON line per event:
 *   {"event": "action_logged", "data": {...}}
 *
 * Streams the response body via fetch + ReadableStream and parses
 * SSE-framed `event:`/`data:` blocks separated by blank lines. This
 * avoids depending on globalThis.EventSource (only stable in Node 22+
 * and not enabled by default everywhere).
 *
 * Resolves when `limit` is reached, when the server closes the body,
 * or when `signal` fires. Returns a fail result on connect error.
 */
export async function cmdWatch(opts: WatchOptions): Promise<CmdResult> {
  const out = opts.out ?? process.stdout;
  const limit = opts.limit ?? Number.POSITIVE_INFINITY;
  let res: Response;
  try {
    res = await fetch(opts.url, {
      headers: { Accept: "text/event-stream" },
      ...(opts.signal ? { signal: opts.signal } : {}),
    });
  } catch (err) {
    return fail(`error: failed to connect to ${opts.url}: ${(err as Error).message}\n`);
  }
  if (!res.ok || !res.body) {
    return fail(`error: failed to connect to ${opts.url}: HTTP ${res.status}\n`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let received = 0;
  let event = "message";
  const dataLines: string[] = [];

  const emit = (): void => {
    if (dataLines.length === 0) return;
    const raw = dataLines.join("\n");
    let parsed: unknown = raw;
    try {
      parsed = JSON.parse(raw);
    } catch {
      /* leave raw */
    }
    out.write(JSON.stringify({ event, data: parsed }) + "\n");
    received += 1;
    event = "message";
    dataLines.length = 0;
  };

  try {
    while (received < limit) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let nl: number;
      while ((nl = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, nl).replace(/\r$/, "");
        buffer = buffer.slice(nl + 1);
        if (line === "") {
          emit();
          if (received >= limit) break;
        } else if (line.startsWith(":")) {
          /* heartbeat / comment — ignore */
        } else if (line.startsWith("event:")) {
          event = line.slice(6).trim();
        } else if (line.startsWith("data:")) {
          dataLines.push(line.slice(5).replace(/^ /, ""));
        }
      }
    }
  } finally {
    try {
      await reader.cancel();
    } catch {
      /* ignore */
    }
  }
  return ok("");
}
