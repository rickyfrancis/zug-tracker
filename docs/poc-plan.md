# zug-tracker: Proof of Concept Implementation Plan

> **Revision note.** This plan was stress-tested against the real data sources on
> 2026-08-28. Every figure in section 3 was measured, not estimated. Several
> original assumptions did not survive contact with the feeds — most importantly
> **train numbers do not exist in the source data**. Decisions that changed are
> marked **[revised]**.

## 1. Goal

Build **zug-tracker**, a portfolio-grade German train tracking application inspired by FlightRadar24.

The POC should demonstrate:

- Germany-wide train activity
- Dark command-center style interface
- Trains moving smoothly across an interactive map
- Estimated train positions when GPS is unavailable
- Realtime delay data where available
- Train details, routes, stations and activity
- Fully open-source stack
- Free external data sources
- Dockerized development and deployment
- Easy continuous deployment through Coolify
- Architecture clean enough to explain confidently in technical interviews

The POC should prioritize **visual impact + clean engineering**, not perfect railway simulation.

---

# 2. POC Scope

Start with **German long-distance trains only**:

| Category | Trips in feed |
| -------- | ------------- |
| ICE      | 3,936         |
| IC       | 902           |
| EC       | 461           |
| ECE      | 162           |
| RJ (Railjet)   | 73      |
| EN (EuroNight) | 55      |

All six categories are confirmed present in the source feed. Regional trains are
explicitly a **future** addition, but the interfaces described in Phase 2 and
Phase 4 are designed now so that adding them is an import, not a redesign.

### Position strategy

Every train should have a position source:

```text
REALTIME
SCHEDULED
```

If realtime information exists:

```text
GTFS schedule
    +
GTFS-RT delay/update
    ↓
estimated current position
```

Otherwise:

```text
GTFS schedule
    ↓
scheduled estimated position
```

The source feed contains **zero vehicle positions** — GPS is not available at
any price. Position estimation is therefore not a simplification, it is the
only possible approach.

Measured realtime coverage is **~60% of in-motion long-distance trains**, so the
REALTIME/SCHEDULED distinction is a real and roughly even split, not a rare
edge case. It is worth surfacing prominently in the UI.

### Cross-border trains **[revised]**

The feed contains international operators (SBB, ÖBB, NS, PKP, SNCF, ČD, DSB,
MÁV, ZSSK) and stops as far out as Stockholm, Paris and Warszawa.

**Decision: render full trips, frame the map on Germany.** Trains that run off
toward Basel or Wien read as correct behaviour. Clipping trips at the border
would make trains vanish mid-journey; filtering to wholly-German trips would
delete most EC/ECE/EN/RJ traffic, including the night trains.

This supersedes the original "multiple countries" exclusion, which is now
narrowed to mean *do not add new national feeds*.

---

# 3. Data Sources — Verified 2026-08-28

Both feeds were downloaded, parsed and cross-checked. These numbers are
measurements from the live sources.

## 3.1 Static feed

```text
https://download.gtfs.de/germany/fv_free/latest.zip
```

Published by **gtfs.de**, data from **DELFI e.V.** 415 KB.

```text
5,589 trips        95 routes         13 agencies
1,198 stops        (631 platform-level + 567 parent stations)
54,928 stop_times
```

### Structural facts that affect implementation

**No `trip_short_name`.** `trips.txt` contains exactly three columns:

```text
route_id, service_id, trip_id
```

There are **no train numbers**. "ICE 507" cannot be rendered from this feed.
What exists instead:

- `route_short_name` — a *line*, e.g. `ICE 10`, `ICE 42`, `IC 55`
- `stop_headsign` — **100% populated**, e.g. `Warszawa Wschodnia`

**No `shapes.txt`.** There is no route geometry of any kind. Corridor geometry
must be supplied by us (Phase 3).

**Non-standard column order.** `routes.txt` ships as
`route_long_name, route_short_name, agency_id, route_type, route_id`.
Parse every CSV **by header name**. Positional parsing corrupts silently.

**Feed validity is 31 days.** The current feed covers `20260822` → `20260921`.
An expired feed produces an empty map. Re-import must be automated (Phase 2).

**16% of trips cross midnight.** 889 of 5,589 trips contain `stop_times` past
`24:00:00`, with a maximum hour of **35**. This is not an edge case.

