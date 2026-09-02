# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false
"""Worker foundation: identity, handler registry, execute_job lifecycle, shutdown."""

import pytest

from jobs.models import JobStatus
from jobs.service import JobService
import worker as worker_mod


def test_worker_identity_default(monkeypatch):
    monkeypatch.setattr(
        worker_mod, "settings", worker_mod.settings.model_copy(update={"worker_name": None})
    )
    ident = worker_mod.worker_identity()
    assert ident.startswith("worker@")


def test_worker_identity_configured(monkeypatch):
    monkeypatch.setattr(
        worker_mod, "settings", worker_mod.settings.model_copy(update={"worker_name": "ci-runner-3"})
    )
    assert worker_mod.worker_identity() == "ci-runner-3"


def test_handler_registry_is_explicit_and_safe():
    # Batch 3: exactly "noop" (tests) + "generation" (text->create). No shell /
    # subprocess / docker / exec handler.
    assert set(worker_mod.JOB_HANDLERS) == {"noop", "generation"}
    import ast
    import inspect

    for handler in worker_mod.JOB_HANDLERS.values():
        tree = ast.parse(inspect.getsource(handler))
        called = {
            (n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", ""))
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
        }
        for forbidden in {"system", "popen", "Popen", "eval", "exec", "run", "call", "check_output"}:
            assert forbidden not in called, f"{handler.__name__} calls {forbidden!r}"


async def test_ping_task():
    result = await worker_mod.ping({}, "hi")
    assert result["pong"] is True
    assert result["echo"] == "hi"
    assert "worker" in result


def _ctx(job_try: int = 1) -> dict:
    channel = None
    svc = JobService(channel=channel)
    return {"job_service": svc, "job_try": job_try}


async def test_execute_job_success(db_ready, clean_jobs):
    ctx = _ctx()
    job = await ctx["job_service"].create("noop", params={"result_ref": "local://ok"})
    out = await worker_mod.execute_job(ctx, job.id)
    assert out["status"] == JobStatus.SUCCEEDED.value
    stored = await ctx["job_service"].get(job.id)
    assert stored.status is JobStatus.SUCCEEDED
    assert stored.result_ref == "local://ok"
    assert stored.attempt == 1


async def test_execute_job_missing_job(db_ready):
    out = await worker_mod.execute_job(_ctx(), "no-such-id")
    assert out["status"] == "missing"


async def test_execute_job_unknown_type_fails(db_ready, clean_jobs):
    ctx = _ctx()
    job = await ctx["job_service"].create("totally-unknown-type")
    out = await worker_mod.execute_job(ctx, job.id)
    assert out["status"] == JobStatus.FAILED.value
    stored = await ctx["job_service"].get(job.id)
    assert "no handler" in (stored.error or "")


async def test_execute_job_retries_then_fails(db_ready, clean_jobs):
    from arq import Retry

    svc = JobService()
    job = await svc.create("noop", params={"fail_times": 99}, max_attempts=2)

    # try 1 -> requeue + Retry raised
    with pytest.raises(Retry):
        await worker_mod.execute_job({"job_service": svc, "job_try": 1}, job.id)
    after_first = await svc.get(job.id)
    assert after_first is not None and after_first.status is JobStatus.QUEUED

    # try 2 (== max_attempts) -> failed
    out = await worker_mod.execute_job({"job_service": svc, "job_try": 2}, job.id)
    assert out["status"] == JobStatus.FAILED.value
    final = await svc.get(job.id)
    assert final is not None and final.status is JobStatus.FAILED


async def test_execute_job_respects_prior_cancellation(db_ready, clean_jobs):
    svc = JobService()
    job = await svc.create("noop")
    await svc.mark_cancelled(job.id, error="user cancelled")
    out = await worker_mod.execute_job({"job_service": svc, "job_try": 1}, job.id)
    assert out["status"] == JobStatus.CANCELLED.value


async def test_worker_startup_shutdown_clean(redis_ready):
    ctx: dict = {}
    await worker_mod._on_startup(ctx)
    assert "job_service" in ctx and "job_channel" in ctx
    await worker_mod._on_shutdown(ctx)  # must not raise


async def test_worker_startup_disables_generated_code_rendering(redis_ready):
    """The worker must be incapable of executing generated code — the
    screenshot_preview tool (renders HTML/JS in Chromium) is hard-disabled."""
    import preview_screenshot.registry as psr

    psr._available = True  # pretend Chromium is present (conftest restores after)
    ctx: dict = {}
    await worker_mod._on_startup(ctx)
    try:
        assert psr.is_screenshot_preview_available() is False
    finally:
        await worker_mod._on_shutdown(ctx)
