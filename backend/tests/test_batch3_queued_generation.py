# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false
"""Phase 1 Batch 3 — the one migrated generation path (text → create) on the
Redis/arq worker.

Covers spec §12: job creation, worker lifecycle, disconnect independence,
reconnect/status, and security (no secrets in payload/logs, no code execution).
"""

import asyncio
from typing import Any, cast
import importlib
import json

import pytest

import routes.generation_relay as relay_mod
from config import settings
from jobs.events import GENERATION_TYPE, JobEvent, JobEventChannel
from jobs.models import JobStatus
from jobs.service import JobService

TEXT_CREATE_PARAMS = {
    "generatedCodeConfig": "html_tailwind",
    "inputMode": "text",
    "generationType": "create",
    "prompt": {"text": "A simple hello world landing page", "images": [], "videos": []},
    "history": [],
    "isImageGenerationEnabled": False,
    # secrets the browser would send — MUST NOT be persisted / enqueued
    "openAiApiKey": "sk-SECRET-should-not-persist",
    "anthropicApiKey": "sk-ant-SECRET",
    "geminiApiKey": "SECRET-gemini",
}

_SECRET_VALUES = ["sk-SECRET-should-not-persist", "sk-ant-SECRET", "SECRET-gemini"]


class _FakePool:
    def __init__(self):
        self.enqueued: list[tuple] = []

    async def enqueue_job(self, name, *args, **kwargs):
        self.enqueued.append((name, args, kwargs))
        return None


@pytest.fixture()
def queue_on(monkeypatch):
    monkeypatch.setattr(
        relay_mod, "settings", settings.model_copy(update={"job_queue_enabled": True})
    )


@pytest.fixture()
def testclient_infra():
    """For SYNC TestClient tests: require DB env + null the async clients so the
    app (running on TestClient's own loop) builds them there, not on the
    pytest-asyncio loop."""
    import os

    import db.engine as _dbe
    import redis_client as _rc

    if not os.environ.get("DATABASE_URL"):
        import pytest as _pytest

        (_pytest.fail if os.environ.get("REQUIRE_INFRA", "").lower() in {"1", "true"} else _pytest.skip)(
            "DATABASE_URL not set"
        )
    _dbe._engine = None
    _dbe._sessionmaker = None
    _rc._client = None
    yield
    _dbe._engine = None
    _dbe._sessionmaker = None
    _rc._client = None


# --- A. build_generation_request strips secrets --------------------------------

def test_build_generation_request_has_no_secrets():
    req = relay_mod.build_generation_request(dict(TEXT_CREATE_PARAMS), "http://127.0.0.1:7001")
    params = req.to_params()
    blob = json.dumps(params)
    for secret in _SECRET_VALUES:
        assert secret not in blob
    for key in ("openAiApiKey", "anthropicApiKey", "geminiApiKey", "replicateApiKey"):
        assert key not in params
    assert req.stack == "html_tailwind"
    assert req.input_mode == "text" and req.generation_type == "create"


def test_is_queued_text_create_gated_by_flag(queue_on):
    assert relay_mod.is_queued_text_create(dict(TEXT_CREATE_PARAMS)) is True
    # not text
    assert relay_mod.is_queued_text_create({**TEXT_CREATE_PARAMS, "inputMode": "image"}) is False
    # update
    assert relay_mod.is_queued_text_create({**TEXT_CREATE_PARAMS, "generationType": "update"}) is False
    # reconnect payloads are never "new"
    assert relay_mod.is_queued_text_create({**TEXT_CREATE_PARAMS, "jobId": "x"}) is False


async def test_flag_off_means_not_queued(db_ready):
    # default settings: job_queue_enabled is False
    assert relay_mod.is_queued_text_create(dict(TEXT_CREATE_PARAMS)) is False


# --- B. API creates + enqueues a job over the WebSocket -----------------------