**`stop_times` reference platform-level stops**, all of which carry a
`parent_station`. Resolve to the parent station for display and for geometry,
or segments between platforms of the same station will have near-zero length.

## 3.2 Realtime feed

```text
https://realtime.gtfs.de/realtime-free.pb
```

```text
51.9 MB per fetch      FULL_DATASET (not incremental)
191,215 entities  =  88,343 trip_updates + 102,872 alerts
0 vehicle positions
parse time ≈ 0.23 s
```

**The ID namespace is shared with the static feed.** Verified by stop-sequence
alignment: 185 of 191 matching trip_ids have perfectly identical stop sequences.
Joining RT to static on `trip_id` is correct.

**The feed is nationwide, not long-distance.** 88,343 trip_updates arrive to
serve roughly 250 long-distance trains. ~97% of each fetch is discarded today —
and is exactly the data required when regional trains are added later.

### Measured coverage, Friday 12:40

```text
1,113  trips scheduled that day
  253  trips in motion
  151  of those carry realtime      (59.7%)

13,818  vehicles in motion nationwide (all modes)
```

### Measured delays

```text
median   240 s  (4 min)
p90    1,620 s  (27 min)
max    6,900 s  (115 min)
on time (<60 s): 34.2%
```

## 3.3 Bandwidth

The realtime feed is a full snapshot with no filtered endpoint. Poll cost:

```text
poll every  10s ->  5.19 MB/s   448.5 GB/day   (original .env default)
poll every  30s ->  1.73 MB/s   149.5 GB/day
poll every  60s ->  0.87 MB/s    74.8 GB/day   <- chosen
poll every 300s ->  0.17 MB/s    15.0 GB/day
```

**`WORKER_INTERVAL_SECONDS=60`.** [revised — was 10]

This is *ingress bandwidth*, not storage; stored state stays in the kilobytes.
Delays change on the order of minutes, and Phase 8's client-side extrapolation
keeps motion smooth regardless of poll rate, so 60s costs nothing visually.

Because the feed is already nationwide, **adding regional trains later costs
zero additional ingress.** This budget is pre-paid.

## 3.4 Segment geometry

Straight-line interpolation error is proportional to segment length. Measured
distances between consecutive stops:

```text
median  36.2 km     p90  94.3 km
p99    192.9 km     max 496.8 km
8.7% of segments exceed 100 km
```

There are 1,044 distinct station pairs (795 wholly German), so exhaustive
curation is infeasible. Ranking German pairs over 25 km by
`instances × distance` gives the payoff curve:

```text
top  30 pairs -> 38.4% of all instance-km
top  50 pairs -> 49.3%
top 100 pairs -> 64.9%
```

The highest-value pairs are Germany's Neubaustrecken — Göttingen–Hannover,
Köln–Frankfurt Flughafen, Würzburg–Nürnberg, Nürnberg–München,
Berlin–Wolfsburg–Hannover, Mannheim–Stuttgart, Erfurt–Leipzig — precisely where
a straight line looks most wrong.

**Target: 30–50 hand-authored polylines.**

---

# 4. Architecture Decision Records

```text
docs/adr/
├── 0000-template.md
├── 0001-single-repo-shared-python-image.md      (existing)
├── 0002-estimate-positions-without-gps.md
├── 0003-curated-corridor-geometry.md
├── 0004-redis-holds-segment-state.md
├── 0005-poll-before-sse.md
├── 0006-materialized-daily-trips.md
└── 0007-versioned-dataset-atomic-swap.md
```

Do **not** create ADRs for trivial implementation details.

An ADR should be created when a decision involves:

- architectural boundaries
- technology selection
- storage strategy
- communication protocols
- important performance decisions
- significant compromises
- decisions that may otherwise look strange later

Simple format:

```markdown
# ADR-0002: Estimate Positions Without GPS

## Status

Accepted

## Context

What problem required a decision?

## Decision

What did we choose?

## Alternatives Considered

What realistic alternatives existed?

## Consequences

What benefits and tradeoffs does this introduce?
```

The purpose is to preserve **why** important decisions were made, not just what the code currently does.

---

# 5. Technology Stack

## Frontend

```text
Next.js
TypeScript
Tailwind CSS
shadcn/ui
MapLibre GL JS
OpenFreeMap
Lucide Icons
```

