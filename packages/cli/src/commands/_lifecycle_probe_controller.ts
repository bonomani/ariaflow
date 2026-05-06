import {
  ACTIONS,
  TARGETS,
  aria2AutoStartInstalled,
  findAria2c,
  findNetworkQuality,
  prefValue,
  probeAria2Reachable,
  type Aria2Client,
  type EventBus,
} from "@ariaflow/core";
import type { CliContext } from "../context.js";

interface LifecycleProbeController {
  running: () => boolean;
  launch: () => Promise<void>;
  stop: () => void;
}

interface LifecycleSnapshot {
  aria2_running: boolean;
  aria2_installed: boolean;
  networkquality_installed: boolean;
  auto_start_installed: boolean;
}

async function snapshot(aria2: Aria2Client | undefined): Promise<LifecycleSnapshot> {
  const aria2Running = (await probeAria2Reachable(aria2)) === true;
  return {
    aria2_running: aria2Running,
    aria2_installed: Boolean(findAria2c()),
    networkquality_installed: Boolean(findNetworkQuality()),
    auto_start_installed: aria2AutoStartInstalled(),
  };
}

function snapshotsEqual(a: LifecycleSnapshot, b: LifecycleSnapshot): boolean {
  return (
    a.aria2_running === b.aria2_running &&
    a.aria2_installed === b.aria2_installed &&
    a.networkquality_installed === b.networkquality_installed &&
    a.auto_start_installed === b.auto_start_installed
  );
}

/**
 * BG-63: backend self-runs lifecycle probes (aria2 reachability,
 * binary presence, supervisor plist) on a timer instead of waiting
 * for a `/api/lifecycle` request. On axis flips it publishes
 * `lifecycle_changed` so the FE can drop its 30s warm poll. Pause
 * when the operator stopped the scheduler — they explicitly opted
 * out of background work.
 *
 * Cadence is `lifecycle_probe_interval_seconds` (default 60); the
 * declaration is re-read every tick so live preference changes apply
 * without restart. interval≤0 disables the loop.
 */
export function createLifecycleProbeController(
  ctx: CliContext,
  aria2: Aria2Client | undefined,
  bus: EventBus,
): LifecycleProbeController {
  let timer: NodeJS.Timeout | undefined;
  let last: LifecycleSnapshot | null = null;
  let inFlight = false;

  const tick = async (): Promise<void> => {
    if (inFlight) return;
    inFlight = true;
    try {
      const state = await ctx.state.load();
      // Pause when operator explicitly stopped the scheduler (matches
      // the BG-52 periodic probe gating).
      if (state.scheduler_intent === "stopped") return;
      const next = await snapshot(aria2);
      if (last && !snapshotsEqual(last, next)) {
        bus.publish("lifecycle_changed", next);
        await ctx.actions.record({
          action: ACTIONS.systemLifecycle,
          target: TARGETS.system,
          outcome: "changed",
          reason: "lifecycle_probe_flip",
          before: { lifecycle: last },
          after: { lifecycle: next },
          detail: next as unknown as Record<string, unknown>,
        });
      }
      last = next;
    } catch (err) {
      console.error("lifecycle probe failed:", err);
    } finally {
      inFlight = false;
    }
  };

  const launch = async (): Promise<void> => {
    if (timer) return;
    const declaration = await ctx.declaration.load();
    const intervalSec =
      Number(prefValue(declaration, "lifecycle_probe_interval_seconds", 60)) || 0;
    if (intervalSec <= 0) return;
    last = await snapshot(aria2);
    timer = setInterval(() => void tick(), intervalSec * 1000);
    timer.unref();
  };

  const stop = (): void => {
    if (!timer) return;
    clearInterval(timer);
    timer = undefined;
  };

  return { running: () => Boolean(timer), launch, stop };
}
