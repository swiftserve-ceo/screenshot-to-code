"""Queued-generation WebSocket relay (Phase 1 Batch 3).

The migrated **text→create** path. The WebSocket here *observes* a queued job; it
does not own the generation lifecycle:

    client --WS--> API --create job--> Postgres
                       --enqueue-----> Redis/arq --> worker --> generation
    worker --events--> JobEventChannel (Redis) --WS relay--> client

* a client disconnect does NOT cancel the job (the relay loop just ends);
* a reconnecting client re-opens the WS with ``{"jobId": "..."}``; the relay
  replays the full event backlog then tails live events;
* the frontend event vocabulary (``variantCount`` / ``status`` / ``setCode`` /
  ``variantComplete`` / ``error`` …) is preserved; ``jobCreated`` /
  ``jobStatus`` are additive.

No provider credentials are ever placed in the job, Redis, or WS payloads.
"""

from __future__ import annotations

from typing import Any

from starlette.websockets import WebSocket, WebSocketDisconnect
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK

from config import settings
from jobs.events import GENERATION_TYPE, JobEvent, JobEventChannel
from jobs.models import JobStatus
from jobs.service import JobService
from logging_config import get_logger
from prompts.request_parsing import parse_prompt_content, parse_prompt_history
from queue_client import get_arq_pool
from ws.constants import APP_ERROR_WEB_SOCKET_CODE, USER_CLOSE_WEB_SOCKET_CODE

from generation.types import GenerationEvent, GenerationRequest

logger = get_logger("generation_relay")

_TERMINAL = {
    JobStatus.SUCCEEDED.value,
    JobStatus.FAILED.value,
    JobStatus.CANCELLED.value,
}
# Keys we must never persist / enqueue.
_SECRET_KEYS = {
    "openAiApiKey",
    "anthropicApiKey",
    "geminiApiKey",
    "replicateApiKey",
    "openAiBaseURL",
    "screenshotOneApiKey",
}


def is_queued_text_create(params: dict[str, Any]) -> bool:
    """Only the smallest real path is queue-backed this batch."""
    return (
        settings.job_queue_enabled
        and params.get("inputMode") == "text"
        and params.get("generationType", "create") == "create"
        and not params.get("jobId")
    )


def build_generation_request(params: dict[str, Any], asset_base_url: str) -> GenerationRequest:
    """Sanitised request — **no secrets**."""
    from prompts.prompt_types import Stack
    from typing import get_args

    stack = params.get("generatedCodeConfig", "")
    if stack not in get_args(Stack):
        raise ValueError(f"Invalid generated code config: {stack!r}")

    design_system = params.get("designSystem")
    if not (isinstance(design_system, str) and design_system.strip()):
        design_system = None

    return GenerationRequest(
        stack=stack,
        prompt=parse_prompt_content(params.get("prompt")),
        history=parse_prompt_history(params.get("history")),
        design_system=design_system,
        should_generate_images=bool(params.get("isImageGenerationEnabled", True)),
        should_extract_assets=False,
        asset_base_url=asset_base_url,
        input_mode="text",
        generation_type="create",
    )


async def start_queued_generation(
    websocket: WebSocket, params: dict[str, Any], asset_base_url: str, request_id: str | None
) -> None:
    """Create + enqueue a generation job, then relay its events."""
    channel: JobEventChannel = JobEventChannel()
    service = JobService(channel=channel)
    try:
        try:
            req = build_generation_request(params, asset_base_url)
        except ValueError as exc:
            await _safe_send(websocket, {"type": "error", "value": str(exc)})
            await _safe_close(websocket, APP_ERROR_WEB_SOCKET_CODE)
            return

        try:
            job = await service.create(
                GENERATION_TYPE, params=req.to_params(), request_id=request_id
            )
        except Exception:
            # DB unavailable / misconfigured — the queued path cannot run.
            logger.exception("could not persist queued generation job")
            await _safe_send(
                websocket,
                {
                    "type": "error",
                    "value": "The generation service is temporarily unavailable. Please try again.",
                },
            )
            await _safe_close(websocket, APP_ERROR_WEB_SOCKET_CODE)
            return

        try:
            pool = await get_arq_pool()
            # _job_id == our job id so POST /api/jobs/{id}/cancel can abort it.
            await pool.enqueue_job("execute_job", job.id, _job_id=job.id)
        except Exception:
            # Redis/queue unavailable: fail the job cleanly instead of leaving it
            # QUEUED forever, and tell the client (spec queue failure mode A).
            logger.exception("could not enqueue generation job", extra={"job_id": job.id})
            try:
                await service.mark_failed(
                    job.id, error="QueueUnavailable: could not enqueue job"
                )
            except Exception:
                logger.exception("could not mark un-enqueued job failed", extra={"job_id": job.id})
            await _safe_send(
                websocket,
                {
                    "type": "error",
                    "value": "The generation queue is temporarily unavailable. Please try again.",
                },
            )
            await _safe_close(websocket, APP_ERROR_WEB_SOCKET_CODE)
            return

        logger.info("queued generation job", extra={"job_id": job.id, "stack": req.stack})

        await _safe_send(websocket, {"type": "jobCreated", "value": job.id, "variantIndex": 0})
        await _safe_send(
            websocket,
            {"type": "status", "value": "Queued...", "variantIndex": 0},
        )
        await _relay(websocket, job.id, channel, service)
    finally:
        await channel.close()


