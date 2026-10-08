"use client";

import "maplibre-gl/dist/maplibre-gl.css";

import { useRef } from "react";

import { EmptyState } from "./empty-state";
import { MapHud } from "./map-hud";
import { MapLegend } from "./map-legend";
import { SelectionChip } from "./selection-chip";
import { useTrainMap } from "./use-train-map";

export default function MapView() {
  const containerRef = useRef<HTMLDivElement>(null);
  const map = useTrainMap(containerRef);

  return (
    <div className="relative h-full w-full bg-background">
      {/* Sized, not positioned: MapLibre's unlayered stylesheet sets
          `position: relative` on the container, which beats Tailwind's layers. */}
      <div ref={containerRef} className="h-full w-full" />

      <div className="pointer-events-none absolute inset-x-3 top-3 flex flex-col items-start gap-2 sm:flex-row sm:items-start sm:justify-between">
        <MapHud liveness={map.liveness} snapshot={map.snapshot} failing={map.failing} />
        <SelectionChip
          selection={map.selection}
          notice={map.notice}
          onClose={() => map.select(null)}
        />
      </div>

      {map.snapshot?.trainCount === 0 && (
        <EmptyState networkTotal={map.networkTotal} onShowGermany={map.resetView} />
      )}

      <MapLegend />
    </div>
  );
}
