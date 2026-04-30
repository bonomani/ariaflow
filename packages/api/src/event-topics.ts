// BG-32: SSE event → topic mapping.
//
// `/api/events?topics=items,scheduler` filters the stream so a client
// that only reads e.g. lifecycle data doesn't pay the wire cost for
// every action_logged tick. The dashboard's FreshnessRouter picks
// topics from `meta.transport_topics` in /api/_meta.
//
// Topic vocabulary (low cardinality on purpose — this is a coarse
// filter, not a routing tree):
//   items      — queue rows: status, progress, transitions
//   scheduler  — scheduler loop / dispatch state
//   log        — action log appends
//   lifecycle  — service-manager (aria2 / ariaflow-server) state
//   bandwidth  — probe results / cap changes
//
// Unknown event names default to ALL_TOPICS so a new event surfaces
// to every subscriber until it's classified — the safe default for
// an advisory filter.

export type EventTopic = "items" | "scheduler" | "log" | "lifecycle" | "bandwidth";

export const ALL_TOPICS: readonly EventTopic[] = [
  "items",
  "scheduler",
  "log",
  "lifecycle",
  "bandwidth",
];

const EVENT_TOPICS: Record<string, readonly EventTopic[]> = {
  action_logged: ["log"],
  session_started: ["scheduler"],
  session_closed: ["scheduler"],
  // Reserved for future emitters; pre-classified so adding the
  // publish() call doesn't require touching the registry too.
  state_changed: ["items", "scheduler"],
  lifecycle_changed: ["lifecycle"],
  bandwidth_probed: ["bandwidth"],
};

/** Topics this event belongs to. Unknown events fall through to all. */
export function eventTopics(event: string): readonly EventTopic[] {
  return EVENT_TOPICS[event] ?? ALL_TOPICS;
}

/** Parse `?topics=a,b,c`. Empty/missing → all topics (back-compat). */
export function parseTopics(raw: string | undefined): Set<EventTopic> {
  const all = new Set<EventTopic>(ALL_TOPICS);
  if (!raw) return all;
  const wanted = raw
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  if (wanted.length === 0) return all;
  const allowed = new Set<EventTopic>();
  for (const w of wanted) {
    if ((ALL_TOPICS as readonly string[]).includes(w)) allowed.add(w as EventTopic);
  }
  // If the caller passed only unknown names, treat that as "no
  // matches" rather than silently widening to all topics — the
  // advisory contract is that a typo means an empty stream, not a
  // firehose.
  return allowed;
}

/** True if `event` should be delivered to a client subscribed to `subset`. */
export function eventMatchesTopics(event: string, subset: Set<EventTopic>): boolean {
  for (const t of eventTopics(event)) if (subset.has(t)) return true;
  return false;
}
