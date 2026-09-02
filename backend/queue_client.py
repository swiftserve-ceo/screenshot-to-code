"""Process-wide arq pool for enqueueing jobs from the API.

The API only *enqueues*; the worker executes. Kept tiny and lazy so importing it
never forces a Redis connection (tests that don't touch the queue stay fast).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Literal, Optional

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from arq.constants import abort_jobs_ss, default_queue_name, health_check_key_suffix

from config import settings
from logging_config import get_logger

logger = get_logger("queue")

_pool: Optional[ArqRedis] = None

# arq writes this key every ``health_check_interval`` seconds with a TTL of
# ``interval + 1``; its presence means a worker recorded health recently.
_WORKER_HEALTH_KEY = f"{default_queue_name}{health_check_key_suffix}"


@dataclass(frozen=True)
class WorkerStatus:
    state: Literal["ok", "down"]
    detail: Optional[str] = None


async def check_worker(timeout: float = 3.0) -> WorkerStatus:
    """Report whether a live arq worker exists, via arq's health-check key.

    ``down`` means no worker has refreshed the key within its TTL (or Redis is
    unreachable — the Redis check in /health disambiguates). Never raises, never
    returns a connection string.
    """
    from redis_client import get_redis

    try:
        exists = await asyncio.wait_for(
            get_redis().exists(_WORKER_HEALTH_KEY), timeout=timeout
        )
        return WorkerStatus("ok") if exists else WorkerStatus("down", "no health key")
    except Exception as exc:  # noqa: BLE001 - health probe must never raise
        logger.warning("worker health check failed", extra={"error": type(exc).__name__})
        return WorkerStatus("down", type(exc).__name__)


async def get_arq_pool() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        logger.info("arq pool connected")
    return _pool


async def close_arq_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None


async def request_job_abort(job_id: str) -> None:
    """Fire-and-forget: ask a worker (allow_abort_jobs=True) to cancel a running
    task. Adds the job id to arq's abort sorted-set; the worker polls it and
    raises CancelledError in the matching task. Does not wait for the outcome."""
    import time

    pool = await get_arq_pool()
    await pool.zadd(abort_jobs_ss, {job_id: int(time.time() * 1000)})
