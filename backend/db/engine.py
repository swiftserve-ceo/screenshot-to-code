"""Async engine + session lifecycle + a non-fatal health probe."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator, Literal, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config import settings
from logging_config import get_logger

logger = get_logger("db")

_engine: Optional[AsyncEngine] = None
_sessionmaker: Optional[async_sessionmaker[AsyncSession]] = None
_lock = asyncio.Lock()


class DatabaseNotConfiguredError(RuntimeError):
    """Raised when a DB operation is attempted but DATABASE_URL is unset."""


def _build_engine() -> AsyncEngine:
    assert settings.database_url is not None
    return create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        pool_recycle=1800,
        future=True,
    )


def get_engine() -> AsyncEngine:
    """Return the process-wide async engine. Raises if DATABASE_URL is unset."""
    global _engine
    if settings.database_url is None:
        raise DatabaseNotConfiguredError("DATABASE_URL is not set")
    if _engine is None:
        _engine = _build_engine()
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            get_engine(), expire_on_commit=False, class_=AsyncSession
        )
    return _sessionmaker


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """A transactional session: commits on success, rolls back on error, always
    closes. Use for a unit of work; do not leak the session past the block."""
    maker = get_sessionmaker()
    session = maker()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def dispose_engine() -> None:
    """Dispose the engine and its pool (call on shutdown)."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


@dataclass(frozen=True)
class DatabaseStatus:
    state: Literal["ok", "error", "disabled"]
    detail: Optional[str] = None


async def check_database(timeout: float = 3.0) -> DatabaseStatus:
    """Detect database availability without raising.

    Returns ``disabled`` when no DATABASE_URL is configured, ``ok`` when a
    ``SELECT 1`` round-trips, ``error`` (with a short reason, no connection
    string) otherwise.
    """
    if settings.database_url is None:
        return DatabaseStatus("disabled", "DATABASE_URL not set")
    async def _probe() -> None:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    try:
        await asyncio.wait_for(_probe(), timeout=timeout)
        return DatabaseStatus("ok")
    except Exception as exc:  # noqa: BLE001 - health probe must never raise
        logger.warning("database health check failed", extra={"error": type(exc).__name__})
        return DatabaseStatus("error", type(exc).__name__)
