# zug-tracker web

Next.js 16 (App Router, Turbopack) and MapLibre GL JS. `/` is the live map and
`/status` reports the stack's health. Run it through `make dev` at the repo
root, which also starts the API it polls.

## Layout

```text
src/app/                  routes: / (map), /status
src/components/map/       the map's React shell: lifecycle, HUD, legend, overlays
src/lib/api/              typed API client; schema.d.ts is generated, never edited
src/lib/map/              MapLibre outside React: controller, layers, icons
src/lib/trains/           framework-free logic: bbox, features, liveness, poller
scripts/                  copy-maplibre-worker.mjs (runs before dev and build)
```

MapLibre and the poller live outside React. The map component creates both once
per mount and tears them down on unmount, so StrictMode's double mount and Fast
Refresh each leave exactly one map. Train positions go straight into a GeoJSON
source and never pass through React state.

`maplibre-gl` 6 loads its web worker relative to its own module URL, which a
bundler breaks. `predev` and `prebuild` therefore copy the self-contained
worker to `public/vendor/` (git-ignored), and the map loads it from there.

## Scripts

| Command | |
|---|---|
| `npm run dev` | Dev server (normally run by `make dev`) |
| `npm run lint` | ESLint |
| `npm run typecheck` | Route types plus `tsc --noEmit` |
| `npm test` | Vitest unit tests for `src/lib` |
| `npm run build` | Production build (`output: "standalone"`) |

## API types

The types in `src/lib/api/schema.d.ts` are generated from the backend's OpenAPI
schema ([ADR-0006](../../docs/adr/0006-generate-web-api-types-from-openapi.md)).
From the repo root:

```bash
make api-types         # regenerate after changing an API response model
make api-types-check   # fails if the committed types are behind the backend
```

## Tests

Vitest runs in a node environment against the pure modules in `src/lib`:
viewport bbox, train features, liveness and the poller (with fake timers). The
map itself is WebGL and is checked in a browser. A Playwright smoke test is
planned for Phase 13.