Use **MapLibre GL JS** because it is open source, GPU accelerated, works well
with vector maps, and can efficiently render large amounts of geographic data.

At 253 long-distance trains this choice is comfortable. At the ~13,800
nationwide vehicles that regional support implies, it becomes load-bearing.

Use **OpenFreeMap** as the initial basemap provider.

## Backend

```text
Python
FastAPI
Pydantic
SQLAlchemy 2
GeoAlchemy / PostGIS
httpx
protobuf / GTFS-Realtime
pytest
ruff
mypy
uv
```

Use OOP for domain and business logic.

FastAPI route handlers should remain thin.

Avoid putting GTFS parsing, train calculations, database logic, or realtime
processing directly inside API routes.

## Infrastructure

```text
PostgreSQL
PostGIS
Redis
Docker
Docker Compose
SSE
Coolify
```

---

# 6. Repository Structure

Project location:

```text
/home/ricky/projects/portfolio-projects/zug-tracker
```

Use one Git repository.

```text
zug-tracker/
│
├── apps/
│   ├── web/
│   │   ├── src/
│   │   ├── public/
│   │   ├── Dockerfile
│   │   └── package.json
│   │
│   └── api/
│       ├── app/
│       │   ├── api/
│       │   ├── core/
│       │   ├── models/
│       │   ├── schemas/
│       │   ├── repositories/
│       │   ├── services/
│       │   ├── providers/
│       │   ├── worker/
│       │   └── main.py
│       │
│       ├── tests/
│       ├── Dockerfile
│       └── pyproject.toml
│
├── data/
│   ├── corridors/            # curated corridor polylines (GeoJSON)
│   └── .gitkeep
│
├── docs/
│   ├── adr/
│   └── poc-plan.md
│
├── infra/
│   └── postgres/
│
├── scripts/
│
├── .github/
│   └── workflows/
│       └── ci.yml
│
├── docker-compose.yml
├── docker-compose.dev.yml
├── .env.example
├── .gitignore
├── Makefile
└── README.md
```

---

# 7. Git Strategy

Keep Git simple.

```text
main
  ↑
short-lived feature branches
```

`main` should always be deployable.

Use Conventional Commits:

```text
feat:  fix:  refactor:  test:  docs:  chore:
```

Examples:

```text
feat(map): render active trains
feat(api): expose active train endpoint
fix(position): handle midnight trips
docs(adr): document corridor geometry decision
```

Do not create separate repositories for frontend and backend.

---

# 8. Milestones

The plan has two delivery checkpoints, not one.

```text
MILESTONE A  — Phases 2-5, schedule-only, DEPLOYED
               A dark map of Germany with trains moving on real timetable
               data. No realtime dependency. This is already most of the
               visual pitch, and deploying here de-risks the whole delivery
               chain early instead of at the end.

MILESTONE B  — Phases 6-12
               Realtime, SSE, detail panel, ticker, polish.
```

Deploy to Coolify at Milestone A. Do not wait for Milestone B to test the
deployment path.

---

# Phase 1: Bootstrap the Project — COMPLETE

```text
apps/web  apps/api  docs/adr
docker-compose.yml  .env.example  Makefile  README.md
```

### Docker Compose services

```yaml
services:
  web:
  api:
  worker:
  postgres:
  redis:
```

The `api` and `worker` share one Python application image.

```text
api    → runs FastAPI
worker → data ingestion, realtime polling, snapshot computation
```

### Developer commands

```bash
make dev   make up    make down   make logs
make test  make lint  make import-data
```

### Done when

`docker compose up` starts the complete development stack. ✅

---

# Phase 2: Build the Static GTFS Importer

```text
providers/gtfs_static.py
services/gtfs_import_service.py
```

Provider abstraction:

```python
class TransitDataProvider:
    ...

class GTFSStaticProvider(TransitDataProvider):
    ...
```

Import:

```text
agency  routes  trips  stops  stop_times  calendar  calendar_dates
```

**Parse every file by header name, never by column position.** See 3.1.

## Database model **[revised]**

```text
Dataset        feed_id, version, imported_at, valid_from, valid_to, is_active
Agency
Route          + category   (ICE / IC / EC / ECE / RJ / EN / RE / S ...)
Trip
Stop           + parent_station_id, PostGIS point
StopTime
TripInstance   materialized daily expansion  <- new
```

