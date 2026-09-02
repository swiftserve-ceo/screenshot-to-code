"""Database foundation (Phase 1 Batch 2).

A thin async SQLAlchemy 2.0 layer: engine + session lifecycle + a health probe.
**No domain models** — later phases add tables via Alembic migrations. The only
infrastructure table is ``jobs`` (see ``jobs.models``).

The database is **optional**: if ``DATABASE_URL`` is unset or unreachable the app
still starts and the synchronous generation path keeps working; the health
endpoint reports the database as unavailable.
"""

from db.base import Base
from db.engine import (
    DatabaseStatus,
    check_database,
    dispose_engine,
    get_engine,
    get_sessionmaker,
    session_scope,
)

__all__ = [
    "Base",
    "DatabaseStatus",
    "check_database",
    "dispose_engine",
    "get_engine",
    "get_sessionmaker",
    "session_scope",
]
