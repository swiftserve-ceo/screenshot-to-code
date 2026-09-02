"""Readiness endpoint reporting infrastructure dependency status.

`GET /` stays a plain liveness string (unchanged). `GET /health` reports the
database and Redis without leaking connection strings (spec FR-E8 / API-2 / A-9).
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from config import settings
from db.engine import check_database
from queue_client import check_worker
from redis_client import check_redis

router = APIRouter()


class HealthResponse(BaseModel):
    status: str  # "ok" | "degraded"
    checks: dict[str, str]
    job_queue_enabled: bool


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    db = await check_database()
    redis = await check_redis()
    worker = await check_worker()

    checks = {"database": db.state, "redis": redis.state, "worker": worker.state}
    # "degraded" if a *configured* dependency is failing. An unconfigured DB
    # ("disabled") is a valid state for the current phase — the sync generation
    # path does not need it. A missing worker only matters when the queue is on.
    degraded = (
        redis.state == "error"
        or db.state == "error"
        or (settings.job_queue_enabled and worker.state != "ok")
    )
    return HealthResponse(
        status="degraded" if degraded else "ok",
        checks=checks,
        job_queue_enabled=settings.job_queue_enabled,
    )
