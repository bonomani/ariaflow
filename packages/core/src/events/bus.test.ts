import { describe, expect, it, vi } from "vitest";
import { EventBus } from "./bus.js";

describe("EventBus", () => {
  it("delivers published events to all subscribers", () => {
    const bus = new EventBus();
    const a = vi.fn();
    const b = vi.fn();
    bus.subscribe(a);
    bus.subscribe(b);
    bus.publish("hello", { x: 1 });
    expect(a).toHaveBeenCalledWith("hello", { x: 1 });
    expect(b).toHaveBeenCalledWith("hello", { x: 1 });
    expect(bus.size).toBe(2);
  });

  it("subscribe returns an unsubscribe handle", () => {
    const bus = new EventBus();
    const a = vi.fn();
    const off = bus.subscribe(a);
    off();
    bus.publish("x", null);
    expect(a).not.toHaveBeenCalled();
    expect(bus.size).toBe(0);
  });

  it("a throwing listener does not stop later listeners", () => {
    const bus = new EventBus();
    const consoleErr = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const good = vi.fn();
    bus.subscribe(() => {
      throw new Error("boom");
    });
    bus.subscribe(good);
    bus.publish("e", null);
    expect(good).toHaveBeenCalled();
    expect(consoleErr).toHaveBeenCalled();
    consoleErr.mockRestore();
  });
});
