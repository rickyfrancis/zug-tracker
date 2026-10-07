/**
 * Trains as GeoJSON for the map's `trains` source.
 *
 * Everything the style distinguishes is decided here, as plain properties, so
 * that the layer expressions stay lookups and the decisions stay testable.
 */

import type { Feature, FeatureCollection, Point } from "geojson";

import type { Train } from "@/lib/api";

import { categoryGroup, GROUP_STYLES, type CategoryGroup } from "./categories";

/**
 * A train counts as delayed from six minutes late: DB's own punctuality
 * line. The measured median delay is four minutes, so a one-minute threshold
 * would paint most of the fleet as late. Phase 9's delayed count uses this too.
 */
export const DELAYED_AT_SECONDS = 360;

export interface TrainProperties {
  trip_id: string;
  service_date: string;
  label: string;
  destination: string;
  group: CategoryGroup;
  /** Degrees clockwise from north; 0 when unknown (see `has_bearing`). */
  bearing: number;
  has_bearing: boolean;
  realtime: boolean;
  delayed: boolean;
  /** `+12′` for a delayed train, else empty. */
  delay_label: string;
  sort_key: number;
}

export type TrainFeatureCollection = FeatureCollection<Point, TrainProperties>;

export function trainsToFeatureCollection(trains: readonly Train[]): TrainFeatureCollection {
  return { type: "FeatureCollection", features: trains.map(trainToFeature) };
}

export function trainToFeature(train: Train): Feature<Point, TrainProperties> {
  const group = categoryGroup(train.category);
  const delayed = isDelayed(train.delay_seconds);
  return {
    type: "Feature",
    geometry: { type: "Point", coordinates: [train.lon, train.lat] },
    properties: {
      trip_id: train.trip_id,
      service_date: train.service_date,
      label: train.label,
      destination: train.destination,
      group,
      bearing: train.bearing ?? 0,
      has_bearing: train.bearing !== null,
      realtime: train.position_source === "realtime",
      delayed,
      delay_label: delayed ? `+${Math.round((train.delay_seconds ?? 0) / 60)}′` : "",
      sort_key: GROUP_STYLES[group].order,
    },
  };
}

/** `null` means no realtime data, which is not a delay. */
export function isDelayed(delaySeconds: number | null): boolean {
  return delaySeconds !== null && delaySeconds >= DELAYED_AT_SECONDS;
}
