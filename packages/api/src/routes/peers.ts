import { withMeta } from "../freshness.js";
import type { RouteContext } from "./_context.js";

export function registerPeersRoutes({ app, deps }: RouteContext): void {
  app.get("/api/peers", async () => {
    const peers = deps.peerRegistry?.list() ?? [];
    return withMeta("GET", "/api/peers", { ok: true, peers });
  });
}
