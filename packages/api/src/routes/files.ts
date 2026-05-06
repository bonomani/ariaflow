import { promises as fsp, statSync } from "node:fs";
import { basename, dirname, isAbsolute, join, normalize, relative, resolve, sep } from "node:path";
import { ACTIONS, TARGETS, errorPayload, prefValue } from "@ariaflow/core";
import type { FastifyReply } from "fastify";
import { requireObjectBody, type RouteContext } from "./_context.js";

interface ResolvedPath {
  abs: string;
  rel: string;
}

async function loadDownloadDir(
  deps: RouteRegisterDeps["deps"],
): Promise<string | null> {
  const declaration = await deps.declarationStore.load();
  const raw = String(prefValue(declaration, "download_dir", "") ?? "").trim();
  if (!raw) return null;
  try {
    return await fsp.realpath(raw);
  } catch {
    return null;
  }
}

interface RouteRegisterDeps {
  deps: RouteContext["deps"];
}

/**
 * BG-56: validate that `path` resolves inside `<download_dir>`.
 * Canonicalizes via realpath when the target exists; for non-existing
 * targets (e.g. rename destination), we canonicalize the parent and
 * append the basename. Rejects `..` traversal, absolute paths outside
 * the dir, and symlinks that escape.
 */
async function resolveSafe(
  rawPath: string,
  rootAbs: string,
  reply: FastifyReply,
  { mustExist = true }: { mustExist?: boolean } = {},
): Promise<ResolvedPath | null> {
  if (typeof rawPath !== "string" || !rawPath.trim()) {
    reply.code(400).send(errorPayload("invalid_path", "path is required"));
    return null;
  }
  const trimmed = rawPath.trim();
  const candidate = isAbsolute(trimmed) ? trimmed : join(rootAbs, trimmed);
  // Reject `..` traversal even before realpath (so a missing parent
  // can't bypass the check via symlink-creation race).
  const norm = normalize(candidate);
  let abs: string;
  try {
    abs = await fsp.realpath(norm);
  } catch (err) {
    if (mustExist || (err as NodeJS.ErrnoException).code !== "ENOENT") {
      reply.code(404).send(errorPayload("not_found", "path does not exist"));
      return null;
    }
    // For non-existing destinations, canonicalize the parent + reattach
    // the basename. Parent must exist and be inside the root.
    const parent = dirname(norm);
    let parentReal: string;
    try {
      parentReal = await fsp.realpath(parent);
    } catch {
      reply
        .code(404)
        .send(errorPayload("parent_not_found", "destination's parent directory missing"));
      return null;
    }
    abs = join(parentReal, basename(norm));
  }
  const rel = relative(rootAbs, abs);
  if (rel === "" || rel.startsWith("..") || isAbsolute(rel)) {
    reply
      .code(400)
      .send(errorPayload("path_outside_download_dir", "path escapes <download_dir>"));
    return null;
  }
  return { abs, rel };
}

