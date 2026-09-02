# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false, reportPrivateUsage=false
"""Phase 1 Batch 4 — queue / worker failure modes (spec §Queue failure modes A–F).

Every test drives real code paths; the only things faked are the *transport*
edges (a pool that refuses to connect, a worker that never runs).
"""

from typing import Any, cast

import pytest

import routes.generation_relay as relay_mod
from config import settings
from jobs.events import GENERATION_TYPE, JobEvent, JobEventChannel
from jobs.models import JobStatus
from jobs.service import JobService
import worker as worker_mod


class _CollectWS:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_json(self, payload: dict[str, Any]) -> None:
        self.sent.append(payload)

    async def close(self, code: int = 1000) -> None:
        self.sent.append({"closed": code})


TEXT_CREATE_PARAMS = {
    "generatedCodeConfig": "html_tailwind",
    "inputMode": "text",
    "generationType": "create",
    "prompt": {"text": "hello", "images": [], "videos": []},
    "history": [],
    "isImageGenerationEnabled": False,
}


# --- A. Redis unavailable -> API fails gracefully -----------------------------


async def test_a_redis_unavailable_fails_job_and_notifies_client(
    db_ready, clean_jobs, monkeypatch
):
    async def _boom():
        raise ConnectionError("cannot reach redis")

    monkeypatch.setattr(relay_mod, "get_arq_pool", _boom)
    monkeypatch.setattr(
        relay_mod, "settings", settings.model_copy(update={"job_queue_enabled": True})
    )

    ws = _CollectWS()
    await relay_mod.start_queued_generation(
        cast(Any, ws), dict(TEXT_CREATE_PARAMS), "http://127.0.0.1:7001", "req-A"
    )

    errors = [m for m in ws.sent if m.get("type") == "error"]
    assert len(errors) == 1
    assert "queue is temporarily unavailable" in errors[0]["value"]
    assert any(m.get("closed") == relay_mod.APP_ERROR_WEB_SOCKET_CODE for m in ws.sent)

    # the job must not be left dangling as QUEUED
    svc = JobService()
    recent = await svc.list_recent(limit=5)
    assert recent and recent[0].status is JobStatus.FAILED
    assert recent[0].error and "QueueUnavailable" in recent[0].error


# --- B. Worker down -> job stays QUEUED, API stays healthy -------------------


async def test_b_worker_down_leaves_job_queued_and_queryable(
    db_ready, clean_jobs, redis_ready, monkeypatch
):
    enqueued: list[tuple[str, tuple[Any, ...]]] = []

    class _Pool:
        async def enqueue_job(self, name: str, *args: Any, **kw: Any):
            enqueued.append((name, args))

    async def _pool():
        return _Pool()

    monkeypatch.setattr(relay_mod, "get_arq_pool", _pool)
    monkeypatch.setattr(
        relay_mod, "settings", settings.model_copy(update={"job_queue_enabled": True})
    )

    channel = JobEventChannel()
    svc = JobService(channel=channel)
    job = await svc.create(GENERATION_TYPE, params={"stack": "html_tailwind"})
    pool = await relay_mod.get_arq_pool()
    await pool.enqueue_job("execute_job", job.id)

    assert enqueued == [("execute_job", (job.id,))]
    # no worker ran -> still queued, still fetchable via the service (API path)
    fetched = await svc.get(job.id)
    assert fetched is not None and fetched.status is JobStatus.QUEUED
    await channel.close()


# --- C. Worker starts AFTER the job exists -> it is processed ---------------


async def test_c_worker_started_after_enqueue_processes_backlog(
    db_ready, clean_jobs, redis_ready
):
    channel = JobEventChannel()
    svc = JobService(channel=channel)
    job = await svc.create("noop", params={"result_ref": "local://late"})
    # job has been sitting QUEUED; now a worker comes up and drains it
    ctx = {"job_service": svc, "job_channel": channel, "job_try": 1}
    out = await worker_mod.execute_job(ctx, job.id)
    assert out["status"] == JobStatus.SUCCEEDED.value
    final = await svc.get(job.id)
    assert final is not None and final.status is JobStatus.SUCCEEDED
    await channel.close()


# --- D. Generation raises -> job FAILED with a sanitised error --------------