async def resume_job(websocket: WebSocket, job_id: str) -> None:
    """Reconnect: replay the job's events and tail if still running."""
    channel = JobEventChannel()
    service = JobService(channel=channel)
    try:
        job = await service.get(job_id)
        if job is None:
            await _safe_send(websocket, {"type": "error", "value": "Unknown job id."})
            await _safe_close(websocket, APP_ERROR_WEB_SOCKET_CODE)
            return
        await _safe_send(websocket, {"type": "jobCreated", "value": job_id, "variantIndex": 0})
        await _relay(websocket, job_id, channel, service)
    finally:
        await channel.close()


async def _relay(
    websocket: WebSocket, job_id: str, channel: JobEventChannel, service: JobService
) -> None:
    sub = await channel.open_subscription(job_id)
    forwarder = _Forwarder(websocket, job_id)
    try:
        max_seq = 0
        for event in await sub.replay():
            max_seq = max(max_seq, event.seq)
            if await forwarder.forward(event):
                return

        job = await service.get(job_id)
        if job is not None and job.status.value in _TERMINAL:
            # Job finished during replay but its terminal event may not be in the
            # backlog yet — synthesise the terminal close.
            await forwarder.forward_terminal(job.status.value, job.error)
            return

        async for event in sub.events(after_seq=max_seq):
            if await forwarder.forward(event):
                return
    except (WebSocketDisconnect, ConnectionClosedOK, ConnectionClosedError):
        # Client went away — the worker keeps running. Nothing to do.
        logger.info("relay client disconnected; job continues", extra={"job_id": job_id})
    finally:
        await sub.aclose()


class _Forwarder:
    """Translates JobEvents to WS messages, exactly once per logical event.

    Tracks whether a generation ``error`` event has already been sent so the
    terminal ``failed`` transition does not produce a **second** error toast
    (Batch 3 follow-up)."""

    def __init__(self, websocket: WebSocket, job_id: str) -> None:
        self._ws = websocket
        self._job_id = job_id
        self._error_sent = False

    async def forward(self, event: JobEvent) -> bool:
        if event.type == GENERATION_TYPE and event.payload is not None:
            ev = GenerationEvent.from_payload(event.payload)
            if ev.message_type == "error":
                self._error_sent = True
            await _safe_send(
                self._ws,
                {
                    "type": ev.message_type,
                    "value": ev.value,
                    "variantIndex": ev.variant_index,
                    "data": ev.data,
                    "eventId": ev.event_id,
                },
            )
            return False

        if event.type in {"queued", "running", "retrying"}:
            await _safe_send(
                self._ws,
                {
                    "type": "jobStatus",
                    "value": event.type,
                    "variantIndex": 0,
                    "data": {"jobId": self._job_id, "attempt": event.attempt},
                },
            )
            return False

        return await self.forward_terminal(event.type, event.error)

    async def forward_terminal(self, status: str, error: str | None) -> bool:
        if status == JobStatus.SUCCEEDED.value:
            await _safe_send(
                self._ws,
                {
                    "type": "jobStatus",
                    "value": "succeeded",
                    "variantIndex": 0,
                    "data": {"jobId": self._job_id},
                },
            )
            await _safe_close(self._ws, 1000)
            return True
        if status == JobStatus.FAILED.value:
            # Emit ONE user-facing error. If the generation already sent a
            # descriptive `error` event, don't send another — just close.
            if not self._error_sent:
                await _safe_send(
                    self._ws,
                    {"type": "error", "value": _user_facing_error(error), "variantIndex": 0},
                )
            await _safe_close(self._ws, APP_ERROR_WEB_SOCKET_CODE)
            return True
        if status == JobStatus.CANCELLED.value:
            await _safe_close(self._ws, USER_CLOSE_WEB_SOCKET_CODE)
            return True
        return False


_INTERNAL_ERROR_PREFIXES = (
    "NonRetryableGenerationError:",
    "RuntimeError:",
    "Exception:",
    "ValueError:",
)


def _user_facing_error(error: str | None) -> str:
    if not error:
        return "Generation failed. Please retry."
    for prefix in _INTERNAL_ERROR_PREFIXES:
        if error.startswith(prefix):
            return "Generation failed. Please retry."
    return error


async def _safe_send(websocket: WebSocket, payload: dict[str, Any]) -> None:
    try:
        await websocket.send_json(payload)
    except (RuntimeError, WebSocketDisconnect, ConnectionClosedOK, ConnectionClosedError):
        raise WebSocketDisconnect()


async def _safe_close(websocket: WebSocket, code: int) -> None:
    try:
        await websocket.close(code)
    except (RuntimeError, WebSocketDisconnect, ConnectionClosedOK, ConnectionClosedError):
        pass
