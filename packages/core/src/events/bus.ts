export type EventListener = (event: string, data: unknown) => void;

/**
 * In-process pub/sub used to bridge storage-layer events (action log
 * appends, session lifecycle, etc.) to live HTTP/SSE consumers.
 *
 * Kept deliberately small — no priorities, no async listeners. If a
 * listener throws, the error is surfaced via console.error and the
 * remaining listeners still run.
 */
export class EventBus {
  private readonly listeners = new Set<EventListener>();

  publish(event: string, data: unknown): void {
    for (const listener of [...this.listeners]) {
      try {
        listener(event, data);
      } catch (err) {
        console.error("EventBus listener threw:", err);
      }
    }
  }

  subscribe(listener: EventListener): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  get size(): number {
    return this.listeners.size;
  }
}
