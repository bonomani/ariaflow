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

export interface RenderFormulaInput {
  version: string;
  url: string;
  sha256: string;
}

/**
 * Render the Homebrew formula text for ariaflow-server. Mirrors
 * scripts/homebrew_formula.py::render_formula byte-for-byte (modulo
 * whitespace normalization) so the generated output is interchangeable.
 */
export function renderFormula({ version, url, sha256 }: RenderFormulaInput): string {
  return `class AriaflowServer < Formula
  desc "Sequential aria2 queue driver with adaptive bandwidth control"
  homepage "https://github.com/bonomani/ariaflow-server"
  url "${url}"
  sha256 "${sha256}"
  version "${version}"
  license "MIT"
  depends_on "python"
  depends_on "aria2"
  head "https://github.com/bonomani/ariaflow-server.git", branch: "main"

  resource "portalocker" do
    url "https://files.pythonhosted.org/packages/source/p/portalocker/portalocker-3.2.0.tar.gz"
    sha256 "1f3002956a54a8c3730586c5c77bf18fae4149e07eaf1c29fc3faf4d5a3f89ac"
  end

  def install
    python3 = "python3"
    venv = libexec/"venv"
    system python3, "-m", "venv", venv
    venv_pip = venv/"bin/pip"
    resource("portalocker").stage { system venv_pip, "install", "." }

    libexec.install "src"

    (bin/"ariaflow-server").write <<~EOS
      #!/bin/bash
      VENV="#{libexec}/venv"
      SITE=$(find "$VENV/lib" -maxdepth 1 -name 'python3.*' -print -quit)/site-packages
      exec env PYTHONPATH="#{libexec}/src:$SITE:\${PYTHONPATH}" "$VENV/bin/python3" -m ariaflow_server "$@"
    EOS
    chmod 0755, bin/"ariaflow-server"
  end

  service do
    run [opt_bin/"ariaflow-server", "serve", "--host", "127.0.0.1", "--port", "8000"]
    keep_alive true
    working_dir var
    log_path var/"log/ariaflow-server.log"
    error_log_path var/"log/ariaflow-server.err.log"
  end

  test do
    system bin/"ariaflow-server", "--help"
  end
end
`;
}

/** Write the rendered formula to disk, creating parent dirs as needed. */
export async function writeFormula(path: string, content: string): Promise<void> {
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path, content, "utf8");
}