Three additions, each justified by a specific measured fact:

**`Dataset.feed_id`** — the feed is identified explicitly rather than assumed.
Adding `rv_free` (regional) later becomes an import, not a migration.

**`Route.category`** — stored as a first-class filterable column, not inferred
from which feed was imported. Phase 9's filter panel needs it regardless, and
it is the mechanism by which long-distance and regional coexist in one table.

**`TripInstance`** — see below.

## Service dates and the materialized daily trip table **[revised]**

Active-trip detection is the hardest correctness problem in this project, and
the original plan gave it one line. The measured facts:

- 16% of trips cross midnight; `stop_times` hours reach **35**
- service days come from `calendar` + `calendar_dates`, keyed on **service date**
- Europe/Berlin loses 02:00–03:00 in March and repeats it in October

GTFS defines times as offsets from **noon minus twelve hours** on the service
date, precisely to sidestep DST. Adding a `timedelta` to local midnight is
wrong twice a year.

**Decision:** a nightly job expands `calendar` + `calendar_dates` into concrete
`TripInstance` rows:

```text
TripInstance(service_date, trip_id, starts_at_utc, ends_at_utc)
```

Absolute UTC bounds, computed once at expansion time. The worker's hot loop
(which now runs continuously) becomes an indexed range query:

```sql
WHERE starts_at_utc <= now() AND ends_at_utc >= now()
```

Midnight crossings and DST are solved once, at expansion, rather than
re-derived on every tick.

## Idempotency: versioned dataset with atomic swap **[revised]**

GTFS IDs are not guaranteed stable across feed releases. Upserting by ID
accumulates orphaned trips forever; truncate-and-reload exposes a window where
the API serves an empty country.

**Decision:** every import writes under a new `Dataset` row. A pointer flips to
the new version only once the load completes. Old versions are pruned.

```text
import -> new Dataset (is_active=false)
       -> load all entities under that dataset_id
       -> flip is_active atomically
       -> prune superseded datasets
```

Re-running `make import-data` is then trivially safe.

## Scheduled re-import **[new]**

The feed expires **2026-09-21**. Nothing about a manual step survives contact
with a deployed demo.

**Decision:** the worker checks the feed's `Last-Modified` header **daily** and
re-imports on change, through the atomic swap above. This also exercises the
swap path continuously rather than once.

### Done when

```text
Which trains operate today?          (via TripInstance)
Which stops belong to a trip?
When does a train arrive and depart?
Where are those stations geographically?
Does re-running the import change anything?   (it must not)
```

---

# Phase 3: Build the Position Engine

The core domain feature.

```text
services/position_estimator.py
services/corridor_geometry.py
```

```python
class TrainPositionEstimator:
    def estimate(self, trip_instance, now, realtime_update=None) -> SegmentState:
        ...
```

`now` stays an injected parameter — it is what makes the whole engine
deterministically testable.

For each active trip instance:

1. Find the previous station.
2. Find the next station.
3. Determine effective departure time.
4. Determine effective arrival time.
5. Apply realtime delay if available.
6. Calculate progress between the two stops.
7. Interpolate position along the corridor geometry.
8. Derive bearing from the geometry tangent.
9. Return the segment state.

```text
progress = (now - departure) / (arrival - departure)
clamp 0 <= progress <= 1
```

## Train identity **[revised]**

There is no `train_number` in the source data. Labels are built from what the
feed actually contains:

```text
label       = route_short_name        e.g. "ICE 10"
destination = stop_headsign           e.g. "München Hbf"
display     = "ICE 10 → München Hbf"
```

This is feed-native, needs no second data source, and is arguably more
informative to a viewer than a bare train number. It also generalises cleanly
to regional trains, which are always identified by line rather than by number.

## Corridor geometry **[revised]**

The original plan forbade railway geometry outright. Measurement showed why
that fails: 8.7% of segments exceed 100 km and the worst is 497 km.

**Decision: 30–50 hand-authored corridor polylines**, stored as static GeoJSON
in `data/corridors/`, keyed by **location** (station coordinates, not station
IDs or names, which are not stable across feed releases) **[revised]**, ranked by
`instances × distance` (see 3.4). Straight-line fallback for every uncovered
pair.

