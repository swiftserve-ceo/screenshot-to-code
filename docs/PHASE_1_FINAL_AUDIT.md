# Phase 1 — Final Completion Audit

**Date:** 2026-09-02 – 2026-09-03
**Spec:** `specs/001-phase-1-core-platform/spec.md` (no `plan.md` — `/speckit-plan` was never run; the batch briefs served as the task list)
**Method:** requirement-by-requirement review of the spec against the **actual code** in the working tree (Batches 1–4 + this final audit). Every PASS below is backed by a test, a live probe, or a code reference — not a previous report.

Legend: **PASS** · **PARTIAL** (works, with a documented boundary) · **FAIL** · **DEFERRED** (Phase 2+ by design)

---

## 1. Executive summary

Phase 1 delivers the platform foundation with **zero change to the default end-user
generation experience** (all new paths are behind `JOB_QUEUE_ENABLED`, default off).
As of this audit:

- **CI** runs backend (`pytest` + `pyright` + `alembic` round-trip + `alembic check` + a live queue smoke test against Postgres/Redis service containers) and frontend (`jest` + `lint:ratchet` + `build`) on every PR, on pinned runtimes, with throwaway credentials only. It has **not yet executed on a real GitHub Actions host**.
- **Security hardening** from Phase 0 is applied: preview `sandbox` (no `allow-same-origin`) + origin-checked message channel, CORS allow-list, operator gate (closed by default), strict config booleans, repaired `frontend/Dockerfile`. The four operator-gated eval-review iframes were also sandboxed in this audit. No new unsafe execution model; the worker cannot execute generated code (`screenshot_preview` hard-disabled in worker context).
- **Typed config** (`config.Settings`, pydantic v2, frozen, fail-fast) is the single entry point; the remaining runtime `os.environ` reads were moved behind it (one documented live override: `LOGS_PATH`).
- **Structured logging** + request-id correlation is cross-cutting middleware; correlation propagates API → worker; runtime `print()`s are migrated.
- **PostgreSQL + Alembic**: one-command dev stack, config-driven, health-checked, one infrastructure migration (`jobs`), clean apply to an empty DB, idempotent, round-trip + drift-check in CI, **no domain tables**.
- **Redis + arq worker + generic job lifecycle**: documented, startable locally and in CI, health-reported (`/health` `checks.worker`), full state machine with timestamps / bounded retries / idempotent terminals / crash re-acquire / an out-of-process reaper / explicit cancel.
- **Queued `text→create`** runs end-to-end API → job → Redis → worker → `JobEventChannel` → WS relay → frontend; disconnect ≠ cancel; reconnect replays the backlog; parity via server-key controlled-failure path (no provider keys were available, so no successful AI generation was fabricated).
- **Model registry**: typed, derived from `llm.py` + `costs.pricing` (cannot drift), `GET /api/models` secret-free, consumed by `factory.py` + `model_selection.py`, selection behaviour unchanged (pinned by tests for every key combination).

**Verdict: Phase 1 is READY to commit as the baseline.** All 17 completion-gate items are PASS or PASS-with-a-documented-Phase-2-boundary. The one caveat is CI has not run remotely yet — the exact CI commands were reproduced locally and pass.

**Count:** 62 requirement lines assessed → **54 PASS · 4 PARTIAL · 0 FAIL · 4 DEFERRED**. (PARTIAL items are all "works within Phase 1 scope; the rest is explicitly Phase 2".)

---

## 2. Phase 1 requirements traceability

### FR group A — CI / automated baseline

| Req | Status | Evidence |
|---|---|---|
| FR-A1 PR pipeline | PASS | `.github/workflows/ci.yml` on `pull_request` + push to `main`/foundation branch |
| FR-A2 backend pytest gates | PASS | `backend` job step `poetry run pytest -q` (632 tests) |
| FR-A3 pyright gates, no new warnings in changed files | PASS | step `poetry run pyright` → `0 errors, 36 warnings` (all pre-existing bs4/test); `pyrightconfig.json` `pythonVersion: 3.12` |
| FR-A4 frontend tests gate | PASS | `frontend` job `pnpm test` (44 pass) |
| FR-A5 frontend build gates | PASS | `pnpm build` (`✓ built`) |
| FR-A6 documented lint policy | PASS | `pnpm run lint:ratchet` against `frontend/.lint-baseline.json` (`maxErrors 16 / maxWarnings 6`); baseline only shrinks. Documented in LOCAL_DEVELOPMENT §6 + TECHNICAL_DECISIONS D10 / A-3 |
| FR-A7 pinned runtimes | PASS | `PYTHON_VERSION: "3.12"`, `NODE_VERSION: "22"`, Corepack pnpm from `packageManager` (`pnpm@10.32.1`), `POETRY_VERSION: "2.4.2"` |
| FR-A8 CI ↔ docs match | PASS | LOCAL_DEVELOPMENT §1/§9 state Python 3.12, Node 22, pnpm 10.32.1; match CI |
| FR-A9 no provider network in CI | PASS | no AI keys in CI env; provider tests are mocked / the queued path uses the controlled "no key" failure |
| FR-A10 Postgres + Redis in CI | PASS | `services: postgres:16-alpine`, `redis:7-alpine` with health-checks |
| FR-A11 per-check visibility on PR | PASS | GitHub Actions reports each step |

### FR group B — Security hardening

