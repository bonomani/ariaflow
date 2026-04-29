import { describe, expect, it } from "vitest";
import { validateChangeOptions } from "./options.js";
import { defaultDeclaration } from "../contracts/declaration.js";

describe("validateChangeOptions", () => {
  it("rejects non-object / empty payloads", () => {
    expect(validateChangeOptions(null, defaultDeclaration())).toMatchObject({
      ok: false,
      error: "empty_options",
    });
    expect(validateChangeOptions({}, defaultDeclaration())).toMatchObject({
      ok: false,
      error: "empty_options",
    });
    expect(validateChangeOptions([], defaultDeclaration())).toMatchObject({
      ok: false,
      error: "empty_options",
    });
  });

  it("forbids the managed-set options", () => {
    const r = validateChangeOptions(
      { "max-overall-download-limit": "100000" },
      defaultDeclaration(),
    );
    expect(r).toMatchObject({ ok: false, error: "managed_options" });
  });

  it("rejects unsafe options when aria2_unsafe_options=false", () => {
    const r = validateChangeOptions({ "rpc-secret": "abc" }, defaultDeclaration());
    expect(r).toMatchObject({ ok: false, error: "rejected_options" });
  });

  it("allows safe options through", () => {
    const r = validateChangeOptions(
      { "max-concurrent-downloads": 4 },
      defaultDeclaration(),
    );
    expect(r).toEqual({ ok: true, options: { "max-concurrent-downloads": "4" } });
  });

  it("permits arbitrary options when aria2_unsafe_options=true", () => {
    const decl = defaultDeclaration();
    const pref = decl.uic.preferences.find((p) => p.name === "aria2_unsafe_options")!;
    pref.value = true;
    const r = validateChangeOptions({ "rpc-secret": "abc" }, decl);
    expect(r).toEqual({ ok: true, options: { "rpc-secret": "abc" } });
  });
});
