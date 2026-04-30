import { describe, expect, it } from "vitest";
import {
  ARIA2_LAUNCHD_LABEL,
  ARIA2_SYSTEMD_UNIT,
  buildAria2Plist,
  buildAria2SystemdUnit,
  planLaunchdInstall,
  planLaunchdUninstall,
  planSystemdInstall,
  planSystemdUninstall,
} from "./services.js";

describe("buildAria2Plist", () => {
  it("interpolates the bin path and the canonical label", () => {
    const plist = buildAria2Plist({ binPath: "/usr/local/bin/aria2c" });
    expect(plist).toContain('<string>/usr/local/bin/aria2c</string>');
    expect(plist).toContain(`<string>${ARIA2_LAUNCHD_LABEL}</string>`);
    expect(plist).toContain("<string>--enable-rpc=true</string>");
    expect(plist).toContain("<true/>"); // RunAtLoad / KeepAlive
  });

  it("respects rpcPort override", () => {
    const plist = buildAria2Plist({ binPath: "aria2c", rpcPort: 16800 });
    expect(plist).toContain("<string>--rpc-listen-port=16800</string>");
  });

  it("emits valid XML structure (open + close root)", () => {
    const plist = buildAria2Plist({ binPath: "aria2c" });
    expect(plist).toMatch(/<\?xml version="1.0"/);
    expect(plist.endsWith("</plist>\n")).toBe(true);
  });
});

describe("buildAria2SystemdUnit", () => {
  it("produces a [Unit]/[Service]/[Install] block with the bin path", () => {
    const unit = buildAria2SystemdUnit({ binPath: "/usr/bin/aria2c" });
    expect(unit).toMatch(/^\[Unit\]/);
    expect(unit).toContain("Description=aria2 RPC daemon");
    expect(unit).toContain("ExecStart=/usr/bin/aria2c");
    expect(unit).toContain("--rpc-listen-port=6800");
    expect(unit).toContain("WantedBy=default.target");
    expect(unit).toContain("Restart=on-failure");
  });

  it("respects port + dir overrides", () => {
    const unit = buildAria2SystemdUnit({
      binPath: "aria2c",
      rpcPort: 16800,
      sessionDir: "/tmp/s",
      downloadDir: "/tmp/dl",
    });
    expect(unit).toContain("--rpc-listen-port=16800");
    expect(unit).toContain("--dir=/tmp/dl");
    expect(unit).toContain("--input-file=/tmp/s/session.txt");
  });
});

describe("plan helpers", () => {
  it("planLaunchdInstall produces a 4-step shell plan", () => {
    const plan = planLaunchdInstall("/usr/local/bin/aria2c");
    expect(plan).toHaveLength(4);
    expect(plan[0]!.startsWith("mkdir -p")).toBe(true);
    expect(plan[plan.length - 1]!.includes("launchctl bootstrap")).toBe(true);
    expect(plan.some((s) => s.includes("PLIST"))).toBe(true);
  });

  it("planLaunchdUninstall removes the plist + bootouts the label", () => {
    const plan = planLaunchdUninstall();
    expect(plan.some((s) => s.includes("launchctl bootout"))).toBe(true);
    expect(plan.some((s) => s.includes(ARIA2_LAUNCHD_LABEL))).toBe(true);
    expect(plan.some((s) => s.startsWith("rm -f "))).toBe(true);
  });

  it("planSystemdInstall ends with `enable --now`", () => {
    const plan = planSystemdInstall("aria2c");
    expect(plan.some((s) => s.includes(`enable --now ${ARIA2_SYSTEMD_UNIT}`))).toBe(true);
    expect(plan.some((s) => s.includes("daemon-reload"))).toBe(true);
  });

  it("planSystemdUninstall disables + removes the unit", () => {
    const plan = planSystemdUninstall();
    expect(plan[0]!.includes(`disable --now ${ARIA2_SYSTEMD_UNIT}`)).toBe(true);
    expect(plan.some((s) => s.startsWith("rm -f "))).toBe(true);
  });
});
