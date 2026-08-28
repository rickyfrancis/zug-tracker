# ADR-0004: No shared transit-provider abstraction

## Status

Accepted

## Context

The POC plan specified a provider hierarchy:

```python
class TransitDataProvider:
    ...

class GTFSStaticProvider(TransitDataProvider):
    ...
```

with `GTFSRealtimeProvider` to follow in Phase 6. The intent was sound: keep
transport-source code behind an interface so the rest of the application does not
know where its data comes from.

Writing the static provider made the shape of the two sources concrete, and they
have almost nothing in common:

| | static | realtime |
|---|---|---|
| returns | 7 CSV tables in a zip | protobuf trip updates |
| size | 415 KB | 51.9 MB |
| cadence | daily, conditional on `ETag` | every 60 s, full snapshot |
| consumer | the importer, writing PostgreSQL | the worker, writing Redis |
| lifecycle | staged to a temp file, parsed, discarded | parsed in memory, mostly discarded |

The only shared behaviour is "fetch bytes over HTTP", which `httpx` already
provides. More decisively: **no caller ever holds a provider without knowing
which one it is.** The importer wants CSV tables; the realtime service wants trip
updates. A base class here would never be used polymorphically - it would be a
placeholder for a substitution that cannot happen.

## Decision

**Two concrete classes, no shared base.**

`GTFSStaticProvider` exposes what a static feed actually offers:

```python
async def fetch_metadata() -> FeedMetadata
async def download(known: FeedMetadata | None) -> DownloadedFeed | None   # None on 304
```

Phase 6's realtime provider will expose whatever a protobuf snapshot actually
offers. The boundary the plan wanted is still real - external feeds are reached
only through `app/providers/`, and services depend on the provider's methods
rather than on `httpx` - it is just not expressed as inheritance.

Tests substitute a provider by structural typing, not by subclassing: the import
tests pass a `StubProvider` that implements `download` and nothing else.

## Alternatives Considered

- **Keep the ABC as specified.** One abstract method (`_get(url)`) that both
  subclasses would inherit and no call site that benefits. It would read as an
  abstraction to a reviewer while functioning as a namespace.
- **A `Protocol` covering both.** Same problem: the two return types have no
  supertype more specific than `object`, so the protocol would describe nothing.
- **Wait and extract the base class in Phase 6, once both exist.** Defensible,
  and if a genuine shared need appears - shared retry policy, shared metrics -
  that is exactly when to do it. Nothing is lost by not having it now.

## Consequences

- One fewer indirection between the importer and the feed. `GTFSStaticProvider`
  can expose a conditional-GET API (`FeedMetadata`, `None` on 304) that would
  make no sense on a protobuf snapshot.
- The provider boundary is a package convention rather than a type. A reviewer
  looking for the interface finds concrete classes with docstrings instead of an
  ABC.
- This contradicts the POC plan, which is why it is recorded here: without an
  ADR, the absent base class reads as the plan being ignored rather than
  reconsidered.
- If Phase 6 turns up real shared behaviour, extracting a base class from two
  working implementations is easier than having guessed at one up front.
