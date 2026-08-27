# zug-tracker

Live map of German long-distance trains (ICE, IC/EC, night trains), in the
spirit of FlightRadar24. Positions come from GTFS schedules and, where
available, GTFS-Realtime updates - every train reports whether its position is
**realtime-backed** or **schedule-estimated**.

> Status: **Phase 1 complete** - the stack runs end to end. Trains arrive with
> the GTFS importer in Phase 2 and the map in Phase 5.

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

The landing page reports the status of every service, so a green page means the
stack is wired up correctly.

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
| `make import-data` | Import the static GTFS feed (Phase 2) |
| `make check` | Lint, type-check and test both apps |
| `make psql` / `make redis-cli` | Open a database or Redis shell |
| `make clean` | Stop the stack and delete its volumes |

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
      worker/    background loop
    alembic/     migrations
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
- **ADRs** record decisions with real tradeoffs - see [docs/adr](docs/adr).

## Roadmap

| Phase | | |
|---|---|---|
| 1 | Bootstrap the stack | done |
| 2 | Static GTFS importer | next |
| 3 | Position engine | |
| 4 | REST API | |
| 5 | MapLibre map | |
| 6 | GTFS-Realtime ingestion | |
| 7 | SSE streaming | |
| 8 | Smooth client-side animation | |
| 9-12 | Command-center UI, detail panel, activity feed, polish | |
| 13-15 | Tests, CI/CD, deployment | |
