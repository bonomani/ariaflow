const SERVICE_TYPE = "_ariaflow-server._tcp.";

/**
 * Parse a single line of `dns-sd -B` output.
 *
 * Returns `{ instance, event, isAdd }` or null. Add lines look like:
 *   12:00:00.000  Add        3  4  local.  _ariaflow-server._tcp.  bc's Mac AriaFlow
 *   12:00:01.000  Rmv        0  4  local.  _ariaflow-server._tcp.  bc's Mac AriaFlow
 */
export function parseDnsSdBrowseLine(
  line: string,
): { instance: string; event: "Add" | "Rmv"; isAdd: boolean } | null {
  const parts = line.split(/\s+/);
  if (parts.length < 7) return null;
  const event = parts[1];
  if (event !== "Add" && event !== "Rmv") return null;
  const idx = line.indexOf(SERVICE_TYPE);
  if (idx < 0) return null;
  const instance = line.slice(idx + SERVICE_TYPE.length).trim();
  if (!instance) return null;
  return { instance, event, isAdd: event === "Add" };
}

/**
 * Parse TXT-record fragments out of a raw avahi/dns-sd line.
 * Accepts both quoted (`"path=/api"`) and bare (`path=/api`) tokens.
 */
export function parseTxtRecords(raw: string): Record<string, string> {
  const out: Record<string, string> = {};
  const re = /"?(\w+)=([^"]*)"?/g;
  for (const m of raw.matchAll(re)) {
    out[m[1]!] = m[2]!;
  }
  return out;
}

export interface AvahiAddedPeer {
  instance: string;
  host: string;
  port: number;
  path: string;
  tls: boolean;
  base_url: string;
  last_seen: number;
  status: "discovered";
}

export interface AvahiBrowsedPeer {
  instance: string;
  status: "browsed";
  last_seen: number;
}

export interface AvahiRemovedPeer {
  removed: true;
}

export type AvahiParsedPeer = AvahiAddedPeer | AvahiBrowsedPeer | AvahiRemovedPeer;

/**
 * Parse one line of `avahi-browse -r -p` output (parseable mode).
 *
 * `=` lines carry the resolved host/port + TXT records, `+` lines mean
 * the service was just browsed but not yet resolved, `-` removes a peer.
 */
export function parseAvahiBrowseLine(
  line: string,
  now: () => number = Date.now,
): { instance: string; peer: AvahiParsedPeer } | null {
  if (!line || line.startsWith("Failed")) return null;
  const parts = line.split(";");
  if (parts.length < 6) return null;
  const event = parts[0];
  const instance = parts[3];
  if (!instance) return null;

  if (event === "-") {
    return { instance, peer: { removed: true } };
  }

  if (event === "=") {
    if (parts.length < 9) return null;
    const host = parts[6]!;
    const port = Number(parts[8]);
    if (!Number.isFinite(port)) return null;
    const txtRaw = parts.length > 9 ? parts.slice(9).join(";") : "";
    const txt = parseTxtRecords(txtRaw);
    const tls = txt.tls === "1";
    const path = txt.path ?? "/api";
    const scheme = tls ? "https" : "http";
    return {
      instance,
      peer: {
        instance,
        host,
        port,
        path,
        tls,
        base_url: `${scheme}://${host}:${port}${path}`,
        last_seen: now() / 1000,
        status: "discovered",
      },
    };
  }

  if (event === "+") {
    return {
      instance,
      peer: { instance, status: "browsed", last_seen: now() / 1000 },
    };
  }

  return null;
}