This is deliberately **not** OSM ingest plus shortest-path routing. There is no
rail graph, no switch modelling, no map-matching — just a curated lookup table
with a fallback. Coverage ≈ 38–49% of instance-km for a weekend of work.

Still forbidden:

```text
OpenStreetMap railway graph
railway switches
track routing / shortest path
GPS
```

Two consequences to settle in ADR-0003:

- Progress is interpolated **by time**, positioned **along arc length**. Trains
  therefore hold constant speed through curves. Accepted.
- Regional trains, when added, keep straight lines — their segments are 5–10 km
  where straight-line error is negligible. The split is principled, not a
  stopgap.

## Output: segment state, not a point **[revised]**

The engine returns the data a client needs to compute position itself:

```json
{
  "trip_id": "1579104",
  "label": "ICE 10",
  "destination": "München Hbf",
  "category": "ICE",
  "operator": "DB Fernverkehr AG",
  "lat": 51.234,
  "lon": 12.345,
  "bearing": 142,
  "progress": 0.64,
  "previous_stop": "Leipzig Hbf",
  "next_stop": "Erfurt Hbf",
  "departure_utc": 1787916214,
  "arrival_utc": 1787919000,
  "geometry_ref": "leipzig-erfurt",
  "delay": 420,
  "position_source": "scheduled"
}
```

`lat`/`lon` are included for first paint. `departure_utc`, `arrival_utc` and
`geometry_ref` are what let the browser extrapolate to *now* (Phase 8).

Measured payload: **~229 bytes per train**, 0.06 MB for the full national
long-distance fleet.

---

# Phase 4: Expose the API

```text
GET /api/v1/trains
GET /api/v1/trains/{trip_id}
GET /api/v1/stats
GET /api/v1/health
```

## `/api/v1/trains` **[revised]**

```text
?bbox=west,south,east,north     viewport filter
?zoom=6                         zoom level
?category=ICE,IC,EC             category filter
```

**The `bbox` and `zoom` parameters exist from day one.** At 253 trains they are
nearly free. They are also the single most expensive thing to retrofit, because
adding them later changes the REST contract, the SSE payload and the Redis read
path simultaneously. Measured justification:

```text
   253 trains (today)      ->  0.06 MB per push
13,818 trains (nationwide) ->  3.16 MB per push, per client
                              = 4.6 GB/day per connected viewer
```

Response:

```json
{
  "timestamp": "...",
  "snapshot_age_seconds": 12,
  "trains": [ ... ]
}
```

Resolved in Phase 4 **[revised]** (ADR-0005):

- `bbox` keeps a train when its *segment's* bounds overlap the box, so trains
  about to enter the view are present for Phase 8's extrapolation.
- `zoom` is validated and reserved for level of detail; it has no effect until
  regional trains exist.
- `category` is validated by shape, not against a list; `/stats` lists the
  categories the timetable has.
- `snapshot_age_seconds` is the age of the positions, always 0 while they are
  computed per request. Timestamps are ISO 8601 UTC, not epoch seconds.

## `/api/v1/trains/{trip_id}`

```text
label + destination        operator        origin / destination
current position           previous / next station
delay                      full stop sequence
position source            route polyline
```

## `/api/v1/health` 

Reports process health **and worker heartbeat age**, so a dead worker behind a
healthy API is visible to Coolify and CI rather than only in the UI.

### Done when

Every endpoint can be inspected and tested through Swagger.

---

# Phase 5: Build the Map

Full-screen MapLibre map, dark basemap, initial view Germany at zoom ≈ 5–6.

Do not render individual React `<Marker>` components.

```text
GeoJSON Source
    ↓
MapLibre Symbol Layer
```

**Transport at this phase is plain polling** against `/api/v1/trains`. SSE
arrives in Phase 7. This removes proxy-buffering and reconnect work from the
critical path to a first deployable demo. [revised]

Visual states:

```text
ICE          IC / EC / ECE
RJ           EN (night)
Delayed      Selected
Realtime-backed vs schedule-estimated
```

### Done when

Opening the application shows active trains distributed across Germany —
**Milestone A. Deploy here.**

---

# Phase 6: Add Realtime Data

```text
providers/gtfs_realtime.py
services/realtime_service.py
services/snapshot_service.py
```

```text
GTFS-RT (51.9 MB, 60s)
   ↓
Worker  — filter to known trip_ids, discard ~97%
   ↓
Position engine — compute segment state for all active trips
   ↓
Redis  — latest snapshot only
```

