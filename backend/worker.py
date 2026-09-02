"""arq background worker (Phase 1 Batch 2 foundation).

Start it with::

    cd backend && poetry run arq worker.WorkerSettings

The worker:
  * connects to Redis (arq broker),
  * exposes a ``ping`` health task and a generic ``execute_job`` task that drives
    the ``jobs`` table through its lifecycle and publishes events,
  * retries transient failures up to ``JOB_MAX_ATTEMPTS`` (arq-native), then
    marks the job ``failed`` with a short error summary,
  * shuts down cleanly on SIGTERM/SIGINT (arq default).

**It does NOT execute generated code and has no shell/Docker access.** Job
handlers are an explicit in-process registry (see ``JOB_HANDLERS``). This batch
registers ``noop`` (tests) and ``generation`` (the queued text→create path,
which calls the existing agent/provider layer only — no shell/subprocess).
"""

from __future__ import annotations

import asyncio
import socket
from typing import Any, Awaitable, Callable, Optional

from arq import Retry, cron
from arq.connections import RedisSettings

from config import settings
from db.engine import dispose_engine
from generation.job import JOB_TYPE as GENERATION_JOB_TYPE
from generation.job import handle_generation_job
from generation.types import NonRetryableGenerationError
from jobs.events import JobEventChannel
from jobs.models import Job, JobStatus
from jobs.service import InvalidJobTransition, JobService
from logging_config import configure_logging, get_logger, request_context

configure_logging()
logger = get_logger("worker")


def worker_identity() -> str:
    return settings.worker_name or f"worker@{socket.gethostname()}:{_pid()}"


def _pid() -> int:
    import os

    return os.getpid()


# --- job handler registry -----------------------------------------------------
# job_type -> async handler(ctx, job) -> result_ref | None
JobHandler = Callable[[dict[str, Any], Job], Awaitable[Optional[str]]]


async def _noop_handler(ctx: dict[str, Any], job: Job) -> Optional[str]:
    """Test handler: optionally sleeps, optionally fails N times, then succeeds."""
    params: dict[str, Any] = dict(job.params or {})
    sleep_seconds = float(params.get("sleep_seconds", 0) or 0)
    if sleep_seconds > 0:
        await asyncio.sleep(sleep_seconds)
    fail_times = int(params.get("fail_times", 0))
    if job.attempt <= fail_times:
        raise RuntimeError(f"noop handler failing on attempt {job.attempt}")
    result_ref = params.get("result_ref")
    return str(result_ref) if result_ref is not None else None


JOB_HANDLERS: dict[str, JobHandler] = {
    "noop": _noop_handler,
    GENERATION_JOB_TYPE: handle_generation_job,
}

# Deterministic failures that must NOT be retried (spec §10).
NON_RETRYABLE_ERRORS: tuple[type[Exception], ...] = (
    NonRetryableGenerationError,
    ValueError,
)


# --- arq tasks --------------------------------------------------------------
async def ping(ctx: dict[str, Any], payload: Optional[str] = None) -> dict[str, Any]:
    logger.info("ping", extra={"worker": worker_identity(), "payload": payload})
    return {"pong": True, "worker": worker_identity(), "echo": payload}


async def execute_job(ctx: dict[str, Any], job_id: str) -> dict[str, Any]:
    """Run the handler for a persisted job, managing its lifecycle + retries."""
    service: JobService = ctx["job_service"]
    worker = worker_identity()
    try_number = int(ctx.get("job_try", 1))

    job = await service.get(job_id)
    if job is None:
        logger.warning("execute_job: job not found", extra={"job_id": job_id})
        return {"job_id": job_id, "status": "missing"}

    with request_context(job.request_id or None):
        handler = JOB_HANDLERS.get(job.job_type)
        if handler is None:
            await service.mark_failed(job_id, error=f"no handler for job_type {job.job_type!r}")
            return {"job_id": job_id, "status": JobStatus.FAILED.value}

        try:
            job = await service.mark_running(job_id, worker=worker)
        except InvalidJobTransition:
            # Already cancelled or terminal — respect that (spec FR-F9 / JL-2).
            current = await service.get(job_id)
            logger.info(
                "execute_job: not runnable",
                extra={"job_id": job_id, "status": current.status.value if current else "gone"},
            )
            return {"job_id": job_id, "status": current.status.value if current else "gone"}

        try:
            result_ref = await handler(ctx, job)
            await service.mark_succeeded(job_id, result_ref=result_ref)
            return {"job_id": job_id, "status": JobStatus.SUCCEEDED.value}
        except asyncio.CancelledError:
            # Cooperative cancellation (spec FR-F9 / JL-5): the API set the row to
            # CANCELLED and asked arq to abort this task. Record it and re-raise
            # so arq marks the job aborted; do NOT fall through to mark_failed.
            await service.mark_cancelled(job_id, error="cancelled by user")
            logger.info("job cancelled", extra={"job_id": job_id})
            raise
        except Exception as exc:  # noqa: BLE001 - deliberate: classify + record
            summary = _sanitised_error(exc)
            retryable = not isinstance(exc, NON_RETRYABLE_ERRORS)
            if retryable and try_number < job.max_attempts:
                await service.requeue_for_retry(job_id, error=summary)
                logger.warning(
                    "job will retry",
                    extra={"job_id": job_id, "attempt": job.attempt, "max": job.max_attempts},
                )
                raise Retry(defer=ctx.get("job_try", 1) * 5)
            await service.mark_failed(job_id, error=summary)
            logger.error(
                "job failed",
                extra={
                    "job_id": job_id,
                    "attempts": job.attempt,
                    "error": type(exc).__name__,
                    "retryable": retryable,
                },
            )
            return {"job_id": job_id, "status": JobStatus.FAILED.value}


