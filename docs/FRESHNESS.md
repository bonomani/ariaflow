# Per-endpoint Freshness Contract (BG-31)

Every JSON endpoint that opts in stamps a `meta` block onto its
response body. The same data is also exposed verbatim at
`GET /api/_meta` so the dashboard's `FreshnessRouter` can decide
cadence without per-endpoint hardcoding.

Design rationale and seven-class taxonomy:
`../../ariaflow-dashboard/docs/FRESHNESS_AXIS.md` (frontend repo).
This file is the server-side mirror — it lives next to the code that
emits the stamps so the contract stays co-located.

## Meta block

```jsonc
"meta": {
  "freshness": "bootstrap" | "live" | "warm" | "cold" | "on-action" | "swr" | "derived",
  "ttl_s": 30,                              // required for warm / swr
  "revalidate_on": ["POST /api/.../action"], // required for on-action
  "transport": "sse"                         // required for live
}
```

## Class semantics

| Class       | Client behavior                                                |
|-------------|----------------------------------------------------------------|
| `bootstrap` | Fetch once per session; cache. Body is stable across calls.    |
| `live`      | Server pushes via `transport`. Client follows the push.        |
| `warm`      | Refetch when older than `ttl_s` seconds.                       |
| `cold`      | Fetch on demand; never refresh automatically.                  |
| `on-action` | Refetch only after one of `revalidate_on` mutations completes. |
| `swr`       | Show cached, refetch in background; bound staleness by `ttl_s`.|
| `derived`   | Computed from another endpoint's body; never fetched directly. |

## Initial coverage

| Endpoint                          | Class       | Extras                                                      |
|-----------------------------------|-------------|-------------------------------------------------------------|
| `GET /api/status`                 | `live`      | `transport: "sse"`                                          |
| `GET /api/lifecycle`              | `warm`      | `ttl_s: 30`, `revalidate_on: ["POST /api/lifecycle/:target/:action"]` |
| `GET /api/bandwidth`              | `on-action` | `revalidate_on: ["POST /api/bandwidth/probe"]`              |
| `GET /api/aria2/get_global_option`| `cold`      |                                                             |
| `GET /api/aria2/global_option`    | `cold`      |                                                             |
| `GET /api/log`                    | `swr`       | `ttl_s: 10`                                                 |
| `GET /api/health`                 | `bootstrap` |                                                             |
| `GET /api/version`                | `bootstrap` |                                                             |
| `GET /api/_meta`                  | `bootstrap` |                                                             |

## Rules

1. **Single source of truth.** All meta lives in
   `packages/api/src/freshness.ts`. Inline `meta: {...}` literals in
   route handlers are forbidden — wrap with `withMeta(method, path, body)`
   instead.
2. **`withMeta` throws on unregistered keys.** Adding a meta stamp to
   a new endpoint requires registering it first; this prevents
   silently-undocumented endpoints from leaking into the contract.
3. **Validation runs at registration time:** `warm`/`swr` require
   `ttl_s`, `on-action` requires `revalidate_on`, `live` requires
   `transport: "sse"`.
4. **Revalidate triggers must reference real routes.** Tested at the
   server-test layer (`BG-31: GET /api/_meta lists registered
   endpoints; revalidate_on references real routes`).
5. **Anti-goal:** this is not a cache implementation, not a transport,
   not enforcement. The schema is advisory — server lying is a bug,
   not a security issue.

## Adding an endpoint

1. Add an entry to `registerDefaultFreshness()` in
   `packages/api/src/freshness.ts`.
2. Wrap the handler's return value with `withMeta(method, path, body)`.
3. If you reference it from `revalidate_on`, make sure the trigger
   path matches the registered Fastify route literally (parametric
   segments included, e.g. `:id`, `:target`).
