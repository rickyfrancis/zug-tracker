# ADR-0005: Serve positions as a snapshot

## Status

Accepted

## Context

Phase 4 exposes the position engine over REST. Positions are computed per
request for now, but Phase 6 moves that into the worker: once per tick it
estimates every train and writes the result to Redis, so the cost is per train
rather than per train per client. The REST contract written in Phase 4 is what
the map (Phase 5), the SSE stream (Phase 7) and client-side animation (Phase 8)
are built on, so it must not change when Phase 6 does.

Two related questions come with it:

- **What `snapshot_age_seconds` means** before a snapshot is stored anywhere.
- **What a viewport filter keeps.** Phase 8 extrapolates every train along its
  segment between 60-second updates, so a payload filtered to the trains
  currently inside the viewport is missing the ones that will drive into it
  before the next update.

## Decision

**Every train endpoint reads one `PositionSnapshot` - every running train at
one instant - through a `SnapshotReader`, and never asks how it was made.**

```text
GET /trains, /trains/{id}, /stats
        │
   TrainService ──► SnapshotReader.read() -> PositionSnapshot(generated_at, trains)
        │                 │
        │                 ├─ Phase 4: LiveSnapshotReader  (PositionService, now)
        │                 └─ Phase 6: a Redis reader       (the worker's last tick)
        └──► TimetableRepository   (stops, route, categories: static data)
```

`SnapshotReader` is a `Protocol`. Unlike the provider base class ADR-0004
rejected, it will have two implementations that really are used
interchangeably, and tests already substitute a third. Changing the source is
one line in `api/deps.py`.

**`timestamp` is the snapshot's `generated_at`; `snapshot_age_seconds` is
`floor(now - generated_at)`, clamped at 0.** Computed per request, the age is
always 0, which is an accurate value. From Phase 6 it grows when the worker
stops, and the UI uses it to switch from LIVE to STALE. It is not the timetable's
age. That is already on `/health`, and mixing the two would mark a healthy
worker on an old feed as stale.

**A bbox keeps a train when the bounds of its current segment overlap it**, not
when its current point lies inside. A train approaching the edge of the view is
in the payload before it crosses into view.

**`zoom` is accepted, validated and unused.** Its meaning is set now so that
clients send it: once regional trains exist, their categories are omitted below
a threshold zoom. Adding a parameter later would change the REST contract, the
SSE payload and the Redis read path all at once.

## Alternatives Considered

- **Call `PositionService` from the handlers directly.** Fine until Phase 6, and
  then every endpoint changes at once. The seam costs a protocol and a
  three-line class.
- **Report the timetable's age as `snapshot_age_seconds`** so it is not always 0
  in Phase 4. This makes the field nonzero now but gives it the wrong meaning:
  LIVE/STALE is about whether positions are being refreshed, not about the feed.
- **Filter by the train's current point.** Smaller payloads, but trains appear
  late at the viewport's edges once the browser extrapolates between updates.
- **Filter by the exact segment line instead of its bounds.** This would drop a
  few extra trains near the corners of the view, which matters little at
  hundreds of trains, and the check gets more complicated once curated corridors
  bend outside a straight line.
- **An `?at=` parameter for estimating at any instant.** Useful for debugging,
  but a Redis snapshot only holds "now". `make positions at=...` already covers
  this.

## Consequences

- Phase 6 replaces the reader, not the endpoints. Its grid-cell Redis layout can
  push the bbox down into the reader without changing the response.
- A detail request computes the whole fleet in Phase 4 so that the position it
  shows matches the map's exactly. This is negligible at ~250 trains and free
  once the snapshot comes from Redis.
- Viewport payloads include some trains just outside the view, more of them on
  long segments.
- `zoom` does nothing until regional trains arrive. The OpenAPI description says
  so, so nobody needs to look in the code to find out.