def test_ws_creates_persisted_queued_job(monkeypatch, testclient_infra):
    fake_pool = _FakePool()

    async def _fake_get_pool():
        return fake_pool

    monkeypatch.setattr(relay_mod, "settings", settings.model_copy(update={"job_queue_enabled": True}))
    monkeypatch.setattr(relay_mod, "get_arq_pool", _fake_get_pool)

    from fastapi.testclient import TestClient

    main = importlib.import_module("main")
    importlib.reload(main)
    with TestClient(main.app) as client:
        with client.websocket_connect("/generate-code") as ws:
            ws.send_json(TEXT_CREATE_PARAMS)
            first = ws.receive_json()
            assert first["type"] == "jobCreated"
            job_id = first["value"]
            assert job_id
            # a "Queued…" status follows
            second = ws.receive_json()
            assert second["type"] == "status"

        # job persisted + queued (checked via the safe status endpoint)
        status = client.get(f"/api/jobs/{job_id}").json()
        assert status["job_type"] == GENERATION_TYPE
        assert status["status"] in ("queued", "running")
        assert "params" not in status

    # enqueued exactly once, with no secrets in the call
    assert fake_pool.enqueued == [("execute_job", (job_id,), {"_job_id": job_id})]
    assert not any(s in json.dumps(fake_pool.enqueued) for s in _SECRET_VALUES)


# --- C + E. worker runs the generation handler; missing key -> controlled FAIL

async def test_worker_generation_missing_credentials_fails_without_retry(
    db_ready, clean_jobs, redis_ready, monkeypatch, caplog
):
    import config
    import worker as worker_mod

    # No server provider keys (whatever the machine has, force empty).
    no_keys = settings.model_copy(
        update={"openai_api_key": None, "anthropic_api_key": None, "gemini_api_key": None}
    )
    monkeypatch.setattr(config, "settings", no_keys)
    monkeypatch.setattr("generation.service.settings", no_keys)

    channel = JobEventChannel()
    svc = JobService(channel=channel)
    job = await svc.create(
        GENERATION_TYPE,
        params={
            "stack": "html_tailwind",
            "prompt": {"text": "hi", "images": [], "videos": []},
            "history": [],
            "input_mode": "text",
            "generation_type": "create",
        },
        max_attempts=3,
    )

    ctx = {"job_service": svc, "job_channel": channel, "job_try": 1}
    out = await worker_mod.execute_job(ctx, job.id)

    assert out["status"] == JobStatus.FAILED.value
    final = await svc.get(job.id)
    assert final is not None
    assert final.status is JobStatus.FAILED
    assert final.attempt == 1  # deterministic failure -> not retried
    assert final.error and "\n" not in final.error and len(final.error) <= 500
    # a client-facing error event is on the backlog
    events = await channel.replay(job.id)
    assert any(
        e.type == GENERATION_TYPE and (e.payload or {}).get("message_type") == "error"
        for e in events
    ), "expected a generation 'error' event"
    # no secret ever logged
    for secret in _SECRET_VALUES:
        assert secret not in caplog.text
    await channel.close()


# --- C. relay tolerates a disconnected client without touching the job --------

async def test_relay_disconnect_does_not_change_job(db_ready, clean_jobs, redis_ready):
    channel = JobEventChannel()
    svc = JobService(channel=channel)
    job = await svc.create(GENERATION_TYPE, params={"stack": "html_tailwind"})
    await svc.mark_running(job.id, worker="w")  # pretend the worker started it

    class _DeadWS:
        async def send_json(self, payload):
            from starlette.websockets import WebSocketDisconnect

            raise WebSocketDisconnect()

        async def close(self, code=1000):
            pass

    # publish an event so the relay has something to forward (and then blow up on send)
    await channel.publish(JobEvent(job_id=job.id, type="running", status="running"))
    await relay_mod._relay(cast(Any, _DeadWS()), job.id, channel, svc)  # must not raise

    after = await svc.get(job.id)
    assert after is not None and after.status is JobStatus.RUNNING  # untouched
    await channel.close()


