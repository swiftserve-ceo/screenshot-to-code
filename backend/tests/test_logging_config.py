# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false
"""Structured logging + request-id correlation groundwork."""

import logging

from logging_config import (
    configure_logging,
    get_logger,
    get_request_id,
    new_request_id,
    request_context,
)
from utils import _safe_print, print_prompt_preview


def test_get_logger_is_namespaced():
    logger = get_logger("thing")
    assert logger.name == "app.thing"


def test_request_context_binds_and_clears():
    configure_logging()
    logger = get_logger("test")
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Capture()
    # Mirror the real handler's filter so records carry request_id.
    for existing in logging.getLogger("app").handlers:
        for flt in existing.filters:
            handler.addFilter(flt)
    logging.getLogger("app").addHandler(handler)
    try:
        with request_context("rid-123") as rid:
            assert rid == "rid-123"
            assert get_request_id() == "rid-123"
            logger.info("hello", extra={"k": "v"})
        assert get_request_id() is None
    finally:
        logging.getLogger("app").removeHandler(handler)

    assert records
    assert getattr(records[-1], "request_id", None) == "rid-123"
    assert getattr(records[-1], "k", None) == "v"


def test_new_request_id_is_unique():
    assert new_request_id() != new_request_id()


def test_configure_logging_is_idempotent():
    configure_logging()
    logger = logging.getLogger("app")
    before = len(logger.handlers)
    configure_logging()
    assert len(logger.handlers) == before


def test_safe_print_never_raises(capsys):
    # Box-drawing characters that crash a cp1252 stdout are handled.
    _safe_print("┌─ box ─┐")
    print_prompt_preview([{"role": "system", "content": "hi"}])  # type: ignore[list-item]
    out: str = capsys.readouterr().out
    assert "PROMPT PREVIEW" in out
