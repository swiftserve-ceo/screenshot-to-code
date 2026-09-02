"""Alembic environment — async engine, URL from the typed settings.

``alembic upgrade head`` / ``alembic downgrade base`` both work. If
``DATABASE_URL`` is unset, Alembic exits with a clear message rather than a
traceback.
"""

from __future__ import annotations

import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy import pool

# Make the backend package importable when alembic runs from backend/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import settings  # noqa: E402
from db.base import Base  # noqa: E402

# Import every module that defines tables so autogenerate sees them.
import jobs.models  # noqa: E402,F401

alembic_config = context.config

if alembic_config.config_file_name is not None:
    fileConfig(alembic_config.config_file_name)

target_metadata = Base.metadata


def _require_url() -> str:
    if not settings.database_url:
        raise SystemExit(
            "DATABASE_URL is not set. Start Postgres (docker compose up -d postgres) "
            "and export DATABASE_URL, e.g. "
            "postgresql+asyncpg://appbuilder:appbuilder@localhost:5432/appbuilder"
        )
    return settings.database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_require_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection) -> None:
    context.configure(
        connection=connection, target_metadata=target_metadata, compare_type=True
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    configuration = alembic_config.get_section(alembic_config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _require_url()
    connectable = async_engine_from_config(
        configuration, prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
