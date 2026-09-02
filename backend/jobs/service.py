"""Job lifecycle service — the durable state machine.

The next batch calls ``create`` from the API, then the worker calls
``mark_running`` / ``mark_succeeded`` / ``mark_failed`` / ``mark_cancelled``.
Illegal transitions raise ``InvalidJobTransition`` (spec JL-2).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import delete, select

from db.base import utcnow
from db.engine import session_scope
from jobs.events import JobEvent, JobEventChannel
from jobs.models import Job, JobStatus
from logging_config import get_logger, get_request_id

logger = get_logger("jobs.service")

TERMINAL_STATUSES: frozenset[JobStatus] = frozenset(
    {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}
)

# spec JL-2. "retrying" is modelled as running -> queued (attempt++) here.
# QUEUED -> FAILED covers a job that is structurally un-runnable (no handler,
# rejected before it ever starts).
LEGAL_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.QUEUED: frozenset(
        {JobStatus.RUNNING, JobStatus.CANCELLED, JobStatus.FAILED}
    ),
    # RUNNING -> RUNNING permits a worker to re-acquire a job it had already
    # started but did not finish (previous worker crashed / was killed before it
    # could record a terminal state — spec queue failure mode E). arq's
    # ``max_tries`` still bounds the total number of attempts.
    JobStatus.RUNNING: frozenset(
        {
            JobStatus.RUNNING,
            JobStatus.SUCCEEDED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
            JobStatus.QUEUED,
        }
    ),
    JobStatus.SUCCEEDED: frozenset(),
    JobStatus.FAILED: frozenset(),
    JobStatus.CANCELLED: frozenset(),
}


class InvalidJobTransition(RuntimeError):
    def __init__(self, current: JobStatus, target: JobStatus) -> None:
        super().__init__(f"illegal job transition {current.value} -> {target.value}")
        self.current = current
        self.target = target


class JobService:
    """Stateless helper around the ``jobs`` table + the event channel."""

    def __init__(self, channel: Optional[JobEventChannel] = None) -> None:
        self._channel = channel

    async def _emit(self, job: Job, transition: str) -> None:
        logger.info(
            "job %s",
            transition,
            extra={
                "job_id": job.id,
                "job_type": job.job_type,
                "status": job.status.value,
                "attempt": job.attempt,
                "worker": job.worker,
                "request_id": job.request_id,
            },
        )
        if self._channel is not None:
            await self._channel.publish(
                JobEvent(
                    job_id=job.id,
                    type=transition,
                    status=job.status.value,
                    attempt=job.attempt,
                    error=job.error,
                    request_id=job.request_id,
                )
            )

    async def create(
        self,
        job_type: str,
        *,
        params: Optional[dict] = None,
        max_attempts: Optional[int] = None,
        request_id: Optional[str] = None,
    ) -> Job:
        from config import settings

        async with session_scope() as session:
            job = Job(
                job_type=job_type,
                status=JobStatus.QUEUED,
                params=params,
                max_attempts=max_attempts or settings.job_max_attempts,
                request_id=request_id or get_request_id(),
            )
            session.add(job)
            await session.flush()
            await session.refresh(job)
            session.expunge(job)
        await self._emit(job, "queued")
        return job

    async def get(self, job_id: str) -> Optional[Job]:
        async with session_scope() as session:
            job = await session.get(Job, job_id)
            if job is not None:
                session.expunge(job)
            return job

    async def _transition(
        self,
        job_id: str,
        target: JobStatus,
        *,
        worker: Optional[str] = None,
        error: Optional[str] = None,
        result_ref: Optional[str] = None,
        bump_attempt: bool = False,
    ) -> tuple[Job, bool]:
        """Apply a state transition. Returns ``(job, changed)``.

        ``changed`` is ``False`` when the job is already in the requested
        terminal state — a re-delivered worker message or a double
        ``mark_*`` call is idempotent (spec JL: idempotent terminal handling),
        not an error.
        """
        async with session_scope() as session:
            job = await session.get(Job, job_id, with_for_update=True)
            if job is None:
                raise LookupError(f"job {job_id} not found")
            if job.status == target and target in TERMINAL_STATUSES:
                session.expunge(job)
                return job, False
            if target not in LEGAL_TRANSITIONS[job.status]:
                raise InvalidJobTransition(job.status, target)

            now = utcnow()
            job.status = target
            if worker is not None:
                job.worker = worker
            if bump_attempt:
                job.attempt += 1
            if target == JobStatus.RUNNING and job.started_at is None:
                job.started_at = now
            if target in TERMINAL_STATUSES:
                job.finished_at = now
            if target == JobStatus.QUEUED:
                # retry: clear the previous run's timing
                job.started_at = None
                job.finished_at = None
            if error is not None:
                job.error = error[:2000]
            elif target == JobStatus.SUCCEEDED:
                # A prior attempt's transient error is not relevant once the job
                # succeeds.
                job.error = None
            if result_ref is not None:
                job.result_ref = result_ref

            await session.flush()
            await session.refresh(job)
            session.expunge(job)
        return job, True

    async def mark_running(self, job_id: str, *, worker: str) -> Job:
        job, changed = await self._transition(
            job_id, JobStatus.RUNNING, worker=worker, bump_attempt=True
        )
        if changed:
            await self._emit(job, "running")
        return job

    async def mark_succeeded(self, job_id: str, *, result_ref: Optional[str] = None) -> Job:
        job, changed = await self._transition(
            job_id, JobStatus.SUCCEEDED, result_ref=result_ref
        )
        if changed:
            await self._emit(job, "succeeded")
        return job

    async def mark_failed(self, job_id: str, *, error: str) -> Job:
        job, changed = await self._transition(job_id, JobStatus.FAILED, error=error)
        if changed:
            await self._emit(job, "failed")
        return job

    async def mark_cancelled(self, job_id: str, *, error: Optional[str] = None) -> Job:
        job, changed = await self._transition(job_id, JobStatus.CANCELLED, error=error)
        if changed:
            await self._emit(job, "cancelled")
        return job

    async def requeue_for_retry(self, job_id: str, *, error: str) -> Job:
        """running -> queued, keeping the attempt counter for the retry policy."""
        job, _ = await self._transition(job_id, JobStatus.QUEUED, error=error)
        await self._emit(job, "retrying")
        return job

    async def reap_stuck_running(
        self, *, max_running_seconds: int, now: Optional[datetime] = None
    ) -> int:
        """Fail jobs left ``running`` past a wall-clock ceiling (spec JL-4).

        arq's in-process ``job_timeout`` handles a *hung* job on a live worker;
        this covers the other case — a worker that was killed before it could
        record a terminal state, leaving the row ``running`` forever. Only
        ``running`` rows with a ``started_at`` older than the ceiling are
        touched. Returns the number of jobs failed.
        """
        if max_running_seconds < 1:
            return 0

        cutoff = (now or utcnow()) - timedelta(seconds=max_running_seconds)
        reaped: list[str] = []
        async with session_scope() as session:
            rows = (
                await session.execute(
                    select(Job)
                    .where(Job.status == JobStatus.RUNNING)
                    .where(Job.started_at.is_not(None))
                    .where(Job.started_at < cutoff)
                    .with_for_update(skip_locked=True)
                )
            ).scalars().all()
            for job in rows:
                job.status = JobStatus.FAILED
                job.finished_at = utcnow()
                job.error = (
                    f"WatchdogTimeout: job exceeded {max_running_seconds}s in 'running' "
                    "(worker presumed dead)"
                )
                reaped.append(job.id)
            await session.flush()
        for job_id in reaped:
            logger.warning("reaped stuck job", extra={"job_id": job_id})
            if self._channel is not None:
                await self._channel.publish(
                    JobEvent(
                        job_id=job_id,
                        type="failed",
                        status=JobStatus.FAILED.value,
                        error="WatchdogTimeout: worker presumed dead",
                    )
                )
        return len(reaped)

    async def prune_terminal(
        self, *, retention_days: int, now: Optional[datetime] = None
    ) -> int:
        """Delete terminal jobs whose ``finished_at`` is older than the window.

        Conservative by construction: only ``succeeded`` / ``failed`` /
        ``cancelled`` rows with a non-null ``finished_at`` are considered, so a
        still-queued or still-running job can never be removed (spec DR-6).
        Returns the number of rows deleted.
        """
        if retention_days < 1:
            return 0

        cutoff = (now or utcnow()) - timedelta(days=retention_days)
        async with session_scope() as session:
            result = await session.execute(
                delete(Job)
                .where(Job.status.in_(tuple(TERMINAL_STATUSES)))
                .where(Job.finished_at.is_not(None))
                .where(Job.finished_at < cutoff)
            )
        deleted = int(getattr(result, "rowcount", 0) or 0)
        if deleted:
            logger.info(
                "pruned terminal jobs",
                extra={"deleted": deleted, "retention_days": retention_days},
            )
        return deleted

    async def list_recent(self, limit: int = 50) -> list[Job]:
        async with session_scope() as session:
            rows = (
                await session.execute(
                    select(Job).order_by(Job.created_at.desc()).limit(limit)
                )
            ).scalars().all()
            for job in rows:
                session.expunge(job)
            return list(rows)
