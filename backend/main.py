# Load environment variables first
from dotenv import load_dotenv

load_dotenv()


from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from logging_config import configure_logging, get_logger
from operator_gate import log_operator_gate_status, require_operator
from request_context import RequestContextMiddleware
from routes import (
    capabilities,
    screenshot,
    generate_code,
    health,
    home,
    jobs,
    models,
    evals,
    export,
    design_systems,
    prompt_reports,
    agent_runs,
    eval_sets,
)
from uploaded_assets import configure_uploaded_asset_routes

configure_logging()
logger = get_logger("startup")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # --- startup -------------------------------------------------------
    logger.info(
        "backend startup complete",
        extra={
            "debug_mode": settings.is_debug_enabled,
            "is_prod": settings.is_prod,
            "cors_allowed_origins": settings.cors_allowed_origins,
            "log_format": settings.log_format,
            "job_queue_enabled": settings.job_queue_enabled,
            "database_configured": settings.database_url is not None,
        },
    )
    log_operator_gate_status()

    # Detect (and warm up) headless Chromium so the screenshot_preview tool is
    # only offered when it can actually run. Never fatal.
    try:
        from preview_screenshot import probe_screenshot_preview

        available = await probe_screenshot_preview()
        logger.info("screenshot_preview probe complete", extra={"available": available})
    except Exception:  # pragma: no cover - defensive; the probe already catches
        logger.exception("screenshot_preview probe raised; tool disabled")

    yield

    # --- shutdown ----------------------------------------------------
    from db.engine import dispose_engine
    from queue_client import close_arq_pool
    from redis_client import close_redis

    await close_arq_pool()
    await dispose_engine()
    await close_redis()
    logger.info("backend shutdown complete")


app = FastAPI(
    openapi_url=None, docs_url=None, redoc_url=None, lifespan=lifespan
)
configure_uploaded_asset_routes(app)

# Request/trace correlation: assign every request an id, echo X-Request-ID.
app.add_middleware(RequestContextMiddleware)

# CORS: explicit allow-list (no wildcard). Configure other environments with
# CORS_ALLOWED_ORIGINS. Credentials are allowed only because the origin list is
# now explicit.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Public routes
app.include_router(generate_code.router)
app.include_router(screenshot.router)
app.include_router(home.router)
app.include_router(health.router)
app.include_router(jobs.router)
app.include_router(models.router)
app.include_router(capabilities.router)
app.include_router(export.router)
app.include_router(design_systems.router)

# Operator-gated routes: internal evaluation / telemetry surfaces (spec FR-B4).
_operator_only = [Depends(require_operator)]
app.include_router(evals.router, dependencies=_operator_only)
app.include_router(prompt_reports.router, dependencies=_operator_only)
app.include_router(agent_runs.router, dependencies=_operator_only)
app.include_router(eval_sets.router, dependencies=_operator_only)
