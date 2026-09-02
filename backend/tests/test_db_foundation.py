# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false
"""Database foundation — connection lifecycle + non-fatal health probe."""

import pytest
from sqlalchemy import text

import db.engine as engine_mod
from db.engine import (
    DatabaseNotConfiguredError,
    DatabaseStatus,
    check_database,
    get_engine,
    session_scope,
)


def _with_url(url):
    return engine_mod.settings.model_copy(update={"database_url": url})


async def test_check_database_disabled_when_unset(monkeypatch):
    monkeypatch.setattr(engine_mod, "settings", _with_url(None))
    status = await check_database()
    assert status == DatabaseStatus("disabled", "DATABASE_URL not set")


async def test_get_engine_raises_when_unset(monkeypatch):
    monkeypatch.setattr(engine_mod, "settings", _with_url(None))
    monkeypatch.setattr(engine_mod, "_engine", None)
    with pytest.raises(DatabaseNotConfiguredError):
        get_engine()


async def test_check_database_error_is_not_raised(monkeypatch):
    monkeypatch.setattr(
        engine_mod,
        "settings",
        _with_url("postgresql+asyncpg://nobody:nobody@127.0.0.1:59999/nope"),
    )
    monkeypatch.setattr(engine_mod, "_engine", None)
    monkeypatch.setattr(engine_mod, "_sessionmaker", None)
    status = await check_database(timeout=2.0)
    assert status.state == "error"
    assert "59999" not in (status.detail or "")  # no connection string leaked


async def test_check_database_ok(db_ready):
    status = await check_database()
    assert status.state == "ok"


async def test_session_scope_commits_and_closes(db_ready):
    async with session_scope() as session:
        value = (await session.execute(text("SELECT 1"))).scalar_one()
        assert value == 1


async def test_session_scope_rolls_back_on_error(db_ready):
    with pytest.raises(RuntimeError):
        async with session_scope() as session:
            await session.execute(text("SELECT 1"))
            raise RuntimeError("boom")
    # engine still usable afterwards
    async with session_scope() as session:
        assert (await session.execute(text("SELECT 2"))).scalar_one() == 2


async def test_jobs_table_exists_after_migration(db_ready):
    async with session_scope() as session:
        exists = (
            await session.execute(
                text("SELECT to_regclass('public.jobs') IS NOT NULL")
            )
        ).scalar_one()
        assert exists is True
