"""Pure-unit cover for the job state machine + event serialisation (no infra)."""

import pytest

from jobs.events import JobEvent
from jobs.models import Job, JobStatus
from jobs.service import LEGAL_TRANSITIONS, TERMINAL_STATUSES, InvalidJobTransition


def test_job_status_values():
    assert {s.value for s in JobStatus} == {
        "queued",
        "running",
        "succeeded",
        "failed",
        "cancelled",
    }


def test_terminal_statuses():
    assert TERMINAL_STATUSES == frozenset(
        {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}
    )
    for terminal in TERMINAL_STATUSES:
        assert LEGAL_TRANSITIONS[terminal] == frozenset()


def test_legal_transitions_match_spec_jl2():
    assert LEGAL_TRANSITIONS[JobStatus.QUEUED] == frozenset(
        {JobStatus.RUNNING, JobStatus.CANCELLED, JobStatus.FAILED}
    )
    assert LEGAL_TRANSITIONS[JobStatus.RUNNING] == frozenset(
        {
            JobStatus.RUNNING,  # re-acquire after a worker crash (failure mode E)
            JobStatus.SUCCEEDED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
            JobStatus.QUEUED,
        }
    )


def test_invalid_job_transition_message():
    exc = InvalidJobTransition(JobStatus.SUCCEEDED, JobStatus.RUNNING)
    assert "succeeded -> running" in str(exc)
    assert exc.current is JobStatus.SUCCEEDED
    assert exc.target is JobStatus.RUNNING


def test_job_as_dict_shape():
    job = Job(id="abc", job_type="noop", status=JobStatus.QUEUED, attempt=0, max_attempts=3)
    d = job.as_dict()
    assert set(d) == {
        "id",
        "job_type",
        "status",
        "created_at",
        "started_at",
        "finished_at",
        "attempt",
        "max_attempts",
        "error",
        "request_id",
        "worker",
        "result_ref",
    }
    assert d["status"] == "queued"
    # No tenant / user / org / billing fields (spec FR-E7 / FR-F15).
    assert not {k for k in d if k in {"tenant_id", "user_id", "org_id", "organization_id", "workspace_id", "cost"}}


def test_job_event_roundtrip():
    ev = JobEvent(job_id="j1", type="running", status="running", attempt=2, request_id="r1")
    back = JobEvent.from_json(ev.to_json())
    assert back == ev
    assert back.ts == ev.ts


def test_job_event_from_bad_json_raises():
    with pytest.raises(ValueError):
        JobEvent.from_json("not json")
