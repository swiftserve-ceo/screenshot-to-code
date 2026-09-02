"""Config + Alembic wiring cover that needs no running services."""

from pathlib import Path

import pytest

from config import Settings


def test_database_url_normalises_plain_scheme(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
    s = Settings.from_env()
    assert s.database_url == "postgresql+asyncpg://u:p@localhost:5432/db"


def test_database_url_rejects_non_postgres(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "mysql://x")
    with pytest.raises(Exception):
        Settings.from_env()


def test_database_url_optional(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    s = Settings.from_env()
    assert s.database_url is None


def test_job_and_redis_settings_defaults(monkeypatch):
    for k in ("REDIS_URL", "JOB_QUEUE_ENABLED", "JOB_MAX_ATTEMPTS", "JOB_TIMEOUT_SECONDS", "WORKER_NAME"):
        monkeypatch.delenv(k, raising=False)
    s = Settings.from_env()
    assert s.redis_url == "redis://127.0.0.1:6379/0"
    assert s.job_queue_enabled is False
    assert s.job_max_attempts == 3
    assert s.job_timeout_seconds == 900


def test_alembic_scaffold_present():
    backend = Path(__file__).resolve().parents[1]
    assert (backend / "alembic.ini").is_file()
    assert (backend / "migrations" / "env.py").is_file()
    assert (backend / "migrations" / "script.py.mako").is_file()
    versions = list((backend / "migrations" / "versions").glob("*.py"))
    assert len(versions) >= 1, "expected at least the baseline migration"


def test_baseline_migration_is_a_single_head_and_only_infra_tables():
    backend = Path(__file__).resolve().parents[1]
    versions = sorted((backend / "migrations" / "versions").glob("*.py"))
    texts = [p.read_text(encoding="utf-8") for p in versions]
    heads = [t for t in texts if "down_revision: Union[str, None] = None" in t or "down_revision = None" in t]
    assert len(heads) == 1, "exactly one base migration expected"
    joined = "\n".join(texts).lower()
    assert "create_table('jobs'" in joined
    for forbidden in ("create_table('users'", "create_table('organizations'", "create_table('projects'", "create_table('workspaces'"):
        assert forbidden not in joined, f"domain table {forbidden!r} must not exist yet"
