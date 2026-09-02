"""Central typed configuration for the backend.

Single source of truth for environment-derived settings. Values are read from the
environment **once**, at import time, into a validated :class:`Settings` model.

Two ways to consume configuration:

* the module-level constants below (``OPENAI_API_KEY``, ``IS_PROD`` …) — kept for
  backward compatibility with existing imports;
* ``from config import settings`` and then ``settings.is_prod`` etc.

Invalid configuration (a non-boolean flag, a non-numeric cost ceiling, a
malformed URL) raises at import time so the process fails fast instead of running
with a silently wrong flag. See Phase 1 spec FR-C1..C6 and constitution
Principle XV.

Secrets (provider API keys, the operator token) live here only as values read
from the environment; they are never logged and never written to disk by this
module.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# --- environment parsing helpers ------------------------------------------------

_TRUTHY = {"1", "true", "yes", "on", "y", "t"}
_FALSY = {"", "0", "false", "no", "off", "n", "f"}


def env_bool(name: str, default: bool = False) -> bool:
    """Parse an environment variable as a strict boolean.

    Only explicit truthy tokens (``1 true yes on y t``) return ``True``; explicit
    falsy tokens (``0 false no off n f`` or empty) and an unset variable return
    the default (normally ``False``). Any other value raises ``ValueError`` so a
    typo like ``IS_PROD=flase`` fails fast instead of being treated as truthy.

    This replaces the historical ``bool(os.environ.get(...))`` /
    ``os.environ.get(..., False)`` patterns, where the string ``"false"`` was
    truthy.
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in _TRUTHY:
        return True
    if value in _FALSY:
        return False
    raise ValueError(
        f"Environment variable {name}={raw!r} is not a valid boolean. Use one of "
        f"{sorted(_TRUTHY)} for true or {sorted(_FALSY)} for false."
    )


def env_str(name: str, default: str | None = None) -> str | None:
    raw = os.environ.get(name)
    if raw is None:
        return default
    raw = raw.strip()
    return raw if raw != "" else default


def env_list(name: str, default: list[str]) -> list[str]:
    """Parse a comma-separated environment variable into a list of trimmed items."""
    raw = os.environ.get(name)
    if raw is None:
        return list(default)
    items = [part.strip() for part in raw.split(",")]
    return [item for item in items if item]


def env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(
            f"Environment variable {name}={raw!r} is not a valid number."
        ) from exc


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(
            f"Environment variable {name}={raw!r} is not a valid integer."
        ) from exc


# Default origins the SPA is served from during local development. Production /
# other environments override these with CORS_ALLOWED_ORIGINS.
_DEFAULT_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5180",
    "http://127.0.0.1:5180",
]

_BACKEND_DIR = Path(__file__).resolve().parent


