/**
 * The map's look: basemap, initial view and the layers drawn over it.
 *
 * Layer order, bottom to top:
 *
 *   basemap fills and lines
 *   route-casing, route-line, route-stops   (the selected train's route)
 *   basemap labels                           (so city names stay readable)
 *   train-selected                           (ring under the selected train)
 *   trains-realtime                          (ring: realtime-backed; amber if delayed)
 *   trains                                   (one icon per train, coloured by category)
 *
 * Every train is drawn whatever its source: scheduled trains are the plain
 * case, and realtime adds a ring. Until Phase 6 every train is scheduled with
 * no delay, and that alone must already read as a complete map.
 */

import type { AddLayerObject, ExpressionSpecification, LngLatBoundsLike } from "maplibre-gl";

import { GROUP_STYLES, type CategoryGroup } from "@/lib/trains/categories";

/** OpenFreeMap: OpenStreetMap vector tiles, free, no API key, no usage limits. */
export const BASEMAP_STYLE_URL = "https://tiles.openfreemap.org/styles/dark";

/** Germany's extent. Trains beyond it are drawn; the map is only framed on it. */
export const GERMANY_BOUNDS: LngLatBoundsLike = [
  [5.87, 47.27],
  [15.04, 55.06],
];

export const MIN_ZOOM = 3;
export const MAX_ZOOM = 14;

export const SOURCE_TRAINS = "trains";
export const SOURCE_ROUTE = "selected-route";

export const LAYER_TRAINS = "trains";
export const LAYER_TRAINS_REALTIME = "trains-realtime";
export const LAYER_TRAIN_SELECTED = "train-selected";
export const ROUTE_LAYERS = ["route-casing", "route-line", "route-stops"] as const;

export const COLORS = {
  background: "#06080c",
  accent: "#38bdf8",
  ok: "#22c55e",
  warn: "#f59e0b",
} as const;

/** Icon image ids, one per category group and shape (see `icons.ts`). */
export function iconId(group: CategoryGroup, shape: "arrow" | "dot"): string {
  return `train-${group}-${shape}`;
}

/** Icons scale with zoom; the rings around them follow the same curve. */
const ICON_SIZE: ExpressionSpecification = [
  "interpolate",
  ["linear"],
  ["zoom"],
  4,
  0.55,
  8,
  0.9,
  12,
  1.3,
];

const RING_RADIUS: ExpressionSpecification = [
  "interpolate",
  ["linear"],
  ["zoom"],
  4,
  7.5,
  8,
  11,
  12,
  15,
];

const SELECTED_RADIUS: ExpressionSpecification = [
  "interpolate",
  ["linear"],
  ["zoom"],
  4,
  11,
  8,
  15,
  12,
  20,
];

/** Scheduled trains sit slightly back; a stale map dims everything. */
export function trainOpacity(stale: boolean): ExpressionSpecification {
  const scale = stale ? 0.5 : 1;
  return ["case", ["get", "realtime"], scale, 0.85 * scale];
}

export function ringOpacity(stale: boolean): number {
  return stale ? 0.5 : 1;
}

/** The `iconId` for the train's group, as an arrow when it has a bearing. */
const ICON_IMAGE: ExpressionSpecification = [
  "concat",
  "train-",
  ["get", "group"],
  "-",
  ["case", ["get", "has_bearing"], "arrow", "dot"],
];

export const ICON_GROUPS = Object.keys(GROUP_STYLES) as CategoryGroup[];

/** Nothing below z7, a delay from z7, and line plus delay from z8. */
const TRAIN_TEXT: ExpressionSpecification = [
  "step",
  ["zoom"],
  "",
  7,
  ["get", "delay_label"],
  8,
  [
    "case",
    ["get", "delayed"],
    ["concat", ["get", "label"], " ", ["get", "delay_label"]],
    ["get", "label"],
  ],
];

export function routeLayers(): AddLayerObject[] {
  return [
    {
      id: "route-casing",
      type: "line",
      source: SOURCE_ROUTE,
      filter: ["==", ["geometry-type"], "LineString"],
      layout: { "line-join": "round", "line-cap": "round" },
      paint: { "line-color": COLORS.background, "line-width": 6, "line-opacity": 0.7 },
    },
    {
      id: "route-line",
      type: "line",
      source: SOURCE_ROUTE,
      filter: ["==", ["geometry-type"], "LineString"],
      layout: { "line-join": "round", "line-cap": "round" },
      paint: { "line-color": COLORS.accent, "line-width": 2.5, "line-opacity": 0.9 },
    },
    {
      id: "route-stops",
      type: "circle",
      source: SOURCE_ROUTE,
      filter: ["==", ["geometry-type"], "Point"],
      paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 4, 2, 10, 4],
        "circle-color": COLORS.background,
        "circle-stroke-color": COLORS.accent,
        "circle-stroke-width": 1.5,
      },
    },
  ];
}

export function trainLayers(stale: boolean): AddLayerObject[] {
  return [
    {
      id: LAYER_TRAIN_SELECTED,
      type: "circle",
      source: SOURCE_TRAINS,
      filter: selectedFilter(null),
      paint: {
        "circle-radius": SELECTED_RADIUS,
        "circle-color": COLORS.accent,
        "circle-opacity": 0.18,
        "circle-stroke-color": COLORS.accent,
        "circle-stroke-width": 2,
      },
    },
    {
      id: LAYER_TRAINS_REALTIME,
      type: "circle",
      source: SOURCE_TRAINS,
      filter: ["==", ["get", "realtime"], true],
      paint: {
        "circle-radius": RING_RADIUS,
        "circle-opacity": 0,
        "circle-stroke-width": 1.5,
        "circle-stroke-color": ["case", ["get", "delayed"], COLORS.warn, COLORS.ok],
        "circle-stroke-opacity": ringOpacity(stale),
      },
    },
    {
      id: LAYER_TRAINS,
      type: "symbol",
      source: SOURCE_TRAINS,
      layout: {
        "icon-image": ICON_IMAGE,
        "icon-size": ICON_SIZE,
        "icon-rotate": ["get", "bearing"],
        "icon-rotation-alignment": "map",
        // A train is never hidden to make room for another, least of all on
        // a sparse night map.
        "icon-allow-overlap": true,
        "icon-ignore-placement": true,
        "symbol-sort-key": ["get", "sort_key"],
        "text-field": TRAIN_TEXT,
        "text-font": ["Noto Sans Regular"],
        "text-size": 11,
        "text-anchor": "left",
        "text-offset": [1.1, 0],
        "text-optional": true,
      },
      paint: {
        "icon-opacity": trainOpacity(stale),
        "text-color": ["case", ["get", "delayed"], COLORS.warn, "#c9d1d9"],
        "text-halo-color": COLORS.background,
        "text-halo-width": 1.2,
      },
    },
  ];
}

export function selectedFilter(tripId: string | null): ExpressionSpecification {
  return ["==", ["get", "trip_id"], tripId ?? ""];
}
