import { existsSync, readFileSync } from "node:fs";
import { platform as osPlatform } from "node:os";

export const isMacOS = (): boolean => osPlatform() === "darwin";
export const isWindows = (): boolean => osPlatform() === "win32";
export const isLinux = (): boolean => osPlatform() === "linux";

/** Detect WSL1/WSL2 by sniffing /proc/version for "microsoft". */
export function isWSL(): boolean {
  if (!isLinux()) return false;
  try {
    if (!existsSync("/proc/version")) return false;
    return readFileSync("/proc/version", "utf8").toLowerCase().includes("microsoft");
  } catch {
    return false;
  }
}