async def prune_jobs(ctx: dict[str, Any]) -> dict[str, Any]:
    """Cron task: delete terminal job rows older than the retention window.

    A no-op unless ``JOB_RETENTION_DAYS`` is set (spec DR-6: opt-in, prunable).
    Never touches queued or running jobs.
    """
    retention = settings.job_retention_days
    if not retention:
        return {"pruned": 0, "enabled": False}
    service: JobService = ctx["job_service"]
    deleted = await service.prune_terminal(retention_days=retention)
    return {"pruned": deleted, "enabled": True}


async def reap_jobs(ctx: dict[str, Any]) -> dict[str, Any]:
    """Cron task: fail jobs left ``running`` past ``JOB_REAP_AFTER_SECONDS``.

    The out-of-process half of the JL-4 watchdog: arq's ``job_timeout`` handles a
    hung job on a live worker; this catches a job whose worker was killed before
    it could record a terminal state. Disabled when the setting is 0.
    """
    ceiling = settings.job_reap_after_seconds
    if ceiling <= 0:
        return {"reaped": 0, "enabled": False}
    service: JobService = ctx["job_service"]
    reaped = await service.reap_stuck_running(max_running_seconds=ceiling)
    return {"reaped": reaped, "enabled": True}


def _sanitised_error(exc: Exception) -> str:
    """`<ExcType>: <message>` truncated — never a payload / secret / traceback."""
    message = str(exc).strip().splitlines()[0] if str(exc).strip() else ""
    summary = f"{type(exc).__name__}: {message}" if message else type(exc).__name__
    return summary[:500]


# --- arq worker settings ---------------------------------------------------
async def _on_startup(ctx: dict[str, Any]) -> None:
    # The worker must never execute generated code. Rendering generated HTML in
    # headless Chromium (screenshot_preview) counts — hard-disable it here so the
    # agent tool layer will not offer it in worker context (spec SEC).
    from preview_screenshot import disable_screenshot_preview

    disable_screenshot_preview()

    ctx["job_channel"] = JobEventChannel()
    ctx["job_service"] = JobService(channel=ctx["job_channel"])
    logger.info(
        "worker started",
        extra={"worker": worker_identity(), "redis": _redacted_redis(), "queue": True},
    )


async def _on_shutdown(ctx: dict[str, Any]) -> None:
    channel: Optional[JobEventChannel] = ctx.get("job_channel")
    if channel is not None:
        await channel.close()
    await dispose_engine()
    logger.info("worker stopped", extra={"worker": worker_identity()})


def _redacted_redis() -> str:
    url = settings.redis_url
    # Never log credentials if the URL carries any.
    if "@" in url:
        return url.split("@", 1)[1]
    return url


class WorkerSettings:
    functions: list[Any] = [ping, execute_job]
    # Daily retention sweep (03:17) + a stuck-job reaper every 5 minutes. Both
    # self-disable unless their setting is configured (JOB_RETENTION_DAYS /
    # JOB_REAP_AFTER_SECONDS).
    cron_jobs: list[Any] = [
        cron(prune_jobs, hour=3, minute=17, run_at_startup=False),
        cron(reap_jobs, minute=set(range(0, 60, 5)), run_at_startup=True),
    ]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    on_startup = _on_startup
    on_shutdown = _on_shutdown
    max_tries = settings.job_max_attempts
    job_timeout = settings.job_timeout_seconds
    # Lets the API abort a running job (POST /api/jobs/{id}/cancel -> arq abort ->
    # asyncio.CancelledError in execute_job). Spec FR-F9 / JL-5.
    allow_abort_jobs = True
    # Keep results briefly so a client can read a terminal outcome after the fact.
    keep_result = 3600
    # Refresh the arq health-check key often enough that /health can treat its
    # absence as "no live worker" (spec FR-F2 / SC-006 / OB-5). arq's default is
    # 3600s, which would leave a stale key for an hour after a worker dies.
    health_check_interval = settings.worker_health_interval_seconds
