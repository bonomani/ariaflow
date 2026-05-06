import {
  ACTIONS,
  errorPayload,
  installAria2Service,
  prefValue,
  uninstallAria2Service,
} from "@ariaflow/core";
import { withMeta } from "../freshness.js";
import type { RouteContext } from "./_context.js";
import {
  buildAria2Row,
  buildAriaflowServerRow,
  buildNetworkqualityRow,
  probeAria2,
} from "./_lifecycle_rows.js";
import {
  ARIA2_SERVICE_TARGETS,
  dispatchAria2Update,
  dispatchAriaflowCheckUpdate,
  dispatchAriaflowRestart,
  dispatchAriaflowUpdate,
} from "./_lifecycle_actions.js";

export function registerLifecycleRoutes({ app, deps }: RouteContext): void {
  app.get("/api/lifecycle", async () => {
    const state = await deps.stateStore.load();
    const items = await deps.queueStore.load();
    const aria2Probe = await probeAria2(deps.aria2);

    return withMeta("GET", "/api/lifecycle", {
      ok: true,
      "ariaflow-server": buildAriaflowServerRow(deps),
      aria2: buildAria2Row(aria2Probe, state, items),
      networkquality: buildNetworkqualityRow(state),
      session_id: state.session_id,
      session_started_at: state.session_started_at,
      session_last_seen_at: state.session_last_seen_at,
      session_closed_at: state.session_closed_at,
      session_closed_reason: state.session_closed_reason,
    });
  });

  app.post<{ Params: { target: string; action: string }; Querystring: { dry_run?: string } }>(
    "/api/lifecycle/:target/:action",
    async (req, reply) => {
      const target = req.params.target;
      const action = req.params.action;
      const dryRun = req.query?.dry_run === "1" || req.query?.dry_run === "true";

      const beforeState = await deps.stateStore.load();
      const before = { lifecycle: { state: beforeState } };

      // BG-59: read-only update probe — synchronous, returns the
      // verdict in the body. No side effect.
      if (target === "ariaflow-server" && action === "check_update") {
        const dispatch = await dispatchAriaflowCheckUpdate(deps.version ?? "0.0.0");
        await deps.actionLog.record({
          action: ACTIONS.checkUpdate,
          target,
          outcome:
            dispatch.status === 200
              ? dispatch.body.update_available === true
                ? "changed"
                : "unchanged"
              : "blocked",
          reason: action,
          before,
          after: { target, action, ...dispatch.body },
          detail: { target, action, ...dispatch.body },
        });
        return reply.code(dispatch.status).send({
          target,
          action,
          ...dispatch.body,
        });
      }

      // BG-43: ariaflow-server/{restart,update} dispatch via supervisor /
      // installer detection. Returns 202 on success and runs the side
      // effect (launchctl/systemctl/docker exit/brew upgrade/...) AFTER
      // the response is sent so the operator gets the ack before any
      // bounce. Dry-run returns the plan without executing.
      if (
        (target === "ariaflow-server" && (action === "restart" || action === "update")) ||
        (target === "aria2" && action === "update")
      ) {
        // BG-62: read auto_restart_after_upgrade so the brew/pipx upgrade
        // can chain a bootout+bootstrap and pick up the new bottle.
        const declaration = await deps.declarationStore.load();
        const autoRestart = Boolean(prefValue(declaration, "auto_restart_after_upgrade", true));
        const dispatch =
          target === "aria2"
            ? dispatchAria2Update()
            : action === "restart"
              ? dispatchAriaflowRestart()
              : dispatchAriaflowUpdate({ autoRestart });
        await deps.actionLog.record({
          action: ACTIONS.systemLifecycle,
          target,
          outcome: dispatch.status === 202 ? "changed" : "blocked",
          reason: action,
          before,
          after: { target, action, dry_run: dryRun, ...dispatch.body },
          detail: { target, action, dry_run: dryRun, ...dispatch.body },
        });
        if (dispatch.status === 202 && !dryRun && dispatch.after) {
          // Schedule the side effect after the reply flushes.
          reply.raw.on("finish", () => {
            try {
              dispatch.after?.();
            } catch (err) {
              // Don't crash the server on a failed restart subprocess.
              console.error("BG-43 lifecycle action side effect failed:", err);
            }
          });
        }
        return reply.code(dispatch.status).send({
          ok: dispatch.status === 202,
          target,
          action,
          dry_run: dryRun,
          ...dispatch.body,
        });
      }

      try {
        let result: Record<string, unknown>;
        if (ARIA2_SERVICE_TARGETS.has(target) && action === "install") {
          const out = await installAria2Service({ dryRun });
          result = {
            [out.target]: {
              ok: out.ok,
              commands: out.commands,
              ...(out.results ? { results: out.results } : { dry_run: true }),
            },
          };
        } else if (ARIA2_SERVICE_TARGETS.has(target) && action === "uninstall") {
          const out = await uninstallAria2Service({ dryRun });
          result = {
            [out.target]: {
              ok: out.ok,
              commands: out.commands,
              ...(out.results ? { results: out.results } : { dry_run: true }),
            },
          };
        } else {
          return reply
            .code(400)
            .send(errorPayload("unsupported_action", `${target}/${action} not supported`, { target, action }));
        }

        await deps.actionLog.record({
          action: ACTIONS.systemLifecycle,
          target,
          outcome: "changed",
          reason: action,
          before,
          after: { target, action, result },
          detail: { target, action, dry_run: dryRun, result },
        });
        return { ok: true, target, action, dry_run: dryRun, result };
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        await deps.actionLog.record({
          action: ACTIONS.systemLifecycle,
          target,
          outcome: "failed",
          reason: "exception",
          before,
          detail: { error: message, target, action, dry_run: dryRun },
        });
        return reply
          .code(500)
          .send(errorPayload("lifecycle_action_failed", message));
      }
    },
  );
}