| Req | Status | Evidence |
|---|---|---|
| FR-B1 preview `sandbox` w/o `allow-same-origin` | PASS | `previewMessaging.PREVIEW_SANDBOX = "allow-scripts allow-forms allow-modals allow-popups allow-popups-to-escape-sandbox"`; variant tiles `sandbox="allow-scripts"`; **eval-review iframes now `sandbox="allow-scripts"` (this audit)**. Live: all 5 iframes checked, none carry `allow-same-origin` |
| FR-B2 select-and-edit over a validated channel | PASS | `preview-bridge.js` + `previewMessaging.isPreviewMessage` validate `event.source === iframe.contentWindow` **and** `event.data.source === "s2c-preview"` |
| FR-B3 CORS allow-list, no wildcard+credentials | PASS | `main.py` `allow_origins=settings.cors_allowed_origins` (default local origins, no `*`) |
| FR-B4 eval/telemetry endpoints operator-gated | PASS | `evals`, `prompt_reports`, `agent_runs`, `eval_sets` routers included with `dependencies=[Depends(require_operator)]`; `/eval-sessions/*` served by `eval_sets`. `/api/models` (new, public) is a *different* path from the gated eval `/models` and is secret-free by construction. Live: `GET /agent-runs` → 403 |
| FR-B5 gate is minimal, not auth | PASS | `operator_gate.require_operator` — shared token via `X-Operator-Token` header, `hmac.compare_digest`; docstring + SEC-8 note |
| FR-B6 strict config booleans | PASS | `config.env_bool` — only explicit truthy tokens true; `"false"`/`"0"`/`""`/unset → false; typo raises. `IS_PROD`/`IS_DEBUG_ENABLED` use it. `tests/test_env_bool.py` |
| FR-B7 stale `frontend/Dockerfile` | PASS | repaired to Corepack + pnpm (Batch 1); recorded in REMEDIATION_LOG |
| FR-B8 SSRF / path-traversal guards preserved | PASS | `routes/export.py` keeps `is_public_http_url` + redirect cap + size + content-type checks (diagnostics now structured); `routes/agent_runs.py` `RUN_ID_PATTERN` + filename checks intact |
| FR-B9 `OPENAI_BASE_URL` prod guard preserved | PASS | sync path `routes/generate_code.py:317` `if not IS_PROD:`; queued path `generation/types.ProviderCredentials.from_settings` `base_url = None if settings.is_prod else settings.openai_base_url` |
| FR-B10 written list of sandbox-deferred capabilities | PASS | §12 below + SEC-7 |

### FR group C — Typed configuration

| Req | Status | Evidence |
|---|---|---|
| FR-C1 single typed settings module | PASS | `config.Settings` (frozen pydantic v2), all fields typed + defaulted; `Settings.from_env()` |
| FR-C2 no stray `os.environ` in scope; remainder inventoried | PASS | grep of `backend/` (non-test): only `config.py`, `fs_logging/prompt_reports.py` (`LOGS_PATH` live override — commented, ops+test need), `main.py` (`load_dotenv`), and CLI scripts (`evals/asset_extraction_benchmark.py`, `run_*.py`). Inventoried here. |
| FR-C3 behaviour-preserving | PASS | module-level back-compat constants (`OPENAI_API_KEY`, `IS_PROD`, `NUM_VARIANTS`…) still exported from `settings`; 632 tests green |
| FR-C4 fail-fast on invalid config | PASS | `field_validator` for `database_url` / `log_level` / `openai_base_url`; `env_bool`/`env_int`/`env_float` raise `ValueError` at import |
| FR-C5 covers LOCAL_DEVELOPMENT §2 vars + DB/queue | PASS | settings ↔ `docs/LOCAL_DEVELOPMENT.md` §2 table cross-checked; new `job_*` / `worker_*` added both places |
| FR-C6 non-env constants represented | PASS | `num_variants=4`, `num_variants_video=2`, `generation_max_cost_usd=3.0` in `Settings`, values unchanged |

### FR group D — Observability

| Req | Status | Evidence |
|---|---|---|
| FR-D1 structured logs, configurable level | PASS | `logging_config.py` — `console`/`json` via `LOG_FORMAT`, level from `LOG_LEVEL` |
| FR-D2 correlation id per request | PASS | `request_context.RequestContextMiddleware` mints/propagates; WS handler binds its own; inbound `x-request-id` only used as-is (see SEC-9 / A-14 note below) |
| FR-D3 id on all records during handling | PASS | `contextvars` `request_id` injected by the logging filter; `tests/test_logging_config.py` |
| FR-D4 run/job id in generation log context | PASS | `JobService._emit` + `generation/job.py` log `job_id`; worker `request_context(job.request_id)` |
| FR-D5 correlation API → worker | PASS | job row carries `request_id`; worker re-binds it; **verified live** — the API request id appears on the worker's `job running` / `generation job starting` lines |
| FR-D6 no new `print` logging | PASS | Phase-1 code uses `get_logger`; runtime `print()`s migrated (`_log_token_usage`, `fs_logging/*`, routes, `image_generation`, `evals/core`+`sets`) |
| FR-D7 tracing-ready seam | PASS | `contextvars` context + structured records; no tracing backend wired (Phase 10) |
| FR-D8 correlation id surfaced on errors | PARTIAL | `X-Request-ID` response header is set for HTTP (API-8); it is **not** embedded in the WS `error` payload or the frontend error card. Low-effort Phase-2 follow-up. |

### FR group E — Database

