"""Aggregates every v1 router behind a single prefix."""

from fastapi import APIRouter

from app.api.v1 import health, stats, trains

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(trains.router)
api_router.include_router(stats.router)
