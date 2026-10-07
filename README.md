# zug-tracker

Live map of German long-distance trains (ICE, IC/EC, night trains), in the
spirit of FlightRadar24. Positions come from GTFS schedules and, where
available, GTFS-Realtime updates - every train reports whether its position is
**realtime-backed** or **schedule-estimated**.

> Status: **Phase 4 complete** - the API serves every running train's estimated
> position at `/api/v1/trains`. The map arrives in Phase 5.

## Architecture

```text
Static GTFS ──► Worker ──► PostgreSQL + PostGIS ──┐
                                                  │
GTFS-Realtime ─► Worker ──► Redis ────────────────┤
                                                  ▼
                                          FastAPI (position engine)
                                                  │
                                            REST + SSE
                                                  ▼
                                    Next.js + MapLibre GL JS
```

| Service | Role |
|---|---|
| `web` | Next.js frontend, MapLibre map, client-side animation |
| `api` | FastAPI: REST endpoints, SSE stream, position estimation |
| `worker` | GTFS import and realtime polling - same image as `api`, different command |
| `postgres` | PostGIS-enabled durable transport data |
| `redis` | Transient realtime state only; nothing here needs to survive a restart |

`api` and `worker` share one Python image
([ADR-0001](docs/adr/0001-single-repo-shared-python-image.md)).

## Quickstart

Requires Docker with Compose v2.

```bash
cp .env.example .env
make dev            # http://localhost:3000, API at http://localhost:8000/docs
make migrate        # apply database migrations
```

The worker imports the timetable itself on startup (~10s) and re-checks the feed
daily, so there is no manual import step. `make import-data` still exists to
force the issue.

The landing page reports the status of every service, so a green page means the
stack is wired up correctly. `GET /api/v1/health` additionally reports which
timetable is being served and when it expires.

For host-side tooling (linting, tests, editor integration):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # backend
cd apps/web && npm install                        # frontend
```

## Commands

Run `make` for the full list.

| Command | Description |
|---|---|
| `make dev` | Full stack with hot reload |
| `make up` / `make down` | Production-shaped stack / stop everything |
| `make logs s=api` | Follow one service's logs |
| `make migrate` | Apply migrations |
| `make revision m="..."` | Create a migration |
| `make import-data` | Import the static GTFS feed now, ahead of the worker's daily refresh (`force=1` to re-import unchanged data) |
| `make prune-data` | Delete superseded datasets beyond the retention limit |
| `make positions` | Print every running train's estimated position, now or `at=<ISO 8601>` |
| `make check` | Lint, type-check and test both apps |
| `make test-fast` | Backend tests that need no database container |
| `make psql` / `make redis-cli` | Open a database or Redis shell |
| `make clean` | Stop the stack and delete its volumes |

## API

Interactive docs at <http://localhost:8000/docs>.

| Endpoint | Returns |
|---|---|
| `GET /api/v1/trains` | Every running train and its current segment. Filters: `?bbox=west,south,east,north`, `?category=ICE,IC`, `?zoom=` |
| `GET /api/v1/trains/{trip_id}` | One trip: stops, route as GeoJSON, position while running. `?service_date=` picks the day |
| `GET /api/v1/stats` | Running trains by category, status and position source |
| `GET /api/v1/health` | Dependencies, worker heartbeat, active dataset and its expiry |

Positions are segment state, not just a point: the two stations a train is
between and when it leaves and arrives, so a client can keep placing it between
updates. Every response carries `timestamp` and `snapshot_age_seconds`. While
positions are computed per request the age is always 0; from Phase 6 they come
from the worker and a growing age means the data is stale
([ADR-0005](docs/adr/0005-serve-positions-as-a-snapshot.md)). A `bbox` keeps
trains whose *segment* overlaps it, so trains about to drive into view are
already in the payload.

## The timetable data

The feed is [gtfs.de](https://gtfs.de)'s `fv_free` (data from DELFI e.V.):
~400 KB, ~5,400 trips across ICE, IC, EC, ECE, RJ and EN. The worker downloads
it, loads it under a new **dataset**, expands it into dated trips, and flips a
pointer to the new version - so importing again is always safe.

One release, the 2026-08-29 one, to give a sense of scale - every count shifts a
little with each refresh:

```text
5,354 trips     96 routes      13 agencies      1,222 stops
53,411 stop times  ->  33,278 trip instances  +  311,060 stop-time instances
```

Five facts about this feed shaped the schema, and each cost a design decision:

- **There are no train numbers.** `trips.txt` has three columns
  (`route_id, service_id, trip_id`) and no `trip_short_name`, so "ICE 507"
  cannot be rendered. Trains are identified by line and destination instead.
- **`route_short_name` is often just a category.** 953 trips (17%) sit on routes
  named plainly `ICE` or `EC`, with no line number, and `route_long_name` is
  empty on every route. `Route` therefore stores `category` and a *nullable*
  `line`, plus both raw names verbatim.
- **Service dates are not calendar dates.** 60 service_ids exist only in
  `calendar_dates.txt` with no weekly pattern, 16% of trips cross midnight, and
  stop times reach hour **35**. All of it is resolved once at import into
  absolute UTC ([ADR-0003](docs/adr/0003-materialized-trip-instances.md)).
- **The feed expires after 31 days.** The worker therefore re-checks it daily
  (`GTFS_REFRESH_INTERVAL_SECONDS`) and re-imports when the bytes change; an
  unchanged feed answers `304` and costs nothing. `/api/v1/health` reports the
  active dataset's `valid_to` and days remaining, which is how you find out that
  the refresh stopped.
- **Parent stations are named for local transit.** `S+U Berlin Hauptbahnhof`
  and `Hamburg, Hamburg Hbf` are parent stations; their platforms say
  `Berlin Hbf` and `Hamburg Hbf`. Platforms are not uniformly clean either
  (`München Hbf Gl.5-10`, `Bahnhof, Wittenberge`), so the import chooses each
  station's `display_name` from its most-called comma-free platform name, with
  track ranges stripped.

Every CSV is parsed **by header name**: `routes.txt` ships as
`route_long_name, route_short_name, agency_id, route_type, route_id`, and
positional parsing against that header corrupts silently.

## Layout

```text
apps/
  api/           FastAPI application and worker (one image, two commands)
    app/
      api/       thin HTTP handlers
      core/      configuration, database, redis, logging
      models/    SQLAlchemy models
      schemas/   Pydantic request/response models
      repositories/  database access
      services/  domain and business logic
      providers/ external transit data sources (GTFS static, GTFS-RT)
      worker/    background jobs (heartbeat, daily feed refresh)
      cli.py     data management commands (import-data, prune)
    alembic/     migrations
    tests/db/    tests needing a real PostGIS container
  web/           Next.js frontend