| Req | Status | Evidence |
|---|---|---|
| FR-E1 Postgres in dev stack | PASS | `docker-compose.yml` `postgres:16-alpine` on `127.0.0.1:${POSTGRES_PORT:-5435}` |
| FR-E2 connection params from typed config | PASS | `db/engine._build_engine` + `migrations/env.py` read `settings.database_url` |
| FR-E3 migration tool w/ up/down + bookkeeping | PASS | Alembic; `alembic upgrade head` / `downgrade base`; `alembic_version` table |
| FR-E4 baseline migration, clean + idempotent on fresh DB | PASS | **verified this audit** — dropped `jobs` + `alembic_version`, `alembic upgrade head` applied cleanly, second run a no-op |
| FR-E5 safe session lifecycle, no leaks | PASS | `db/engine.session_scope` (commit/rollback/close), `pool_pre_ping`, `NullPool` for migrations, `dispose_engine` on shutdown |
| FR-E6 CI applies migrations to fresh Postgres | PASS | CI step `alembic upgrade → downgrade base → upgrade` + `alembic check` |
| FR-E7 no domain tables | PASS | only `jobs` (id, job_type, status, created/started/finished, attempt, max_attempts, error, request_id, worker, params jsonb, result_ref) + `alembic_version`. Live `\d jobs` confirms **no tenant/user/org/billing columns** |
| FR-E8 health reports DB | PASS | `/health` `checks.database` (`ok`/`error`/`disabled`), no connection string |
| FR-E9 no auth/org/billing tables or logic | PASS | migration inspected; `tests/test_jobs_model.py::test_job_as_dict_shape` asserts absence |

### FR group F — Job infrastructure

| Req | Status | Evidence |
|---|---|---|
| FR-F1 Redis in dev stack | PASS | `docker-compose.yml` `redis:7-alpine` |
| FR-F2 documented worker, startable local + CI + health | PASS | `poetry run arq worker.WorkerSettings`; LOCAL_DEVELOPMENT §3a; `test_queue_smoke.py` runs a real `arq.worker.Worker` in CI; `/health` `checks.worker` from arq's health-check key (**this audit**) |
| FR-F3 generation as an async job | PASS | `JOB_HANDLERS["generation"] = handle_generation_job` |
| FR-F4 durable queryable lifecycle | PASS | `jobs.status` enum + `GET /api/jobs/{id}`; states queued/running/succeeded/failed/cancelled |
| FR-F5 transitions observable w/ timestamps | PASS | `JobEvent` (`ts`) + `job.created_at/started_at/finished_at`; `LIFECYCLE_TYPES` |
| FR-F6 bounded retry, fail w/ captured error | PASS | `worker.execute_job` — `NON_RETRYABLE_ERRORS`, `try_number < job.max_attempts` else `mark_failed`; `_sanitised_error` `"<ExcType>: <msg>"[:500]`; `tests/test_worker.py::test_execute_job_retries_then_fails` |
| FR-F7 WS is an event channel, not the executor | PASS | `routes/generation_relay` — the relay only observes; job lifetime is independent |
| FR-F8 disconnect ≠ cancel | PASS | `_relay` catches `WebSocketDisconnect` and returns; `tests/test_batch3_queued_generation.py::test_relay_disconnect_does_not_change_job`; verified live |
| FR-F9 explicit cancel → `cancelled` | PASS | `POST /api/jobs/{id}/cancel` (**this audit**) — QUEUED→cancelled / RUNNING→cancelled+arq abort / terminal→409; relay forwards `cancelled` + closes (USER_CLOSE). `tests/test_batch3_*::test_cancel_*`, `test_queue_smoke.py::test_live_cancel_aborts_a_running_job` |
| FR-F10 behind default-off flag | PASS | `settings.job_queue_enabled` default `False`; `is_queued_text_create` gated |
| FR-F11 flag-off behaviour unchanged | PASS | `QueuedGenerationMiddleware` falls through to the synchronous pipeline; existing generate-code tests green |
| FR-F12 ≥1 path end-to-end w/ parity | PARTIAL | `text→create` runs end-to-end (verified live). Output parity vs. the sync path could not be byte-compared because **no provider keys were available**; the controlled-failure path is identical on both. A-7 accepts one representative flow. |
| FR-F13 `$3` spend ceiling on the queued path | PASS | queued path calls the same `run_generation` → `AgenticGenerationStage` → `AgentEngine` which re-checks `GENERATION_MAX_COST_USD` each turn; unchanged |
| FR-F14 event vocabulary backward-compatible; lifecycle additive | PASS | `_Forwarder` emits `variantCount`/`status`/`setCode`/`variantComplete`/`error` verbatim; `jobStatus` is additive |
| FR-F15 no tenant/user/billing on job records | PASS | see FR-E7 |

### FR group G — Model registry