# --- D. reconnect: resume_job replays the backlog ---------------------------

async def test_resume_job_replays_backlog(db_ready, clean_jobs, redis_ready):
    channel = JobEventChannel()
    svc = JobService(channel=channel)
    job = await svc.create(GENERATION_TYPE, params={"stack": "html_tailwind"})
    await svc.mark_running(job.id, worker="w")
    await channel.publish(
        JobEvent(
            job_id=job.id,
            type=GENERATION_TYPE,
            status="running",
            payload={"message_type": "setCode", "value": "<html>done</html>", "variant_index": 0},
        )
    )
    await svc.mark_succeeded(job.id, result_ref=f"eventlog:{job.id}")

    sent: list[dict] = []

    class _CollectWS:
        async def send_json(self, payload):
            sent.append(payload)

        async def close(self, code=1000):
            sent.append({"closed": code})

    await relay_mod.resume_job(cast(Any, _CollectWS()), job.id)

    types = [m.get("type") for m in sent]
    assert "jobCreated" in types
    assert "setCode" in types
    assert any(m.get("closed") == 1000 for m in sent)  # terminal -> normal close
    await channel.close()


async def test_failed_job_relays_exactly_one_error(db_ready, clean_jobs, redis_ready):
    """A failed queued generation must produce exactly ONE user-facing error.

    The worker emits a descriptive generation ``error`` event and then the job
    transitions to FAILED. The relay must not append a second (sanitised)
    ``error`` on the terminal transition.
    """
    channel = JobEventChannel()
    svc = JobService(channel=channel)
    job = await svc.create(GENERATION_TYPE, params={"stack": "html_tailwind"})
    await svc.mark_running(job.id, worker="w")
    await channel.publish(
        JobEvent(
            job_id=job.id,
            type=GENERATION_TYPE,
            status="running",
            payload={
                "message_type": "error",
                "value": "No Anthropic API key configured.",
                "variant_index": 0,
            },
        )
    )
    await svc.mark_failed(job.id, error="RuntimeError: boom internal detail")

    sent: list[dict] = []

    class _CollectWS:
        async def send_json(self, payload):
            sent.append(payload)

        async def close(self, code=1000):
            sent.append({"closed": code})

    await relay_mod.resume_job(cast(Any, _CollectWS()), job.id)

    errors = [m for m in sent if m.get("type") == "error"]
    assert len(errors) == 1, f"expected exactly one error message, got {errors}"
    assert errors[0]["value"] == "No Anthropic API key configured."
    # internal exception text is never surfaced
    assert not any("boom internal detail" in json.dumps(m) for m in sent)
    assert any(m.get("closed") == relay_mod.APP_ERROR_WEB_SOCKET_CODE for m in sent)
    await channel.close()


async def test_failed_job_without_prior_error_gets_one_sanitised_error(
    db_ready, clean_jobs, redis_ready
):
    """If the worker never emitted an ``error`` event, the terminal transition
    supplies exactly one sanitised error."""
    channel = JobEventChannel()
    svc = JobService(channel=channel)
    job = await svc.create(GENERATION_TYPE, params={"stack": "html_tailwind"})
    await svc.mark_running(job.id, worker="w")
    await svc.mark_failed(job.id, error="RuntimeError: internal traceback detail")

    sent: list[dict] = []

    class _CollectWS:
        async def send_json(self, payload):
            sent.append(payload)

        async def close(self, code=1000):
            sent.append({"closed": code})

    await relay_mod.resume_job(cast(Any, _CollectWS()), job.id)

    errors = [m for m in sent if m.get("type") == "error"]
    assert len(errors) == 1, f"expected exactly one error message, got {errors}"
    assert "internal traceback detail" not in json.dumps(sent)
    await channel.close()


