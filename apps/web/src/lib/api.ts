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

const PUBLIC_API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export function apiBaseUrl(): string {
  if (typeof window === "undefined") {
    return process.env.API_INTERNAL_URL ?? PUBLIC_API_URL;
  }
  return PUBLIC_API_URL;
}

export type DependencyStatus = "ok" | "error" | "unknown";

export interface DependencyHealth {
  name: string;
  status: DependencyStatus;
  latency_ms: number | null;
  detail: string | null;
}

export interface HealthResponse {
  status: "ok" | "degraded";
  environment: string;
  checked_at: string;
  dependencies: DependencyHealth[];
}

export type HealthResult =
  | { ok: true; health: HealthResponse }
  | { ok: false; error: string };

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

    return { ok: true, health: (await response.json()) as HealthResponse };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : "unreachable" };
  }
}
