"use client";

import { type RefObject, useCallback, useEffect, useRef, useState } from "react";

import { ApiError, fetchStats, fetchTrain, fetchTrains } from "@/lib/api";
import { type SelectedTrain, TrainMapController } from "@/lib/map/train-map-controller";
import { trainsToFeatureCollection } from "@/lib/trains/features";
import { type Liveness, liveness, type Received } from "@/lib/trains/liveness";
import { TrainPoller } from "@/lib/trains/poller";

interface Snapshot extends Received {
  trainCount: number;
  timestamp: string;
}

export interface TrainMapState {
  liveness: Liveness;
  /** `null` until the first response. */
  snapshot: Snapshot | null;
  /** The last poll failed; the map still shows the one before. */
  failing: boolean;
  /** Trains running anywhere, fetched only while the view is empty. */
  networkTotal: number | null;
  selection: SelectedTrain | null;
  notice: string | null;
  select: (train: SelectedTrain | null) => void;
  resetView: () => void;
}

/**
 * Wires the map, the poller and the selection together. The map and the
 * poller live outside React; this holds only what the overlays display.
 */
export function useTrainMap(containerRef: RefObject<HTMLDivElement | null>): TrainMapState {
  const controllerRef = useRef<TrainMapController | null>(null);
  const detailRequestRef = useRef<AbortController | null>(null);

  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [failing, setFailing] = useState(false);
  const [networkTotal, setNetworkTotal] = useState<number | null>(null);
  const [selection, setSelection] = useState<SelectedTrain | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const now = useNow(1000);
  const state = liveness(snapshot, now);

  const select = useCallback((train: SelectedTrain | null) => {
    detailRequestRef.current?.abort();
    detailRequestRef.current = null;
    setSelection(train);
    setNotice(null);

    const controller = controllerRef.current;
    controller?.setSelected(train?.tripId ?? null);
    controller?.setRoute(null);
    if (train === null) {
      return;
    }

    const request = new AbortController();
    detailRequestRef.current = request;
    fetchTrain(train.tripId, train.serviceDate, request.signal)
      .then((detail) => controllerRef.current?.setRoute(detail))
      .catch((error: unknown) => {
        if (request.signal.aborted) {
          return;
        }
        if (error instanceof ApiError && error.status === 404) {
          // Trip ids change with each timetable release.
          setSelection(null);
          controllerRef.current?.setSelected(null);
          setNotice("That train is no longer in the timetable.");
        } else {
          setNotice("Could not load this train's route.");
        }
      });
  }, []);

  useEffect(() => {
    const container = containerRef.current;
    if (container === null) {
      return;
    }
    const lifetime = new AbortController();
    let viewWasEmpty = false;

    const poller = new TrainPoller({
      fetchTrains,
      onData: (list, receivedAt) => {
        controller.setTrains(trainsToFeatureCollection(list.trains));
        setFailing(false);
        setSnapshot({
          snapshotAgeSeconds: list.snapshot_age_seconds,
          receivedAt,
          trainCount: list.trains.length,
          timestamp: list.timestamp,
        });

        const viewIsEmpty = list.trains.length === 0;
        if (viewIsEmpty && !viewWasEmpty) {
          fetchStats(lifetime.signal)
            .then((stats) => setNetworkTotal(stats.total))
            .catch(() => setNetworkTotal(null));
        } else if (!viewIsEmpty) {
          setNetworkTotal(null);
        }
        viewWasEmpty = viewIsEmpty;
      },
      onError: () => setFailing(true),
    });

    const controller = new TrainMapController(container, {
      onViewportChange: (query) => poller.setViewport(query),
      onSelect: select,
    });
    controllerRef.current = controller;

    const onVisibilityChange = () => (document.hidden ? poller.stop() : poller.start());
    document.addEventListener("visibilitychange", onVisibilityChange);
    poller.start();

    return () => {
      document.removeEventListener("visibilitychange", onVisibilityChange);
      lifetime.abort();
      detailRequestRef.current?.abort();
      poller.stop();
      controller.destroy();
      controllerRef.current = null;
    };
  }, [containerRef, select]);

  useEffect(() => {
    controllerRef.current?.setStale(state === "stale");
  }, [state]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        select(null);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [select]);

  const resetView = useCallback(() => controllerRef.current?.resetView(), []);

  return {
    liveness: state,
    snapshot,
    failing,
    networkTotal,
    selection,
    notice,
    select,
    resetView,
  };
}

/** `Date.now()`, refreshed on an interval; 0 until the first tick. */
function useNow(intervalMs: number): number {
  const [now, setNow] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}