## Worker responsibilities **[revised]**

The worker, not the API, computes positions. Cost is `O(trains)` per tick
rather than `O(trains × clients)` per request.

```text
every 60s:  fetch RT -> filter -> recompute snapshot -> write Redis
daily:      check static feed Last-Modified -> re-import if changed
nightly:    expand TripInstance rows for the coming days
```

Redis holds only the latest snapshot. Do not store realtime events in
PostgreSQL.

```text
PostgreSQL → static and durable transport data
Redis      → temporary realtime operational state
```

## Snapshot layout **[revised]**

The snapshot is **keyed by spatial grid cell** rather than written as a single
blob, so viewport reads do not scan the whole fleet.

> Note: at 253 trains a single blob would perform identically — this is
> explicitly an investment against the ~13,800-vehicle regional case. Because
> the `bbox` contract in Phase 4 already hides the storage layout, this can be
> reverted to a single blob with no API change if it proves premature.

## Staleness **[new]**

Every snapshot carries a generation timestamp. The API exposes its age. A
snapshot older than the threshold flips the UI from `LIVE` to `STALE`.

Without this, a dead worker serves a stale snapshot indefinitely beneath an
animated LIVE indicator — trains gliding confidently along outdated segments.
Reconnect logic (Phase 7) does not catch this; it is a different failure.

Fallback per train:

```python
source = "realtime" if realtime_update else "scheduled"
```

Expect roughly a 60/40 split.

---

# Phase 7: Add SSE Streaming

```text
GET /api/v1/trains/stream
```

Upgrade from Phase 5's polling.

```text
Worker → Redis → FastAPI → SSE → Next.js
```

SSE is appropriate because communication is `server → browser` rather than
bidirectional.

Because Phase 8 extrapolates on the client, **the transport is nearly
irrelevant to visual smoothness** — polling and SSE deliver the same payload at
the same cadence. SSE buys efficiency and a reconnect story, not smoothness.
This is why deferring it was cheap.

The server sends periodic state updates. Do not send animation frames from the
backend.

---

# Phase 8: Smooth Train Animation

One of the most important portfolio features.

## The problem the original plan did not close **[revised]**

The original specified `interpolate(previousPosition, nextPosition, progress)`.
But when the client receives position A, position B does not yet exist — it
arrives on the next tick. That yields motion which is smooth but permanently
one full interval stale. At 60s polling that is a 60-second lag.

## Decision: extrapolate to `now`

The server publishes **segment state** (previous stop, next stop, effective
departure and arrival, delay, geometry reference). The client computes position
for the current instant on every frame:

```text
progress   = (now - departure_utc) / (arrival_utc - departure_utc)
position   = pointAlong(geometry, progress)
bearing    = tangent(geometry, progress)
```

```text
Network updates  → 60 s apart
Visual animation → ~60 FPS
```

The backend determines **where the train should be**.
The frontend determines **how smoothly it visually moves there**.

Because the client extrapolates rather than chases, trains render *current*
positions, not historical ones — and poll rate no longer trades against
smoothness.

Use `requestAnimationFrame()`. Ease bearing changes so trains rotate naturally
rather than snapping.

---

# Phase 9: Build the Command Center UI

Keep the map as the dominant component.

```text
┌─────────────────────────────────────────────────────────────┐
│ ZUG TRACKER   253 ACTIVE   38 DELAYED   LIVE ●      SEARCH  │
├─────────────┬───────────────────────────────────────────────┤
│             │                                               │
│ FILTERS     │                                               │
│             │                  MAP                          │
│ ICE    ●    │                                               │
│ IC     ●    │        🚆       🚆                            │
│ EC     ●    │                    🚆                         │
│ RJ     ●    │                                               │
│ EN     ●    │                                               │
│             │                                               │
│ STATUS      │                                               │
│ realtime    │                                               │
│ scheduled   │                                               │
│             │                                               │
├─────────────┴───────────────────────────────────────────────┤
│ ICE 10 → München +8m   IC 55 → Hamburg on time              │
└─────────────────────────────────────────────────────────────┘
```

## Top HUD

```text
Active trains            (~253 at midday, far fewer overnight)
Delayed trains           (expect ~65% delayed >60s)
On-time trains
Realtime-covered trains  (expect ~60%)
Last data update / staleness state
```

