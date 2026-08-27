# ADR-0001: One repository, one Python image for API and worker

## Status

Accepted

## Context

zug-tracker needs two kinds of Python execution:

- a request/response API serving the map frontend, and
- background work that must not run inside request handlers: downloading and
  importing the static GTFS feed (Phase 2) and polling the GTFS-Realtime feed
  every few seconds (Phase 6).

Both share the same domain code - models, repositories, position estimation and
configuration. The question was how to split them across repositories, images
and processes without importing infrastructure the project does not need.

## Decision

One Git repository containing `apps/web` and `apps/api`, and **one Python image
built from `apps/api`, run as two services that differ only by command**:

```yaml
api:     uvicorn app.main:app       # FastAPI
worker:  python -m app.worker.main  # ingestion and realtime polling
```

The worker is a plain `asyncio` loop with signal-based graceful shutdown
(`app/worker/main.py`), not a task queue.

## Alternatives Considered

- **Separate frontend and backend repositories.** Two pull requests for one
  feature and no way to change an API contract and its consumer atomically. The
  POC is one deployable product, not two.
- **Separate images for API and worker.** Duplicate Dockerfiles and two builds
  to keep in step, for code that is identical apart from the entrypoint.
- **Celery (or RQ) with a broker.** Adds a broker, worker pool and result
  backend to run one periodic job. The POC has no task fan-out, no retries
  worth orchestrating and no user-triggered background work.
- **Background tasks inside FastAPI** (`BackgroundTasks`, `asyncio.create_task`
  on startup). Simplest to write, but ties ingestion to the API's lifecycle and
  makes realtime polling compete with request handling; scaling the API to more
  replicas would multiply the polling.

## Consequences

- Shared domain code is imported directly, with no packaging step.
- One image to build, scan and deploy; `docker compose` runs it twice.
- API and worker scale independently even though they share an image.
- The worker carries the API's dependencies (uvicorn, starlette) it does not
  use - a slightly larger image in exchange for one build path.
- A dependency change affects both services at once, so they cannot be upgraded
  independently. Acceptable while they share nearly all of their code.
- If background work later needs scheduling, retries or fan-out, a queue can be
  introduced behind the same service boundary without moving code between
  repositories.
