/**
 * Access to the zug-tracker API.
 *
 * There are two base URLs and they are not interchangeable:
 *
 *   - Server components run inside the docker network and reach the API by its
 *     compose service name (`http://api:8000`).
 *   - The browser cannot resolve that name, so client-side code must use the
 *     published URL (`http://localhost:8000` in development).
 *
 * `NEXT_PUBLIC_*` values are inlined at build time, hence the literal reference
 * below - it cannot be read dynamically from `process.env`.
 */

import type { Health, Stats, TrainDetail, TrainList } from "./types";

export type * from "./types";

const PUBLIC_API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export function apiBaseUrl(): string {
  if (typeof window === "undefined") {
    return process.env.API_INTERNAL_URL ?? PUBLIC_API_URL;
  }
  return PUBLIC_API_URL;
}

/** The API answered, but not with what was asked for. */
export class ApiError extends Error {
  constructor(readonly status: number) {
    super(`API responded with ${status}`);
    this.name = "ApiError";
  }
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${apiBaseUrl()}${path}`, { signal });
  if (!response.ok) {
    throw new ApiError(response.status);
  }
  return (await response.json()) as T;
}

/** The viewport a train list is asked for, as `GET /trains` takes it. */
export interface TrainQuery {
  /** `west,south,east,north`; see `lib/trains/bbox.ts`. */
  bbox: string;
  zoom: number;
}

export function fetchTrains(query: TrainQuery, signal?: AbortSignal): Promise<TrainList> {
  const params = new URLSearchParams({ bbox: query.bbox, zoom: String(query.zoom) });
  return getJson(`/api/v1/trains?${params}`, signal);
}

/**
 * One trip in detail. `serviceDate` comes from the train list: without it the
 * API picks "the instance running now, else the most recent", which is not
 * necessarily the train that was clicked.
 */
export function fetchTrain(
  tripId: string,
  serviceDate: string,
  signal?: AbortSignal,
): Promise<TrainDetail> {
  const params = new URLSearchParams({ service_date: serviceDate });
  return getJson(`/api/v1/trains/${encodeURIComponent(tripId)}?${params}`, signal);
}

export function fetchStats(signal?: AbortSignal): Promise<Stats> {
  return getJson("/api/v1/stats", signal);
}

export type HealthResult = { ok: true; health: Health } | { ok: false; error: string };

/**
 * Fetch API health. A degraded API answers with 503 and a valid body, so only
 * transport failures and unparseable responses are treated as errors here.
 */
export async function fetchHealth(): Promise<HealthResult> {
  try {
    const response = await fetch(`${apiBaseUrl()}/api/v1/health`, {
      signal: AbortSignal.timeout(5000),
    });

    if (!response.ok && response.status !== 503) {
      return { ok: false, error: `API responded with ${response.status}` };
    }

    return { ok: true, health: (await response.json()) as Health };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : "unreachable" };
  }
}
