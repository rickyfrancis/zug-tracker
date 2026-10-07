/**
 * Whether the positions on screen are current: LIVE or STALE.
 *
 * Two clocks add up to the data's age. The API reports how old its snapshot
 * was when it answered (`snapshot_age_seconds`: always 0 until the worker
 * produces snapshots in Phase 6), and the browser knows how long ago that
 * answer arrived. Both are differences on one clock each, so a skewed client
 * clock cannot flip the state; the response's `timestamp` is never compared
 * with `Date.now()`.
 */

/** Two of the Phase 6 worker's 60-second ticks. */
export const STALE_AFTER_SECONDS = 120;

export type Liveness = "connecting" | "live" | "stale";

export interface Received {
  snapshotAgeSeconds: number;
  /** `Date.now()` when the response arrived. */
  receivedAt: number;
}

export function dataAgeSeconds(received: Received, now: number): number {
  return received.snapshotAgeSeconds + Math.max(0, now - received.receivedAt) / 1000;
}

export function liveness(received: Received | null, now: number): Liveness {
  if (received === null) {
    return "connecting";
  }
  return dataAgeSeconds(received, now) < STALE_AFTER_SECONDS ? "live" : "stale";
}