export function registerFilesRoutes({ app, deps }: RouteContext): void {
  const ensureRoot = async (
    reply: FastifyReply,
  ): Promise<string | null> => {
    const root = await loadDownloadDir(deps);
    if (!root) {
      reply
        .code(409)
        .send(errorPayload("download_dir_unset", "declaration.download_dir is empty"));
      return null;
    }
    return root;
  };

  // ── GET /api/files ──────────────────────────────────────────────────
  app.get<{ Querystring: { recursive?: string } }>("/api/files", async (req, reply) => {
    const root = await ensureRoot(reply);
    if (!root) return;
    const recursive = String(req.query.recursive ?? "") === "true";
    const items = await deps.queueStore.load();
    const byPath = new Map<string, (typeof items)[number]>();
    for (const it of items) {
      const p = (it as { output_path?: string | null }).output_path;
      if (p) byPath.set(p, it);
    }

    interface FileRow {
      path: string;
      rel_path: string;
      size: number;
      modified_at: string;
      type: "file" | "directory";
      history_match: { item_id: string; url: string; downloaded_at?: string | null } | null;
    }
    const out: FileRow[] = [];
    const MAX_DEPTH = 3;
    const walk = async (dir: string, depth: number): Promise<void> => {
      let entries;
      try {
        entries = await fsp.readdir(dir, { withFileTypes: true });
      } catch {
        return;
      }
      for (const e of entries) {
        const abs = join(dir, e.name);
        let st;
        try {
          st = await fsp.stat(abs);
        } catch {
          continue;
        }
        const rel = relative(root, abs);
        const histItem = byPath.get(abs);
        out.push({
          path: abs,
          rel_path: rel,
          size: e.isDirectory() ? 0 : st.size,
          modified_at: st.mtime.toISOString(),
          type: e.isDirectory() ? "directory" : "file",
          history_match: histItem
            ? {
                item_id: histItem.id,
                url: histItem.url,
                downloaded_at: histItem.completed_at ?? null,
              }
            : null,
        });
        if (e.isDirectory() && recursive && depth + 1 < MAX_DEPTH) {
          await walk(abs, depth + 1);
        }
      }
    };
    await walk(root, 0);
    return reply.send({ ok: true, files: out });
  });

  // ── POST /api/files/rename ──────────────────────────────────────────
  app.post("/api/files/rename", async (req, reply) => {
    const obj = requireObjectBody(req.body, reply, "expected {path, new_name}");
    if (!obj) return;
    const root = await ensureRoot(reply);
    if (!root) return;
    const newName = String(obj.new_name ?? "").trim();
    if (!newName || basename(newName) !== newName || newName.includes(sep)) {
      return reply
        .code(400)
        .send(errorPayload("invalid_new_name", "new_name must be a bare filename"));
    }
    const src = await resolveSafe(String(obj.path ?? ""), root, reply);
    if (!src) return;
    const dstAbs = join(dirname(src.abs), newName);
    const dst = await resolveSafe(dstAbs, root, reply, { mustExist: false });
    if (!dst) return;
    try {
      statSync(dst.abs);
      return reply
        .code(409)
        .send(errorPayload("destination_exists", "a file with that name already exists"));
    } catch {
      /* ENOENT — good */
    }
    try {
      await fsp.rename(src.abs, dst.abs);
    } catch (err) {
      return reply
        .code(500)
        .send(errorPayload("rename_failed", err instanceof Error ? err.message : "rename failed"));
    }
    const items = await deps.queueStore.load();
    let touched = false;
    for (const it of items) {
      if ((it as { output_path?: string | null }).output_path === src.abs) {
        (it as { output_path: string }).output_path = dst.abs;
        touched = true;
      }
    }
    if (touched) await deps.queueStore.save(items);
    await deps.actionLog.record({
      action: ACTIONS.fileRename,
      target: TARGETS.files,
      outcome: "changed",
      reason: "api_request",
      detail: { from: src.abs, to: dst.abs },
    });
    return reply.send({ ok: true, path: dst.abs });
  });

  // ── POST /api/files/move ────────────────────────────────────────────
  app.post("/api/files/move", async (req, reply) => {
    const obj = requireObjectBody(req.body, reply, "expected {path, new_subdir}");
    if (!obj) return;
    const root = await ensureRoot(reply);
    if (!root) return;
    const subdirRaw = String(obj.new_subdir ?? "").trim();
    if (!subdirRaw) {
      return reply
        .code(400)
        .send(errorPayload("invalid_new_subdir", "new_subdir is required"));
    }
    const src = await resolveSafe(String(obj.path ?? ""), root, reply);
    if (!src) return;
    const subdirAbs = isAbsolute(subdirRaw) ? subdirRaw : join(root, subdirRaw);
    const subdir = await resolveSafe(subdirAbs, root, reply, { mustExist: false });
    if (!subdir) return;
    await fsp.mkdir(subdir.abs, { recursive: true });
    const dstAbs = join(subdir.abs, basename(src.abs));
    try {
      statSync(dstAbs);
      return reply
        .code(409)
        .send(errorPayload("destination_exists", "a file with that name already exists in target"));
    } catch {
      /* good */
    }
    try {
      await fsp.rename(src.abs, dstAbs);
    } catch (err) {
      return reply
        .code(500)
        .send(errorPayload("move_failed", err instanceof Error ? err.message : "move failed"));
    }
    const items = await deps.queueStore.load();
    let touched = false;
    for (const it of items) {
      if ((it as { output_path?: string | null }).output_path === src.abs) {
        (it as { output_path: string }).output_path = dstAbs;
        touched = true;
      }
    }
    if (touched) await deps.queueStore.save(items);
    await deps.actionLog.record({
      action: ACTIONS.fileMove,
      target: TARGETS.files,
      outcome: "changed",
      reason: "api_request",
      detail: { from: src.abs, to: dstAbs },
    });
    return reply.send({ ok: true, path: dstAbs });
  });

  // ── DELETE /api/files ───────────────────────────────────────────────
  app.delete("/api/files", async (req, reply) => {
    const obj = requireObjectBody(req.body, reply, "expected {path, recursive?}");
    if (!obj) return;
    const root = await ensureRoot(reply);
    if (!root) return;
    const recursive = obj.recursive === true;
    const target = await resolveSafe(String(obj.path ?? ""), root, reply);
    if (!target) return;
    const st = await fsp.stat(target.abs);
    if (st.isDirectory()) {
      const entries = await fsp.readdir(target.abs);
      if (entries.length > 0 && !recursive) {
        return reply
          .code(409)
          .send(
            errorPayload("directory_not_empty", "directory is non-empty; pass recursive: true"),
          );
      }
      await fsp.rm(target.abs, { recursive: true, force: true });
    } else {
      await fsp.unlink(target.abs);
    }
    const items = await deps.queueStore.load();
    let touched = false;
    for (const it of items) {
      if ((it as { output_path?: string | null }).output_path === target.abs) {
        (it as { file_present_on_disk?: boolean }).file_present_on_disk = false;
        touched = true;
      }
    }
    if (touched) await deps.queueStore.save(items);
    await deps.actionLog.record({
      action: ACTIONS.fileDelete,
      target: TARGETS.files,
      outcome: "changed",
      reason: "api_request",
      detail: { path: target.abs, recursive },
    });
    return reply.code(204).send();
  });

  // ── POST /api/files/clean ───────────────────────────────────────────
  app.post("/api/files/clean", async (req, reply) => {
    const obj = requireObjectBody(req.body, reply, "expected {status?, older_than_days?, orphaned?}");
    if (!obj) return;
    const root = await ensureRoot(reply);
    if (!root) return;
    const status = obj.status ? String(obj.status) : null;
    const olderDays = Number(obj.older_than_days ?? 0) || 0;
    const orphaned = obj.orphaned === true;
    const items = await deps.queueStore.load();
    const now = Date.now();
    let deleted = 0;
    let freedBytes = 0;
    let touched = false;

    if (orphaned) {
      // Reconcile-only: flag history rows whose file is gone. No disk
      // side-effect.
      let flagged = 0;
      for (const it of items) {
        const p = (it as { output_path?: string | null }).output_path;
        if (!p) continue;
        try {
          await fsp.stat(p);
        } catch {
          (it as { file_present_on_disk?: boolean }).file_present_on_disk = false;
          flagged += 1;
          touched = true;
        }
      }
      if (touched) await deps.queueStore.save(items);
      await deps.actionLog.record({
        action: ACTIONS.fileClean,
        target: TARGETS.files,
        outcome: "changed",
        reason: "orphaned_reconcile",
        detail: { flagged },
      });
      return reply.send({ ok: true, flagged });
    }

    for (const it of items) {
      if (status && it.status !== status) continue;
      const p = (it as { output_path?: string | null }).output_path;
      if (!p) continue;
      // Bound to root
      const rel = relative(root, p);
      if (rel.startsWith("..") || isAbsolute(rel)) continue;
      if (olderDays > 0) {
        const ts = it.completed_at ? Date.parse(String(it.completed_at)) : NaN;
        if (!Number.isFinite(ts)) continue;
        if (now - ts < olderDays * 86_400_000) continue;
      }
      try {
        const st = await fsp.stat(p);
        await fsp.unlink(p);
        deleted += 1;
        freedBytes += st.size;
        (it as { file_present_on_disk?: boolean }).file_present_on_disk = false;
        touched = true;
      } catch {
        /* skip files that no longer exist */
      }
    }
    if (touched) await deps.queueStore.save(items);
    await deps.actionLog.record({
      action: ACTIONS.fileClean,
      target: TARGETS.files,
      outcome: deleted > 0 ? "changed" : "unchanged",
      reason: "clean_recipe",
      detail: { status, older_than_days: olderDays, deleted, freed_bytes: freedBytes },
    });
    return reply.send({ ok: true, deleted, freed_bytes: freedBytes });
  });
}
