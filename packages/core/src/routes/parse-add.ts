import { isAbsolute, sep } from "node:path";
import { resolve as pathResolve } from "node:path";
import {
  errorPayload,
  isValidBase64,
  validateOutputPath,
  validateUrl,
} from "./helpers.js";

export interface ParsedAddItem {
  url: string;
  output: string | null;
  post_action_rule: string | null;
  mirrors: string[] | null;
  torrent_data: string | null;
  metalink_data: string | null;
  priority: number;
  distribute: boolean;
}

const splitParts = (p: string): string[] => p.split(/[/\\]/).filter(Boolean);

const isStringRecord = (v: unknown): v is Record<string, unknown> =>
  !!v && typeof v === "object" && !Array.isArray(v);

const trimmedString = (v: unknown): string =>
  typeof v === "string" ? v.trim() : v == null ? "" : String(v).trim();

/**
 * Validate and normalize the body of POST /api/downloads.
 *
 * Returns either the parsed items array or an `errorPayload` describing
 * the first invalid item. The cwd is injectable so tests can pin it.
 */
export function parseAddItems(
  payload: unknown,
  opts: { cwd?: string } = {},
): { items: ParsedAddItem[] } | { error: Record<string, unknown> } {
  const cwd = opts.cwd ?? process.cwd();

  if (!isStringRecord(payload)) {
    return { error: errorPayload("invalid_payload", "expected a JSON object") };
  }
  const rawItems = payload.items;
  if (!Array.isArray(rawItems) || rawItems.length === 0) {
    return { error: errorPayload("invalid_items", "items must be a non-empty list") };
  }

  const out: ParsedAddItem[] = [];
  for (let index = 0; index < rawItems.length; index++) {
    const raw = rawItems[index];
    if (!isStringRecord(raw)) {
      return {
        error: errorPayload("invalid_item", `items[${index}] must be an object`, { index }),
      };
    }

    const url = trimmedString(raw.url);
    if (!url) {
      return {
        error: errorPayload(
          "invalid_item",
          `items[${index}].url must be a non-empty string`,
          { index },
        ),
      };
    }
    const urlError = validateUrl(url);
    if (urlError) {
      return {
        error: errorPayload("invalid_url", `items[${index}].url: ${urlError}`, { index }),
      };
    }

    const outputValue = trimmedString(raw.output);
    const outputError = validateOutputPath(outputValue, {
      cwd,
      isAbsolute,
      splitParts,
      resolve: (c, p) => pathResolve(c, p) + (sep === "/" ? "" : ""),
    });
    if (outputError) {
      return {
        error: errorPayload("invalid_output", `items[${index}].output: ${outputError}`, {
          index,
        }),
      };
    }

    let mirrors: string[] | null = null;
    if (Array.isArray(raw.mirrors)) {
      mirrors = (raw.mirrors as unknown[])
        .map((m) => (typeof m === "string" ? m.trim() : String(m).trim()))
        .filter(Boolean);
      for (let mi = 0; mi < mirrors.length; mi++) {
        const mErr = validateUrl(mirrors[mi]!);
        if (mErr) {
          return {
            error: errorPayload(
              "invalid_url",
              `items[${index}].mirrors[${mi}]: ${mErr}`,
              { index },
            ),
          };
        }
      }
    }

    const torrentDataStr =
      raw.torrent_data == null || raw.torrent_data === ""
        ? null
        : String(raw.torrent_data);
    if (torrentDataStr !== null && !isValidBase64(torrentDataStr)) {
      return {
        error: errorPayload(
          "invalid_torrent_data",
          `items[${index}].torrent_data must be valid base64`,
          { index },
        ),
      };
    }
    const metalinkDataStr =
      raw.metalink_data == null || raw.metalink_data === ""
        ? null
        : String(raw.metalink_data);
    if (metalinkDataStr !== null && !isValidBase64(metalinkDataStr)) {
      return {
        error: errorPayload(
          "invalid_metalink_data",
          `items[${index}].metalink_data must be valid base64`,
          { index },
        ),
      };
    }

    const priorityRaw = raw.priority ?? 0;
    const priorityNum = Number(priorityRaw);
    const priority = Number.isFinite(priorityNum) ? Math.trunc(priorityNum) : 0;

    const postActionRaw = raw.post_action_rule;
    const postActionRule =
      postActionRaw === undefined || postActionRaw === null
        ? null
        : String(postActionRaw).trim() || null;

    out.push({
      url,
      output: outputValue || null,
      post_action_rule: postActionRule,
      mirrors,
      torrent_data: torrentDataStr,
      metalink_data: metalinkDataStr,
      priority,
      distribute: Boolean(raw.distribute),
    });
  }

  return { items: out };
}