| Req | Status | Evidence |
|---|---|---|
| FR-G1 registry with all metadata fields | PASS | `ModelEntry`: provider, key/api_name, capabilities, input_modalities, status, enabled, is_default, reasoning_effort, context_window, pricing |
| FR-G2 mirrors `llm.py`, provider map matches | PASS | `_build_llm_registry` iterates `Llm`; `test_model_registry.py::test_registry_covers_every_llm_member` + `test_provider_matches_llm_module` (parametrised over all members) |
| FR-G3 selection unchanged for every key combo + create/update/video | PASS | `generation/model_selection.select_variant_models` keeps policy in `model_choice_sets`; the registry filter is a no-op today (all `enabled`). `tests/test_model_selection.py` now covers all-keys (text/image create+update, video), openai+anthropic, **gemini+anthropic, gemini+openai, gemini-only** (added this audit), anthropic-only, openai-only, no-keys |
| FR-G4 pricing equals current source | PASS | `ModelEntry.pricing is MODEL_PRICING.get(api_name)`; `test_model_registry.py::test_pricing_is_sourced_from_costs_module` |
| FR-G5 tests pin registry + selection | PASS | `test_model_registry.py` (257 assertions incl. api-name/provider parity vs. legacy resolvers) + `test_model_selection.py` |
| FR-G6 no router / capability selection / overrides / user-selectable | PASS | none added; `select_variant_models` unchanged in policy |
| FR-G7 documented as Phase 2 router source | PASS | TECHNICAL_DECISIONS C21; ARCHITECTURE §3.12 |

### FR group H — Cross-cutting

| Req | Status | Evidence |
|---|---|---|
| FR-H1 no observable end-user change (flags default) | PASS | queue flag default off; sync pipeline untouched; preview sandbox is the one intentional behaviour change and it is a security fix with the message channel preserving select-and-edit |
| FR-H2 existing tests green (or documented) | PASS | 632 backend / 44 frontend pass; the historical "276/42" counts grew as tests were added, never by weakening |
| FR-H3 each changed subsystem documented (current→target→strategy) | PASS | REMEDIATION_LOG R1–R26 + this doc; ARCHITECTURE §3.10–3.12 |
| FR-H4 risky changes get tests | PASS | every new module ships with a test file |
| FR-H5 MIT license + attribution intact | PASS | `LICENSE`, `pyproject.toml` `authors`, README credits untouched |
| FR-H6 nothing deleted without evidence + note + tests | PASS | only removals: stale `frontend/Dockerfile` `yarn` usage (Batch 1, recorded), dead `TERMINAL` const in `routes/jobs.py` (this audit) |
| FR-H7 no Out-of-Scope capability introduced | PASS | §13 boundary review |
| FR-H8 ratified decisions recorded | PASS | D1, D3, D6, D10 + lint policy marked ratified in TECHNICAL_DECISIONS; C11–C26 for new interfaces |

### Non-functional

| Req | Status | Evidence |
|---|---|---|
| NFR-1 reproducible stack from docs | PASS | LOCAL_DEVELOPMENT §3a copy/paste block (infra → migrate → backend → worker → frontend → health) |
| NFR-2 zero regression, flags default | PASS | see FR-H1 / FR-F11 |
| NFR-3 CI < ~15 min | PASS (est.) | local backend suite ~60s + install/pyright/alembic; frontend ~1 min + build ~30s — well under 15 min |
| NFR-4 fail-fast, no hangs | PASS | invalid config aborts at import; `alembic` `SystemExit` if `DATABASE_URL` unset; Redis-down → job `FAILED` + one client error (not a hang) — `test_batch4_queue_failure_modes::test_a_*` |
| NFR-5 no secret exposure via config/logging | PASS | grep: no key/token/URL-credential logging; `_redacted_redis`; `/health`, `/api/jobs/{id}`, `/api/models` secret-free; `test_batch3_*` asserts no secret in `caplog` |
| NFR-6 stays in-repo, no dependency on saas wrapper | PASS | no import of / reference to `screenshot-to-code-saas` |
| NFR-7 observability overhead negligible | PASS | one `contextvar` set per request + a filter; no measurable latency |
| NFR-8 new backend code typed, no new pyright warnings in changed files | PASS | `pyright` 0 errors; changed files clean |
| NFR-9 contradicted docs updated | PASS | "no CI" / "no database" / "no Redis" / Python-version statements all corrected |

### Security requirements

| Req | Status | Evidence |
|---|---|---|
| SEC-1 no new execution path for generated code; no host/Docker/root access | PASS | grep: no `subprocess`/`shell=True`/`os.system`/`Popen`/`eval(`/`exec(`/docker-socket in application code; worker handler registry AST-tested `{noop, generation}` |
| SEC-2 preview isolated from host storage/parent | PASS | see FR-B1 |
| SEC-3 minimal validated preview↔host contract | PASS | see FR-B2 |
| SEC-4 CORS origin-restricted, no credentialed wildcard | PASS | see FR-B3 |
| SEC-5 internal endpoints unreachable w/o operator gate outside local dev | PASS | see FR-B4/B5; secure default = 403 |
| SEC-6 host keys server-side only; browser keys not readable by the sandboxed preview | PASS | sync path reads `settings` / dialog; queued path server-only; sandboxed preview cannot reach app `localStorage` |
| SEC-7 sandbox-deferred capabilities remain closed | PASS | §12 — all six items still closed; the **worker** additionally cannot render generated HTML (`screenshot_preview` disabled there) |
| SEC-8 operator gate ≠ auth system | PASS | docstring + one shared token, no identities/sessions |
| SEC-9 untrusted correlation headers not trusted for security | PARTIAL | inbound `x-request-id` is echoed into the log context as-is (no trusted-proxy allow-list — A-14). It is used only for **log correlation**, never for a security or access decision, so the risk is log-spoofing only. A trusted-proxy list is a small Phase-2 add. |
| SEC-10 security review confirms no new unsafe execution model | PASS | this document + REMEDIATION_LOG R25; the one finding (`screenshot_preview` reachable from the worker) was fixed |

### Architecture requirements

