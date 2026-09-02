# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false, reportPrivateUsage=false
"""Phase 1 Batch 4 — live queue smoke test (spec: CI live queue smoke test).

A **real** end-to-end trip through the queue with nothing faked:

    JobService.create  ->  arq pool.enqueue_job  ->  Redis
                        ->  a real arq Worker (burst mode)
                        ->  execute_job  ->  the ``noop`` handler
                        ->  terminal state in Postgres

No AI provider is touched. Deterministic and fast (burst mode exits as soon as
the queue drains).
"""

import asyncio

import pytest
from arq.connections import RedisSettings
from arq.worker import Worker

from config import settings
from jobs.events import JobEventChannel
from jobs.models import JobStatus
from jobs.service import JobService
from queue_client import close_arq_pool, get_arq_pool
from worker import _on_shutdown, _on_startup, execute_job, ping

pytestmark = pytest.mark.asyncio


async def _run_worker_burst() -> None:
    worker = Worker(
        functions=[execute_job, ping],
        redis_settings=RedisSettings.from_dsn(settings.redis_url),
        on_startup=_on_startup,
        on_shutdown=_on_shutdown,
        burst=True,
        poll_delay=0.1,
        max_tries=1,
        handle_signals=False,
    )
    try:
        await worker.async_run()
    finally:
        # arq's close() sends SIGUSR1 unless it thinks it owns signal handling;
        # that signal does not exist on Windows. Flip the flag so close() skips
        # it and still runs on_shutdown + closes the Redis pool.
        worker._handle_signals = True
        await worker.close()


async def test_live_queue_processes_a_noop_job_end_to_end(
    db_ready, clean_jobs, redis_ready
):
    channel = JobEventChannel()
    svc = JobService(channel=channel)
    job = await svc.create("noop", params={"result_ref": "local://smoke-ok"})

    pool = await get_arq_pool()
    enqueued = await pool.enqueue_job("execute_job", job.id)
    assert enqueued is not None

    await _run_worker_burst()

    final = await svc.get(job.id)
    assert final is not None
    assert final.status is JobStatus.SUCCEEDED
    assert final.result_ref == "local://smoke-ok"
    assert final.attempt == 1

    # the terminal event reached the Redis backlog a reconnecting client reads
    events = await channel.replay(job.id)
    assert [e.type for e in events][-1] == "succeeded"

    await channel.close()
    await close_arq_pool()


async def test_live_queue_marks_a_failing_job_failed(db_ready, clean_jobs, redis_ready):
    channel = JobEventChannel()
    svc = JobService(channel=channel)
    # noop handler raises while job.attempt <= fail_times; max_attempts=1 => no retry
    job = await svc.create("noop", params={"fail_times": 5}, max_attempts=1)

    pool = await get_arq_pool()
    await pool.enqueue_job("execute_job", job.id)

    await _run_worker_burst()

    final = await svc.get(job.id)
    assert final is not None
    assert final.status is JobStatus.FAILED
    assert final.error and final.error.startswith("RuntimeError:")

    await channel.close()
    await close_arq_pool()


async def test_live_cancel_aborts_a_running_job(db_ready, clean_jobs, redis_ready):
    """End-to-end explicit cancellation (spec FR-F9 / JL-5): a real worker picks
    up a slow job, POST /api/jobs/{id}/cancel sets it CANCELLED and signals arq
    abort, the worker task is cancelled and does not fall through to succeeded."""
    from routes.jobs import cancel_job

    channel = JobEventChannel()
    svc = JobService(channel=channel)
    job = await svc.create("noop", params={"sleep_seconds": 30}, max_attempts=1)

    pool = await get_arq_pool()
    await pool.enqueue_job("execute_job", job.id, _job_id=job.id)

    worker = Worker(
        functions=[execute_job, ping],
        redis_settings=RedisSettings.from_dsn(settings.redis_url),
        on_startup=_on_startup,
        on_shutdown=_on_shutdown,
        poll_delay=0.1,
        max_tries=1,
        handle_signals=False,
        allow_abort_jobs=True,
    )
    run = asyncio.create_task(worker.async_run())
    try:
        # wait until the worker has marked it running
        for _ in range(100):
            await asyncio.sleep(0.1)
            cur = await svc.get(job.id)
            if cur is not None and cur.status is JobStatus.RUNNING:
                break
        else:
            raise AssertionError("job never reached RUNNING")

        resp = await cancel_job(job.id)
        assert resp.status == JobStatus.CANCELLED.value

        # the worker task should stop well before the 30s sleep completes
        for _ in range(100):
            await asyncio.sleep(0.1)
            final = await svc.get(job.id)
            assert final is not None
            if final.status is JobStatus.CANCELLED:
                break
        assert final is not None and final.status is JobStatus.CANCELLED
        assert final.status is not JobStatus.SUCCEEDED
    finally:
        worker._handle_signals = True
        await worker.close()
        run.cancel()
        try:
            await run
        except (asyncio.CancelledError, Exception):
            pass
        await channel.close()
        await close_arq_pool()
