# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false
"""Redis connectivity + the job event channel (Redis pub/sub)."""

import asyncio

import pytest

from jobs.events import JobEvent, JobEventChannel
from redis_client import RedisStatus, check_redis


async def test_check_redis_ok(redis_ready):
    status = await check_redis()
    assert status.state == "ok"


async def test_check_redis_error_is_not_raised(monkeypatch):
    import redis_client as rc

    monkeypatch.setattr(
        rc, "settings", rc.settings.model_copy(update={"redis_url": "redis://127.0.0.1:59998/0"})
    )
    monkeypatch.setattr(rc, "_client", None)
    status = await check_redis(timeout=2.0)
    assert isinstance(status, RedisStatus)
    assert status.state == "error"
    await rc.close_redis()


async def test_job_event_channel_publish_subscribe(redis_ready):
    channel = JobEventChannel()
    sub_channel = JobEventChannel()
    received: list[JobEvent] = []

    async def consume():
        async for event in sub_channel.subscribe("job-xyz"):
            received.append(event)
            if len(received) >= 2:
                break

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.3)  # let the subscription establish

    await channel.publish(JobEvent(job_id="job-xyz", type="running", status="running", attempt=1))
    await channel.publish(JobEvent(job_id="job-xyz", type="succeeded", status="succeeded", attempt=1))

    await asyncio.wait_for(task, timeout=5)
    await channel.close()
    await sub_channel.close()

    assert [e.type for e in received] == ["running", "succeeded"]
    assert received[0].job_id == "job-xyz"


async def test_publish_stamps_seq_and_backlog(redis_ready):
    channel = JobEventChannel()
    job_id = "lonely-" + __import__("uuid").uuid4().hex[:8]
    a = await channel.publish(JobEvent(job_id=job_id, type="queued", status="queued"))
    b = await channel.publish(JobEvent(job_id=job_id, type="running", status="running"))
    # publish returns the stamped event with a monotonic seq
    assert a.seq >= 1 and b.seq == a.seq + 1
    # and it is retained in the TTL'd backlog for late/reconnecting clients
    backlog = await channel.replay(job_id)
    assert [e.type for e in backlog] == ["queued", "running"]
    assert [e.seq for e in backlog] == [a.seq, b.seq]
    await channel.close()


async def test_open_subscription_replay_then_dedup_live(redis_ready):
    pub = JobEventChannel()
    sub_ch = JobEventChannel()
    job_id = "resub-" + __import__("uuid").uuid4().hex[:8]
    e1 = await pub.publish(JobEvent(job_id=job_id, type="queued", status="queued"))

    sub = await sub_ch.open_subscription(job_id)
    backlog = await sub.replay()
    assert [e.type for e in backlog] == ["queued"]
    max_seq = max(e.seq for e in backlog)

    await pub.publish(JobEvent(job_id=job_id, type="running", status="running"))
    await pub.publish(JobEvent(job_id=job_id, type="succeeded", status="succeeded"))

    live: list[str] = []
    async for ev in sub.events(after_seq=max_seq):
        live.append(ev.type)
        if ev.type == "succeeded":
            break
    # the replayed "queued" (seq <= max_seq) is not re-delivered
    assert live == ["running", "succeeded"]
    await sub.aclose()
    await pub.close()
    await sub_ch.close()
