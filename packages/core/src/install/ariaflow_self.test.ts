import { mkdtempSync, rmSync, writeFileSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { detectAriaflowInstalledVia } from "./ariaflow_self.js";

let dir: string;

beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), "ariaflow-self-"));
});

afterEach(() => {
  rmSync(dir, { recursive: true, force: true });
});

describe("detectAriaflowInstalledVia", () => {
  it("returns null for an empty path", () => {
    expect(detectAriaflowInstalledVia("")).toBeNull();
  });

  it("returns 'homebrew' under HOMEBREW_PREFIX", () => {
    expect(
      detectAriaflowInstalledVia("/opt/homebrew/Cellar/ariaflow-server/0.1.270/libexec/cli/dist/index.js", {
        HOMEBREW_PREFIX: "/opt/homebrew",
      }),
    ).toBe("homebrew");
  });

  it("returns 'homebrew' on the Cellar fallback even without HOMEBREW_PREFIX", () => {
    expect(
      detectAriaflowInstalledVia("/usr/local/Cellar/ariaflow-server/0.1.0/libexec/cli/dist/index.js", {}),
    ).toBe("homebrew");
  });

  it("returns 'pipx' under ~/.local/pipx/venvs", () => {
    expect(
      detectAriaflowInstalledVia("/home/bob/.local/pipx/venvs/ariaflow-server/bin/index.js"),
    ).toBe("pipx");
  });

  it("returns 'npm' under lib/node_modules", () => {
    expect(
      detectAriaflowInstalledVia("/usr/local/lib/node_modules/@ariaflow/cli/dist/index.js"),
    ).toBe("npm");
  });

  it("returns 'source' when path is inside a git working tree", () => {
    mkdirSync(join(dir, ".git"));
    const script = join(dir, "packages", "cli", "dist", "index.js");
    mkdirSync(join(dir, "packages", "cli", "dist"), { recursive: true });
    writeFileSync(script, "");
    expect(detectAriaflowInstalledVia(script, {})).toBe("source");
  });

  it("returns null for an unknown path", () => {
    expect(detectAriaflowInstalledVia("/random/place/index.js", {})).toBeNull();
  });
});
