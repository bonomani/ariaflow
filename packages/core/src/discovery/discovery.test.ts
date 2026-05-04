import { describe, expect, it } from "vitest";
import {
  parseAvahiBrowseLine,
  parseDnsSdBrowseLine,
  parseTxtRecords,
} from "./parse.js";
import { matchesAllowlist, matchesContentFilter } from "./filter.js";

describe("parseDnsSdBrowseLine", () => {
  it("parses an Add line", () => {
    const r = parseDnsSdBrowseLine(
      "12:00:00.000  Add        3  4  local.  _ariaflow-server._tcp.  bc-mac",
    );
    expect(r).toEqual({ instance: "bc-mac", event: "Add", isAdd: true });
  });

  it("parses a Rmv line", () => {
    const r = parseDnsSdBrowseLine(
      "12:00:01.000  Rmv        0  4  local.  _ariaflow-server._tcp.  bc-mac",
    );
    expect(r).toEqual({ instance: "bc-mac", event: "Rmv", isAdd: false });
  });

  it("returns null for unrelated lines", () => {
    expect(parseDnsSdBrowseLine("Browsing for _ariaflow-server._tcp")).toBeNull();
    expect(parseDnsSdBrowseLine("")).toBeNull();
  });

  it("handles instance names with spaces", () => {
    const r = parseDnsSdBrowseLine(
      "12:00:00.000  Add        3  4  local.  _ariaflow-server._tcp.  bc's Mac mini AriaFlow",
    );
    expect(r?.instance).toBe("bc's Mac mini AriaFlow");
  });
});

describe("parseTxtRecords", () => {
  it("parses quoted records (the format used by avahi/dns-sd output)", () => {
    expect(parseTxtRecords('"path=/api" "tls=0"')).toEqual({ path: "/api", tls: "0" });
  });
  it("greedily consumes everything after = on bare input", () => {
    // The pattern "[^"]*" greedily eats spaces, so a bare unquoted run
    // collapses into a single value.
    expect(parseTxtRecords("path=/api tls=0")).toEqual({ path: "/api tls=0" });
  });
  it("returns {} for empty input", () => {
    expect(parseTxtRecords("")).toEqual({});
  });
});

describe("parseAvahiBrowseLine", () => {
  const now = () => 1_700_000_000_000;

  it("resolves '=' lines into a discovered peer", () => {
    const out = parseAvahiBrowseLine(
      '=;eth0;IPv4;bc-mac;_ariaflow-server._tcp;local;bc-mac.local;192.168.1.10;8080;"path=/api" "tls=0"',
      now,
    );
    expect(out).toEqual({
      instance: "bc-mac",
      peer: {
        instance: "bc-mac",
        host: "bc-mac.local",
        port: 8080,
        path: "/api",
        tls: false,
        base_url: "http://bc-mac.local:8080/api",
        last_seen: 1_700_000_000,
        status: "discovered",
      },
    });
  });

  it("uses https when tls=1", () => {
    const out = parseAvahiBrowseLine(
      '=;eth0;IPv4;p;_ariaflow-server._tcp;local;h;1.2.3.4;443;"path=/api" "tls=1"',
      now,
    );
    expect((out!.peer as { base_url: string }).base_url).toBe("https://h:443/api");
  });

  it("'+' lines mark a peer as browsed but unresolved", () => {
    const out = parseAvahiBrowseLine(
      "+;eth0;IPv4;bc-mac;_ariaflow-server._tcp;local",
      now,
    );
    expect(out!.peer).toEqual({
      instance: "bc-mac",
      status: "browsed",
      last_seen: 1_700_000_000,
    });
  });

  it("'-' lines mark a peer as removed", () => {
    const out = parseAvahiBrowseLine("-;eth0;IPv4;bc-mac;_ariaflow-server._tcp;local");
    expect(out).toEqual({ instance: "bc-mac", peer: { removed: true } });
  });

  it("returns null on Failed/empty/short", () => {
    expect(parseAvahiBrowseLine("Failed to resolve")).toBeNull();
    expect(parseAvahiBrowseLine("")).toBeNull();
    expect(parseAvahiBrowseLine("=;foo")).toBeNull();
  });

  it("returns null when port is not numeric", () => {
    expect(
      parseAvahiBrowseLine(
        "=;eth0;IPv4;p;_ariaflow-server._tcp;local;h;1.2.3.4;notaport;",
      ),
    ).toBeNull();
  });
});

describe("matchesContentFilter", () => {
  it("matches on torrent.name first", () => {
    expect(matchesContentFilter({ name: "ubuntu.iso" }, "ubuntu*")).toBe(true);
    expect(matchesContentFilter({ name: "windows.iso" }, "ubuntu*")).toBe(false);
  });
  it("falls back to url when name is missing", () => {
    expect(matchesContentFilter({ url: "http://h/release.zip" }, "*release*")).toBe(true);
  });
  it("empty pattern accepts everything", () => {
    expect(matchesContentFilter({ name: "anything" }, "")).toBe(true);
  });
  it("supports `?` and character classes", () => {
    expect(matchesContentFilter({ name: "v1.iso" }, "v?.iso")).toBe(true);
    expect(matchesContentFilter({ name: "vA.iso" }, "v[0-9].iso")).toBe(false);
  });
});

describe("matchesAllowlist", () => {
  it("empty allowlist allows all", () => {
    expect(matchesAllowlist({ instance: "x" }, "")).toBe(true);
  });
  it("trims whitespace and matches by exact instance name", () => {
    expect(matchesAllowlist({ instance: "bc-mac" }, "bc-mac, other")).toBe(true);
    expect(matchesAllowlist({ instance: "stranger" }, "bc-mac, other")).toBe(false);
  });
  it("ignores empty entries", () => {
    expect(matchesAllowlist({ instance: "x" }, ", , ,")).toBe(false);
  });
});