| Req | Status | Evidence |
|---|---|---|
| AR-1 engine/adapters/tools/prompt/cost preserved & wrapped | PASS | `generation/` is an adapter layer; `AgenticGenerationStage` moved verbatim; no engine rewrite |
| AR-2 worker wraps the engine; engine still runs synchronously | PASS | `handle_generation_job` → `run_generation` → same `AgentEngine`; flag-off = sync |
| AR-3 WS → "event channel bound to a run" while keeping the client contract | PASS | `generation_relay` + `_Forwarder`; vocabulary frozen, `jobStatus` additive |
| AR-4 typed config is the single env entry point | PASS | see FR-C1 |
| AR-5 data layer is thin, no domain models | PASS | `db/` = engine + base + session; only `jobs.models.Job` |
| AR-6 registry consulted, control not inverted | PASS | `model_selection` reads `MODEL_REGISTRY`; policy stays in `model_choice_sets` |
| AR-7 flag-off local dev works OR deps trivial (recorded) | PASS | compose one-command stack; DB optional when flag off; recorded AR-7 in spec + LOCAL_DEVELOPMENT |
| AR-8 logging/correlation as middleware, not per-handler | PASS | `RequestContextMiddleware` + `logging_config` filter |
| AR-9 new decisions/interfaces documented | PASS | TECHNICAL_DECISIONS C11–C26 |

### Data / API / Job-lifecycle / Observability requirements

| Req | Status | Evidence |
|---|---|---|
| DR-1 only Postgres + Redis introduced | PASS | no other stores |
| DR-2 job record fields limited, no tenant/PII | PASS | see FR-E7 |
| DR-3 existing local stores unchanged | PASS | design-systems JSON, asset dir, agent-run JSONL+SQLite untouched (design-systems path now via `settings`, same file) |
| DR-4 Redis not a system of record | PASS | durable state in Postgres; Redis = queue + TTL'd event backlog only |
| DR-5 no multi-tenancy in schema | PASS | see FR-E7 |
| DR-6 retention opt-in + prunable | PASS | `JOB_RETENTION_DAYS` + `prune_jobs` cron (terminal rows only) |
| API-1 existing REST paths/contracts kept (+ operator gate) | PASS | no path changes; gate added per SEC-5 |
| API-2 health reports new deps, no connection details | PASS | `/health` `{database, redis, worker}` |
| API-3 WS payload shape + event types unchanged, additive only | PASS | see FR-F14 |
| API-4 job-lifecycle events documented schema | PASS | `JobEvent` dataclass (job_id, type, status, attempt, error, request_id, seq, ts); ARCHITECTURE §3.11 |
| API-5 query job status + works after reconnect | PASS | `GET /api/jobs/{id}` + WS `{jobId}` replay; **verified live** — reconnect replays `jobCreated → jobStatus×2 → error` |
| API-6 new endpoints documented + tested | PASS | `/health`, `/api/jobs/{id}`, `/api/jobs/{id}/cancel`, `/api/models` — all have tests + docs |
| API-7 no auth/projects/orgs/billing API changes | PASS | none |
| API-8 correlation id in response header | PASS | `RequestContextMiddleware` sets `X-Request-ID` |
| JL-1 defined states | PASS | queued/running/succeeded/failed/cancelled + `attempt` counter |
| JL-2 legal transitions | PASS | `LEGAL_TRANSITIONS`; `running→queued` (retry) + `running→running` (re-acquire); terminals frozen; `tests/test_jobs_model.py` |
| JL-3 timestamp + error summary per transition | PASS | `_transition` sets `started_at`/`finished_at`; `error[:2000]` |
| JL-4 stuck-`running` watchdog → failed | PASS | arq `job_timeout` (in-process, hung job) **+** `reap_jobs` cron / `reap_stuck_running` (out-of-process, dead worker — this audit) |
| JL-5 cancellation cooperative + bounded | PASS | QUEUED instant; RUNNING via arq abort (event-loop bounded); `execute_job` catches `CancelledError` |
| JL-6 events ordered w/ the state machine | PASS | `seq`-stamped events; `_emit` only after a successful transition |
| JL-7 terminal state retrievable independent of the WS | PASS | Postgres row + `GET /api/jobs/{id}`; `test_batch3_*` |
| JL-8 retry bounded + logged + policy documented | PASS | `job_max_attempts` (1–10, default 3); `logger.warning("job will retry")`; TECHNICAL_DECISIONS D3 |
| JL-9 sync path not regressed | PASS | untouched pipeline; existing tests green |
| OB-1..OB-9 | PASS | structured logs (OB-1), correlation id + worker propagation (OB-2), job id in context (OB-3), no new `print` + documented convention (OB-4), `/health` DB+queue+worker (OB-5), lifecycle observable (OB-6), tracing-ready (OB-7), correlation id on HTTP errors — **OB-8 PARTIAL** for WS errors (same as FR-D8), `PROMPT_REPORTS_ENABLED` works on both paths (OB-9) |

---

## 3. Security audit