async def test_d_handler_exception_marks_failed_with_sanitised_error(
    db_ready, clean_jobs, redis_ready, monkeypatch, caplog
):
    channel = JobEventChannel()
    svc = JobService(channel=channel)

    async def _explode(ctx: dict[str, Any], job: Any) -> str:
        raise RuntimeError("boom sk-SECRET-abc123 internal path /etc/x\nsecond line")

    monkeypatch.setitem(worker_mod.JOB_HANDLERS, "noop", _explode)
    job = await svc.create("noop", max_attempts=1)
    ctx = {"job_service": svc, "job_channel": channel, "job_try": 1}
    out = await worker_mod.execute_job(ctx, job.id)

    assert out["status"] == JobStatus.FAILED.value
    final = await svc.get(job.id)
    assert final is not None and final.status is JobStatus.FAILED
    assert final.error is not None
    assert "\n" not in final.error and len(final.error) <= 500
    assert final.error.startswith("RuntimeError:")
    await channel.close()


# --- E. Worker terminates unexpectedly -> not falsely SUCCEEDED ------------


async def test_e_crashed_job_is_never_reported_succeeded(db_ready, clean_jobs):
    svc = JobService()
    job = await svc.create("noop")
    await svc.mark_running(job.id, worker="w-doomed")
    # worker is SIGKILLed here: no terminal transition is ever recorded.
    stuck = await svc.get(job.id)
    assert stuck is not None
    assert stuck.status is JobStatus.RUNNING
    assert stuck.status is not JobStatus.SUCCEEDED
    assert stuck.finished_at is None


async def test_e_new_worker_can_reacquire_a_running_job(db_ready, clean_jobs, redis_ready):
    channel = JobEventChannel()
    svc = JobService(channel=channel)
    job = await svc.create("noop", params={"result_ref": "local://recovered"}, max_attempts=3)
    await svc.mark_running(job.id, worker="w-doomed")  # previous worker, then crash

    # arq re-delivers; a fresh worker picks it up on attempt 2
    ctx = {"job_service": svc, "job_channel": channel, "job_try": 2}
    out = await worker_mod.execute_job(ctx, job.id)
    assert out["status"] == JobStatus.SUCCEEDED.value
    final = await svc.get(job.id)
    assert final is not None and final.status is JobStatus.SUCCEEDED
    assert final.worker != "w-doomed"
    await channel.close()


# --- F. Redis reconnect -> recover or fail cleanly -------------------------


async def test_f_event_channel_survives_a_transient_redis_client_reset(redis_ready):
    """A dropped Redis client is transparently rebuilt on next use; a publish
    after a reconnect still lands in the backlog."""
    import redis_client as rc

    channel = JobEventChannel()
    job_id = "reconnect-" + __import__("uuid").uuid4().hex[:8]
    await channel.publish(JobEvent(job_id=job_id, type="queued", status="queued"))

    # simulate a connection drop: close + null the shared client
    await rc.close_redis()
    rc._client = None

    # next publish must reconnect rather than raise
    await channel.publish(JobEvent(job_id=job_id, type="running", status="running"))
    backlog = await channel.replay(job_id)
    assert [e.type for e in backlog] == ["queued", "running"]
    await channel.close()


async def test_f_api_enqueue_after_pool_close_reconnects(redis_ready):
    import queue_client

    await queue_client.close_arq_pool()
    pool = await queue_client.get_arq_pool()
    # a real round-trip to Redis proves the reconnect worked
    job = await pool.enqueue_job("ping", "reconnect-check")
    assert job is not None
    await queue_client.close_arq_pool()


# --- worker liveness probe (spec FR-F2 / SC-006 / OB-5) ---------------------


async def test_check_worker_reads_arq_health_key(redis_ready):
    import queue_client
    from redis_client import get_redis

    r = get_redis()
    await r.delete(queue_client._WORKER_HEALTH_KEY)
    assert (await queue_client.check_worker()).state == "down"

    # arq sets this key with a short TTL every health_check_interval seconds
    await r.set(queue_client._WORKER_HEALTH_KEY, "j_complete=0 j_failed=0", ex=31)
    assert (await queue_client.check_worker()).state == "ok"
    await r.delete(queue_client._WORKER_HEALTH_KEY)
