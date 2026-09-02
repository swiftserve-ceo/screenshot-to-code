"""The arq job handler for the queued text→create generation path.

Registered as ``JOB_HANDLERS["generation"]`` in ``worker.py``.

Security:
  * credentials come from **server config only** (`ProviderCredentials.from_settings`)
    — never from the job payload, Redis, or the DB;
  * the handler runs the existing agent/provider layer via `run_generation` and
    **executes no generated code, shell, or subprocess**;
  * `NonRetryableGenerationError` (missing key / bad input / prompt failure) is
    surfaced to `execute_job` so the job goes straight to FAILED with a
    sanitised summary — no retry.
"""

from __future__ import annotations

from typing import Any

from jobs.events import GENERATION_TYPE, JobEvent, JobEventChannel
from jobs.models import Job
from logging_config import get_logger

from generation.service import run_generation
from generation.types import (
    GenerationEvent,
    GenerationRequest,
    NonRetryableGenerationError,
    ProviderCredentials,
)

logger = get_logger("generation.job")

JOB_TYPE = "generation"


async def handle_generation_job(ctx: dict[str, Any], job: Job) -> str | None:
    channel: JobEventChannel = ctx["job_channel"]
    req = GenerationRequest.from_params(job.params or {})
    creds = ProviderCredentials.from_settings()

    async def emit(ev: GenerationEvent) -> None:
        await channel.publish(
            JobEvent(
                job_id=job.id,
                type=GENERATION_TYPE,
                status="running",
                attempt=job.attempt,
                request_id=job.request_id,
                payload=ev.as_payload(),
            )
        )

    logger.info(
        "generation job starting",
        extra={
            "job_id": job.id,
            "stack": req.stack,
            "input_mode": req.input_mode,
            "generation_type": req.generation_type,
            "has_server_key": creds.has_any_llm_key,
        },
    )

    outcome = await run_generation(req, creds, emit, generation_id=f"job_{job.id}")

    succeeded = sum(1 for v in outcome.variants if v.status == "complete")
    logger.info(
        "generation job produced output",
        extra={"job_id": job.id, "variants_ok": succeeded, "variants_total": len(outcome.variants)},
    )
    # The event backlog (jobs:eventlog:<id>) IS the result: it contains every
    # setCode / variantComplete event, so a reconnecting client rebuilds the
    # full output by replaying it. No separate result blob is stored.
    return f"eventlog:{job.id}"


__all__ = ["JOB_TYPE", "handle_generation_job", "NonRetryableGenerationError"]
