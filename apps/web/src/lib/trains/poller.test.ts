import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { TrainList, TrainQuery } from "@/lib/api";
import { makeTrainList } from "@/test/trains";

import {
  MAX_BACKOFF_MS,
  POLL_INTERVAL_MS,
  REQUEST_TIMEOUT_MS,
  TrainPoller,
  VIEWPORT_DEBOUNCE_MS,
} from "./poller";

const GERMANY: TrainQuery = { bbox: "5.87,47.27,15.04,55.06", zoom: 5.5 };
const BERLIN: TrainQuery = { bbox: "13,52,14,53", zoom: 9 };

interface Call {
  query: TrainQuery;
  signal: AbortSignal;
  resolve: (list: TrainList) => void;
  reject: (error: unknown) => void;
}

/** A fetch whose responses the test hands out one by one. */
function controlledFetch() {
  const calls: Call[] = [];
  const fetchTrains = vi.fn(
    (query: TrainQuery, signal: AbortSignal) =>
      new Promise<TrainList>((resolve, reject) => {
        calls.push({ query, signal, resolve, reject });
        signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
      }),
  );
  return { calls, fetchTrains };
}

function setup() {
  const { calls, fetchTrains } = controlledFetch();
  const onData = vi.fn();
  const onError = vi.fn();
  const poller = new TrainPoller({ fetchTrains, onData, onError });
  return { poller, calls, fetchTrains, onData, onError };
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("TrainPoller", () => {
  it("waits for a viewport before fetching", async () => {
    const { poller, fetchTrains } = setup();
    poller.start();
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS);
    expect(fetchTrains).not.toHaveBeenCalled();
  });

  it("fetches the first viewport at once and then on a fixed interval", async () => {
    const { poller, calls, onData } = setup();
    poller.start();
    poller.setViewport(GERMANY);
    expect(calls).toHaveLength(1);
    expect(calls[0].query).toEqual(GERMANY);

    const list = makeTrainList();
    calls[0].resolve(list);
    await vi.advanceTimersByTimeAsync(0);
    expect(onData).toHaveBeenCalledWith(list, Date.now());

    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS - 1);
    expect(calls).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(calls).toHaveLength(2);
  });

  it("never overlaps requests: the interval starts when a response settles", async () => {
    const { poller, calls } = setup();
    poller.start();
    poller.setViewport(GERMANY);

    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 0.5);
    expect(calls).toHaveLength(1);

    calls[0].resolve(makeTrainList());
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS - 1);
    expect(calls).toHaveLength(1);
  });

  it("debounces a viewport change, aborts the request in flight and refetches", async () => {
    const { poller, calls, onData } = setup();
    poller.start();
    poller.setViewport(GERMANY);

    poller.setViewport({ bbox: "1,1,2,2", zoom: 7 });
    poller.setViewport(BERLIN);
    await vi.advanceTimersByTimeAsync(VIEWPORT_DEBOUNCE_MS - 1);
    expect(calls).toHaveLength(1);

    await vi.advanceTimersByTimeAsync(1);
    expect(calls).toHaveLength(2);
    expect(calls[0].signal.aborted).toBe(true);
    expect(calls[1].query).toEqual(BERLIN);

    calls[1].resolve(makeTrainList());
    await vi.advanceTimersByTimeAsync(0);
    expect(onData).toHaveBeenCalledTimes(1);
  });

  it("drops a superseded response even if it arrives despite the abort", async () => {
    const { poller, calls, onData, onError } = setup();
    poller.start();
    poller.setViewport(GERMANY);
    const stale = calls[0];

    poller.setViewport(BERLIN);
    await vi.advanceTimersByTimeAsync(VIEWPORT_DEBOUNCE_MS);
    stale.resolve(makeTrainList());
    await vi.advanceTimersByTimeAsync(0);

    expect(onData).not.toHaveBeenCalled();
    expect(onError).not.toHaveBeenCalled();
  });

  it("reports failures and backs off, then resets after a success", async () => {
    const { poller, calls, onError } = setup();
    poller.start();
    poller.setViewport(GERMANY);

    calls[0].reject(new Error("down"));
    await vi.advanceTimersByTimeAsync(0);
    expect(onError).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 2 - 1);
    expect(calls).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(calls).toHaveLength(2);

    calls[1].reject(new Error("down"));
    await vi.advanceTimersByTimeAsync(MAX_BACKOFF_MS);
    expect(calls).toHaveLength(3);

    calls[2].reject(new Error("down"));
    await vi.advanceTimersByTimeAsync(MAX_BACKOFF_MS);
    expect(calls).toHaveLength(4);

    calls[3].resolve(makeTrainList());
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS);
    expect(calls).toHaveLength(5);
  });

  it("treats a request that times out as a failure", async () => {
    const { poller, calls, onError } = setup();
    poller.start();
    poller.setViewport(GERMANY);

    await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS);
    expect(calls[0].signal.aborted).toBe(true);
    expect(onError).toHaveBeenCalledTimes(1);
  });

  it("stops polling when stopped and fetches at once when started again", async () => {
    const { poller, calls, onError } = setup();
    poller.start();
    poller.setViewport(GERMANY);

    poller.stop();
    expect(calls[0].signal.aborted).toBe(true);
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 4);
    expect(calls).toHaveLength(1);
    expect(onError).not.toHaveBeenCalled();

    poller.start();
    expect(calls).toHaveLength(2);
  });

  it("remembers a viewport set while stopped", async () => {
    const { poller, calls } = setup();
    poller.setViewport(BERLIN);
    expect(calls).toHaveLength(0);
    poller.start();
    expect(calls[0].query).toEqual(BERLIN);
  });
});
