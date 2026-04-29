/**
 * Convert a fnmatch-style glob (`*`, `?`, `[abc]`) into a RegExp.
 * Matches Python's fnmatch.fnmatch semantics for our use cases.
 */
function fnmatchToRegExp(pattern: string): RegExp {
  let re = "^";
  for (let i = 0; i < pattern.length; i++) {
    const c = pattern[i]!;
    if (c === "*") re += ".*";
    else if (c === "?") re += ".";
    else if (c === "[") {
      const end = pattern.indexOf("]", i + 1);
      if (end < 0) {
        re += "\\[";
      } else {
        re += "[" + pattern.slice(i + 1, end) + "]";
        i = end;
      }
    } else if (/[.+^$(){}|\\]/.test(c)) {
      re += "\\" + c;
    } else {
      re += c;
    }
  }
  return new RegExp(re + "$");
}

/**
 * Match a peer torrent against the configured `peer_content_filter` glob.
 * Empty pattern -> always matches. The torrent's `name` is preferred,
 * falling back to its `url`.
 */
export function matchesContentFilter(
  torrent: { name?: string; url?: string },
  pattern: string,
): boolean {
  if (!pattern) return true;
  const subject = torrent.name || torrent.url || "";
  return fnmatchToRegExp(pattern).test(subject);
}

/**
 * Apply the `peer_allowlist` setting (comma-separated instance names).
 * Empty allowlist -> all peers permitted.
 */
export function matchesAllowlist(
  peer: { instance?: string },
  allowlist: string,
): boolean {
  if (!allowlist) return true;
  const allowed = new Set(
    allowlist
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean),
  );
  return allowed.has(peer.instance ?? "");
}
