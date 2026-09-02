"""Structured application logging + request/trace correlation.

Phase 1 observability foundation (constitution Principle X, spec FR-D1..D8):

* one configured handler, structured output (``console`` key=value or ``json``);
* every log record carries a ``request_id`` taken from a context variable, so all
  lines produced while handling one HTTP request or WebSocket session share an id;
* the stream is forced to UTF-8 with a non-fatal error handler, so logging can
  never crash the process on non-ASCII content (the failure mode that
  ``print`` of box-drawing characters caused on a cp1252 console — see
  BASELINE_FUNCTIONAL_AUDIT KF-1 / KF-2).

This module intentionally has no dependency on FastAPI so it can be imported
from anywhere, including at startup before the app is built.
"""

from __future__ import annotations

import contextvars
import io
import json
import logging
import sys
import uuid
from typing import Any, Iterator
from contextlib import contextmanager

from config import settings

# Correlation id for the current request / WebSocket session. ``None`` outside a
# request (module import, background startup, tests).
_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)

_LOGGER_NAME = "app"
_configured = False

# Record attributes that logging sets itself; everything else a caller passed via
# ``extra=`` is treated as a structured field.
_RESERVED = set(
    logging.makeLogRecord({}).__dict__.keys()
) | {"message", "asctime", "request_id", "taskName"}


def new_request_id() -> str:
    return uuid.uuid4().hex


def get_request_id() -> str | None:
    return _request_id.get()


def set_request_id(request_id: str | None) -> contextvars.Token[str | None]:
    return _request_id.set(request_id)


def reset_request_id(token: contextvars.Token[str | None]) -> None:
    try:
        _request_id.reset(token)
    except (LookupError, ValueError):
        _request_id.set(None)


@contextmanager
def request_context(request_id: str | None = None) -> Iterator[str]:
    """Bind a request id for the duration of the block."""
    rid = request_id or new_request_id()
    token = _request_id.set(rid)
    try:
        yield rid
    finally:
        _request_id.reset(token)


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get() or "-"
        return True


class _ConsoleFormatter(logging.Formatter):
    """Human-readable, greppable ``key=value`` structured line."""

    def format(self, record: logging.LogRecord) -> str:
        base = (
            f"{self.formatTime(record, '%Y-%m-%dT%H:%M:%S%z')} "
            f"level={record.levelname} "
            f"logger={record.name} "
            f"request_id={getattr(record, 'request_id', '-')} "
            f"msg={record.getMessage()!r}"
        )
        extras = _extra_fields(record)
        if extras:
            base += " " + " ".join(f"{k}={v!r}" for k, v in extras.items())
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "msg": record.getMessage(),
        }
        payload.update(_extra_fields(record))
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=repr)


def _extra_fields(record: logging.LogRecord) -> dict[str, Any]:
    return {
        key: value
        for key, value in record.__dict__.items()
        if key not in _RESERVED and not key.startswith("_")
    }


def _utf8_stream() -> io.TextIOBase:
    """A stderr stream that will not raise on non-ASCII characters."""
    stream = sys.stderr
    try:
        # Python 3.7+: switch the existing stream to permissive UTF-8.
        stream.reconfigure(encoding="utf-8", errors="backslashreplace")  # type: ignore[union-attr]
        return stream  # type: ignore[return-value]
    except Exception:
        buffer = getattr(stream, "buffer", None)
        if buffer is not None:
            return io.TextIOWrapper(
                buffer, encoding="utf-8", errors="backslashreplace", line_buffering=True
            )
        return stream  # type: ignore[return-value]


def configure_logging(force: bool = False) -> None:
    """Install the structured handler on the ``app`` logger. Idempotent."""
    global _configured
    if _configured and not force:
        return

    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(settings.log_level)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    handler = logging.StreamHandler(_utf8_stream())
    handler.setFormatter(
        _JsonFormatter() if settings.log_format == "json" else _ConsoleFormatter()
    )
    handler.addFilter(_RequestIdFilter())
    logger.addHandler(handler)

    # Route uvicorn's own loggers through the same handler so request lines and
    # app lines interleave consistently and carry the request id when present.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv = logging.getLogger(name)
        uv.handlers = [handler]
        uv.propagate = False

    _configured = True


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a child of the configured ``app`` logger."""
    if not _configured:
        configure_logging()
    return logging.getLogger(_LOGGER_NAME if not name else f"{_LOGGER_NAME}.{name}")