docs/adr/        architecture decision records
infra/postgres/  database init scripts
data/            downloaded GTFS feeds (git-ignored)
```

## Conventions

- **Thin controllers.** Route handlers delegate to services; GTFS parsing,
  position estimation and database access never live in a route.
- **One database driver.** psycopg (v3) serves both the async application
  engine and synchronous Alembic migrations, so a single `DATABASE_URL` scheme
  (`postgresql+psycopg://`) works everywhere.
- **Two API URLs.** Server components reach the API at `API_INTERNAL_URL`
  (`http://api:8000`); the browser uses `NEXT_PUBLIC_API_URL`. Both are
  resolved in one place, `apps/web/src/lib/api.ts`.
- **Conventional Commits** (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`,
  `chore:`) on short-lived branches off `main`, which stays deployable.
- **Datasets, not upserts.** Every GTFS table is keyed by
  `(dataset_id, <gtfs id>)` and an import writes under a new dataset before a
  pointer flips to it, so re-importing can neither orphan rows nor serve an
  empty map ([ADR-0002](docs/adr/0002-versioned-dataset-atomic-swap.md)).
- **Real database in tests where a fake would prove nothing.** Composite foreign
  keys, the partial unique index, `COPY` and the atomic swap are tested against
  PostGIS via testcontainers, marked `db`; everything else runs without Docker
  (`make test-fast`).
- **ADRs** record decisions with real tradeoffs - see [docs/adr](docs/adr).

## Roadmap

| Phase | | |
|---|---|---|
| 1 | Bootstrap the stack | done |
| 2 | Static GTFS importer | done |
| 3 | Position engine | done: estimator and straight-line geometry; curated corridors deferred until after Phase 5 |
| 4 | REST API | done |
| 5 | MapLibre map | |
| 6 | GTFS-Realtime ingestion | |
| 7 | SSE streaming | |
| 8 | Smooth client-side animation | |
| 9-12 | Command-center UI, detail panel, activity feed, polish | |
| 13-15 | Tests, CI/CD, deployment | |
