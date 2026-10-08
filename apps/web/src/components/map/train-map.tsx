"use client";

import dynamic from "next/dynamic";

/**
 * MapLibre needs `window` and WebGL, so the map is only ever rendered in the
 * browser. `ssr: false` is allowed only in a client component, hence this one.
 */
const MapView = dynamic(() => import("./map-view"), {
  ssr: false,
  loading: () => (
    <div className="flex h-full w-full items-center justify-center bg-background">
      <span className="font-mono text-xs uppercase tracking-widest text-muted">
        Loading map…
      </span>
    </div>
  ),
});

export function TrainMap() {
  return <MapView />;
}
