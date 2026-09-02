"""Request/trace correlation middleware.

Assigns every HTTP request a correlation id (accepted from a trusted upstream
header when present, otherwise minted) and binds it for the duration of the
request so all log records share it. Echoes it back as ``X-Request-ID``.

WebSocket connections are not covered by Starlette HTTP middleware; the
``/generate-code`` handler binds its own id via ``logging_config.request_context``.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.types import ASGIApp

from logging_config import new_request_id, reset_request_id, set_request_id

# Header a caller / proxy may use to propagate an existing id.
_INBOUND_HEADERS = ("x-request-id", "x-correlation-id")
_MAX_ID_LEN = 128


class RequestContextMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        request_id = _inbound_id(request) or new_request_id()
        token = set_request_id(request_id)
        try:
            response = await call_next(request)
        finally:
            reset_request_id(token)
        response.headers["X-Request-ID"] = request_id
        return response


def _inbound_id(request: Request) -> str | None:
    for header in _INBOUND_HEADERS:
        value = request.headers.get(header)
        if value:
            value = value.strip()
            if 0 < len(value) <= _MAX_ID_LEN and value.isprintable():
                return value
    return None