def test_job_status_endpoint_is_safe(monkeypatch, testclient_infra):
    from fastapi.testclient import TestClient

    fake_pool = _FakePool()

    async def _fake_get_pool():
        return fake_pool

    monkeypatch.setattr(relay_mod, "settings", settings.model_copy(update={"job_queue_enabled": True}))
    monkeypatch.setattr(relay_mod, "get_arq_pool", _fake_get_pool)

    main = importlib.import_module("main")
    importlib.reload(main)
    with TestClient(main.app) as client:
        # create a real generation job via the WS relay
        with client.websocket_connect("/generate-code") as ws:
            ws.send_json(TEXT_CREATE_PARAMS)
            job_id = ws.receive_json()["value"]

        resp = client.get(f"/api/jobs/{job_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert set(body) == {
            "job_id", "job_type", "status", "created_at", "started_at",
            "finished_at", "error", "request_id",
        }
        assert "params" not in body and "worker" not in body and "result_ref" not in body
        for secret in _SECRET_VALUES:
            assert secret not in resp.text
        assert client.get("/api/jobs/does-not-exist").status_code == 404


async def test_cancel_queued_job_sets_cancelled(db_ready, clean_jobs, redis_ready):
    """Explicit cancel of a QUEUED job -> CANCELLED; the worker then skips it
    (spec FR-F9 / JL-5). A client disconnect never does this (FR-F8)."""
    from routes.jobs import cancel_job

    channel = JobEventChannel()
    svc = JobService(channel=channel)
    job = await svc.create(GENERATION_TYPE, params={"stack": "html_tailwind"})

    resp = await cancel_job(job.id)
    assert resp.status == JobStatus.CANCELLED.value

    # the worker must respect the prior cancellation and not run it
    import worker as worker_mod

    ctx = {"job_service": svc, "job_channel": channel, "job_try": 1}
    out = await worker_mod.execute_job(ctx, job.id)
    assert out["status"] == JobStatus.CANCELLED.value
    final = await svc.get(job.id)
    assert final is not None and final.status is JobStatus.CANCELLED
    await channel.close()


async def test_cancel_notifies_a_connected_relay(db_ready, clean_jobs, redis_ready):
    """cancel_job publishes the `cancelled` lifecycle event so a relay watching
    the job closes the socket with the user-close code (FR-F9 notify)."""
    from routes.jobs import cancel_job

    channel = JobEventChannel()
    svc = JobService(channel=channel)
    job = await svc.create(GENERATION_TYPE, params={"stack": "html_tailwind"})

    sent: list[dict] = []

    class _WS:
        async def send_json(self, p):
            sent.append(p)

        async def close(self, code=1000):
            sent.append({"closed": code})

    async def _run_relay():
        await relay_mod._relay(
            cast(Any, _WS()), job.id, JobEventChannel(), JobService(channel=JobEventChannel())
        )

    task = asyncio.create_task(_run_relay())
    await asyncio.sleep(0.5)
    await cancel_job(job.id)
    await asyncio.wait_for(task, timeout=5)

    assert any(
        m.get("closed") == relay_mod.USER_CLOSE_WEB_SOCKET_CODE for m in sent
    ), f"relay did not close with the user-close code: {sent}"
    await channel.close()


async def test_cancel_terminal_job_is_conflict(db_ready, clean_jobs, redis_ready):
    from fastapi import HTTPException

    from routes.jobs import cancel_job

    svc = JobService()
    job = await svc.create(GENERATION_TYPE, params={"stack": "html_tailwind"})
    await svc.mark_running(job.id, worker="w")
    await svc.mark_succeeded(job.id)

    try:
        await cancel_job(job.id)
        assert False, "expected 409"
    except HTTPException as exc:
        assert exc.status_code == 409

    try:
        await cancel_job("no-such-job")
        assert False, "expected 404"
    except HTTPException as exc:
        assert exc.status_code == 404
