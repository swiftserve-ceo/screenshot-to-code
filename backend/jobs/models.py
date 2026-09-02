"""The ``jobs`` table + status enum.

Infrastructure only — see the scope guard in ``jobs/__init__.py``.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Enum as SAEnum
from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base, utcnow


class JobStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Job(Base):
    __tablename__ = "jobs"

    # Identity
    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    job_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # Lifecycle
    status: Mapped[JobStatus] = mapped_column(
        SAEnum(JobStatus, name="job_status", native_enum=False, length=16),
        nullable=False,
        default=JobStatus.QUEUED,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Retry metadata (spec JL-8)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Failure info — a short summary only, never secrets / payloads.
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Correlation with the originating request (Batch 1 request-id groundwork).
    request_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)

    # Which worker last touched the job (diagnostics only).
    worker: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # Non-sensitive parameters describing the unit of work, and a pointer to
    # where the output lives once produced (never the output itself).
    params: Mapped[Optional[dict[str, object]]] = mapped_column(JSONB, nullable=True)
    result_ref: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "job_type": self.job_type,
            "status": self.status.value,
            "created_at": _iso(self.created_at),
            "started_at": _iso(self.started_at),
            "finished_at": _iso(self.finished_at),
            "attempt": self.attempt,
            "max_attempts": self.max_attempts,
            "error": self.error,
            "request_id": self.request_id,
            "worker": self.worker,
            "result_ref": self.result_ref,
        }


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None
