# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false
"""Job lifecycle service against a real Postgres (see conftest db_ready)."""

from datetime import timedelta

import pytest

from db.base import utcnow
from jobs.models import JobStatus
from jobs.service import InvalidJobTransition, JobService


async def test_create_starts_queued(db_ready, clean_jobs):
    svc = JobService()
    job = await svc.create("noop", params={"k": "v"}, request_id="req-1")
    assert job.status is JobStatus.QUEUED
    assert job.attempt == 0
    assert job.request_id == "req-1"
    assert job.created_at is not None
    assert job.started_at is None and job.finished_at is None


async def test_happy_path_lifecycle(db_ready, clean_jobs):
    svc = JobService()
    job = await svc.create("noop")
    job = await svc.mark_running(job.id, worker="w1")
    assert job.status is JobStatus.RUNNING
    assert job.attempt == 1
    assert job.started_at is not None
    assert job.worker == "w1"
    job = await svc.mark_succeeded(job.id, result_ref="local://out/1")
    assert job.status is JobStatus.SUCCEEDED
    assert job.finished_at is not None
    assert job.result_ref == "local://out/1"
    assert job.error is None


async def test_failure_records_error_summary(db_ready, clean_jobs):
    svc = JobService()
    job = await svc.create("noop")
    await svc.mark_running(job.id, worker="w1")
    job = await svc.mark_failed(job.id, error="RuntimeError: kaboom")
    assert job.status is JobStatus.FAILED
    assert job.error == "RuntimeError: kaboom"
    assert job.finished_at is not None


async def test_cancel_from_queued(db_ready, clean_jobs):
    svc = JobService()
    job = await svc.create("noop")
    job = await svc.mark_cancelled(job.id, error="user cancelled")
    assert job.status is JobStatus.CANCELLED
    assert job.finished_at is not None


async def test_illegal_transitions_blocked(db_ready, clean_jobs):
    svc = JobService()
    job = await svc.create("noop")
    await svc.mark_running(job.id, worker="w1")
    await svc.mark_succeeded(job.id)
    with pytest.raises(InvalidJobTransition):
        await svc.mark_running(job.id, worker="w1")
    with pytest.raises(InvalidJobTransition):
        await svc.mark_failed(job.id, error="x")


async def test_retry_requeue_keeps_attempt_and_clears_timing(db_ready, clean_jobs):
    svc = JobService()
    job = await svc.create("noop", max_attempts=3)
    job = await svc.mark_running(job.id, worker="w1")
    assert job.attempt == 1
    job = await svc.requeue_for_retry(job.id, error="transient")
    assert job.status is JobStatus.QUEUED
    assert job.attempt == 1  # not bumped by requeue
    assert job.started_at is None and job.finished_at is None
    assert job.error == "transient"
    # second run bumps attempt
    job = await svc.mark_running(job.id, worker="w1")
    assert job.attempt == 2


async def test_terminal_marks_are_idempotent(db_ready, clean_jobs):
    """A re-delivered worker message (double mark_succeeded / mark_failed) must
    not raise and must not change the recorded outcome."""
    svc = JobService()
    job = await svc.create("noop")
    await svc.mark_running(job.id, worker="w1")
    first = await svc.mark_succeeded(job.id, result_ref="local://out/1")
    again = await svc.mark_succeeded(job.id, result_ref="local://out/IGNORED")
    assert again.status is JobStatus.SUCCEEDED
    assert again.finished_at == first.finished_at
    assert again.result_ref == "local://out/1"  # unchanged

    # failed is likewise idempotent
    job2 = await svc.create("noop")
    await svc.mark_running(job2.id, worker="w1")
    await svc.mark_failed(job2.id, error="ValueError: bad")
    repeat = await svc.mark_failed(job2.id, error="ValueError: different")
    assert repeat.error == "ValueError: bad"


