# syntax=docker/dockerfile:1

# One image serves both the API and the worker; they differ only by command.
# See docs/adr/0001-single-repo-shared-python-image.md.

FROM ghcr.io/astral-sh/uv:python3.13-trixie-slim AS base
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    PYTHONUNBUFFERED=1
WORKDIR /app


# --- development -------------------------------------------------------------
# Dependencies only: the source tree is bind-mounted by docker-compose.dev.yml
# so edits reload without a rebuild.
FROM base AS dev
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]


# --- build -------------------------------------------------------------------
FROM base AS builder
ENV UV_NO_DEV=1
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked


# --- production --------------------------------------------------------------
# uv itself is not needed at runtime, only the virtualenv it produced.
FROM python:3.13-slim-trixie AS prod
RUN useradd --create-home --uid 1000 zug
COPY --from=builder --chown=zug:zug /app /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1
WORKDIR /app
USER zug
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
