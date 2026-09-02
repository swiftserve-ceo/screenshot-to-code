import asyncio
from typing import Optional

from babel_cdn import normalize_babel_cdn
from logging_config import get_logger
from preview_screenshot.base import ScreenshotBackend
from preview_screenshot.playwright_backend import PlaywrightBackend

logger = get_logger("screenshot_preview")

# Upper bound on the one-time startup probe. A cold headless Chromium launches in
# well under this; a missing / broken browser must not hang app startup (spec
# NFR-4 — a missing infra dependency fails, it does not hang).
_PROBE_TIMEOUT_SECONDS = 30.0

# The active backend. Defaults to local Chromium; a deployment can swap in an
# alternative (e.g. an external rendering API) via set_screenshot_backend.
_backend: ScreenshotBackend = PlaywrightBackend()

# Cached result of the startup probe: whether _backend can run here. None until
# the first probe runs. Used to gate the tool so it isn't offered when it can't.
_available: Optional[bool] = None


def set_screenshot_backend(backend: ScreenshotBackend) -> None:
    """Install the screenshot backend (call once, before the startup probe)."""
    global _backend
    _backend = backend


def disable_screenshot_preview() -> None:
    """Hard-disable the screenshot_preview tool for this process.

    The background worker calls this at startup: rendering generated HTML in
    headless Chromium *executes* untrusted markup/JS, and the worker MUST remain
    incapable of executing generated code (Phase 1 spec SEC / constitution). The
    synchronous API process is unaffected.
    """
    global _available
    _available = False


async def probe_screenshot_preview() -> bool:
    """Check (once, cached) whether the active backend can run here.

    Time-bounded: if the probe (a headless-browser launch) does not settle
    within ``_PROBE_TIMEOUT_SECONDS`` the tool is marked unavailable rather than
    hanging startup.
    """
    global _available
    if _available is None:
        try:
            _available = await asyncio.wait_for(
                _backend.available(), timeout=_PROBE_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            logger.warning(
                "screenshot_preview probe timed out after %ss; tool disabled",
                _PROBE_TIMEOUT_SECONDS,
            )
            _available = False
        except Exception:  # noqa: BLE001 - probe must never propagate
            logger.warning("screenshot_preview probe raised; tool disabled", exc_info=True)
            _available = False
    return _available


def is_screenshot_preview_available() -> bool:
    """Synchronous accessor for the cached probe result.

    Defaults to True when the probe hasn't run yet so we never wrongly hide the
    tool before startup has checked; the runtime still fails safe if a call
    errors. In practice the startup probe sets this before any request.
    """
    return _available if _available is not None else True


async def capture_preview_screenshot(
    html: str,
    device: str = "desktop",
    full_page: bool = True,
) -> bytes:
    """Render HTML to PNG via the active backend.

    The public entry point the screenshot_preview tool calls; the backend choice
    is invisible to callers. Normalizes the Babel CDN first so generated React
    pages (old and new) actually mount before we capture.
    """
    return await _backend.capture(normalize_babel_cdn(html), device, full_page)