async def test_idempotency_does_not_cross_terminal_states(db_ready, clean_jobs):
    svc = JobService()
    job = await svc.create("noop")
    await svc.mark_running(job.id, worker="w1")
    await svc.mark_succeeded(job.id)
    with pytest.raises(InvalidJobTransition):
        await svc.mark_failed(job.id, error="x")
    with pytest.raises(InvalidJobTransition):
        await svc.mark_cancelled(job.id)


async def test_prune_terminal_respects_retention_and_never_touches_active(
    db_ready, clean_jobs
):
    svc = JobService()
    old_done = await svc.create("noop")
    await svc.mark_running(old_done.id, worker="w1")
    await svc.mark_succeeded(old_done.id)
    recent_done = await svc.create("noop")
    await svc.mark_running(recent_done.id, worker="w1")
    await svc.mark_failed(recent_done.id, error="RuntimeError: x")
    queued = await svc.create("noop")
    running = await svc.create("noop")
    await svc.mark_running(running.id, worker="w1")

    # nothing is old yet
    assert await svc.prune_terminal(retention_days=7) == 0

    # pretend "now" is 30 days in the future
    future = utcnow() + timedelta(days=30)
    deleted = await svc.prune_terminal(retention_days=7, now=future)
    assert deleted == 2  # both terminal jobs
    assert await svc.get(old_done.id) is None
    assert await svc.get(recent_done.id) is None
    # active jobs survive regardless of age
    surviving_queued = await svc.get(queued.id)
    surviving_running = await svc.get(running.id)
    assert surviving_queued is not None and surviving_queued.status is JobStatus.QUEUED
    assert surviving_running is not None and surviving_running.status is JobStatus.RUNNING


async def test_reap_stuck_running_fails_only_old_running_jobs(db_ready, clean_jobs):
    svc = JobService()
    stuck = await svc.create("noop")
    await svc.mark_running(stuck.id, worker="w-dead")
    fresh = await svc.create("noop")
    await svc.mark_running(fresh.id, worker="w-live")
    queued = await svc.create("noop")
    done = await svc.create("noop")
    await svc.mark_running(done.id, worker="w")
    await svc.mark_succeeded(done.id)

    # nothing is old yet
    assert await svc.reap_stuck_running(max_running_seconds=900) == 0

    future = utcnow() + timedelta(hours=2)
    reaped = await svc.reap_stuck_running(max_running_seconds=900, now=future)
    assert reaped == 2  # both running jobs are now "old" relative to `future`

    for jid, expected in ((stuck.id, JobStatus.FAILED), (queued.id, JobStatus.QUEUED),
                          (done.id, JobStatus.SUCCEEDED)):
        j = await svc.get(jid)
        assert j is not None and j.status is expected
    failed = await svc.get(stuck.id)
    assert failed is not None and failed.error and "WatchdogTimeout" in failed.error
    assert failed.finished_at is not None


async def test_reap_disabled_is_noop(db_ready, clean_jobs):
    svc = JobService()
    job = await svc.create("noop")
    await svc.mark_running(job.id, worker="w")
    assert await svc.reap_stuck_running(max_running_seconds=0) == 0
    j = await svc.get(job.id)
    assert j is not None and j.status is JobStatus.RUNNING


async def test_prune_disabled_is_noop(db_ready, clean_jobs):
    svc = JobService()
    job = await svc.create("noop")
    await svc.mark_running(job.id, worker="w1")
    await svc.mark_succeeded(job.id)
    assert await svc.prune_terminal(retention_days=0) == 0
    assert await svc.get(job.id) is not None


async def test_get_and_list_recent(db_ready, clean_jobs):
    svc = JobService()
    a = await svc.create("noop")
    b = await svc.create("noop")
    fetched = await svc.get(a.id)
    assert fetched is not None and fetched.id == a.id
    assert await svc.get("does-not-exist") is None
    recent = await svc.list_recent(limit=10)
    assert {j.id for j in recent} == {a.id, b.id}
