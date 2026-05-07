import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { resolveDefaultDownloadDir } from "./download_dir.js";

describe("resolveDefaultDownloadDir (BG-58)", () => {
  const origXdg = process.env.XDG_DOWNLOAD_DIR;
  const origHome = process.env.HOME;

  beforeEach(() => {
    delete process.env.XDG_DOWNLOAD_DIR;
  });
  afterEach(() => {
    if (origXdg === undefined) delete process.env.XDG_DOWNLOAD_DIR;
    else process.env.XDG_DOWNLOAD_DIR = origXdg;
    if (origHome === undefined) delete process.env.HOME;
    else process.env.HOME = origHome;
  });

  it("uses $XDG_DOWNLOAD_DIR when set", () => {
    process.env.XDG_DOWNLOAD_DIR = "/foo/bar";
    expect(resolveDefaultDownloadDir()).toBe("/foo/bar");
  });

  it("trims surrounding whitespace from $XDG_DOWNLOAD_DIR", () => {
    process.env.XDG_DOWNLOAD_DIR = "  /foo  ";
    expect(resolveDefaultDownloadDir()).toBe("/foo");
  });

  it("falls back to ~/Downloads when $XDG_DOWNLOAD_DIR is unset", () => {
    process.env.HOME = "/home/u";
    expect(resolveDefaultDownloadDir()).toBe("/home/u/Downloads");
  });

  it("ignores empty $XDG_DOWNLOAD_DIR (treats as unset)", () => {
    process.env.XDG_DOWNLOAD_DIR = "   ";
    process.env.HOME = "/h";
    expect(resolveDefaultDownloadDir()).toBe("/h/Downloads");
  });
});
