/**
 * Polls `GET /trains` for the current viewport.
 *
 * Plain polling is Phase 5's transport; Phase 7 replaces it with SSE, so this
 * owns nothing but timing:
 *
 *   - a `setTimeout` chain, so the next request is only scheduled once the
 *     last has settled and requests never overlap;
 *   - a viewport change is debounced, aborts the request in flight and fetches
 *     at once, restarting the interval;
 *   - failures back off, and the last good data is left alone;
 *   - `stop()` (a hidden tab) cancels everything; `start()` fetches at once.
 */

import type { TrainList, TrainQuery } from "@/lib/api";

export const POLL_INTERVAL_MS = 15_000;
export const VIEWPORT_DEBOUNCE_MS = 300;
export const REQUEST_TIMEOUT_MS = 10_000;
export const MAX_BACKOFF_MS = 60_000;

export interface TrainPollerOptions {
  fetchTrains: (query: TrainQuery, signal: AbortSignal) => Promise<TrainList>;
  onData: (list: TrainList, receivedAt: number) => void;
  onError: (error: unknown) => void;
}

export class TrainPoller {
  private query: TrainQuery | null = null;
  private running = false;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private inFlight: AbortController | null = null;
  /** Bumped by every request and by `stop()`; a settled request that no longer
   * matches is ignored, whatever the browser did with the abort. */
  private requestId = 0;
  private failures = 0;

  constructor(private readonly options: TrainPollerOptions) {}

  start(): void {
    if (this.running) {
      return;
    }
    this.running = true;
    if (this.query !== null) {
      void this.poll();
    }
  }

  stop(): void {
    this.running = false;
    this.requestId += 1;
    this.clearTimer();
    this.inFlight?.abort();
    this.inFlight = null;
  }

  setViewport(query: TrainQuery): void {
    const first = this.query === null;
    this.query = query;
    if (!this.running) {
      return;
    }
    this.clearTimer();
    if (first) {
      void this.poll();
    } else {
      this.timer = setTimeout(() => void this.poll(), VIEWPORT_DEBOUNCE_MS);
    }
  }

  private async poll(): Promise<void> {
    const query = this.query;
    if (!this.running || query === null) {
      return;
    }
    this.clearTimer();
    this.inFlight?.abort();

    const id = ++this.requestId;
    const controller = new AbortController();
    this.inFlight = controller;
    const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

    try {
      const list = await this.options.fetchTrains(query, controller.signal);
      if (id !== this.requestId) {
        return;
      }
      this.failures = 0;
      this.options.onData(list, Date.now());
    } catch (error) {
      // A superseded request was aborted on purpose. One that is still current
      // can only have been aborted by its timeout, which is a real failure.
      if (id !== this.requestId) {
        return;
      }
      this.failures += 1;
      this.options.onError(error);
    } finally {
      clearTimeout(timeout);
      if (id === this.requestId) {
        this.inFlight = null;
        this.timer = setTimeout(() => void this.poll(), this.nextDelay());
      }
    }
  }

  /** 15 s, then 30 s and 60 s after consecutive failures. */
  private nextDelay(): number {
    return Math.min(POLL_INTERVAL_MS * 2 ** this.failures, MAX_BACKOFF_MS);
  }

  private clearTimer(): void {
    if (this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
    }
  }
}
