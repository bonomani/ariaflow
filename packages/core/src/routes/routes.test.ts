import { describe, expect, it } from "vitest";
import {
  errorPayload,
  isValidBase64,
  validateItemId,
  validateOutputPath,
  validateUrl,
} from "./helpers.js";
import { parseAddItems } from "./parse-add.js";

describe("errorPayload", () => {
  it("emits the canonical {ok:false, error, message} shape with details", () => {
    expect(errorPayload("e", "m", { index: 2 })).toEqual({
      ok: false,
      error: "e",
      message: "m",
      index: 2,
    });
  });
});

describe("validateItemId", () => {
  it("accepts a v4-shaped UUID", () => {
    expect(validateItemId("12345678-1234-1234-1234-123456789abc")).toBe(true);
  });
  it("rejects malformed UUIDs", () => {
    expect(validateItemId("not-a-uuid")).toBe(false);
    expect(validateItemId("")).toBe(false);
  });
});

describe("validateUrl", () => {
  it.each([
    ["http://h/x", null],
    ["https://h/x", null],
    ["ftp://h/x", null],
    ["sftp://h/x", null],
    ["magnet:?xt=urn:btih:abc", null],
    ["file:///etc/passwd", "URL scheme 'file' not allowed (use http, https, ftp, sftp, or magnet)"],
  ])("validates %s", (url, expected) => {
    expect(validateUrl(url)).toBe(expected);
  });

  it("flags malformed URLs", () => {
    expect(validateUrl("::::")).toBe("malformed URL");
  });

});

describe("validateOutputPath", () => {
  const cwd = "/work";
  const opts = {
    cwd,
    isAbsolute: (p: string) => p.startsWith("/"),
    splitParts: (p: string) => p.split("/").filter(Boolean),
    resolve: (c: string, p: string) => `${c}/${p}`.replace(/\/+/g, "/"),
  };

  it("accepts safe relative paths", () => {
    expect(validateOutputPath("dl/file.iso", opts)).toBeNull();
    expect(validateOutputPath("", opts)).toBeNull();
  });
  it("rejects absolute paths", () => {
    expect(validateOutputPath("/abs/path", opts)).toBe(
      "output must be a relative path, not absolute",
    );
  });
  it("rejects '..' traversal", () => {
    expect(validateOutputPath("a/../b", opts)).toBe("output must not contain '..'");
  });
  it("rejects hidden directories", () => {
    expect(validateOutputPath(".hidden/x", opts)).toBe(
      "output must not contain hidden directories or files",
    );
  });
  it("rejects paths that escape cwd via the resolver", () => {
    expect(
      validateOutputPath("ok/file", {
        ...opts,
        resolve: () => "/elsewhere/ok/file",
      }),
    ).toBe("output path escapes current directory");
  });
});

describe("isValidBase64", () => {
  it.each([
    ["", false],
    ["abc", false], // length not %4
    ["abcd", true],
    ["YWJj", true], // "abc"
    ["YWJj==", false], // bad padding for length 6
    ["!!!=", false],
  ])("isValidBase64(%j) -> %s", (input, expected) => {
    expect(isValidBase64(input)).toBe(expected);
  });
});

describe("parseAddItems", () => {
  it("rejects non-object payloads", () => {
    const r = parseAddItems(null);
    expect("error" in r && r.error.error).toBe("invalid_payload");
  });

  it("rejects empty / non-list items", () => {
    const r = parseAddItems({ items: [] });
    expect("error" in r && r.error.error).toBe("invalid_items");
  });

  it("rejects an item missing a url", () => {
    const r = parseAddItems({ items: [{}] });
    expect("error" in r && r.error.error).toBe("invalid_item");
    expect("error" in r && r.error.index).toBe(0);
  });

  it("rejects bad URL schemes", () => {
    const r = parseAddItems({ items: [{ url: "file:///etc/passwd" }] });
    expect("error" in r && r.error.error).toBe("invalid_url");
  });

  it("normalizes a typical item", () => {
    const r = parseAddItems({
      items: [
        {
          url: " http://h/file.iso ",
          output: " out/file.iso ",
          mirrors: ["http://h/file.iso", " http://b/file.iso "],
          priority: "5",
          distribute: true,
        },
      ],
    });
    expect("items" in r).toBe(true);
    if (!("items" in r)) return;
    expect(r.items[0]).toMatchObject({
      url: "http://h/file.iso",
      output: "out/file.iso",
      mirrors: ["http://h/file.iso", "http://b/file.iso"],
      priority: 5,
      distribute: true,
    });
  });

  it("rejects invalid base64 in torrent_data", () => {
    const r = parseAddItems({
      items: [{ url: "http://h/file", torrent_data: "!!!" }],
    });
    expect("error" in r && r.error.error).toBe("invalid_torrent_data");
  });
});
