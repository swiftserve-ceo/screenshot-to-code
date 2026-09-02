"""Background job foundation (Phase 1 Batch 2).

A minimal, durable job lifecycle that the *next* batch will move one generation
path onto. This batch provides the model, the lifecycle service, the Redis event
channel, and the arq worker wiring — but **does not migrate generation**.

Scope guard (spec FR-E7 / FR-F15): the ``jobs`` table has **no** tenant / user /
organization / billing columns. Multi-tenant persistence is Phase 2.
"""

from jobs.events import JobEvent, JobEventChannel
from jobs.models import Job, JobStatus
from jobs.service import (
    JobService,
    LEGAL_TRANSITIONS,
    TERMINAL_STATUSES,
)

__all__ = [
    "Job",
    "JobStatus",
    "JobEvent",
    "JobEventChannel",
    "JobService",
    "LEGAL_TRANSITIONS",
    "TERMINAL_STATUSES",
]
