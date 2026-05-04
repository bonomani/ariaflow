/**
 * Pure command builders for Homebrew install/uninstall flows. Dry-run
 * side only: the shell-out is left to a service layer to keep this
 * package side-effect free.
 */
export function homebrewInstallCommands(): string[][] {
  return [
    ["brew", "tap", "bonomani/ariaflow-server"],
    ["brew", "install", "ariaflow-server"],
  ];
}

export function homebrewUninstallCommands(): string[][] {
  return [["brew", "uninstall", "ariaflow-server"]];
}

export const formatCommands = (cmds: string[][]): string[] =>
  cmds.map((c) => c.join(" "));
