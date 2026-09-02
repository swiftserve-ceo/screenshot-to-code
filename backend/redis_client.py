"""Minimal Redis connectivity helper + non-fatal health probe."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Literal, Optional

from redis.asyncio import Redis

from config import settings
from logging_config import get_logger

logger = get_logger("redis")

_client: Optional[Redis] = None


def get_redis() -> Redis:
    """Process-wide Redis client (decoded responses)."""
    global _client
    if _client is None:
        _client = Redis.from_url(settings.redis_url, decode_responses=True)
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None


@dataclass(frozen=True)
class RedisStatus:
    state: Literal["ok", "error"]
    detail: Optional[str] = None


async def check_redis(timeout: float = 3.0) -> RedisStatus:
    """PING Redis without raising. Never returns the URL."""
    try:
        pong = await asyncio.wait_for(get_redis().ping(), timeout=timeout)
        return RedisStatus("ok" if pong else "error", None if pong else "no PONG")
    except Exception as exc:  # noqa: BLE001 - health probe must never raise
        logger.warning("redis health check failed", extra={"error": type(exc).__name__})
        return RedisStatus("error", type(exc).__name__)
