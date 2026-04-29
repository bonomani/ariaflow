import { describe, expect, it } from "vitest";
import { bencode, computePieceSize } from "./bencode.js";

const dec = new TextDecoder();
const s = (u: Uint8Array) => dec.decode(u);

describe("bencode", () => {
  it("encodes integers", () => {
    expect(s(bencode(0))).toBe("i0e");
    expect(s(bencode(42))).toBe("i42e");
    expect(s(bencode(-7))).toBe("i-7e");
  });

  it("encodes strings as length-prefixed UTF-8", () => {
    expect(s(bencode("spam"))).toBe("4:spam");
    expect(s(bencode(""))).toBe("0:");
  });

  it("encodes lists", () => {
    expect(s(bencode([1, "a"]))).toBe("li1e1:ae");
  });

  it("encodes dicts with sorted keys", () => {
    expect(s(bencode({ b: 2, a: 1 }))).toBe("d1:ai1e1:bi2ee");
  });

  it("encodes raw bytes by length", () => {
    expect(s(bencode(new Uint8Array([0x61, 0x62, 0x63])))).toBe("3:abc");
  });
});

describe("computePieceSize", () => {
  it("returns 256KB for empty/zero size", () => {
    expect(computePieceSize(0)).toBe(256 * 1024);
    expect(computePieceSize(-1)).toBe(256 * 1024);
  });

  it("clamps to min 256KB for small files", () => {
    expect(computePieceSize(1000)).toBe(1 << 18);
  });

  it("clamps to max 16MB for huge files", () => {
    expect(computePieceSize(1024 ** 4)).toBe(1 << 24);
  });

  it("returns a power of two", () => {
    for (const size of [1e6, 1e8, 1e9, 5e9]) {
      const ps = computePieceSize(size);
      expect((ps & (ps - 1)) === 0).toBe(true);
    }
  });
});