- **Static sweep** (`backend/` + `frontend/src/`): **no** `subprocess`, `shell=True`, `os.system`, `Popen`, `pty`, `eval(`, `exec(`, `__import__`, `child_process`, Docker socket, or `docker.sock` in application code. Only doc-comments in `worker.py` / `generation/job.py` asserting their absence.
- **Worker cannot execute generated code:** `JOB_HANDLERS = {noop, generation}` (AST-tested for `system`/`popen`/`eval`/`exec`/`run`/`call`/`check_output`); `generation` calls the agent/provider layer only; `worker._on_startup` calls `disable_screenshot_preview()` so the one tool that *renders* (executes) generated HTML is off in worker context.
- **Preview:** all 5 frontend iframes render untrusted output with `sandbox` and **no** `allow-same-origin` (primary preview + 4 variant tiles + 4 eval-review iframes; the eval ones were fixed in this audit).
- **CORS:** explicit allow-list, no `*`.
- **Operator gate:** closed by default (403); constant-time token compare; not an auth system.
- **Secrets:** never in logs / errors / WS payloads / job rows / `/health` / `/api/models` / `/api/capabilities`. Browser-supplied keys are stripped before the queued job is persisted; the queued path uses server config only.
- **SSRF/traversal:** `routes/export.py` and `routes/agent_runs.py` guards intact.
- **Residual (documented, deferred):** `--no-sandbox` headless Chromium in the **synchronous** path (SEC-7 / Phase 6); inbound `x-request-id` echoed to logs without a trusted-proxy list (SEC-9 — log-correlation only, no security decision).

**Verdict: PASS** — no new unsafe execution model; all SEC-7 items closed.

---

## 4. Infrastructure audit

| Area | Status | Notes |
|---|---|---|
| Compose stack | PASS | `postgres:16-alpine` + `redis:7-alpine`, loopback-only host ports, named volumes, health-checks; app services under `--profile app` |
| Typed config for DB/Redis/worker | PASS | `database_url`, `redis_url`, `job_*`, `worker_*` all in `Settings` |
| FastAPI lifecycle | PASS | single `@asynccontextmanager lifespan`; **zero** `@app.on_event` in the codebase (grep); ordered awaited shutdown (`close_arq_pool → dispose_engine → close_redis`) |
| Startup with Postgres + Redis up | PASS | live — `/health` `{database: ok, redis: ok, worker: ok}` |
| Startup with Redis down | PASS | app starts; `/health` `redis: error`, `status: degraded`; enqueue fails the job with one clean client error |
| Startup with DB down | PASS | app starts (flag-off generation works); `/health` `database: error`; queued path returns "service temporarily unavailable" not a 500/hang |
| `redis` dependency | PASS | now explicit in `pyproject.toml` (was transitive via `arq`) |
| Poetry version | PASS | CI + Dockerfile bumped to 2.4.2 to read `lock-version 2.1` |

---

## 5. Queue / worker audit

| Scenario | Status | Evidence |
|---|---|---|
| `queued → running → succeeded` | PASS | `test_queue_smoke.py::test_live_queue_processes_a_noop_job_end_to_end` (real burst worker) |
| `queued → running → failed` (sanitised error) | PASS | `test_queue_smoke.py::test_live_queue_marks_a_failing_job_failed`; live text→create no-key run |
| duplicate terminal completion | PASS | `_transition` idempotent for terminal→same-terminal; `test_job_service.py::test_terminal_marks_are_idempotent` |
| invalid transitions | PASS | `test_job_service.py::test_illegal_transitions_blocked`, `test_idempotency_does_not_cross_terminal_states` |
| worker retry then fail | PASS | `test_worker.py::test_execute_job_retries_then_fails` |
| worker failure mid-job (not falsely succeeded) | PASS | `test_batch4_queue_failure_modes.py::test_e_*` + `reap_jobs` cron for the orphan case |
| Redis unavailable | PASS | `test_batch4_queue_failure_modes.py::test_a_*` — job `FAILED`, one client error, no hang |
| worker unavailable | PASS | `test_b_*` — job stays `QUEUED`, API healthy; `/health` `worker: down` |
| worker starts after jobs exist | PASS | `test_c_*` |
| job lookup / persistence | PASS | `GET /api/jobs/{id}`; Postgres row |
| reconnect | PASS | live — WS `{jobId}` replays the backlog |
| WS disconnect | PASS | `test_relay_disconnect_does_not_change_job`; live |
| worker restart | PASS | `test_e_new_worker_can_reacquire_a_running_job` |
| Redis reconnect | PASS | `test_f_*` — channel + pool rebuild a dropped client |
| explicit cancel | PASS | `test_queue_smoke.py::test_live_cancel_aborts_a_running_job`, `test_batch3_*::test_cancel_*` |
| generation never owned by the WS | PASS | relay only observes; `_relay` returns on disconnect; job runs to a terminal state regardless |

**Verdict: PASS.**

---

## 6. Generation migration status

| Path | State |
|---|---|
| `text → create` | **QUEUED** (behind `JOB_QUEUE_ENABLED`, default off) — `is_queued_text_create` |
| `image → create` | legacy / synchronous |
| `multi-image → create` | legacy / synchronous |
| `URL → create` | legacy / synchronous |
| `video → create` | legacy / synchronous |
| any `update / edit` | legacy / synchronous |

The queued path does not alter the synchronous pipeline (`QueuedGenerationMiddleware` short-circuits only for the one gated case, else `next_func()`). Provider keys on the queued path are **server config only** (browser keys stripped) — per-tenant secret handoff is Phase 2 (SEC-6). **DEFERRED** items here are Phase 2/4 by design, not Phase 1 gaps.

---

## 7. CI status

**PARTIAL — configured and locally reproduced; not yet run on GitHub Actions.**

