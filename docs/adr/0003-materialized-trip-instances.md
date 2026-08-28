# ADR-0003: Materialize dated trip instances

## Status

Accepted

## Context

"Which trains are running right now?" is the query the worker runs on every tick
and the hardest correctness problem in this project. Answering it from raw GTFS
means resolving, per trip, per tick:

- **Service dates.** A trip runs on the dates implied by `calendar` *and*
  `calendar_dates` together. In this feed **60 of 1,057 service_ids appear only
  in `calendar_dates.txt`**, with no weekly pattern at all - so the natural
  implementation (walk `calendar`, then patch it) silently drops them along with
  their trips.
- **Times that are not times.** GTFS stop times are offsets from *noon minus
  twelve hours* on the service date. **16% of this feed's trips cross midnight**
  and hours reach **35**, which no SQL time type accepts.
- **Daylight saving.** Europe/Berlin loses an hour in March and repeats one in
  October. Adding a `timedelta` to local midnight is wrong twice a year and
  silently right the rest of the time.

Doing this per tick means re-deriving the same answer thousands of times a day
and having the DST bug in the hot path.

## Decision

**Expand `trips x service dates` into concrete rows at import time, with
absolute UTC timestamps.**

```text
trip_instance       (dataset_id, service_date, trip_id)
                    route_id, starts_at_utc, ends_at_utc

stop_time_instance  (dataset_id, service_date, trip_id, stop_sequence)
                    stop_id, arrival_utc, departure_utc
```

The worker's hot loop becomes an indexed range query:

```sql
WHERE dataset_id = :active AND starts_at_utc <= now() AND ends_at_utc >= now()
```

Supporting choices:

- **The full validity window is expanded**, not a rolling few days. It is 33,527
  trip instances and 307,023 stop-time instances - small enough that a rolling
  window would only add a "did the nightly job run?" failure mode.
- **Expansion happens inside the import transaction**, so the swap flips
  schedule and instances together and no dataset is ever active without them.
- **The arithmetic is Python, not SQL.** Postgres's `AT TIME ZONE` implements the
  rule correctly and would avoid moving 340k rows over the wire, but it would put
  the single hardest rule in the project inside a string literal, reachable by
  tests only through a live database. In `time_conversion.py` it is one function,
  unit-tested against synthetic 2027-03-28 and 2026-10-25 dates with nothing
  running. Expansion costs about three seconds a day.
- **`route_id` is denormalized onto `trip_instance`**, so category filtering is a
  single-table predicate. It is immutable within a dataset, so there is nothing
  to keep in step.
- **Raw `stop_time` is kept** alongside the instances. It is the source of truth,
  it is what re-expansion reads, and the corridor-ranking query in Phase 3 wants
  the pattern rather than dated copies of it.

## Alternatives Considered

- **Compute active trips from `calendar` on every tick.** Puts the DST rule in
  the hot path and re-derives an unchanging answer thousands of times a day.
- **Materialize trip bounds only, and compute per-stop times at read time.** Ten
  times fewer rows, and the position engine would do one integer addition per
  stop instead of an indexed lookup. Rejected in favour of making Phase 3's read
  path a plain query; the extra 307k rows are cheap.
- **A rolling 3-day window refreshed nightly.** Solves a size problem that does
  not exist here and adds a scheduled job whose failure empties the map.
- **A PostgreSQL generated column or `INSERT ... SELECT` for the timezone
  arithmetic.** Faster, but moves business logic into SQL.

## Consequences

- Midnight crossings and DST are resolved exactly once per import, in one tested
  function, rather than in every consumer.
- The worker's "what is running now" query is an index scan over 33k rows.
- Instances only exist for the imported feed's validity window. If the feed is
  never re-imported the map goes empty on expiry rather than degrading - so
  `/api/v1/health` reports the active dataset's `valid_to` and days remaining.
- An import writes ~405k rows and takes a few seconds.
- Changing what expansion produces means re-importing, not mutating instances in
  place. Deleting and rebuilding instances under the *active* dataset would
  recreate exactly the empty-map window ADR-0002 exists to prevent, which is why
  there is no `expand` command.
