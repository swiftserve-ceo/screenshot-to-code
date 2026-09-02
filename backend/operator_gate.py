"""Phase 1 operator gate for privileged development / operator endpoints.

This is **not** the future authentication / authorization system. Its only job is
to stop the evaluation, prompt-report, and agent-run surfaces (which expose
internal telemetry, absolute host paths, and an eval runner that spends money)
from being reachable by anyone who can open a socket to the backend — the
"accidental unrestricted exposure" flagged in BASELINE_FUNCTIONAL_AUDIT (SF-4).

Policy (spec FR-B4 / FR-B5):

* ``OPERATOR_ENDPOINTS_PUBLIC=true`` — gate disabled (local-dev escape hatch).
* otherwise, if ``OPERATOR_TOKEN`` is set — callers must send a matching
  ``X-Operator-Token`` header.
* otherwise — the endpoints return 403 (secure default: closed until configured).

Real per-user / per-org permissions are Phase 2 and deliberately out of scope.
"""

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, status

from config import settings
from logging_config import get_logger

logger = get_logger("operator_gate")

_OPERATOR_TOKEN_HEADER = "X-Operator-Token"


async def require_operator(
    x_operator_token: str | None = Header(default=None, alias=_OPERATOR_TOKEN_HEADER),
) -> None:
    if settings.operator_endpoints_public:
        return

    if not settings.operator_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Operator endpoints are disabled. Set OPERATOR_TOKEN (and send it as the "
                f"{_OPERATOR_TOKEN_HEADER} header) or set OPERATOR_ENDPOINTS_PUBLIC=true for "
                "local development."
            ),
        )

    if not x_operator_token or not hmac.compare_digest(
        x_operator_token, settings.operator_token
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Missing or invalid {_OPERATOR_TOKEN_HEADER} header.",
        )


def log_operator_gate_status() -> None:
    if settings.operator_endpoints_public:
        logger.warning(
            "operator endpoints are PUBLIC (OPERATOR_ENDPOINTS_PUBLIC=true) — "
            "acceptable for local development only"
        )
    elif settings.operator_token:
        logger.info("operator endpoints require the %s header", _OPERATOR_TOKEN_HEADER)
    else:
        logger.info(
            "operator endpoints are disabled (no OPERATOR_TOKEN set); set it or "
            "OPERATOR_ENDPOINTS_PUBLIC=true to enable them"
        )
