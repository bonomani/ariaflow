export interface UicPreference {
  name: string;
  value: unknown;
  options: unknown[];
  rationale: string;
}

export interface UicGate {
  name: string;
  class: "readiness" | "integrity" | string;
  blocking: "hard" | "soft" | string;
}

export interface Declaration {
  meta: { contract: string; version: string };
  uic: { gates: UicGate[]; preferences: UicPreference[]; policies: unknown[] };
  targets: { name: string; type: string }[];
}

const PREFERENCES: UicPreference[] = [
  { name: "post_action_rule", value: "pending", options: ["pending"], rationale: "default placeholder" },
  { name: "auto_preflight_on_run", value: false, options: [true, false], rationale: "default off" },
  {
    name: "duplicate_active_transfer_action",
    value: "remove",
    options: ["remove", "pause", "ignore"],
    rationale: "remove duplicate live jobs by default",
  },
  { name: "max_simultaneous_downloads", value: 1, options: [1], rationale: "1 preserves the sequential default" },
  { name: "bandwidth_down_free_percent", value: 20, options: [0, 10, 20, 30, 50], rationale: "reserve this % of downlink for other traffic" },
  {
    name: "bandwidth_down_free_absolute_mbps",
    value: 0,
    options: [0, 1, 2, 5, 10],
    rationale: "reserve this many Mbps downlink (0 = use percent only; stricter of % and absolute wins)",
  },
  { name: "bandwidth_up_free_percent", value: 50, options: [0, 10, 20, 30, 50, 80], rationale: "reserve this % of uplink for other traffic" },
  {
    name: "bandwidth_up_free_absolute_mbps",
    value: 0,
    options: [0, 1, 2, 5, 10],
    rationale: "reserve this many Mbps uplink (0 = use percent only; stricter of % and absolute wins)",
  },
  { name: "bandwidth_probe_interval_seconds", value: 180, options: [60, 120, 180, 300], rationale: "seconds between automatic bandwidth probes" },
  {
    name: "aria2_unsafe_options",
    value: false,
    options: [false, true],
    rationale: "allow setting any aria2 option via API (bypasses safe subset)",
  },
  { name: "max_retries", value: 3, options: [0, 1, 3, 5, 10], rationale: "auto-retry failed downloads up to N times (0 = manual retry only)" },
  {
    name: "archive_completed_after_hours",
    value: 168,
    options: [0, 1, 6, 12, 24, 72, 168],
    rationale: "move completed downloads from queue to archive after N hours (0 = keep completed items in queue)",
  },
  { name: "retry_backoff_seconds", value: 30, options: [10, 30, 60, 120, 300], rationale: "seconds between auto-retries, multiplied by retry count" },
  {
    name: "aria2_max_tries",
    value: 5,
    options: [1, 3, 5, 10, 0],
    rationale: "aria2 retries per download for transient network errors (0 = unlimited)",
  },
  { name: "aria2_retry_wait", value: 10, options: [3, 5, 10, 30, 60], rationale: "seconds aria2 waits between retries" },
  {
    name: "internal_tracker_url",
    value: "",
    options: [],
    rationale: "internal BitTorrent tracker announce URL (empty = distribution disabled)",
  },
  {
    name: "distribute_completed_downloads",
    value: false,
    options: [false, true],
    rationale: "auto-create private torrent and seed after HTTP download completes",
  },
  { name: "distribute_seed_ratio", value: 0, options: [0, 1, 2, 5], rationale: "seed ratio for distributed torrents (0 = seed indefinitely)" },
  { name: "distribute_max_seed_hours", value: 72, options: [24, 48, 72, 168, 0], rationale: "stop seeding after N hours (0 = no time limit)" },
  {
    name: "distribute_max_active_seeds",
    value: 10,
    options: [5, 10, 20, 50, 0],
    rationale: "max concurrent seeds (0 = unlimited, oldest expired first)",
  },
  { name: "max_disk_usage_percent", value: 90, options: [70, 80, 90, 95, 0], rationale: "stop downloading when disk reaches this % usage (0 = no limit)" },
  { name: "download_dir", value: "", options: [], rationale: "download destination directory (empty = aria2 default / cwd)" },
  { name: "torrent_dir", value: "", options: [], rationale: "directory for .torrent files (empty = {config_dir}/torrents/)" },
  {
    name: "auto_discover_peers",
    value: false,
    options: [false, true],
    rationale: "browse local network for other ariaflow instances and auto-download their torrents",
  },
  {
    name: "peer_poll_interval_seconds",
    value: 60,
    options: [30, 60, 120, 300],
    rationale: "seconds between polling discovered peers for new torrents",
  },
  {
    name: "peer_max_auto_downloads",
    value: 5,
    options: [1, 3, 5, 10, 0],
    rationale: "max torrents to auto-fetch per poll cycle (0 = unlimited)",
  },
  {
    name: "peer_content_filter",
    value: "",
    options: [],
    rationale: "glob pattern to filter auto-downloaded torrents by name (empty = accept all)",
  },
  {
    name: "peer_allowlist",
    value: "",
    options: [],
    rationale: "comma-separated instance names to accept (empty = accept all peers)",
  },
];

const GATES: UicGate[] = [
  { name: "aria2_available", class: "readiness", blocking: "hard" },
  { name: "queue_readable", class: "integrity", blocking: "hard" },
];

/**
 * Return a fresh deep clone of the default declaration. Mirrors
 * src/ariaflow_server/contracts.py::DEFAULT_DECLARATION.
 */
export function defaultDeclaration(): Declaration {
  return structuredClone({
    meta: { contract: "UCC", version: "2.0" },
    uic: { gates: GATES, preferences: PREFERENCES, policies: [] as unknown[] },
    targets: [{ name: "queue", type: "queue" }],
  });
}

/**
 * Read a preference value out of a declaration; returns `fallback` if absent.
 */
export function prefValue<T = unknown>(
  declaration: Declaration,
  name: string,
  fallback?: T,
): T | unknown {
  for (const p of declaration.uic?.preferences ?? []) {
    if (p.name === name) return p.value as T;
  }
  return fallback;
}