class Settings(BaseModel):
    """Validated backend configuration. Built once via :meth:`from_env`."""

    model_config = {"frozen": True}

    # --- generation / variants -------------------------------------------------
    num_variants: int = Field(default=4, ge=1, le=16)
    num_variants_video: int = Field(default=2, ge=1, le=16)
    generation_max_cost_usd: float = Field(default=3.0, gt=0)

    # --- LLM / provider credentials (secrets) ---------------------------------
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    gemini_api_key: str | None = None
    openai_base_url: str | None = None
    replicate_api_key: str | None = None

    # --- feature flags -------------------------------------------------------
    is_prod: bool = False
    is_debug_enabled: bool = False
    prompt_reports_enabled: bool = False

    # --- filesystem / assets ------------------------------------------------
    debug_dir: str = ""
    local_asset_dir: str = str(_BACKEND_DIR / "local_assets")
    local_asset_base_url: str = "http://127.0.0.1:7001"
    logs_path: str | None = None
    screenshot_to_code_data_dir: str | None = None
    evals_dir: str = "./evals_data"

    # --- HTTP / security --------------------------------------------------
    cors_allowed_origins: list[str] = Field(default_factory=lambda: list(_DEFAULT_CORS_ORIGINS))
    # Shared secret for the Phase 1 operator gate on eval / agent-run / debug
    # endpoints. When set, those endpoints require an "X-Operator-Token" header.
    operator_token: str | None = None
    # Explicit escape hatch that leaves the operator endpoints open (local dev
    # only). The secure default is False.
    operator_endpoints_public: bool = False

    # --- infrastructure (Batch 2: DB + queue foundation) ------------------
    # SQLAlchemy async URL. Optional: if unset or unreachable the app still
    # starts and the synchronous generation path keeps working; the health
    # endpoint reports the DB as unavailable.
    database_url: str | None = None
    # arq / Redis coordination URL (transient queue state only; durable job
    # state lives in Postgres).
    redis_url: str = "redis://127.0.0.1:6379/0"
    # When true, the async job path may be used. Default false — the existing
    # synchronous generation path stays the default until a later batch proves
    # parity (spec FR-F10).
    job_queue_enabled: bool = False
    # Identifies this worker process in logs (defaults to the hostname).
    worker_name: str | None = None
    # How often the worker refreshes its arq health-check key. /health treats a
    # missing key as "no live worker"; the key TTL is this + 1s.
    worker_health_interval_seconds: int = Field(default=30, ge=5, le=3600)
    # Bounded retry policy for background jobs (spec FR-F6 / JL-8).
    job_max_attempts: int = Field(default=3, ge=1, le=10)
    # Wall-clock ceiling for a single job before the watchdog fails it
    # (spec JL-4), in seconds. Enforced in-process by arq for a hung job on a
    # live worker.
    job_timeout_seconds: int = Field(default=900, ge=30)
    # Out-of-process watchdog: a job left `running` this long is reaped to
    # `failed` by the worker's reap_jobs cron (covers a worker killed mid-job).
    # Must comfortably exceed job_timeout_seconds so arq's own timeout fires
    # first for a merely-hung job. 0 disables the reaper.
    job_reap_after_seconds: int = Field(default=3600, ge=0)
    # Opt-in retention for terminal job rows (spec DR-6: "opt-in, prunable").
    # None disables pruning entirely; a positive value is the age in days after
    # which a *terminal* job (succeeded/failed/cancelled) becomes eligible for
    # deletion. Running/queued jobs are never pruned.
    job_retention_days: int | None = Field(default=None, ge=1, le=3650)

    # --- observability -----------------------------------------------------
    log_level: str = "INFO"
    log_format: Literal["console", "json"] = "console"

    @field_validator("database_url")
    @classmethod
    def _valid_database_url(cls, value: str | None) -> str | None:
        if value and not value.startswith(("postgresql+asyncpg://", "postgresql://", "sqlite+aiosqlite://")):
            raise ValueError(
                "DATABASE_URL must be a postgresql+asyncpg:// URL "
                "(or postgresql:// — it is normalised to asyncpg)"
            )
        # Normalise a plain postgresql:// URL to the async driver.
        if value and value.startswith("postgresql://"):
            return "postgresql+asyncpg://" + value[len("postgresql://") :]
        return value

    @field_validator("log_level")
    @classmethod
    def _valid_log_level(cls, value: str) -> str:
        level = value.strip().upper()
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if level not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {sorted(allowed)}, got {value!r}")
        return level

    @field_validator("openai_base_url")
    @classmethod
    def _valid_base_url(cls, value: str | None) -> str | None:
        if value and not value.startswith(("http://", "https://")):
            raise ValueError("OPENAI_BASE_URL must start with http:// or https://")
        return value

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            num_variants=env_int("NUM_VARIANTS", 4),
            num_variants_video=env_int("NUM_VARIANTS_VIDEO", 2),
            generation_max_cost_usd=env_float("GENERATION_MAX_COST_USD", 3.0),
            openai_api_key=env_str("OPENAI_API_KEY"),
            anthropic_api_key=env_str("ANTHROPIC_API_KEY"),
            gemini_api_key=env_str("GEMINI_API_KEY"),
            openai_base_url=env_str("OPENAI_BASE_URL"),
            replicate_api_key=env_str("REPLICATE_API_KEY"),
            is_prod=env_bool("IS_PROD", False),
            is_debug_enabled=env_bool("IS_DEBUG_ENABLED", False),
            prompt_reports_enabled=env_bool("PROMPT_REPORTS_ENABLED", False),
            debug_dir=env_str("DEBUG_DIR", "") or "",
            local_asset_dir=env_str("LOCAL_ASSET_DIR", str(_BACKEND_DIR / "local_assets"))
            or str(_BACKEND_DIR / "local_assets"),
            local_asset_base_url=env_str("LOCAL_ASSET_BASE_URL", "http://127.0.0.1:7001")
            or "http://127.0.0.1:7001",
            logs_path=env_str("LOGS_PATH"),
            screenshot_to_code_data_dir=env_str("SCREENSHOT_TO_CODE_DATA_DIR"),
            evals_dir=env_str("EVALS_DIR", "./evals_data") or "./evals_data",
            cors_allowed_origins=env_list("CORS_ALLOWED_ORIGINS", _DEFAULT_CORS_ORIGINS),
            operator_token=env_str("OPERATOR_TOKEN"),
            operator_endpoints_public=env_bool("OPERATOR_ENDPOINTS_PUBLIC", False),
            database_url=env_str("DATABASE_URL"),
            redis_url=env_str("REDIS_URL", "redis://127.0.0.1:6379/0") or "redis://127.0.0.1:6379/0",
            job_queue_enabled=env_bool("JOB_QUEUE_ENABLED", False),
            worker_name=env_str("WORKER_NAME"),
            worker_health_interval_seconds=env_int("WORKER_HEALTH_INTERVAL_SECONDS", 30),
            job_max_attempts=env_int("JOB_MAX_ATTEMPTS", 3),
            job_timeout_seconds=env_int("JOB_TIMEOUT_SECONDS", 900),
            job_reap_after_seconds=env_int("JOB_REAP_AFTER_SECONDS", 3600),
            job_retention_days=(
                env_int("JOB_RETENTION_DAYS", 0) or None
            ),
            log_level=env_str("LOG_LEVEL", "INFO") or "INFO",
            log_format=env_str("LOG_FORMAT", "console") or "console",  # type: ignore[arg-type]
        )


settings = Settings.from_env()


# --- backward-compatible module-level constants --------------------------------
# Existing code imports these names directly. They now come from the validated
# `settings` object. New code should prefer `from config import settings`.

NUM_VARIANTS = settings.num_variants
NUM_VARIANTS_VIDEO = settings.num_variants_video

OPENAI_API_KEY = settings.openai_api_key
ANTHROPIC_API_KEY = settings.anthropic_api_key
GEMINI_API_KEY = settings.gemini_api_key
OPENAI_BASE_URL = settings.openai_base_url
REPLICATE_API_KEY = settings.replicate_api_key

IS_DEBUG_ENABLED = settings.is_debug_enabled
DEBUG_DIR = settings.debug_dir

# Hard per-generation spend ceiling; a run that would continue past this is
# aborted. Applies per variant / eval run. Unpriced models are not bounded.
GENERATION_MAX_COST_USD = settings.generation_max_cost_usd

PROMPT_REPORTS_ENABLED = settings.prompt_reports_enabled
LOCAL_ASSET_DIR = settings.local_asset_dir
LOCAL_ASSET_BASE_URL = settings.local_asset_base_url

# Set to True when running in production (on the hosted version). Feature flag
# used to enable / disable certain behaviours.
IS_PROD = settings.is_prod
