import type { CliContext } from "../context.js";
import { fail, json, ok, requireArg, type CmdResult } from "./_shared.js";

export async function cmdSetPref(
  ctx: CliContext,
  name: string,
  rawValue: string,
): Promise<CmdResult> {
  const guard = requireArg("preference name", name);
  if (guard) return guard;
  const declaration = await ctx.declaration.load();
  const pref = declaration.uic.preferences.find((p) => p.name === name);
  if (!pref) return fail(`error: unknown preference: ${name}\n`, 2);
  let value: unknown = rawValue;
  if (rawValue === "true") value = true;
  else if (rawValue === "false") value = false;
  else if (rawValue === "null") value = null;
  else if (rawValue !== "" && Number.isFinite(Number(rawValue))) value = Number(rawValue);
  const before = pref.value;
  pref.value = value;
  await ctx.declaration.save(declaration);
  await ctx.actions.record({
    action: "patch_preferences",
    target: "declaration",
    outcome: "changed",
    reason: "cli_set_pref",
    detail: { applied: { [name]: { before, after: value } } },
  });
  return ok(json({ name, before, after: value }) + "\n");
}
