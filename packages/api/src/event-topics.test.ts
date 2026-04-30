import { describe, expect, it } from "vitest";
import {
  ALL_TOPICS,
  eventMatchesTopics,
  eventTopics,
  parseTopics,
  type EventTopic,
} from "./event-topics.js";

describe("event-topics", () => {
  it("classifies known events", () => {
    expect(eventTopics("action_logged")).toEqual(["log"]);
    expect(eventTopics("session_started")).toEqual(["scheduler"]);
    expect(eventTopics("state_changed")).toEqual(["items", "scheduler"]);
    expect(eventTopics("bandwidth_probed")).toEqual(["bandwidth"]);
    expect(eventTopics("lifecycle_changed")).toEqual(["lifecycle"]);
  });

  it("unknown events fall through to all topics (safe default)", () => {
    expect(eventTopics("brand_new_event")).toEqual(ALL_TOPICS);
  });

  it("parseTopics handles missing/empty as all-topics (back-compat)", () => {
    expect([...parseTopics(undefined)].sort()).toEqual([...ALL_TOPICS].sort());
    expect([...parseTopics("")].sort()).toEqual([...ALL_TOPICS].sort());
  });

  it("parseTopics filters by allow-list and drops unknowns", () => {
    const s = parseTopics("items,scheduler,bogus");
    expect([...s].sort()).toEqual(["items", "scheduler"]);
  });

  it("parseTopics treats only-unknowns as empty (typo → empty stream)", () => {
    expect(parseTopics("bogus,nope").size).toBe(0);
  });

  it("eventMatchesTopics intersects event topics with the client subset", () => {
    const onlyLog = new Set<EventTopic>(["log"]);
    expect(eventMatchesTopics("action_logged", onlyLog)).toBe(true);
    expect(eventMatchesTopics("session_started", onlyLog)).toBe(false);

    const onlySched = new Set<EventTopic>(["scheduler"]);
    expect(eventMatchesTopics("state_changed", onlySched)).toBe(true);
    expect(eventMatchesTopics("action_logged", onlySched)).toBe(false);
  });
});
