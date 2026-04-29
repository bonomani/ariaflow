export const ALLOWED_URL_SCHEMES = new Set(["http", "https", "ftp", "magnet"]);

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

/** Build the canonical {ok:false, error, message, ...detail} payload. */
export function errorPayload(
  error: string,
  message: string,
  detail: Record<string, unknown> = {},
): Record<string, unknown> {
  return { ok: false, error, message, ...detail };
}

/** Loose UUID v4 shape check; mirrors routes._validate_item_id. */
export function validateItemId(itemId: string): boolean {
  return UUID_RE.test(itemId);
}

/**
 * Reject unsafe download URLs. Returns null on accept, or a human
 * message describing the problem. Mirrors downloads._validate_url.
 */
export function validateUrl(url: string): string | null {
  if (url.startsWith("magnet:")) return null;
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return "malformed URL";
  }
  // URL parses `http:foo` with empty hostname; surface that as "no scheme"
  // for parity with Python's urlparse — but Python urlparse extracts
  // "http" as scheme. Keep the scheme path consistent and only trip the
  // "must include scheme" branch when truly empty.
  const scheme = parsed.protocol.replace(/:$/, "").toLowerCase();
  if (!scheme) {
    return "URL must include a scheme (http://, https://, ftp://, magnet:)";
  }
  if (!ALLOWED_URL_SCHEMES.has(scheme)) {
    return `URL scheme '${scheme}' not allowed (use http, https, ftp, or magnet)`;
  }
  if ((scheme === "http" || scheme === "https" || scheme === "ftp") && !parsed.hostname) {
    return "URL must include a hostname";
  }
  return null;
}

/**
 * Reject unsafe output paths: must be relative, free of `..` and hidden
 * directories, and confined to the resolved cwd. Mirrors
 * downloads._validate_output_path.
 *
 * Caller injects the resolution helpers so this stays pure (and so tests
 * can pin a fixed cwd / Path resolver).
 */
export function validateOutputPath(
  output: string,
  opts: {
    cwd: string;
    isAbsolute: (p: string) => boolean;
    splitParts: (p: string) => string[];
    resolve: (cwd: string, p: string) => string;
  },
): string | null {
  if (!output) return null;
  if (opts.isAbsolute(output)) return "output must be a relative path, not absolute";
  const parts = opts.splitParts(output);
  if (parts.includes("..")) return "output must not contain '..'";
  if (parts.some((p) => p.startsWith("."))) {
    return "output must not contain hidden directories or files";
  }
  const resolved = opts.resolve(opts.cwd, output);
  if (!resolved.startsWith(opts.cwd)) return "output path escapes current directory";
  return null;
}

const BASE64_RE = /^[A-Za-z0-9+/]+={0,2}$/;

/**
 * Strict base64 validator (RFC 4648 alphabet, 1-2 trailing `=`, length %4).
 * Mirrors `base64.b64decode(s, validate=True)` — empty strings reject.
 */
export function isValidBase64(value: string): boolean {
  if (!value) return false;
  if (value.length % 4 !== 0) return false;
  return BASE64_RE.test(value);
}
