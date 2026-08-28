# ADR-0002: Versioned datasets with an atomic swap

## Status

Accepted

## Context

The static GTFS feed is re-imported repeatedly: its validity window is 31 days
(the current release covers `20260822` - `20260921`), so a deployment that never
re-imports serves an empty map from day 32. Re-running the import therefore has
to be a safe, boring operation.

Two obvious approaches both fail:

- **Upsert by GTFS id.** GTFS ids are only unique within a feed release and are
  not guaranteed stable across releases. A trip that disappears from the feed is
  never deleted, so orphans accumulate for as long as the deployment lives, and
  the map slowly fills with trains that no longer exist.
- **Truncate and reload.** Correct, but there is a window - the whole load - in
  which the API serves a country with no trains in it.

There is a third problem underneath both. Once more than one release of the feed
can exist in the database at once, nothing structurally prevents a trip from one
release joining a stop time from another. That produces plausible-looking
nonsense rather than an error.

## Decision

**Every import writes under a new `Dataset` row, and a pointer flips to it once
the load has completed.**

```text
import -> new Dataset (is_active = false)
       -> load all entities under that dataset_id
       -> flip is_active
       -> prune superseded datasets
```

Three things make it hold:

**Composite natural primary keys.** Every table is keyed by
`(dataset_id, <gtfs id>)`, and every foreign key carries `dataset_id` through:

```text
stop_time  PK (dataset_id, trip_id, stop_sequence)
           FK (dataset_id, trip_id) -> trip
```

A cross-dataset join is not merely discouraged, it is unrepresentable. This also
removes any id-remapping pass at load time, which is what lets the bulk tables go
in through `COPY`.

**A partial unique index.** `UNIQUE (is_active) WHERE is_active` makes "at most
one active dataset" a promise the database keeps, not one the application
remembers to keep.

**One transaction for the load and the flip.** An import either becomes visible
in its entirety or leaves no trace. There is no half-loaded active dataset and no
instant at which zero datasets are active. Pruning runs afterwards in its own
transaction, because losing an old dataset is not a reason to roll back a good
import.

Readers resolve the active `dataset_id` **once** per request or worker tick and
pass it explicitly into repositories.

Retention is **one** superseded dataset (~405k rows, roughly 10 MB).

## Alternatives Considered

- **Upsert by GTFS id.** Orphans forever, as above.
- **Truncate and reload.** An empty country for the duration of the load, and no
  way back if the new feed turns out to be broken.
- **A surrogate primary key per table with a `(dataset_id, gtfs_id)` unique
  constraint.** Narrower foreign keys and simpler ORM relationships, but it needs
  a GTFS-id-to-surrogate-id map maintained across 55k stop times during the load,
  and it leaves cross-dataset joins possible.
- **Schema-per-import with a `search_path` swap.** Genuinely atomic and genuinely
  fast, but it puts a schema-name variable into every connection's state and
  makes migrations apply to N schemas. Too much machinery for one 415 KB feed.
- **Deleting superseded datasets immediately.** Saves ~10 MB and makes a bad
  import unrecoverable.
- **Resolving the active dataset from a cache or from Redis.** Invents a
  cache-invalidation problem to save a single indexed row read, and the Redis
  variant would make Redis load-bearing for static data, contradicting the
  split this project keeps between PostgreSQL and Redis.

## Consequences

- Re-running `import-data` is trivially safe, which is what makes an automated
  daily re-import (Phase 6) possible at all.
- A bad import is reversible by flipping a boolean, for as long as one superseded
  dataset is retained.
- An in-flight reader holding the previous `dataset_id` does not have rows
  deleted underneath it mid-request.
- Every query and every repository method carries a `dataset_id` parameter. This
  is the cost of the guarantee and it is paid on every line of data access.
- Peak storage is two datasets, ~810k rows.
- Composite foreign keys are checked per row, so the load has an order: agencies
  before routes, stations before the platforms that reference them, trip
  instances before their calls.
- Adding regional trains later is an import under a second `feed_id`, not a
  migration.
