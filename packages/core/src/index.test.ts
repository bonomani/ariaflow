import { describe, expect, it } from "vitest";
import { VERSION } from "./index.js";

describe("core", () => {
  it("exposes VERSION", () => {
    expect(typeof VERSION).toBe("string");
  });
});
