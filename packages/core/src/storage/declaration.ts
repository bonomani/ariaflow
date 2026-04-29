import { join } from "node:path";
import { defaultDeclaration, type Declaration } from "../contracts/declaration.js";
import { readJson, writeJson } from "./json.js";
import { configDir } from "./paths.js";
import type { StorageLock } from "./lock.js";

export const declarationPath = (env?: NodeJS.ProcessEnv): string =>
  join(configDir(env), "declaration.json");

export class DeclarationStore {
  constructor(
    private readonly lock: StorageLock,
    private readonly env: NodeJS.ProcessEnv = process.env,
  ) {}

  /** Load the declaration, writing the default to disk on first access. */
  async ensure(): Promise<Declaration> {
    return this.lock.with(async () => {
      const path = declarationPath(this.env);
      const existing = await readJson<Declaration | null>(path, null);
      if (existing) return existing;
      const fresh = defaultDeclaration();
      await writeJson(path, fresh);
      return fresh;
    });
  }

  /** Convenience alias mirroring Python `load_declaration`. */
  load(): Promise<Declaration> {
    return this.ensure();
  }

  async save(declaration: Declaration): Promise<Declaration> {
    return this.lock.with(async () => {
      await writeJson(declarationPath(this.env), declaration);
      return declaration;
    });
  }
}