Filters map directly onto `Route.category` from Phase 2.

## Overnight expectation **[new]**

Long-distance traffic thins dramatically overnight — EN is only 55 trips in the
entire feed. A 03:00 map showing a couple of dozen trains is the honest output
of a long-distance feed, not a bug. Note this in the README rather than
disguising it. Night-train coverage is included from the first import so the
overnight map is thin but alive.

---

# Phase 10: Train Detail Panel

Clicking a train opens a side panel.

```text
ICE 10 → München Hbf

Berlin Hbf
↓
München Hbf

Status       +8 min
Operator     DB Fernverkehr AG
Source       REALTIME

Previous     Leipzig Hbf
Next         Erfurt Hbf

Route
Berlin · Leipzig · Erfurt · Nürnberg · München
```

The selected train is highlighted on the map, with its route drawn using
curated corridor geometry where available and straight lines elsewhere.

Station names in the feed are inconsistent (`Hauptbahnhof (oben)`, `Pasing`,
`S Spandau Bhf (Berlin)`). Resolve to `parent_station` names and tidy the worst
cases in a small display-name mapping.

---

# Phase 11: Activity Feed

A lightweight operations ticker.

```text
ICE 10 → München  +8 min
ICE 43 arrived Frankfurt
EC 95 departed Dresden
IC 55 → Hamburg  now +3 min
```

Derived from changes between consecutive Redis snapshots. The feed also carries
102,872 alert entities, which are an alternative source if snapshot diffing
proves thin.

Avoid building a complex event-processing system. The goal is visual activity,
not complete railway operations history.

---

# Phase 12: Portfolio Polish

Add only high-value polish:

- subtle dark-map glow
- animated LIVE indicator (and its STALE counterpart)
- train hover cards
- selected train emphasis
- smooth side-panel transitions
- route line
- responsive layout
- loading skeletons
- connection / reconnect indicator
- last-update indicator
- tasteful metric animations
- good empty and error states

Avoid excessive animation. The map remains the hero.

---

# Phase 13: Reliability and Tests

Do not chase maximum coverage. Prioritize business-critical logic.

Backend:

```text
PositionEstimator
corridor geometry lookup + straight-line fallback
GTFS parsing (by header name, non-standard column order)
service-date expansion (TripInstance)
active trip detection
delay application
dataset atomic swap + idempotent re-import
snapshot staleness
realtime fallback
```

Test scenarios:

```text
train between stations
train stopped at station
train before first station
train after final station
delayed train
missing realtime data
cancelled train
midnight-crossing trip            (16% of the feed)
stop_times hour >= 24 (up to 35)
DST spring-forward / autumn-back service date
trip with no corridor geometry    (must fall back)
re-import with changed trip_ids   (must not orphan)
stale snapshot                    (must flip to STALE)
```

Frontend:

```bash
npm run lint && npm run typecheck && npm run build
```

Backend:

```bash
ruff check . && mypy . && pytest
```

---

# Phase 14: CI/CD

GitHub Actions on pull requests and pushes.

```text
frontend lint / typecheck / build
backend  lint / typecheck / tests
```

Preferred deployment flow:

```text
GitHub → main → Coolify → Docker Compose
```

The same repository and Docker configuration must remain usable outside Coolify.

---

# Phase 15: Deployment Readiness

Production stays close to local development.

```text
web  api  worker  postgres  redis
```

Persist only necessary state.

```text
PostgreSQL → persistent volume
Redis      → persistence not required
```

Expose publicly only `web` and `api`. Keep `postgres`, `redis` and `worker`
internal to the Docker network.

Environment variables:

```text
DATABASE_URL          REDIS_URL
API_INTERNAL_URL      NEXT_PUBLIC_API_URL
GTFS_STATIC_URL       GTFS_REALTIME_URL
WORKER_INTERVAL_SECONDS=60
CORS_ORIGINS          ENVIRONMENT
```

Commit `.env.example`. Never commit secrets.

**Bandwidth note for deployment:** at 60s polling the worker pulls **74.8 GB
per day** of ingress (~2.2 TB/month). Confirm the host's transfer allowance
before deploying, and consider 120–300s in production if transfer is metered.

---

# Final Architecture

