"""Job status + cancellation endpoints (spec §7 / §8 reconnect, FR-F9 / JL-5).

`GET /api/jobs/{id}` returns only non-sensitive lifecycle fields — never
`params`, `worker`, `result_ref` internals, connection strings, or stack traces.
`POST /api/jobs/{id}/cancel` is the explicit-cancel trigger for a queued job
(client disconnect alone never cancels — FR-F8).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db.engine import DatabaseNotConfiguredError
from jobs.events import JobEventChannel
from jobs.models import JobStatus
from jobs.service import InvalidJobTransition, JobService
from logging_config import get_logger

router = APIRouter()
logger = get_logger("routes.jobs")

_TERMINAL = {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}


class JobStatusResponse(BaseModel):
    job_id: str
    job_type: str
    status: str
    created_at: str | None
    started_at: str | None
    finished_at: str | None
    error: str | None
    request_id: str | None


def _to_response(job) -> JobStatusResponse:  # type: ignore[no-untyped-def]
    return JobStatusResponse(
        job_id=job.id,
        job_type=job.job_type,
        status=job.status.value,
        created_at=job.created_at.isoformat() if job.created_at else None,
        started_at=job.started_at.isoformat() if job.started_at else None,
        finished_at=job.finished_at.isoformat() if job.finished_at else None,
        error=job.error,
        request_id=job.request_id,
    )


@router.get("/api/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str) -> JobStatusResponse:
    try:
        job = await JobService().get(job_id)
    except DatabaseNotConfiguredError:
        raise HTTPException(status_code=503, detail="Job store is not configured")
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _to_response(job)


@router.post("/api/jobs/{job_id}/cancel", response_model=JobStatusResponse)
async def cancel_job(job_id: str) -> JobStatusResponse:
    """Cooperatively cancel a job (spec FR-F9 / JL-5).

    QUEUED  -> CANCELLED immediately; the worker's ``mark_running`` guard keeps
               it from ever starting.
    RUNNING -> CANCELLED in the row + a best-effort arq abort, which raises
               ``CancelledError`` in the worker task (bounded by the event loop).
    terminal -> 409; nothing to cancel.
    """
    # A channel so mark_cancelled publishes the `cancelled` lifecycle event that
    # a connected relay forwards to the client before closing (FR-F9 notify).
    channel = JobEventChannel()
    service = JobService(channel=channel)
    try:
        try:
            job = await service.get(job_id)
        except DatabaseNotConfiguredError:
            raise HTTPException(status_code=503, detail="Job store is not configured")
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        if job.status in _TERMINAL:
            raise HTTPException(
                status_code=409, detail=f"Job already {job.status.value}; cannot cancel"
            )

        was_running = job.status is JobStatus.RUNNING
        try:
            job = await service.mark_cancelled(job_id, error="cancelled by user")
        except InvalidJobTransition:
            # Raced with a terminal transition — report the current state.
            current = await service.get(job_id)
            if current is None:
                raise HTTPException(status_code=404, detail="Job not found")
            return _to_response(current)

        if was_running:
            try:
                from queue_client import request_job_abort

                await request_job_abort(job_id)
            except Exception:  # noqa: BLE001 - abort is best-effort
                logger.warning("could not signal arq abort", extra={"job_id": job_id})

        logger.info("job cancel requested", extra={"job_id": job_id})
        return _to_response(job)
    finally:
        await channel.close()
