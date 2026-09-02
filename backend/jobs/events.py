"""Job / generation event channel (Redis).

The **transition boundary** between job execution and event delivery (spec §6 /
FR-F7). The worker publishes; a WebSocket relay subscribes. Two delivery modes,
both used by the queued generation path:

* **live** — `PUBLISH jobs:events:<id>` for connected subscribers;
* **backlog** — every event is also appended to a capped, TTL'd Redis list
  `jobs:eventlog:<id>` so a client that connects late / reconnects can `replay`
  the full stream and rebuild UI state.

Each event carries a monotonic `seq` (from `INCR jobs:seq:<id>`) so the relay can
de-duplicate the backlog against live events.

Redis carries only transient event fan-out; durable job state is in Postgres. No
secrets are ever placed on the channel.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Optional, cast

from redis.asyncio import Redis

from config import settings
from logging_config import get_logger

logger = get_logger("jobs.events")

_CHANNEL_PREFIX = "jobs:events:"
_LOG_PREFIX = "jobs:eventlog:"
_SEQ_PREFIX = "jobs:seq:"
_EVENTLOG_TTL_SECONDS = 2 * 60 * 60
_EVENTLOG_MAX = 5000

# Lifecycle transition names + the generation passthrough.
LIFECYCLE_TYPES = {"queued", "running", "succeeded", "failed", "cancelled", "retrying"}
GENERATION_TYPE = "generation"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class JobEvent:
    job_id: str
    type: str  # a LIFECYCLE_TYPES value | "generation"
    status: str
    attempt: int = 0
    error: Optional[str] = None
    request_id: Optional[str] = None
    seq: int = 0
    # For type == "generation": the frontend-vocabulary event payload
    # (message_type/value/variant_index/data/event_id). Never contains secrets.
    payload: Optional[dict[str, Any]] = None
    ts: str = field(default_factory=_now_iso)

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @staticmethod
    def from_json(raw: str) -> "JobEvent":
        data = json.loads(raw)
        return JobEvent(**data)


class JobEventChannel:
    """Publish / subscribe / replay job events over Redis. One channel per job."""

    def __init__(self, redis: Optional[Redis] = None) -> None:
        self._redis = redis
        self._owns_redis = redis is None

    async def _client(self) -> Redis:
        if self._redis is None:
            self._redis = Redis.from_url(settings.redis_url, decode_responses=True)
        return self._redis

    @staticmethod
    def _key(job_id: str) -> str:
        return f"{_CHANNEL_PREFIX}{job_id}"

    @staticmethod
    def _log_key(job_id: str) -> str:
        return f"{_LOG_PREFIX}{job_id}"

    @staticmethod
    def _seq_key(job_id: str) -> str:
        return f"{_SEQ_PREFIX}{job_id}"

    async def publish(self, event: JobEvent) -> JobEvent:
        """Stamp a seq, append to the TTL'd backlog, and fan out live.

        Returns the stamped event.
        """
        client = await self._client()
        seq = int(cast("int", await cast("Any", client.incr(self._seq_key(event.job_id)))))
        stamped = dataclasses.replace(event, seq=seq)
        raw = stamped.to_json()

        pipe = client.pipeline()
        pipe.rpush(self._log_key(event.job_id), raw)
        pipe.ltrim(self._log_key(event.job_id), -_EVENTLOG_MAX, -1)
        pipe.expire(self._log_key(event.job_id), _EVENTLOG_TTL_SECONDS)
        pipe.expire(self._seq_key(event.job_id), _EVENTLOG_TTL_SECONDS)
        pipe.publish(self._key(event.job_id), raw)
        await cast("Any", pipe).execute()
        return stamped

    async def replay(self, job_id: str) -> list[JobEvent]:
        client = await self._client()
        raws = cast("list[str]", await cast("Any", client.lrange(self._log_key(job_id), 0, -1)))
        events: list[JobEvent] = []
        for raw in raws:
            try:
                events.append(JobEvent.from_json(str(raw)))
            except (ValueError, TypeError):
                logger.warning("dropping malformed backlog event", extra={"job_id": job_id})
        return events

    async def open_subscription(self, job_id: str) -> "JobEventSubscription":
        """Subscribe *now* (so nothing published after this is missed), then let
        the caller `replay()` the backlog and iterate live events. Live events
        already covered by the backlog are de-duplicated by `seq`."""
        client = await self._client()
        pubsub = client.pubsub()
        await pubsub.subscribe(self._key(job_id))
        return JobEventSubscription(job_id, pubsub, self)

    async def subscribe(self, job_id: str) -> AsyncIterator[JobEvent]:
        """Yield live events for one job until the caller stops iterating."""
        client = await self._client()
        pubsub = client.pubsub()
        await pubsub.subscribe(self._key(job_id))
        try:
            async for raw in pubsub.listen():  # pyright: ignore[reportUnknownVariableType]
                msg = cast("dict[str, object]", raw)
                if msg.get("type") != "message":
                    continue
                try:
                    yield JobEvent.from_json(str(msg["data"]))
                except (ValueError, TypeError):
                    logger.warning("dropping malformed job event", extra={"job_id": job_id})
        finally:
            await pubsub.unsubscribe(self._key(job_id))
            await pubsub.aclose()

    async def close(self) -> None:
        if self._redis is not None and self._owns_redis:
            await self._redis.aclose()
            self._redis = None


class JobEventSubscription:
    """A live subscription that also knows how to replay the backlog first."""

    def __init__(self, job_id: str, pubsub: Any, channel: JobEventChannel) -> None:
        self._job_id = job_id
        self._pubsub = pubsub
        self._channel = channel

    async def replay(self) -> list[JobEvent]:
        return await self._channel.replay(self._job_id)

    async def events(self, after_seq: int = 0) -> AsyncIterator[JobEvent]:
        try:
            async for raw in self._pubsub.listen():
                msg = cast("dict[str, object]", raw)
                if msg.get("type") != "message":
                    continue
                try:
                    event = JobEvent.from_json(str(msg["data"]))
                except (ValueError, TypeError):
                    logger.warning(
                        "dropping malformed job event", extra={"job_id": self._job_id}
                    )
                    continue
                if event.seq <= after_seq:
                    continue
                yield event
        finally:
            await self.aclose()

    async def aclose(self) -> None:
        try:
            await self._pubsub.unsubscribe(self._channel._key(self._job_id))
        finally:
            await self._pubsub.aclose()
