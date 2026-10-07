# ADR-0006: Generate the web app's API types from OpenAPI

## Status

Accepted

## Context

From Phase 5 the web app depends on most of the API: the train list, a train's
detail, fleet stats and health. Before Phase 5 the only shape it used was
`/health`, written by hand in `apps/web/src/lib/api.ts`, and that copy had
already drifted: it lacked the `dataset` block that `/health` now returns.

The backend's Pydantic models already define the contract, and FastAPI
publishes them as an OpenAPI 3.1 schema. The question is how the TypeScript
side stays in step without someone remembering to copy every change.

## Decision

**The web app's API types are generated from the backend's OpenAPI schema and
committed.**

```text
apps/api   python -m app.cli openapi   ──►  apps/web/.openapi.json  (git-ignored)
                                                    │  openapi-typescript
                                                    ▼
apps/web   src/lib/api/schema.d.ts  (committed, never edited)
           src/lib/api/types.ts     (readable aliases: Train, TrainDetail, ...)
```

- `make api-types` regenerates the types. The schema comes from
  `create_app().openapi()`, so it needs no running server and no database.
- `make api-types-check` regenerates and fails on any diff. It is part of
  `make check`, and CI runs it from Phase 14.
- A backend change to a response model therefore fails the check until the web
  types are regenerated. The regenerated `schema.d.ts` diff then shows the
  contract change in the same pull request.
- Types only. `openapi-typescript` adds no runtime code. Responses are not
  validated at runtime, because the API is ours and the types come from its
  own source.

## Alternatives Considered

- **Hand-written types.** Cheapest to start, but they drift silently, as the
  health types already had.
- **Generating at build time, uncommitted.** The Docker build context of `web`
  contains only `apps/web`, so it cannot run the backend. Contract changes
  would also stop showing up in review.
- **A generated client (e.g. `openapi-fetch`).** It adds a runtime dependency
  for four GET requests that are already one line each.
- **Runtime validation (zod).** It guards against an API we do not control,
  which this is not, and it is a second copy of the schema to keep in step.

## Consequences

- `schema.d.ts` is a committed generated file. It is excluded from linting and
  must never be edited by hand.
- Generating the types needs both toolchains (`uv` and `npm`). Developers
  already have both for `make lint`.
- Fields with a default, such as `latency_ms`, come out optional (`?:`) even
  though the API always sends them, because FastAPI marks them not-required in
  the schema. The client code treats them as possibly `undefined`.