```text
        Static GTFS (fv_free, 415 KB)
        re-imported daily on Last-Modified
                    │
                    ▼
             ┌──────────────┐
             │    Worker    │◄──── GTFS-RT (51.9 MB / 60s)
             │    Python    │      filter to known trips
             │              │
             │  Position    │
             │  Engine      │
             └──────┬───────┘
                    │
        ┌───────────┴───────────┐
        ▼                       ▼
   PostgreSQL              Redis
    + PostGIS          segment-state snapshot
  static + TripInstance  (spatial cells, timestamped)
        │                       │
        └───────────┬───────────┘
                    ▼
             ┌──────────────┐
             │   FastAPI    │
             │  thin reads  │
             │  bbox + zoom │
             └──────┬───────┘
                    │
            REST (P5) → SSE (P7)
                    │
                    ▼
          ┌─────────────────┐
          │     Next.js     │
          │  extrapolates   │
          │  to now @60fps  │
          │ MapLibre GL JS  │
          └─────────────────┘
                    │
                    ▼
            🚆 🚆 🚆 🚆 🚆
             Germany Live Map
```

---

# POC Definition of Done

1. A polished dark map of Germany.
2. German long-distance trains displayed on the map.
3. Trains moving smoothly rather than jumping between updates.
4. Clicking a train identifies it **by line and destination** (`ICE 10 → München Hbf`).
5. Origin, destination, stops and delay are visible.
6. Realtime-backed and schedule-estimated trains are distinguishable (~60/40).
7. Statistics update without refreshing.
8. The activity ticker shows visible network activity.
9. The client reconnects automatically after temporary interruption, **and a
   stale snapshot is surfaced as STALE rather than shown as live**.
10. Long segments on major corridors follow curated geometry, not straight lines.
11. Re-running the import is safe, and the feed refreshes itself before expiry.
12. The entire project runs using Docker Compose.
13. `main` is continuously deployable.
14. Important technical decisions are documented as ADRs.

---

# Explicitly Out of Scope

```text
❌ User accounts / authentication
❌ Mobile application
❌ Exact GPS                      (not available in any feed)
❌ OSM railway graph / shortest-path track routing
❌ Historical journey storage
❌ Analytics platform
❌ Kubernetes / Kafka / microservices
❌ Celery unless genuinely necessary later
❌ Additional national feeds      (cross-border trips from the German feed ARE in scope)
❌ Admin panel
❌ Custom map tile infrastructure
❌ Regional / bus / tram coverage  (designed for, not built)
```

Avoid introducing infrastructure merely because it is common in large systems.
Every dependency should solve a concrete requirement.

---

# Future Improvements

```text
V1.1  Regional trains (RE / RB / S-Bahn)
      - import rv_free under a new Dataset.feed_id
      - no additional RT bandwidth (feed is already nationwide)
      - straight-line geometry is adequate at regional segment lengths
      - viewport filtering already in place from Phase 4
      - expect ~13,800 vehicles in motion nationwide vs 253 today

V1.2  Track-accurate OSM railway geometry
V1.3  Train search
V1.4  Delay heatmap
V1.5  Station activity visualization
V1.6  Historical movement playback
V1.7  Route congestion visualization
V1.8  Follow-train camera mode
V1.9  Delay and network analytics
V2    Other European countries
```

Regional trains remain the first major enhancement, and the Phase 2/4 interface
decisions exist specifically to make it an import rather than a redesign.

---

# Guiding Engineering Principles

1. Prefer simple solutions over speculative abstractions.
2. Keep FastAPI controllers thin.
3. Keep transport-source code behind provider interfaces.
4. Keep business logic inside services/domain classes.
5. Keep database access inside repositories.
6. Keep realtime temporary state outside PostgreSQL.
7. Keep rendering and animation concerns in the frontend.
8. Avoid premature optimization.
9. Add abstractions only when they solve an existing problem.
10. Make `main` deployable at all times.
11. Record significant architectural decisions using ADRs.
12. Prefer readable code that another developer can understand without extensive documentation.
13. Keep the POC visually impressive while resisting unnecessary scope expansion.
14. **Verify external data before designing against it.** Every assumption in
    this plan that was not measured turned out to be wrong in some detail.
15. **Invest in interfaces, not implementations, when planning for scale.** The
    `bbox` parameter is worth taking early; the storage layout behind it is not.