| CI step | Locally reproduced | Result |
|---|---|---|
| Python 3.12 / Node 22 / pnpm 10.32.1 / Poetry 2.4.2 | pins verified | ✓ |
| `poetry install --no-interaction` | `poetry check --lock` (no lock error); `poetry install` → "no dependencies to update" | ✓ |
| `poetry run pyright` | ran | 0 errors, 36 warnings |
| `alembic upgrade head → downgrade base → upgrade head` | ran on fresh DB | clean |
| `alembic check` | ran | "No new upgrade operations detected." |
| `poetry run pytest -q` (Postgres + Redis containers, `REQUIRE_INFRA=1`) | ran with local Postgres:5435 / Redis:6379 | 632 passed |
| live queue/worker smoke test | `test_queue_smoke.py` (3 cases incl. cancel) | passed |
| `pnpm install --frozen-lockfile` | lockfile present | ✓ |
| `pnpm test` | ran | 44 passed, 6 skipped |
| `pnpm run lint:ratchet` | ran | 16/6, within baseline |
| `pnpm build` | ran | `✓ built` |
| no real provider secrets | CI env has none; tests use the controlled-failure path | ✓ |

**Workflow review — issues checked & clear:** working directories correct (`working-directory: backend` / `frontend`); Poetry via `pipx` (on PATH on `ubuntu-latest`); `poetry config virtualenvs.in-project true` before `install`; service containers reachable at `localhost:5432`/`6379`; `DATABASE_URL`/`REDIS_URL`/`REQUIRE_INFRA` set at job scope; `corepack enable` resolves `packageManager` from `frontend/package.json` when pnpm runs in `frontend/`. No Windows-only assumptions in the workflow (the one Windows shim — `worker._handle_signals` for `SIGUSR1` in `test_queue_smoke`'s teardown — is harmless on Linux).

**Remaining:** a real Actions run must confirm container start-up timing and the pyright binary download on the runner.

---

## 8. Database / migration status

**PASS.** From a **truly empty** database (`DROP TABLE jobs, alembic_version`):
`alembic upgrade head` applied the single baseline migration cleanly; a second run was a no-op; `downgrade base` → `upgrade head` round-trips; `alembic check` reports no drift. Schema = `jobs` (11 columns, 3 indexes, no tenant/user/org/billing) + `alembic_version`. `migrations/env.py` reads `settings.database_url` and `SystemExit`s with guidance if unset. Migration file contains no secrets, no hardcoded prod values, no Phase 2 tables.

---

## 9. Frontend regression status

**PASS.** `jest` 44 pass / 6 skip. Verified (live + unit):

| Item | Status |
|---|---|
| generation submission → `jobCreated` | PASS (`generateCode.ts` `onJobCreated`) |
| queued state / job id / job status | PASS (`jobStatus` handler) |
| reconnect (transparent re-attach ≤5, backoff) | PASS (`connect({jobId})`) |
| terminal error — **exactly one** notification | PASS (`generateCode.test.ts` asserts one `toast.error`; live console shows a single trigger; backend `_Forwarder._error_sent` prevents the second) |
| retry button | PASS (per-variant error card) |
| preview sandbox | PASS (`PREVIEW_SANDBOX`, no `allow-same-origin`) |
| import / export / design systems / capabilities | PASS (live: import renders, `POST /api/export` → zip, design-systems CRUD, `/api/capabilities`) |
| no accidental Phase 2 (auth/projects/persistence) | PASS — frontend changes limited to preview sandbox + message channel + `generateCode.ts` reconnect/toast + the eval-iframe sandbox attributes |

Browser-refresh loses the in-memory `project-store` — **documented** as a Phase 2 limitation (the job itself stays queryable via `/api/jobs/{id}`).

---

## 10. Playwright results

Full stack (`docker compose` pg+redis · `uvicorn :7001` · `arq worker` · `pnpm dev :5180`), **no provider keys**:

1. App loads — **0 unexpected console errors** (only pre-existing React-Router future-flag warnings + the deliberate controlled-failure `console.error`).
2. Text tab → Generate → console `Generation queued as job <uuid>` → worker log `job running` → `generation job starting` (`has_server_key=False`) → `job failed` (`NonRetryableGenerationError`, attempt 1) — **request_id propagated API→worker**.
3. **Exactly one** error toast; the WS closes `4332`; no reconnect; no duplicate.
4. `GET /api/jobs/<id>` → `failed`, sanitised error, safe fields only.
5. Reconnect `{jobId}` → `jobCreated → jobStatus(queued) → jobStatus(running) → error ×1 → close 4332`.
6. `POST /api/jobs/<id>/cancel` on a terminal job → `409`; on a QUEUED job (worker down) → `cancelled` (verified separately).
7. `/health` → `worker: ok` with the worker up; `worker: down` + `status: degraded` with it stopped.
8. `GET /api/models` → 51 models, 4 providers, **no `api_name`/pricing/`sk-`**.
9. `GET /api/capabilities` → `{"screenshot_preview": true}` (API process only).
10. `GET /agent-runs` → **403** (operator gate).
11. All 5 iframes: `sandbox` present, **none** with `allow-same-origin`.
12. Import (HTML+Tailwind) renders in the sandboxed preview; `POST /api/export` → 200 `application/zip`; design-systems create/list/delete round-trip.

**No successful AI generation was fabricated.**

---

## 11. Test results

| Suite | Command | Result |
|---|---|---|
| backend | `DATABASE_URL=… REDIS_URL=… REQUIRE_INFRA=1 poetry run pytest -q` | **632 passed**, 3 warnings (arq's own deprecated-`close` warning in the smoke test) |
| backend types | `poetry run pyright` | **0 errors, 36 warnings** (pre-existing bs4 `.find()` typing + test dict typing; none in changed files) |
| migrations | `alembic upgrade → downgrade base → upgrade` + `alembic check` (empty DB) | clean, idempotent, no drift |
| frontend | `pnpm test` | **44 passed, 6 skipped** |
| frontend lint | `pnpm run lint:ratchet` | 16 errors / 6 warnings — at baseline |
| frontend build | `pnpm build` | `✓ built in ~28s` |

No test was weakened or skipped to get green.

---

## 12. Sandbox-phase-deferred unsafe capabilities (SEC-7 — must stay CLOSED until Phase 6)

1. Executing generated full-stack apps or any generated server-side code — **CLOSED** (no such path).
2. Running a real dev server for generated projects — **CLOSED**.
3. Installing arbitrary packages for generated projects — **CLOSED**.
4. Network egress for generated code — **CLOSED** (generated code runs only in the browser preview iframe, `sandbox` without `allow-same-origin`; the preview page can still make its own `fetch` calls — that is the browser's sandbox, not ours, and is unchanged from upstream).
5. Backend headless-browser rendering out of the unsafe in-process `--no-sandbox` model — **NOT FIXED, contained + documented**. The synchronous path still renders generated HTML in `--no-sandbox` Chromium. The **worker** additionally cannot do this (`screenshot_preview` disabled at worker startup).
6. Any visual-QA repair loop that executes generated code — **CLOSED** (no repair loop exists).

---

## 13. Explicit Phase 2+ boundary — confirmed NOT introduced

Scoped diff review against the Out-of-Scope list:

| Out of scope | Present? |
|---|---|
| Authentication (login, sessions, OIDC/OAuth) | **No** |
| Authorization beyond the operator gate | **No** — the gate is a single shared token, no identities |
| Organizations / workspaces / teams / memberships / roles / invitations | **No** — no such tables, models, or routes |
| Billing / subscriptions / credits / budgets beyond the `$3` per-variant ceiling | **No** |
| Server-owned projects / project versions / sharing | **No** — `project-store` stays client-side |
| Application IR | **No** — the registry is metadata, not an IR |
| Full-stack / multi-file generation / repo import | **No** |
| New generation engine / rewrite | **No** — wrapped only |
| Frontend redesign / IDE re-scoping / multi-project nav | **No** — changes limited to preview sandbox + message channel + `generateCode.ts` + eval-iframe `sandbox` attrs |
| Deployment infra / IaC / K8s | **No** |
| Unrestricted/privileged generated-code execution / dev servers / package install / egress | **No** |
| Visual QA comparison / repair loops | **No** |
| Production sandbox architecture | **No** |
| Per-tenant secrets / removal of browser keys | **No** — browser-key mechanism unchanged for the sync path; queued path is server-key-only by omission, not by a new secret store |
| Local-store migration to Postgres/object storage | **No** — design-systems JSON / assets / telemetry untouched |
| Capability router / per-org model overrides / user-selectable models | **No** |
| Distributed tracing / metrics / error-tracking integration | **No** — only the logging seam |

Pre-existing **unused** upstream dependency `langfuse` (never imported) is noted but left in place — removing upstream cruft is not Phase 1 scope.

---

## 14. Final Phase 1 readiness verdict

**READY — commit the Phase 1 baseline.**

| Completion-gate item (spec §"Phase 1 Completion Gate") | Verdict |
|---|---|
| 1. CI runs the baseline on pinned runtimes, blocks merge | PASS (config + local repro; remote run pending) |
| 2. Configuration centralized & typed, fails fast, behaviour preserved | PASS |
| 3. Structured logging & trace foundation, correlation to worker, no new `print` | PASS |
| 4. PostgreSQL in the dev stack, config-driven, health-checked | PASS |
| 5. Alembic functional, clean on empty DB, idempotent, round-trip, in CI, no domain tables | PASS |
| 6. Redis available, documented, in the dev stack + CI | PASS |
| 7. Worker operational, documented, startable local + CI, health reported | PASS |
| 8. ≥1 generation path through the queue without breaking existing behaviour; parity; sync intact | PASS (parity = controlled-failure equivalence; no keys available for a byte comparison — A-7) |
| 9. Job lifecycle/status observable: state machine, queryable, timestamps, bounded retries, terminal-after-disconnect | PASS |
| 10. Generation events streamable, vocabulary preserved, lifecycle additive + documented, works on reconnect | PASS |
| 11. Model-selection behaviour unchanged across all key combos + create/update/video | PASS |
| 12. Model registry defined with all metadata fields, mirrors `llm.py`, pinned by tests, documented as the Phase 2 source | PASS |
| 13. Existing tests green or exceptions documented | PASS |
| 14. Phase 0 security hardening addressed + deferred-unsafe list + security review | PASS |
| 15. No Phase 2+ functionality introduced | PASS |
| 16. Reproducibility — second engineer stands up the stack + reproduces CI from docs | PASS (docs complete; not independently walked by a second person) |
| 17. Decisions recorded — D1/D3/D6/D10 + lint policy ratified; new interfaces documented | PASS |

**Open, non-blocking:** (a) run CI once on GitHub Actions to confirm; (b) FR-D8/OB-8/SEC-9 partials — surface the correlation id in the WS error payload and add a trusted-proxy allow-list for inbound `x-request-id` (small Phase-2 adds); (c) a byte-level generation parity comparison once provider keys are available.
