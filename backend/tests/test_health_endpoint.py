# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false
"""/health readiness endpoint."""

import importlib

from fastapi.testclient import TestClient


def _client():
    main = importlib.import_module("main")
    importlib.reload(main)
    return TestClient(main.app)


def test_health_shape_and_no_leak():
    with _client() as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert set(body) == {"status", "checks", "job_queue_enabled"}
        assert set(body["checks"]) == {"database", "redis", "worker"}
        assert body["status"] in {"ok", "degraded"}
        assert body["job_queue_enabled"] is False
        # never leak a URL / credentials
        assert "://" not in resp.text
        assert "5432" not in resp.text and "6379" not in resp.text


def test_root_liveness_unchanged():
    with _client() as client:
        resp = client.get("/")
        assert resp.status_code == 200
        assert "backend is running" in resp.text.lower()


def test_health_degraded_when_redis_down(monkeypatch):
    import main  # already imported by other tests / at least importable
    import routes.health as health_mod
    from redis_client import RedisStatus
    from db.engine import DatabaseStatus

    async def _redis_down(timeout: float = 3.0):
        return RedisStatus("error", "ConnectionError")

    async def _db_disabled(timeout: float = 3.0):
        return DatabaseStatus("disabled", "DATABASE_URL not set")

    async def _worker_ok(timeout: float = 3.0):
        from queue_client import WorkerStatus

        return WorkerStatus("ok")

    monkeypatch.setattr(health_mod, "check_redis", _redis_down)
    monkeypatch.setattr(health_mod, "check_database", _db_disabled)
    monkeypatch.setattr(health_mod, "check_worker", _worker_ok)

    with TestClient(main.app) as client:
        resp = client.get("/health")
        assert resp.json()["status"] == "degraded"
        assert resp.json()["checks"] == {
            "database": "disabled",
            "redis": "error",
            "worker": "ok",
        }


def test_health_degraded_when_queue_on_but_no_worker(monkeypatch):
    import main
    import routes.health as health_mod
    from config import settings as real_settings
    from db.engine import DatabaseStatus
    from queue_client import WorkerStatus
    from redis_client import RedisStatus

    async def _redis_ok(timeout: float = 3.0):
        return RedisStatus("ok")

    async def _db_ok(timeout: float = 3.0):
        return DatabaseStatus("ok")

    async def _worker_down(timeout: float = 3.0):
        return WorkerStatus("down", "no health key")

    monkeypatch.setattr(health_mod, "check_redis", _redis_ok)
    monkeypatch.setattr(health_mod, "check_database", _db_ok)
    monkeypatch.setattr(health_mod, "check_worker", _worker_down)
    monkeypatch.setattr(
        health_mod, "settings", real_settings.model_copy(update={"job_queue_enabled": True})
    )

    with TestClient(main.app) as client:
        body = client.get("/health").json()
        assert body["status"] == "degraded"
        assert body["checks"]["worker"] == "down"
        assert body["job_queue_enabled"] is True
