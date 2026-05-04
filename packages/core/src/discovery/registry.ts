import type { AvahiAddedPeer, AvahiBrowsedPeer } from "./parse.js";

export type DiscoveredPeer = AvahiAddedPeer | AvahiBrowsedPeer;

/**
 * In-process registry of mDNS-discovered ariaflow-server peers,
 * keyed by Bonjour instance name.
 *
 * Subprocess-driven browsers land in a later phase; the registry is
 * exported standalone so the /api/peers endpoint and any tests can
 * drive it directly.
 */
export class PeerRegistry {
  private readonly peers = new Map<string, DiscoveredPeer>();

  list(): DiscoveredPeer[] {
    return Array.from(this.peers.values());
  }

  get(instance: string): DiscoveredPeer | undefined {
    return this.peers.get(instance);
  }

  upsert(peer: DiscoveredPeer): DiscoveredPeer {
    this.peers.set(peer.instance, peer);
    return peer;
  }

  remove(instance: string): DiscoveredPeer | undefined {
    const prior = this.peers.get(instance);
    this.peers.delete(instance);
    return prior;
  }

  clear(): void {
    this.peers.clear();
  }

  get size(): number {
    return this.peers.size;
  }
}
