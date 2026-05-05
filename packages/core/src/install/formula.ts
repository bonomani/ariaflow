import { createHash } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import { dirname } from "node:path";

const TAG_RE = /^v(\d+\.\d+\.\d+)$/;

/**
 * Extract the X.Y.Z version from a stable release tag (vX.Y.Z).
 * Throws on any other shape (release candidates, dev tags, etc.) so the
 * caller surfaces a clear error rather than rendering a garbled formula.
 */
export function versionFromTag(tag: string): string {
  const m = TAG_RE.exec(tag);
  if (!m) throw new Error(`Expected stable tag in the form vX.Y.Z, got: ${JSON.stringify(tag)}`);
  return m[1]!;
}

/** Canonical GitHub source tarball URL for a release tag. */
export function tarballUrl(tag: string): string {
  return `https://github.com/bonomani/ariaflow-server/archive/refs/tags/${tag}.tar.gz`;
}

/**
 * Stream `url` and return its sha256 hex digest. Pure HTTP / hashing —
 * no fs writes; uses the global fetch from Node 20+.
 */
export async function downloadSha256(
  url: string,
  fetchImpl: typeof fetch = globalThis.fetch,
): Promise<string> {
  const res = await fetchImpl(url);
  if (!res.ok || !res.body) throw new Error(`failed to fetch ${url}: ${res.status}`);
  const hasher = createHash("sha256");
  const reader = res.body.getReader();
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    if (value) hasher.update(value);
  }
  return hasher.digest("hex");
}

interface RenderFormulaInput {
  version: string;
  url: string;
  sha256: string;
}

/**
 * Render the Homebrew formula for ariaflow-server. Depends on
 * Node + aria2, builds the workspace via Corepack-pinned pnpm,
 * flattens @ariaflow/cli into libexec, then writes thin bin shims
 * for both `ariaflow` (canonical) and `ariaflow-server` (back-compat
 * with users who scripted against the legacy binary name).
 *
 * The brew service stanza launches `ariaflow serve --scheduler` on
 * 127.0.0.1:8000 so the user gets a working downloader once aria2 is
 * also installed. /api/openapi.yaml is generated at request time from
 * the live route schemas (R-J), so no doc file is vendored.
 */
export function renderFormula({ version, url, sha256 }: RenderFormulaInput): string {
  return `class AriaflowServer < Formula
  desc "Sequential aria2 queue driver with adaptive bandwidth control"
  homepage "https://github.com/bonomani/ariaflow-server"
  url "${url}"
  sha256 "${sha256}"
  version "${version}"
  license "MIT"
  depends_on "node"
  depends_on "aria2"
  depends_on "pnpm" => :build
  head "https://github.com/bonomani/ariaflow-server.git", branch: "main"

  def install
    # Stamp the formula version into the CLI package.json so
    # \`ariaflow --version\` and /api/version report the real release.
    # The git source tarball ships 0.0.0; only release-npm.yml's
    # publish path patches this normally.
    inreplace "packages/cli/package.json", /"version": "[^"]*"/,
              "\\"version\\": \\"#{version}\\""

    system "pnpm", "install", "--frozen-lockfile=false"
    system "pnpm", "build"
    system "pnpm", "--filter", "@ariaflow/cli", "deploy", "--prod",
           "#{libexec}/cli"

    # Hardcode the node + script paths via Ruby interpolation —
    # launchd doesn't set HOMEBREW_PREFIX, so $-expansion at shell
    # time would fail (exit 126: command not executable).
    (bin/"ariaflow").write <<~EOS
      #!/bin/bash
      exec "#{Formula["node"].opt_bin}/node" "#{libexec}/cli/dist/index.js" "$@"
    EOS
    chmod 0755, bin/"ariaflow"

    # Back-compat shim: pre-TS users scripted against \`ariaflow-server\`.
    (bin/"ariaflow-server").write <<~EOS
      #!/bin/bash
      exec "#{opt_bin}/ariaflow" "$@"
    EOS
    chmod 0755, bin/"ariaflow-server"
  end

  service do
    run [
      opt_bin/"ariaflow", "serve",
      "--host", "127.0.0.1",
      "--port", "8000",
      "--scheduler"
    ]
    keep_alive true
    working_dir var
    log_path var/"log/ariaflow-server.log"
    error_log_path var/"log/ariaflow-server.err.log"
  end

  test do
    assert_match "ariaflow", shell_output("#{bin}/ariaflow --version")
    system bin/"ariaflow", "doctor", "--pretty"
  end
end
`;
}

/** Write the rendered formula to disk, creating parent dirs as needed. */
export async function writeFormula(path: string, content: string): Promise<void> {
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path, content, "utf8");
}
