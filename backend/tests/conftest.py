# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false
"""Shared fixtures for infrastructure-dependent tests (Batch 2).

Tests that need a real PostgreSQL / Redis use the ``db_ready`` / ``redis_ready``
fixtures. They **skip** when the service is unreachable — so ``pytest`` stays
green on a machine without ``docker compose up -d postgres redis``.

CI sets ``REQUIRE_INFRA=1`` (and ``DATABASE_URL`` / ``REDIS_URL``): then a
would-be skip becomes a hard failure, so CI genuinely exercises the stack.
"""

from __future__ import annotations

import asyncio
import os

import pytest

REQUIRE_INFRA = os.environ.get("REQUIRE_INFRA", "").lower() in {"1", "true", "yes", "on"}


def _fail_or_skip(reason: str) -> None:
    if REQUIRE_INFRA:
        pytest.fail(f"REQUIRE_INFRA=1 but {reason}")
    pytest.skip(reason)


@pytest.fixture(autouse=True)
def _isolate_async_clients():
    """Drop the process-wide async engine / Redis client around every test.

    asyncpg connections and redis-py async clients are event-loop-bound;
    pytest-asyncio and Starlette's TestClient run on different loops, so a leaked
    client causes "attached to a different loop". We null the module globals
    (rather than `await ...dispose()`, which would itself need the original
    loop) so each test lazily builds fresh clients on its own loop. Idle pooled
    connections are reclaimed by the server / GC.
    """
    import db.engine as _dbe
    import queue_client as _qc
    import redis_client as _rc

    import preview_screenshot.registry as _psr

    _screenshot_available = _psr._available

    _dbe._engine = None
    _dbe._sessionmaker = None
    _rc._client = None
    _qc._pool = None
    yield
    _dbe._engine = None
    _dbe._sessionmaker = None
    _rc._client = None
    _qc._pool = None
    # worker._on_startup hard-disables screenshot_preview process-wide; restore it
    # so it doesn't bleed into unrelated tests.
    _psr._available = _screenshot_available


@pytest.fixture()
async def db_ready():
    """Ensure the database is reachable and migrated; yields nothing."""
    from config import settings
    from db.engine import check_database, dispose_engine

    if not settings.database_url:
        _fail_or_skip("DATABASE_URL is not set")
    status = await check_database()
    if status.state != "ok":
        _fail_or_skip(f"database not reachable ({status.detail})")
    yield
    await dispose_engine()


@pytest.fixture()
async def redis_ready():
    from redis_client import check_redis, close_redis

    status = await check_redis()
    if status.state != "ok":
        _fail_or_skip(f"redis not reachable ({status.detail})")
    yield
    await close_redis()


@pytest.fixture()
async def clean_jobs(db_ready):
    """Truncate the jobs table before and after a test."""
    from sqlalchemy import text

    from db.engine import session_scope

    async with session_scope() as session:
        await session.execute(text("DELETE FROM jobs"))
    yield
    async with session_scope() as session:
        await session.execute(text("DELETE FROM jobs"))
