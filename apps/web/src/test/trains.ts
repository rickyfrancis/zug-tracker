import type { Train, TrainList } from "@/lib/api";

/** A running ICE between Leipzig and Erfurt; override what a test is about. */
export function makeTrain(overrides: Partial<Train> = {}): Train {
  return {
    trip_id: "1579104",
    service_date: "2026-10-07",
    label: "ICE 10",
    destination: "München Hbf",
    category: "ICE",
    operator: "DB Fernverkehr AG",
    status: "moving",
    position_source: "scheduled",
    delay_seconds: null,
    lat: 51.2,
    lon: 11.9,
    bearing: 231.5,
    progress: 0.4,
    segment: {
      from_station: { station_id: "1", name: "Leipzig Hbf", lat: 51.345, lon: 12.382 },
      to_station: { station_id: "2", name: "Erfurt Hbf", lat: 50.972, lon: 11.038 },
      departure_utc: "2026-10-07T10:00:00Z",
      arrival_utc: "2026-10-07T10:43:00Z",
      geometry_ref: null,
    },
    ...overrides,
  };
}

export function makeTrainList(trains: Train[] = [makeTrain()], snapshotAgeSeconds = 0): TrainList {
  return { timestamp: "2026-10-07T10:17:00Z", snapshot_age_seconds: snapshotAgeSeconds, trains };
}
