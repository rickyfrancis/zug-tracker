/**
 * Readable names for the API's response types.
 *
 * `schema.d.ts` is generated from the backend's OpenAPI schema by
 * `make api-types` and never edited by hand; `make api-types-check` fails when
 * it has fallen behind the backend (ADR-0006).
 */

import type { components } from "./schema";

type Schemas = components["schemas"];

export type Health = Schemas["HealthResponse"];
export type DependencyHealth = Schemas["DependencyHealth"];
export type DependencyStatus = Schemas["DependencyStatus"];

export type Train = Schemas["TrainOut"];
export type TrainList = Schemas["TrainListResponse"];
export type TrainDetail = Schemas["TrainDetailResponse"];
export type Stats = Schemas["StatsResponse"];
