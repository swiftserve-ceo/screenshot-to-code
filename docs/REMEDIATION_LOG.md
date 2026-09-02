# LG Telecoms App Builder — Remediation Log

Chronological record of remediation work: fixing the inherited application's
confirmed defects while preserving working functionality. Each entry follows the
format required by the batch brief.

Governing sources: `.specify/memory/constitution.md`,
`specs/001-phase-1-core-platform/spec.md`, `docs/BASELINE_FUNCTIONAL_AUDIT.md`,
`docs/LG_TELECOMS_APP_BUILDER_ARCHITECTURE.md`, `docs/TECHNICAL_DECISIONS.md`,
`docs/ROADMAP.md`.

> There is no `specs/001-phase-1-core-platform/plan.md` yet (`/speckit-plan` has
> not been run). This batch follows the spec + constitution + audit directly; the
> batch brief is itself the task list for this increment.

---

## Batch 1 — 2026-09-02

**Scope (from the brief):** preview security hardening; CORS hardening; sensitive
endpoint gating; boolean configuration fixes; typed configuration foundation;
stale Dockerfile assessment/fix; structured logging migration for the
highest-risk application paths. **Explicitly NOT in this batch:** Redis / worker /
job queue, PostgreSQL / Alembic, the AI model registry, and everything in the
constitution's Phase 2+ list.

### Green baseline (before any change)

| Check | Result | Source |
|---|---|---|
| `backend pytest` | **276 passed** | this run + Phase 0 |
| `backend pyright` | **0 errors, 36 warnings** | this run + Phase 0 |
| `frontend pnpm test` | **42 passed, 6 skipped, 1 suite skipped** | this run + Phase 0 |
| `frontend pnpm lint` | **FAIL — 19 errors, 6 warnings** (pre-existing, audit KF-9) | this run + Phase 0 |
| `frontend pnpm build` | **PASS** (chunk-size warning only) | this run + Phase 0 |

The 19 lint errors are pre-existing (`@typescript-eslint/no-explicit-any` ×18,
`no-case-declarations` ×1) in `AgentActivity.tsx`, `commits/types.ts`,
`generateCode.ts`, `BestOfNEvalsPage.tsx`. **Batch 1 does not touch those files
and does not change the count.** The lint-policy decision (audit KF-9) is deferred
to the CI batch.

### Post-batch check results

| Check | Result | Delta |
|---|---|---|
| `backend pytest` | **307 passed** (276 + 31 new) | +31, 0 regressions |
| `backend pyright` | **0 errors, 36 warnings** | unchanged |
| `frontend pnpm test` | **42 passed, 6 skipped, 1 suite skipped** | unchanged |
| `frontend pnpm lint` | **FAIL — 19 errors, 6 warnings** | unchanged (same pre-existing set) |
| `frontend pnpm build` | **PASS** | unchanged (bundle +~5 KB for the inlined preview bridge) |

---

### R1 — Preview iframe not sandboxed (audit SF-1 / SF-2 / KF-4)

**Problem.** The main preview iframe (`PreviewComponent.tsx`) carried no `sandbox`
attribute, so LLM-authored / imported page JavaScript ran same-origin with the
host app and could read `window.parent.localStorage` (which stores provider API
keys), `document.cookie`, and reach `window.parent`. Verified live in the audit:
`canReadParent: true`. The variant-thumbnail iframe (`Variants.tsx`) used
`sandbox="allow-scripts allow-same-origin"` — the "can escape its sandboxing"
anti-pattern (effectively unsandboxed).

**Root cause.** Select-and-edit was built on direct cross-frame DOM access
(`iframe.contentWindow` / `iframe.contentDocument`), which only works when the
iframe shares the host origin — so a real sandbox was never added.

**Change.**
- Main preview iframe now uses
  `sandbox="allow-scripts allow-forms allow-modals allow-popups allow-popups-to-escape-sandbox"`
  — **no `allow-same-origin`, no `allow-top-navigation`**. The previewed page is
  now an opaque origin: the host cannot read its DOM and it cannot read the host's.
- A new **preview bridge** (`preview-bridge.js`, injected into every previewed
  document before its own scripts) is the only channel between preview and host.
  It runs inside the sandbox and does all element selection, hover/selection
  overlays, and the crosshair cursor locally, then `postMessage`s a **serialized**
  snapshot (`{ tagName, outerHTML, context }`) to the host — never a live DOM node.
- Host side (`previewMessaging.ts` + rewritten `PreviewComponent.tsx`): a single
  `message` listener validates `event.source === iframe.contentWindow` **and**
  `event.data.source === "s2c-preview"` on every message; the host posts
  `setSelectMode` / `clearSelection` back with an `"s2c-host"` tag. All direct
  `contentWindow` / `contentDocument` access is removed.
- `app-store.selectedElement` changed from `HTMLElement | null` to
  `SelectedElement | null` (the serialized shape). `App.tsx` and the
  `project-store` test updated accordingly.
- `Variants.tsx` thumbnail iframe → `sandbox="allow-scripts"` (non-interactive;
  never `allow-same-origin`).
- `select-and-edit/overlays.ts` and `select-and-edit/utils.ts` (`describeElementContext`)
  are **unchanged and still unit-tested**; the bridge carries a hand-kept plain-JS
  mirror of their logic (it can't import TS into an injected string). Noted as a
  follow-up de-duplication.

**Files changed.**
- `frontend/src/components/preview/preview-bridge.js` (new)
- `frontend/src/components/preview/previewMessaging.ts` (new)
- `frontend/src/components/preview/PreviewComponent.tsx` (rewritten)
- `frontend/src/components/variants/Variants.tsx`
- `frontend/src/store/app-store.ts`
- `frontend/src/App.tsx`
- `frontend/src/store/project-store.test.ts`

**Tests added.** No new *unit* test file (the selection logic moved into an
injected script that jest's node env can't exercise); covered by browser
verification below. `project-store.test.ts` updated to the new selection shape and
still passes.

**Tests run.** `tsc --noEmit` clean; `pnpm test` 42 passed; `pnpm lint` unchanged
(19/6); `pnpm build` passes.

**Browser verification** (`playwright-cli`, `http://localhost:5180`).
- App loads, **0 console errors**.
- Import an HTML page → preview **renders** (Tailwind CDN executes) — no regression.
- `#preview-desktop` now has the sandbox attribute; from the host,
  `iframe.contentWindow.origin` and `.location.href` both throw `SecurityError`
  (opaque origin — the page cannot reach host storage). `iframe.contentDocument`
  is `null` to the host.
- **Select-and-edit still works**: enter mode → click the `<h1>` in the preview →
  the bridge draws the `<h1>` overlay, the sidebar shows "Selected: `<h1>`", and
  the input switches to "Describe changes for the selected `<h1>` element…".
- "Refresh Preview" re-renders correctly; the bridge is re-injected once
  (idempotent guard).
- Screenshots: `b1-import-preview.png`, `b1-selectmode.png`, `b1-after-refresh.png`.

**Security impact.** Closes SF-1 / SF-2 at the Phase 1 level: sandboxed generated
code can no longer read the host origin, its storage, or its DOM. This is the
"quick win" from spec FR-B1/B2; the full execution-isolation tier (running
generated servers, network egress, the backend `--no-sandbox` browser) remains
**Phase 6** and is still documented as unsafe-until-then.

**Migration implications.** `selectedElement` consumers must use the serialized
shape (`{ tagName, outerHTML, context }`), not a DOM node. Any future preview
feature must go through the postMessage channel, not cross-frame DOM access.

---

### R2 — CORS wide open (audit SF-3 / KF-5)

**Problem.** `main.py` set `allow_origins=["*"]` with `allow_credentials=True`
(invalid per the CORS spec and permissive). Verified live: a preflight from
`https://evil.example` was reflected with credentials allowed.

**Root cause.** Upstream default for a zero-config local tool.

**Change.** CORS now uses an explicit allow-list from
`settings.cors_allowed_origins` (env `CORS_ALLOWED_ORIGINS`, comma-separated).
Default = the local dev origins (`localhost` / `127.0.0.1` on `:5173` and `:5180`).
No wildcard; no production domain hard-coded. `allow_credentials=True` is now
safe because the origin list is explicit.

**Files changed.** `backend/main.py`, `backend/config.py` (the
`cors_allowed_origins` setting), `backend/.env.example` (new).

**Tests added.** `backend/tests/test_http_security.py`:
`test_cors_allows_configured_dev_origin`, `test_cors_rejects_unlisted_origin`,
`test_cors_preflight_from_unlisted_origin_is_not_allowed`.

**Tests run.** `pytest` 307 passed; `pyright` clean.

**Browser / curl verification.** `Origin: http://localhost:5180` →
`access-control-allow-origin: http://localhost:5180`; `Origin: https://evil.example`
→ **no** ACAO header. Frontend on `:5180` continues to work through the Vite proxy
(the browser only ever talks to the frontend origin).

**Security impact.** Closes SF-3. Other environments set `CORS_ALLOWED_ORIGINS`.

**Migration implications.** Deployments that serve the SPA from a non-default
origin must set `CORS_ALLOWED_ORIGINS`.

---

### R3 — Unauthenticated eval / agent-run / telemetry endpoints (audit SF-4 / KF-6)

**Problem.** `/evals/*`, `/eval-sets*`, `/eval-sessions*`, `/prompt-reports*`,
`/agent-runs*`, `/models`, `/output_folders`, `/run_evals*` were reachable with no
authentication and leaked absolute host filesystem paths; `/run_evals` can spend
money.

**Root cause.** No auth layer anywhere in the backend.

**Change.** A minimal **operator gate** (`backend/operator_gate.py`), applied as a
router-level dependency in `main.py` to the `evals`, `eval_sets`,
`prompt_reports`, and `agent_runs` routers. Policy (spec FR-B4/B5):
- `OPERATOR_ENDPOINTS_PUBLIC=true` → gate disabled (local-dev escape hatch);
- else if `OPERATOR_TOKEN` is set → caller must send `X-Operator-Token: <token>`
  (constant-time compare) — 401 otherwise;
- else → **403** (secure default: closed until configured).

This is **explicitly not** authentication/authorization. It is a stopgap boundary
only. The real per-user / per-org permission model is Phase 2.

**Files changed.** `backend/operator_gate.py` (new), `backend/main.py`,
`backend/config.py` (`operator_token`, `operator_endpoints_public`),
`backend/.env.example`.

**Tests added.** `backend/tests/test_http_security.py`:
`test_operator_endpoints_closed_by_default`, `test_public_endpoints_still_open`,
`test_operator_gate_requires_token`, `test_operator_gate_public_escape_hatch`.

**Tests run.** `pytest` 307 passed; `pyright` clean.

**Browser / curl verification.** `GET /agent-runs` → **403** with an actionable
message; `GET /api/capabilities` and `GET /` → **200** (public routes
unaffected). Startup logs the gate status.

**Security impact.** Closes SF-4's "accidental unrestricted exposure". Note: the
eval UI pages (`/evals/*` in the SPA) were already non-functional via `pnpm dev`
(audit KF-3, Vite proxy does not forward those paths) so gating them regresses no
working feature. Wiring the proxy + a real admin role is a later Phase 1 / Phase 2
item.

**Migration implications.** To use the internal eval tooling locally, set
`OPERATOR_ENDPOINTS_PUBLIC=true` **or** `OPERATOR_TOKEN=...` in `backend/.env`.

---

### R4 — Configuration boolean truthiness bugs (audit SF-8)

**Problem.** `IS_PROD = os.environ.get("IS_PROD", False)` and
`IS_DEBUG_ENABLED = bool(os.environ.get("IS_DEBUG_ENABLED", False))` — the string
`"false"` (and `"0"`) evaluated to **true**.

**Root cause.** `bool()` of any non-empty string is `True`.

**Change.** A strict parser `env_bool(name, default)` in `backend/config.py`:
only `1/true/yes/on/y/t` → `True`; `0/false/no/off/n/f`/empty/unset → `False`;
**anything else raises `ValueError`** so a typo fails fast. `IS_PROD`,
`IS_DEBUG_ENABLED`, `PROMPT_REPORTS_ENABLED` and all future flags use it. Sibling
helpers `env_int` / `env_float` / `env_list` / `env_str` added for the same
fail-fast discipline.

**Files changed.** `backend/config.py`.

**Tests added.** `backend/tests/test_env_bool.py` (11 test functions incl.
parametrised token table, garbage → `ValueError`, `"false"` → `False`).

**Tests run.** `pytest` 307 passed; `pyright` clean.

**Security impact.** A deployment that set `IS_PROD=false` expecting dev behaviour
was actually in prod mode (and vice-versa). Now correct.

**Migration implications.** Any env var previously relying on "non-empty = true"
must use a recognised token; an unrecognised value now aborts startup with a
clear message.

---

### R5 — Typed configuration foundation (spec FR-C1..C6)

**Problem.** Configuration was scattered `os.environ.get(...)` calls across
`config.py`, `routes/design_systems.py`, `evals/config.py`,
`fs_logging/prompt_reports.py`, etc., with no validation and the truthiness bugs
above.

**Change.** `backend/config.py` rewritten around a validated `pydantic.BaseModel`
`Settings` (frozen), built once at import via `Settings.from_env()`:
- every value typed, with a documented default or explicit requirement;
- validators: `log_level` ∈ {DEBUG,INFO,WARNING,ERROR,CRITICAL},
  `openai_base_url` must be http(s), numeric bounds on variant counts / cost;
- invalid config raises at import → **fail fast** (spec FR-C4);
- **backward compatible**: the old module-level names (`OPENAI_API_KEY`,
  `IS_PROD`, `NUM_VARIANTS`, `GENERATION_MAX_COST_USD`, …) are still exported,
  now sourced from `settings`, so no other file's imports changed.
- New settings added for this batch: `cors_allowed_origins`, `operator_token`,
  `operator_endpoints_public`, `log_level`, `log_format`.

**Decision — `pydantic` v2 `BaseModel`, not `pydantic-settings`.** `pydantic` v2
is already a dependency; `pydantic-settings` is not, and this batch adds no new
runtime dependency (per the brief's "don't add deps unless required" and to keep
the change offline-safe). The env-reading layer is a thin set of helpers. Swapping
to `pydantic-settings` later is mechanical. *Proposed for TECHNICAL_DECISIONS.*

**Not migrated this batch (documented remaining scattered access):**
`evals/config.py` (`EVALS_DIR` — monkeypatched by two tests),
`routes/design_systems.py` and `routes/screenshot.py` local `os.environ` reads,
`fs_logging/*` reading `config.PROMPT_REPORTS_ENABLED` (works — it's a bool now).
These move to `settings` in a later batch.

**Files changed.** `backend/config.py`, `backend/.env.example` (new).

**Tests added.** `backend/tests/test_env_bool.py`
(`test_settings_from_env_defaults`, `test_settings_from_env_overrides`,
`test_settings_rejects_bad_values`).

**Tests run.** `pytest` 307 passed; `pyright` clean (new module: 0 warnings).

**Migration implications.** New config belongs in `Settings`; `from config import
settings` is the preferred access. `backend/.env.example` documents every
supported variable.

---

### R6 — Structured logging + request/trace correlation (audit SF-10 / KF-1 / KF-2; spec FR-D1..D8)

**Problem.** ~105 `print()` sites, no structured logging, no correlation ids.
Worse: `utils.print_prompt_preview` printed box-drawing characters on the
generation hot path and the screenshot-preview startup probe printed them in its
error handler — on a cp1252 stdout (Windows default, or any byte pipe) this
raised `UnicodeEncodeError`, which **crashed all generation** (KF-1) and **crashed
backend startup when Chromium was absent** (KF-2).

**Root cause.** Unstructured `print` of non-ASCII to a non-UTF-8 stream, with the
exception propagating out of request/lifespan handlers.

**Change.**
- **`backend/logging_config.py` (new)** — one configured `app` logger; structured
  output (`console` key=value default, or `json`); level from `settings.log_level`.
  The handler stream is forced to UTF-8 with `errors="backslashreplace"` so
  **logging can never raise on content**. uvicorn's loggers are routed through the
  same handler. A `contextvars`-based `request_id` is injected into every record
  by a filter; helpers `request_context()`, `new_request_id()`, `get_logger()`.
- **`backend/request_context.py` (new)** — `RequestContextMiddleware` assigns each
  HTTP request a correlation id (accepted from a trusted `X-Request-ID` /
  `X-Correlation-ID` header, else minted) and echoes it as the `X-Request-ID`
  response header.
- **`routes/generate_code.py`** — the WebSocket handler binds a `request_context`
  for the whole generation session (HTTP middleware doesn't run for WS). All 21
  `print()` calls replaced with structured `logger.*` calls carrying `variant`,
  `stack`, `models`, etc. The crashy `print_prompt_preview(...)` → `log_prompt_preview(logger, ...)`
  which only renders at DEBUG and never raises. The misleading
  "Error assembling prompt. Contact support at support@getwhimsyworks.com"
  message (audit SF-9) is replaced with "Error assembling the prompt for this
  request. Check the backend logs for details." and the real exception is now
  `logger.exception`-logged instead of swallowed.
- **`utils.py`** — `_safe_print()` (never raises on encoding); `print_prompt_summary`
  / `print_prompt_preview` / `pprint_prompt` route through it; new
  `log_prompt_preview()` for the request path.
- **`preview_screenshot/playwright_backend.py`** — probe logs via the safe logger
  with `exc_info` instead of `print(exc)`; `main.py` startup probe wrapped so it
  is **never fatal**.
- **`agent/engine.py`, `agent/tools/runtime.py`, `agent/tools/screenshot_preview.py`,
  `agent/tools/extract_assets.py`, `codegen/utils.py`** — the remaining hot-path
  `print()` calls (budget-abort, tool failures, HTML-extract fallback) migrated to
  structured `logger.*`.
- **`main.py`** — `configure_logging()` at import; startup config logged
  structurally.

**Not migrated this batch (deliberately, per the brief):**
`routes/export.py` (9), `routes/agent_runs.py` (1), `fs_logging/*` (11),
`agent/providers/*` deep debug dumps (mostly `IS_DEBUG`-gated), `image_generation/*`
timing prints, and `evals/*` + `start.py` + `run_image_generation_evals.py`
(intentional CLI/script stdout). Categorised list in the appendix. These are
lower-risk and follow in later batches.

**Files changed.** `backend/logging_config.py` (new),
`backend/request_context.py` (new), `backend/main.py`, `backend/utils.py`,
`backend/routes/generate_code.py`, `backend/agent/engine.py`,
`backend/agent/tools/runtime.py`, `backend/agent/tools/screenshot_preview.py`,
`backend/agent/tools/extract_assets.py`, `backend/codegen/utils.py`,
`backend/preview_screenshot/playwright_backend.py`.

**Tests added.** `backend/tests/test_logging_config.py` (structured record carries
`request_id` + extras; `request_context` binds/clears; idempotent
`configure_logging`; `_safe_print` / `print_prompt_preview` never raise).
`backend/tests/test_http_security.py`: `test_response_carries_request_id`,
`test_request_id_from_inbound_header_is_echoed`. Existing `test_prompt_summary.py`
(7 tests) still passes — box output behaviour preserved on a UTF-8 stream.

**Tests run.** `pytest` 307 passed; `pyright` 0 errors / 36 warnings (unchanged).

**Browser / probe verification.**
- Backend started **without `PYTHONUTF8=1`**: starts cleanly, structured logs,
  Chromium probe non-fatal.
- WS probe: text/create with no keys now returns the correct
  **"No OpenAI, Anthropic, or Gemini API key found…"** (previously the
  `UnicodeEncodeError`-induced "Error assembling prompt / whimsyworks"). Invalid
  stack / input-mode errors unchanged. Close code `4332` unchanged.
- In-browser: text generation with no keys shows the correct provider-key error,
  Retry button, app recoverable.
- `X-Request-ID` present on HTTP responses and echoed from an inbound header.

**Security impact.** Removes the crash-the-process failure mode (availability).
Structured logs do not include secrets (credential-source logs record only the
key *name*, e.g. `openAiApiKey`, never the value). Correlation groundwork is in
place for later AI/job tracing (spec FR-D7).

**Migration implications.** New backend code MUST use `get_logger(...)` — no new
`print`. `LOG_LEVEL` / `LOG_FORMAT` are env-configurable. The generation error
copy changed (no functional change to the event contract).

---

### R7 — Stale `frontend/Dockerfile` (audit finding; TECHNICAL_DECISIONS A10 area)

**Assessment (evidence from the repo).**
- The Dockerfile used `yarn install` / `yarn dev` and `COPY package.json yarn.lock`.
- **No `yarn.lock` exists** anywhere in the repo; **`frontend/pnpm-lock.yaml` exists**
  (301 KB); `package.json` pins `"packageManager": "pnpm@10.32.1"`.
- It **is still referenced**: `docker-compose.yml` builds the `frontend` service
  from it, and `README.md` documents `docker-compose up -d --build`.

**Conclusion:** broken but relevant → **repaired**, not deleted.

**Change.** `frontend/Dockerfile` now: `corepack enable` (uses the pinned pnpm),
`COPY package.json pnpm-lock.yaml`, `pnpm install --frozen-lockfile`,
`CMD ["pnpm", "dev", "--host", "0.0.0.0"]`.

**Files changed.** `frontend/Dockerfile`.

**Tests added.** None (Docker build not run in CI yet; a container-build check is a
CI-batch item). Verified by inspection: paths/lockfile now exist, commands match
the repo's package manager.

**Security impact.** None directly; removes a broken build path.

**Migration implications.** `backend/Dockerfile` (poetry 1.8, python 3.12.3) was
**not** changed — the audit only flagged the frontend one and it builds. Pinning
Python 3.12 for dev/CI (TECHNICAL_DECISIONS D6) is a CI-batch item.

---

## Documentation updated this batch

- `docs/REMEDIATION_LOG.md` (this file, new).
- `docs/TECHNICAL_DECISIONS.md` — D1/D6/D10 area unchanged; **added** *PROPOSED*
  D11 (typed config on `pydantic` BaseModel), D12 (operator gate), D13 (structured
  logging), and marked the CORS / boolean / preview-sandbox items as **decided
  (Batch 1)**.
- `docs/LG_TELECOMS_APP_BUILDER_ARCHITECTURE.md` — §3.8 (security boundaries) and
  §3.9 (observability) updated to reflect the sandboxed preview, restricted CORS,
  operator gate, and structured logging now in place.
- `docs/LOCAL_DEVELOPMENT.md` — §2 (env vars) updated with the new settings;
  note that `PYTHONUTF8=1` is **no longer required** for generation; operator-gate
  instructions added.
- `backend/.env.example` (new) — documents every supported backend setting.

## Appendix — `print()` inventory categorisation (for later batches)

| Category | Files | Status |
|---|---|---|
| Generation hot path (backend application logging) | `routes/generate_code.py` (21), `agent/engine.py` (1), `agent/tools/runtime.py` (2), `agent/tools/screenshot_preview.py` (1), `agent/tools/extract_assets.py` (1), `codegen/utils.py` (1), `utils.py` box-print helpers | **migrated (R6)** |
| Startup diagnostics | `main.py` (1), `preview_screenshot/playwright_backend.py` (2) | **migrated (R6)** |
| Non-hot routes | `routes/export.py` (9), `routes/agent_runs.py` (1) | deferred → later batch |
| Filesystem logging subsystem | `fs_logging/agent_runs.py` (9), `fs_logging/prompt_reports.py` (2), `debug/DebugFileWriter.py` (1) | deferred → later batch |
| Provider adapters (mostly `IS_DEBUG`-gated dumps / timing) | `agent/providers/openai.py` (1), `agent/providers/gemini.py` (3), `agent/providers/anthropic/provider.py` (1), `agent/providers/anthropic/image.py` (1), `image_generation/generation.py` (2) | deferred → later batch |
| Intentional CLI / scripts / eval tooling stdout | `start.py` (1), `run_image_generation_evals.py` (3), `evals/runner.py` (16), `evals/asset_extraction_benchmark.py` (7), `evals/core.py` (1), `evals/sets.py` (1) | **left as-is** (intentional output) |

## Known follow-ups created by this batch

1. De-duplicate `preview-bridge.js` overlay/context logic vs.
   `select-and-edit/overlays.ts` + `utils.ts` (kept as the tested reference).
2. `select-and-edit/overlays.ts` is now unused by production code (only its test)
   — decide keep-as-reference vs. remove with its test.
3. Migrate the remaining scattered `os.environ` reads (`evals/config.py`,
   `routes/design_systems.py`, `routes/screenshot.py`) into `Settings`.
4. Migrate the deferred `print()` categories above.
5. Modernise `@app.on_event("startup")` → lifespan handlers (FastAPI deprecation
   warning, pre-existing).
6. Wire the Vite proxy for the operator-gated paths + a real admin role (Phase 1
   CI/Phase 2).

---

## Batch 2 — 2026-09-02

**Scope (from the brief):** CI foundation; PostgreSQL + Alembic foundation;
Redis foundation; worker architecture; job model; WebSocket transition
preparation; observability into the new infrastructure. **Explicitly NOT in this
batch:** migrating generation onto the queue, the AI model registry,
authentication, projects/workspaces, billing, Application IR, the Phase 6
sandbox, any UI change.

### Green baseline confirmed before starting

| Check | Result |
|---|---|
| `backend pytest` | 307 passed |
| `backend pyright` | 0 errors, 36 warnings |
| `frontend pnpm test` | 42 passed, 6 skipped |
| `frontend pnpm lint` | 19 errors, 6 warnings (pre-existing, KF-9) |
| `frontend pnpm build` | PASS |

### Post-batch check results

| Check | Result | Delta |
|---|---|---|
| `backend pytest` (infra up, `REQUIRE_INFRA=1`) | **351 passed** | +44 new, 0 regressions |
| `backend pytest` (no infra) | **335 passed, 16 skipped** | infra tests skip gracefully |
| `backend pyright` | **0 errors, 36 warnings** | unchanged |
| Alembic `upgrade → downgrade base → upgrade` | **clean round trip** | new |
| `frontend pnpm test` | 42 passed, 6 skipped | unchanged |
| `frontend` lint (ratchet) | **19 err / 6 warn == baseline → PASS** | policy added |
| `frontend pnpm build` | **PASS** | unchanged |

### Dependencies added

`sqlalchemy[asyncio] 2.0.52`, `asyncpg 0.31.0`, `alembic 1.19.1`, `arq 0.28.0`
(pulls `redis 5.3.1`, `hiredis`, `mako`, `markupsafe`, `pyjwt`). `poetry.lock`
updated.

---

### R8 — CI foundation (audit KF-9; TECHNICAL_DECISIONS D10)

**Problem.** No CI. `pnpm lint` is red on 19 inherited errors, so a naive gate
would either stall the project or invite blanket suppression.

**Change.** `.github/workflows/ci.yml` — two jobs on `ubuntu-latest`, triggered on
PRs and pushes to `main` / the foundation branch, with `concurrency`
cancel-in-progress:

* **backend** — Python **3.12**, Poetry **1.8.5** (pinned), `poetry install`
  (in-project `.venv`, cached on `poetry.lock` hash); `poetry run pyright`;
  Alembic `upgrade → downgrade base → upgrade` against a fresh Postgres service
  container (spec FR-E6); `poetry run pytest` with `REQUIRE_INFRA=1` +
  `DATABASE_URL` / `REDIS_URL` pointing at **postgres:16** and **redis:7**
  service containers (so CI genuinely exercises the stack, not the skip path).
* **frontend** — Node **22**, pnpm **10.32.1** via `corepack` (from
  `packageManager`), `pnpm install --frozen-lockfile` (pnpm store cached on the
  lockfile hash), `pnpm test`, `pnpm build`, and the **lint ratchet**.

**Lint ratchet policy** (`frontend/scripts/lint-ratchet.mjs` +
`frontend/.lint-baseline.json`, `pnpm run lint:ratchet`): prints the full eslint
report (nothing hidden); **fails** if the error or warning count *exceeds*
`.lint-baseline.json` (`{maxErrors: 19, maxWarnings: 6}`) — i.e. a real
regression; **passes with a reminder** to lower the baseline when the real count
drops. The gate ratchets toward 0/0 as inherited debt is paid down. `pnpm lint`
(the strict `--max-warnings 0` command) is kept for developers who want the raw
list.

**Files created.** `.github/workflows/ci.yml`, `frontend/scripts/lint-ratchet.mjs`,
`frontend/.lint-baseline.json`. **Modified.** `frontend/package.json` (adds
`lint:ratchet`).

**Security.** No secrets in the workflow. The Postgres/Redis credentials are
non-secret throwaway values for ephemeral CI service containers. Provider API
keys are not needed (tests mock/skip). Not yet verified on a real GitHub run
(no push this batch) — the commands mirror what was run locally.

**Local pin note.** CI pins Python 3.12; the local dev env is still 3.13 (the
working `backend-*-py3.13` venv). Pinning 3.12 locally (TECHNICAL_DECISIONS D6)
is a follow-up so as not to disrupt the working env mid-batch.

---

### R9 — PostgreSQL + Alembic foundation (spec FR-E1..E9; D1)

**Change.**
* **`docker-compose.yml`** rewritten: `postgres:16-alpine` and `redis:7-alpine`
  as top-level services with health checks, named volumes (`pgdata`,
  `redisdata`), and **loopback-only** host ports (`127.0.0.1:5435→5432`,
  `127.0.0.1:6379→6379`); all credentials are env-overridable non-secret
  defaults. Host port 5435 avoids collisions with other local Postgres
  instances. The app images (`backend`, `worker`, `frontend`) moved behind a
  `--profile app` so `docker compose up -d postgres redis` starts *just* infra.
* **`backend/db/`** — an async SQLAlchemy 2.0 layer: `Base` (declarative),
  `engine.py` (lazy async engine with `pool_pre_ping`, `session_scope()`
  transactional context manager that commits/rolls-back/closes, `dispose_engine()`,
  and `check_database()` — a non-fatal probe returning `ok` / `error` (reason
  only, **no connection string**) / `disabled`). The DB is **optional**: no
  `DATABASE_URL` → the app still starts and the sync generation path works;
  `/health` reports `database: disabled`.
* **Alembic** — `backend/alembic.ini`, `backend/migrations/env.py` (async,
  reads the URL from the typed settings — **no credentials in a committed
  file**; exits with a clear message if `DATABASE_URL` is unset),
  `script.py.mako`, and **one baseline migration**
  (`6af9c92e5d30_baseline_jobs_infrastructure_table.py`) creating **only** the
  `jobs` infrastructure table (spec FR-E7). No `users` / `organizations` /
  `projects` / `workspaces` / billing tables.
* **`config.py`** — `database_url` (optional; `postgresql://` normalised to
  `postgresql+asyncpg://`; rejected if not a postgres/sqlite-async URL).
* **`GET /health`** (`backend/routes/health.py`) — reports
  `{status, checks:{database, redis}, job_queue_enabled}`; `status` is
  `degraded` only when a *configured* dependency errors (a `disabled` DB is a
  valid current-phase state). Never returns a URL. `GET /` liveness string
  unchanged.

**Tests added.** `tests/test_db_foundation.py` (check_database disabled/ok/error,
`get_engine` raises when unset, `session_scope` commit + rollback, jobs table
exists after migration), `tests/test_infra_config.py` (URL normalisation /
rejection / optionality; Alembic scaffold present; single head; no domain
tables), `tests/test_health_endpoint.py` (shape, no leak, degraded logic, `/`
unchanged).

**Verification.** Locally against the compose Postgres: `check_database()` →
`ok`; `alembic upgrade head` → `alembic current` shows head → re-upgrade no-op →
`downgrade base` → `upgrade head` all clean. Backend `/health` →
`{"status":"ok","checks":{"database":"ok","redis":"ok"}}`; with no `DATABASE_URL`
→ `{"status":"ok","checks":{"database":"disabled","redis":"ok"}}`.

**Security.** No credentials committed (compose defaults are non-secret dev
values; `.env.example` documents overrides; Alembic reads from settings). Host
ports bound to `127.0.0.1` only.

---

### R10 — Redis foundation (spec FR-F1)

**Change.** `redis:7-alpine` compose service (health check, `appendonly no`,
loopback port). `backend/redis_client.py` — a process-wide async client +
`check_redis()` non-fatal PING probe (never returns the URL). `config.py`
`redis_url` (default `redis://127.0.0.1:6379/0` — explicit IPv4 because
`localhost` resolves to `::1` first on Windows and the container binds IPv4).

**Tests added.** `tests/test_redis_and_events.py` (check_redis ok/error; event
channel publish/subscribe round trip; publish-with-no-subscriber returns 0).

**Verification.** `check_redis()` → `ok` against the compose Redis; error path
returns `RedisStatus("error", ...)` without raising.

---

### R11 — Worker architecture (spec FR-F2; DEP-7 / A-4 — **D3 ratified**)

**Decision — arq.** DEP-7 left the runner open (Celery / Dramatiq / arq). The
generation engine is **fully async** (`AgentEngine.run()` awaits;
`asyncio.gather` fans out variants). **arq** is asyncio-native (the worker can
`await` the existing engine directly with zero sync/async bridging), Redis-only
(already required), minimal, and pydantic-family. Celery / Dramatiq are
sync-first and would force `asgiref`/thread bridging of the async engine —
more moving parts, worse fit. *Ratifies TECHNICAL_DECISIONS D3.*

**Change.** `backend/worker.py` — an arq `WorkerSettings` started with
`poetry run arq worker.WorkerSettings`:
* connects to Redis; `on_startup` builds a `JobService` + `JobEventChannel`,
  `on_shutdown` closes them and disposes the DB engine (clean shutdown);
* a `ping` health task; a generic `execute_job(ctx, job_id)` task that looks up
  the persisted job, runs the registered handler for its `job_type`, drives the
  lifecycle (`mark_running` → `mark_succeeded` / retry / `mark_failed`), and
  respects a prior cancellation;
* **arq-native bounded retries** (`max_tries = JOB_MAX_ATTEMPTS`, default 3,
  with backoff); after the last attempt the job is `failed` with a short error
  summary;
* `job_timeout = JOB_TIMEOUT_SECONDS` (default 900) — the watchdog for a stuck
  job (spec JL-4);
* an **explicit in-process handler registry** `JOB_HANDLERS` — the only handler
  this batch registers is `noop` (used by tests). **No generation handler, no
  shell/exec/Docker handler.** Generation moves onto the worker next batch.

**Files created.** `backend/worker.py`.

**Tests added.** `tests/test_worker.py` (identity default/configured; registry
is exactly `{"noop"}`; `ping`; `execute_job` success / missing job / unknown
type / retry-then-fail / respects prior cancellation; startup+shutdown clean).

**Verification (real worker + Redis + Postgres).** `arq worker.WorkerSettings`
starts and logs `worker started`. Enqueued: `ping` → `{pong, worker, echo}`; a
persisted noop job → `succeeded` (attempt 1); a job set to fail twice
(`max_attempts=3`) → **`succeeded` on attempt 3** (arq re-enqueued with 5s/10s
backoff); a job that always fails (`max_attempts=2`) → **`failed` after attempt
2** with the error summary captured. Every transition logged with `job_id`,
`request_id`, `worker`, `job_type`, `status`, `attempt`.

**Security.** The worker executes **no generated code** and has no shell / Docker
/ subprocess access. Handlers are a closed registry.

---

### R12 — Job model + lifecycle (spec JL-1..JL-9; DR-2; FR-E7 / FR-F15)

**Change.**
* **`backend/jobs/models.py`** — the `jobs` table (SQLAlchemy ORM):
  `id` (uuid), `job_type`, `status` (`queued | running | succeeded | failed |
  cancelled`), `created_at` / `started_at` / `finished_at`, `attempt` /
  `max_attempts` (retry metadata), `error` (short summary — **never** payloads /
  secrets), `request_id` (Batch 1 correlation), `worker`, `params` (JSONB —
  non-sensitive), `result_ref` (a pointer to where output lives, **never** the
  output). **No tenant / user / org / billing columns** — a test asserts this.
* **`backend/jobs/service.py`** — `JobService`: `create` (→ `queued`),
  `mark_running` (→ `running`, `attempt++`, `started_at`), `mark_succeeded`
  (clears any transient error, sets `result_ref` + `finished_at`),
  `mark_failed`, `mark_cancelled`, `requeue_for_retry` (`running → queued`,
  clears timing, keeps `attempt`), `get`, `list_recent`. A `LEGAL_TRANSITIONS`
  table enforces the state machine (spec JL-2) — illegal moves raise
  `InvalidJobTransition`. Each transition is logged structurally and (when a
  channel is attached) published as a `JobEvent`.
* **`backend/jobs/events.py`** — `JobEvent` (json-serialisable) +
  `JobEventChannel` (Redis pub/sub, one channel per job id). **This is the
  transition boundary** — see R13.

**Tests added.** `tests/test_jobs_model.py` (enum values, transition table
matches spec, `InvalidJobTransition`, `as_dict` shape + no tenant fields, event
round trip), `tests/test_job_service.py` (create/happy-path/failure/cancel/
illegal-transitions/retry-requeue/get+list — against real Postgres).

**Compatibility.** The `jobs` table is deliberately minimal and additive-only:
Phase 2 adds tenancy columns + a `project_id` FK via migration; nothing here
blocks that.

---

### R13 — WebSocket transition preparation (spec §6 / FR-F7)

**No behaviour change.** The existing `/generate-code` WebSocket is untouched and
still owns generation execution + event delivery.

**Boundary defined.** `JobEventChannel` (R12) is the seam between *job execution*
and *event delivery*:

```
  today            next batch (flag-on)
  -----            --------------------
  Client ──WS──▶ API ──▶ (in-process) generation      Client ──▶ API ──▶ Job Queue ──▶ Worker ──▶ generation
         ◀──WS── events (same socket)                        ◀──WS── events ◀── JobEventChannel ◀── Worker
```

* **Execution path (next batch):** API `JobService.create(...)` →
  `arq.enqueue_job("execute_job", job_id)` → worker runs a *generation* handler
  (added to `JOB_HANDLERS`) wrapping the existing `AgentEngine`.
* **Event path (next batch):** the worker publishes generation + lifecycle
  events to `JobEventChannel`; a WebSocket endpoint (or the flag-on mode of
  `/generate-code`) `subscribe`s to `jobs:events:<job_id>` and relays them, so
  the socket's lifetime no longer bounds the job (spec FR-F7/FR-F8). Terminal
  state is always readable from the `jobs` table (spec JL-7).

All of this is behind `JOB_QUEUE_ENABLED` (default **false**), so the sync path
stays the default until parity is proven (spec FR-F10).

---

### R14 — Observability into the new infrastructure (spec §7; Batch 1 groundwork)

Every job carries, in structured logs: `job_id`, `request_id` (bound from the
originating request via `request_context`), `worker` identity, `job_type`,
lifecycle transition (`queued|running|succeeded|failed|cancelled|retrying`), and
`attempt` / failure reason. The worker logs `worker started` / `worker stopped`
with the redacted Redis host (credentials, if any, stripped). Health checks log
only the exception *type* on failure, never the connection string.

**Not logged:** API keys, tokens, passwords, secrets, generated credentials,
job params beyond their keys, generated output. `error` is a truncated
`"<ExcType>: <message>"` summary.

**Test added.** `tests/test_logging_config.py` (Batch 1) already covers
request-id propagation; `tests/test_job_service.py` asserts the service emits on
each transition.

---

## Documentation updated this batch

- `docs/REMEDIATION_LOG.md` (this section).
- `docs/TECHNICAL_DECISIONS.md` — **D3 ratified → arq**; added C14 (Postgres +
  async SQLAlchemy + Alembic dev harness), C15 (Redis + job model + event
  channel), C16 (CI + lint ratchet), C17 (WebSocket transition boundary).
- `docs/LG_TELECOMS_APP_BUILDER_ARCHITECTURE.md` — §4.2 target topology annotated
  with what now exists; new §3.10 "Infrastructure foundation (Batch 2)".
- `docs/LOCAL_DEVELOPMENT.md` — new "Infrastructure stack" section (compose
  commands, Alembic, worker), env-var table extended, full-stack start commands.

## Known limitations / follow-ups from Batch 2

1. Generation is **not** on the queue — that is the next batch (one path, behind
   the flag, with parity + rollback protection).
2. CI is not yet verified on a real GitHub Actions run (no push this batch).
3. Local Python is still 3.13; pin 3.12 to match CI / upstream (D6).
4. `pyright` in CI runs under Python 3.12 — a first real run may surface
   version-specific findings to fix.
5. `alembic` autogenerate noise comments left in the baseline migration (cosmetic).
6. No job-status REST endpoint yet (spec API-5) — added with the generation
   migration next batch.
7. `@app.on_event` still used (now also for shutdown) — lifespan migration
   remains a follow-up.
8. The `jobs` table has no pruning/retention yet (spec DR-6) — follow-up.

---

## Batch 3 — 2026-09-02

**Scope (from the brief):** migrate **exactly one** generation path — the
smallest real one, **text → create** — onto the Redis/arq worker built in
Batch 2, proving the production architecture
`request → API → job → queue → worker → generation → events → WS → frontend`.
Everything else stays on the synchronous pipeline. **Explicitly NOT in this
batch:** the other generation paths, the model registry, auth, orgs/workspaces,
projects, billing, Application IR, sandbox execution, deployment, visual repair,
autonomous agents, full event sourcing, any UI redesign.

### Green baseline confirmed before starting

pytest 351 (infra) / 335+16-skipped (no infra) · pyright 0/36 · jest 42+6-skipped
· lint ratchet 19/6 · build PASS.

### Post-batch check results

| Check | Result | Δ |
|---|---|---|
| backend `pytest` (infra, `REQUIRE_INFRA=1`) | **360 passed** | +9, 0 regressions |
| backend `pytest` (no infra) | **338 passed, 22 skipped** | infra tests skip |
| backend `pyright` | **0 errors, 36 warnings** | unchanged |
| Alembic `upgrade → downgrade base → upgrade` | clean | unchanged (no new migration) |
| jest | **42 passed, 6 skipped** | unchanged |
| lint ratchet | **16 errors / 6 warnings** — baseline lowered 19→16 | 3 `no-explicit-any` in `generateCode.ts` annotated |
| `pnpm build` | **PASS** | unchanged |

**No new dependencies. No new database migration** — the Batch 2 `jobs` table +
a Redis event backlog cover generation-job metadata and reconnect state.

---

### R15 — Generation path migrated: **text → create**

**Why this path.** Smallest real generation flow: `inputMode="text"`,
`generationType="create"`, no source screenshots / video / asset extraction /
file-state / option-codes. It is `App.tsx::doCreateFromText`.

**What is queue-backed now** (only when `JOB_QUEUE_ENABLED=true`, default off):

```
Text-tab "Generate"
  → WS /generate-code  (QueuedGenerationMiddleware)
  → JobService.create("generation", params=<sanitised, NO keys>)   [Postgres]
  → arq pool.enqueue_job("execute_job", job_id)                    [Redis]
  → WS sends { type:"jobCreated", value:<job_id> } + "Queued..."
  ── (client may now disconnect; the job continues) ──
  → worker execute_job → JOB_HANDLERS["generation"] → run_generation(...)
  → worker publishes lifecycle + generation events to JobEventChannel [Redis]
  → WS relay subscribes, forwards events in the existing frontend vocabulary
  → terminal (succeeded → close 1000 / failed → error + close 4332)
```

Everything else (image / multi-image / URL / video / **update/edit**, and text→create
when the flag is off) is **unchanged** on the synchronous
`routes/generate_code.py` pipeline.

### R16 — Generation service adapter (no engine rewrite)

`backend/generation/`:

* **`variants.py`** — `AgenticGenerationStage` + `MessageType` **moved verbatim**
  from `routes/generate_code.py` (it already took a `send_message` callable, so
  it was never WS-coupled). Both paths now import it from here.
* **`model_selection.py`** — `select_variant_models(...)` **extracted** from
  `ModelSelectionStage._get_variant_models` (behaviour-preserving — the existing
  `test_model_selection.py` still passes). `generate_code.py`'s
  `ModelSelectionStage` now delegates to it.
* **`service.py`** — `run_generation(req, creds, emit) → GenerationOutcome`:
  builds the prompt, selects models, runs every variant, reports progress via
  `emit`. Raises `NonRetryableGenerationError` for deterministic failures.
* **`types.py`** — `GenerationRequest` (persisted params — **no secrets**),
  `ProviderCredentials` (**resolved from server config at execution time, never
  persisted/logged**), `GenerationEvent`, `GenerationOutcome`.
* **`job.py`** — `handle_generation_job(ctx, job)`: the arq handler. Emits
  generation events onto `JobEventChannel`; returns `eventlog:<job_id>` as the
  `result_ref` (the event backlog *is* the result).

### R17 — Job lifecycle (Batch 2 model, reused)

No schema change. `Job` (`queued → running → succeeded/failed`, `cancelled`
supported; retry = `running → queued`). Added `QUEUED → FAILED` for
un-runnable jobs. `execute_job` now:

* takes handlers as `(ctx, job)` (updated `noop` + tests);
* **classifies failures** — `NonRetryableGenerationError` / `ValueError` →
  straight to `FAILED`, **no retry** (spec §10: never retry missing
  credentials / bad input / deterministic errors); other exceptions → bounded
  arq retry then `FAILED`;
* records a **sanitised** `<ExcType>: <first line>` summary, ≤ 500 chars, no
  newlines / payloads / secrets.

### R18 — Event architecture (Redis, minimal)

`JobEventChannel` extended:

* every event gets a monotonic `seq` (`INCR jobs:seq:<id>`);
* every event is appended to a **TTL'd, capped Redis list** `jobs:eventlog:<id>`
  (2 h, 5000 max) — the durable backlog for late/reconnecting clients;
* `open_subscription(job_id)` subscribes **first**, then the caller `replay()`s
  the backlog and tails live events (`seq`-deduped) — no missed/duplicated
  events across the replay↔live boundary;
* generation events travel as `JobEvent(type="generation", payload=<frontend
  event>)`; lifecycle events as `type in {queued,running,succeeded,failed,
  cancelled,retrying}`.

Events carry only safe metadata + generated output (which is already exposed by
the existing `setCode` event). No secrets.

### R19 — API contract + WebSocket compatibility

* `/generate-code` WS: new `jobCreated` (first message, carries `job_id`) and
  `jobStatus` (`queued`/`running`/…) messages are **additive**;
  `variantCount` / `status` / `setCode` / `variantComplete` / `error` are
  preserved.
* **Reconnect:** the client re-opens the WS with `{"jobId": "<id>"}`; the relay
  replays the full backlog then tails. Handled transparently inside
  `frontend/src/generateCode.ts` on an unexpected drop (≤ 5 attempts, linear
  backoff); a completed/failed job replays and closes cleanly.
* **`GET /api/jobs/{job_id}`** (`routes/jobs.py`) — safe status
  (`job_id, job_type, status, created_at, started_at, finished_at, error,
  request_id`); never `params` / `worker` / `result_ref` / connection strings /
  stack traces. 404 for unknown, 503 if the job store is unconfigured.
* A **client disconnect never cancels the job** — the relay catches
  `WebSocketDisconnect` and returns; the worker is untouched.

### R20 — Frontend (minimal)

* `generateCode.ts` — refactored to a `connect(payload)` helper reused for the
  initial connection and reconnects; handles `jobCreated` / `jobStatus`; on an
  unexpected close with a known `jobId`, transparently re-attaches instead of
  failing. The spurious `toast.error` in the raw `ws "error"` handler was moved
  to the `close` handler so a transient drop doesn't toast.
* `App.tsx` — one added callback (`onJobCreated`) that logs the id to the
  execution console. **No UI redesign, no new components, no store changes.**
* `.lint-baseline.json` — lowered 19→16 (the 3 `no-explicit-any` in
  `generateCode.ts` are now explicitly `eslint-disable`d with intent).

### R21 — Observability

Every generation job log carries `request_id` (bound from the originating WS
request via `request_context`), `job_id`, `job_type`, `worker`, lifecycle
transition, `attempt`, and `has_server_key` (bool, never the key). Failures log
the exception **type** + sanitised summary. Verified in the live worker log —
the API request's `request_id` appears on the worker's `generation job starting`
/ `job running` / `job failed` lines.

### Tests added (`backend/tests/test_batch3_queued_generation.py`, 10 cases)

* **A** `build_generation_request` strips every secret key; `is_queued_text_create`
  gated by the flag + only text/create + not a reconnect; flag-off ⇒ sync path.
* **B** WS `/generate-code` with the flag on → `jobCreated` + persisted `queued`
  job of type `generation` + enqueued exactly once; **no secret in the params,
  the enqueue call, or the status endpoint**.
* **C+E** worker `execute_job` on a `generation` job with no server keys →
  `FAILED`, **attempt 1 (not retried)**, sanitised error, a client `error`
  event on the backlog, **no secret in the logs**.
* **C** `_relay` with a disconnected client → returns without touching the
  (still-`running`) job.
* **D** `resume_job` replays the backlog (incl. `setCode`) and closes 1000 for a
  succeeded job; `GET /api/jobs/{id}` returns only safe fields, 404 for unknown.
* Plus the `jobs/events` seq/backlog + `open_subscription` dedup tests, and
  `worker` handler-registry AST check (no `system`/`popen`/`eval`/`exec`/… in any
  handler).

### Security

* **No provider key** is placed in the job params, the Redis payload, the DB
  row, a WS message, a structured log, or the frontend. Browser-supplied keys
  are **stripped** by `build_generation_request`; the queued path uses
  **server-config keys only** (`ProviderCredentials.from_settings`). → **Batch 3
  limitation:** if you rely on browser-entered keys, the queued text→create path
  fails with the controlled "No API key" error. Per-tenant secret handoff is
  Phase 2.
* **The worker executes no generated code.** `JOB_HANDLERS = {noop, generation}`;
  `generation` calls the existing agent/provider layer only. No shell /
  subprocess / Docker / `eval` / `exec` added (AST-tested). The pre-existing
  `screenshot_preview` agent tool (headless `--no-sandbox` Chromium) is
  unchanged and still a Phase 6 concern.
* `GET /api/jobs/{id}` exposes no secrets, params, worker identity, or stack
  traces.

### Verification commands run

```
docker compose up -d postgres redis
cd backend && poetry run alembic upgrade head
DATABASE_URL=... REDIS_URL=... JOB_QUEUE_ENABLED=true poetry run uvicorn main:app --port 7001
DATABASE_URL=... REDIS_URL=... poetry run arq worker.WorkerSettings
cd frontend && pnpm dev --port 5180 --strictPort
# probes: scratchpad queued_probe.py (new + status + reconnect), disconnect_probe.py
# playwright-cli against http://localhost:5180
```

### Playwright / live results

* App loads, **0 console errors**.
* Text-tab "Generate" (flag on, no server keys): console logs
  `Generation queued as job <uuid>`; UI shows `Queued...` then the controlled
  **"No OpenAI, Anthropic, or Gemini API key found…"** error with a working
  **Retry** button — app stays fully usable.
* `GET /api/jobs/<id>` → `status: failed`, sanitised error, **no `params` /
  `worker`**.
* **Reconnect** (`{"jobId": <id>}`) → full backlog replayed
  (`jobCreated` → `jobStatus queued/running` → `error`) then clean close.
* **Disconnect independence** — client drops right after `jobCreated`; the
  worker still drives the job to a terminal state.
* Import → preview still renders in the sandboxed iframe (Batch 1 intact);
  `iframe.contentWindow.origin` → `SecurityError`.
* No real provider credentials were available; the **controlled failure path**
  was verified — **no successful AI generation was fabricated**.

---

## Documentation updated (Batch 3)

- `docs/REMEDIATION_LOG.md` (this section).
- `docs/TECHNICAL_DECISIONS.md` — C18 (text→create migrated), C19 (event backlog
  vs. a result table), C20 (queued path = server keys only).
- `docs/LG_TELECOMS_APP_BUILDER_ARCHITECTURE.md` — §3.11 "Queued generation
  (Batch 3)" + §4.2 topology annotation.
- `docs/LOCAL_DEVELOPMENT.md` — `JOB_QUEUE_ENABLED` + the full queued-path
  startup, reconnect behaviour, "what's still synchronous".
- `docs/ROADMAP.md` — Phase 1 progress note.

## Known limitations / follow-ups from Batch 3

1. Only **text→create** is queued. The other paths (image, multi-image, URL,
   video, **update/edit**) are still synchronous — later batches.
2. **Queued path ignores browser-entered provider keys** (uses server env only).
   Per-tenant secret handoff is Phase 2.
3. Reconnect survives a WS drop **within the session**; a full browser refresh
   still loses the client-side project (in-memory store — Phase 2). The job
   itself remains queryable via `/api/jobs/{id}`.
4. `run_generation` currently rejects a job as `FAILED` (non-retryable) if *all*
   variants fail; partial success (≥1 variant) succeeds. Fine-grained per-variant
   retry is out of scope.
5. Two `error` toasts on a failed queued job (friendly + sanitised terminal) —
   cosmetic.
6. CI's `backend` job does not yet start the worker / assert an end-to-end queued
   run — it exercises the units + service containers. A live-worker CI step is a
   follow-up.
7. Batch 2 follow-ups 2–8 still stand.

---

## Batch 4 — 2026-09-02

**Scope (from the brief):** complete the remaining Phase 1 infrastructure and
hardening — Python-3.12 consistency, a typed model registry, provider/config
cleanup, the FastAPI `lifespan` migration, job-lifecycle hardening + opt-in
pruning, queue failure-mode tests, CI hardening + a live queue smoke test, the
duplicate-error-toast fix, a security + logging review, then the full test /
Playwright / docs pass. **Explicitly NOT in this batch:** auth, orgs, projects,
billing, usage metering, user-owned keys, Application IR, sandbox execution,
deployment, migrating the other generation paths, any UI redesign. No
`/speckit-tasks` / `/speckit-implement`.

### Post-batch check results

| Check | Result | Δ |
|---|---|---|
| backend `pytest` (infra, `REQUIRE_INFRA=1`) | **621 passed** | +261 (mostly the 244 parametrised registry assertions) |
| backend `pyright` | **0 errors, 36 warnings** | unchanged (all pre-existing bs4/test warnings) |
| Alembic `upgrade → downgrade base → upgrade` + `alembic check` | clean, **no drift** | no new migration (retention is config-only) |
| jest | **44 passed, 6 skipped** (+`generateCode.test.ts`, 2 cases) | +2 |
| lint ratchet | **16 errors / 6 warnings** — at baseline | unchanged |
| `pnpm build` | **PASS** (`✓ built in ~29s`) | unchanged |

No new runtime dependencies. `poetry.lock` regenerated for `^3.12` (dropped the
`async-timeout` / `exceptiongroup` / `tomli` backports only).

---

### R17 — Python 3.12 consistency (D6 ratified)

`pyproject.toml` `python = "^3.12"`; new `backend/.python-version` (`3.12`);
`pyrightconfig.json` `"pythonVersion": "3.12"`; `Dockerfile`
`python:3.12-slim-bookworm`; CI already 3.12. **Local machines are not forced
off 3.13** — `^3.12` still admits it — but CI is the authority and always runs
3.12. CI + Dockerfile Poetry bumped **1.8.5 → 2.4.2** to match the committed
lock file (`lock-version = "2.1"`, which Poetry 1.8 cannot read).

### R18 — Typed model registry (`backend/model_registry/`)

`ModelEntry` (frozen) per model: provider, `api_name`, `display_name`,
capabilities, input modalities, status, `enabled`, `is_default`,
`reasoning_effort`, `context_window`, pricing ref. Enums `Provider` / `Modality`
/ `Capability` / `ModelStatus`. **Every value is derived** from `llm.py`,
`OPENAI_MODEL_CONFIG`, `ANTHROPIC_MODEL_CONFIG`, the Gemini api-name rules and
`costs.pricing` — nothing re-declared, so it cannot drift.

* `GET /api/models` → `frontend_model_catalog()`: `{providers, models[]}` where
  each model is `to_public_dict()` — **no `api_name`, no pricing, no keys**
  (51 models = 47 `Llm` + 4 Replicate tools; verified leak-free live).
* `agent/providers/factory.py` migrated to `provider_of(model)`.
* `generation/model_selection.py` drops registry-`enabled=False` models before
  cycling; raises `NoProviderCredentialsError` if that empties the candidate set.
* `tests/test_model_registry.py` — 244 assertions incl. api-name/provider parity
  vs. the legacy `get_openai_api_name` / `_get_anthropic_api_model_name` /
  `_get_gemini_api_model_name`, and a catalog-is-secret-free test.
* **Not in the registry:** API keys, user/org config, billing, usage accounting,
  marketplace — all Phase 2.

### R19 — Provider / config cleanup

Remaining direct `os.environ` reads in application code moved behind
`config.settings`: `evals/config.py` (`EVALS_DIR`), `routes/design_systems.py`
(`SCREENSHOT_TO_CODE_DATA_DIR`), `fs_logging/prompt_reports.py` (`LOGS_PATH` —
kept as a *live* override for ops + test isolation, documented in-code). No
secret is exposed through `/health`, `/api/models`, or any config endpoint; no
secret is logged.

### R20 — FastAPI `lifespan` (C22)

`@app.on_event("startup"/"shutdown")` → one `@asynccontextmanager lifespan()`.
Startup logs config + operator-gate status + runs the (non-fatal)
screenshot-preview probe; shutdown awaits `close_arq_pool()` → `dispose_engine()`
→ `close_redis()`. All `on_event` deprecation warnings gone; startup/shutdown
tests (`test_worker.py`, `test_db_foundation.py`, TestClient lifespans) green.

### R21 — Job lifecycle hardening + opt-in pruning (C23, C24)

* **Idempotent terminals:** `_transition` returns `(job, changed)`; *terminal →
  same terminal* is a no-op (no event emitted) rather than
  `InvalidJobTransition`. `mark_*` only emit when `changed`.
* **Crash re-acquire:** `RUNNING → RUNNING` is now legal so a fresh worker can
  pick up a job whose previous worker was killed pre-terminal; arq `max_tries`
  still bounds attempts. A crashed job is never reported `succeeded`.
* **Pruning:** `JobService.prune_terminal(retention_days, now=)` deletes only
  `succeeded`/`failed`/`cancelled` rows with `finished_at` older than the window
  — queued/running rows are untouchable. Driven by a daily arq `cron`
  (`prune_jobs`, 03:17) that self-disables unless `JOB_RETENTION_DAYS` is set
  (spec DR-6). No new DB column, no owner filter.
* Tests: `test_job_service.py` (+5 cases — idempotency, no cross-terminal,
  retention window, active-job safety, disabled no-op).

### R22 — Queue failure modes (`tests/test_batch4_queue_failure_modes.py`, 8 cases)

| Mode | Behaviour asserted |
|---|---|
| **A** Redis/pool unavailable | `start_queued_generation` catches the enqueue failure, marks the job `FAILED` (`QueueUnavailable: …`), sends **one** client `error` + closes 4332 — no hang, no dangling `QUEUED` |
| **B** worker down | job stays `QUEUED`, still fetchable via `JobService.get` / `/api/jobs/{id}`; API healthy |
| **C** worker starts after jobs exist | backlog job drains to `SUCCEEDED` |
| **D** handler raises | `FAILED` with a sanitised `"<ExcType>: <msg>"` (single line, ≤500 chars); secrets/paths in the message are not surfaced |
| **E** worker killed mid-job | job stays `RUNNING` (never falsely `SUCCEEDED`); a new worker re-acquires and completes it |
| **F** Redis reconnect | `JobEventChannel` + the arq pool rebuild a dropped client on next use; a real `ping` round-trips |

`start_queued_generation` also now guards `service.create` (DB down → clean
client error, no 500).

### R23 — CI hardening + live queue smoke test (C25 CI wiring)

* `alembic check` step added — fails the build on ORM/schema drift.
* `tests/test_queue_smoke.py` (2 cases): `JobService.create` → real arq
  `pool.enqueue_job` → Redis → a real `arq.worker.Worker(burst=True)` →
  `execute_job` → `noop` handler → terminal state in Postgres + the terminal
  event on the Redis backlog. **No AI provider touched.** Runs in CI because the
  `backend` job already has the service containers + `REQUIRE_INFRA=1`.
* `conftest._isolate_async_clients` now also nulls `queue_client._pool` and
  restores `preview_screenshot._available` between tests.

### R24 — One user-facing error on a failed queued generation (Batch 3 follow-up)

`routes/generation_relay._Forwarder` tracks `_error_sent`: when the worker has
already emitted a descriptive generation `error` event, the terminal `failed`
transition **does not** append a second (sanitised) `error` — it just closes
4332. If the worker never sent one, the terminal path supplies exactly one
sanitised message. Verified live: WS reconnect to a failed job replays
`jobCreated → jobStatus(queued) → jobStatus(running) → error ×1 → close 4332`.
Frontend: `src/generateCode.test.ts` (new) asserts exactly one `toast.error` for
that sequence and **no reconnect** after a 4332 close.

### R25 — Security review

Searched `subprocess` / `shell=True` / `os.system` / `Popen` / `eval(` / `exec(`
/ Docker socket / unrestricted FS / leaked env / secrets-in-logs / CORS / WS
origin / operator + debug endpoints.

* **No** `subprocess` / shell / `os.system` / `eval` / `exec` / Docker access in
  application code. The worker handler registry stays `{noop, generation}`
  (AST-tested).
* **Finding (fixed):** the `screenshot_preview` agent tool renders generated
  HTML in headless `--no-sandbox` Chromium — i.e. it *executes* untrusted
  markup/JS — and was reachable from the queued generation path (which runs in
  the worker). `worker._on_startup` now calls
  `preview_screenshot.disable_screenshot_preview()`, so the tool is not offered
  in worker context. The synchronous API process is unchanged (baseline
  behaviour preserved); a real sandbox for generated code remains Phase 6.
* CORS is an explicit allow-list (no wildcard); operator endpoints are gated
  (`require_operator`, closed by default); OpenAPI/docs disabled; `/health`,
  `/api/jobs/{id}`, `/api/models` leak no secrets or connection strings.
* `routes/export.py` keeps its existing SSRF guard (`is_public_http_url`,
  redirect cap, size + content-type checks) — its "asset skipped" diagnostics
  are now structured warnings.

### R26 — Logging review

Remaining runtime `print()`s migrated to the structured `app` logger:

| Area | What |
|---|---|
| `agent/providers/{base,openai,gemini,anthropic}` | `[TOKEN USAGE]` → `_log_token_usage(provider, model, usage, pricing)` — provider/model/counts/cost only, never prompt text or keys |
| `agent/providers/gemini.py` | MIME-detection warning, tool-image fetch failure → `logger.warning(exc_info=True)` |
| `agent/providers/anthropic/image.py` | image-processing timing → `logger.debug` |
| `fs_logging/agent_runs.py` (9), `fs_logging/prompt_reports.py` (2) | swallowed-exception diagnostics → `logger.warning(exc_info=True)` |
| `routes/export.py` (9), `routes/agent_runs.py` (1) | export/prune diagnostics → `logger.info` / `logger.warning` |
| `image_generation/generation.py` (2), `evals/core.py` (1), `evals/sets.py` (1), `debug/DebugFileWriter.py` (2) | runtime/operator-reachable → logger |

**Left as-is:** true CLI scripts (`evals/runner.py`, `evals/asset_extraction_benchmark.py`).
**Never logged:** API keys, auth headers, `DATABASE_URL` / `REDIS_URL`
credentials, full env, raw prompts. Exception info is `exc_info` /
truncated-summary only.

### Playwright / live results (full stack, `JOB_QUEUE_ENABLED=true`, no provider keys)

`docker compose` postgres+redis · `uvicorn main:app :7001` · `arq
worker.WorkerSettings` (`WORKER_NAME=pw-worker`) · `pnpm dev :5180` ·
`playwright-cli`.

1. App loads; **0 unexpected console errors** (only the pre-existing React-Router
   future-flag warnings + the deliberate controlled-failure `console.error`).
2. Text tab → "Generate" → console `Generation queued as job <uuid>`; worker log
   shows `job running` → `generation job starting` (`has_server_key=False`) →
   `job failed` (`NonRetryableGenerationError`, `retryable=False`, attempt 1) —
   **request_id propagated from the API to the worker**.
3. **Exactly one** error toast ("No OpenAI, Anthropic, or Gemini API key
   found…"), auto-dismissed; the four in-flight variant tiles resolve to the
   generic per-variant error card with a working **Retry** — no duplicate
   terminal notification, no raw exception/traceback in the UI.
4. `GET /api/jobs/<id>` → `status: failed`, sanitised error, only the safe
   fields (no `params` / `worker` / `result_ref`).
5. **Reconnect** (`{"jobId": <id>}`) → `jobCreated → jobStatus×2 → error ×1 →
   close 4332` (the `_error_sent` fix).
6. `GET /api/models` → 51 models, providers list, **no `api_name` / pricing**.
   `GET /api/capabilities` → `{"screenshot_preview": true}` (API process only).
7. WS drop mid-job leaves the worker running to a terminal state.
8. Import (HTML + Tailwind) → editor + preview render; preview `<iframe>`
   `sandbox="allow-scripts allow-forms allow-modals allow-popups
   allow-popups-to-escape-sandbox"` — **no `allow-same-origin`** (Batch 1
   intact). Variant tiles' iframes: `sandbox="allow-scripts"` only.
9. Export → `POST /api/export` 200 `application/zip` (valid archive).
10. Design systems → create / list / delete round trip via `/api/design-systems`.

**No successful AI generation was fabricated** — no provider credentials were
available; only the controlled-failure path was exercised.

---

## Documentation updated (Batch 4)

- `docs/REMEDIATION_LOG.md` (this section).
- `docs/TECHNICAL_DECISIONS.md` — D6 + D10 ratified; new C21 (derived model
  registry), C22 (lifespan), C23 (job-lifecycle hardening), C24 (opt-in
  retention), C25 (worker cannot render generated code); C12 logging-follow-through note.
- `docs/LG_TELECOMS_APP_BUILDER_ARCHITECTURE.md` — §3.12 "Model registry +
  hardening (Batch 4)"; topology note that text→create is the migrated path and
  all other generation is legacy/synchronous.
- `docs/LOCAL_DEVELOPMENT.md` — copy/paste full-stack start block, `alembic check`,
  `JOB_RETENTION_DAYS`, `/api/models`, health check.
- `docs/ROADMAP.md` — Phase 1 line items checked off; remaining Phase 1 limits +
  Phase 2 dependencies restated.

## Known limitations / follow-ups from Batch 4

1. Still only **text→create** is queued; image / multi-image / URL / video /
   **update-edit** remain synchronous (later phases).
2. Queued path uses **server** provider keys only (C20). Per-tenant secret
   handoff is Phase 2.
3. A job whose worker is killed mid-run is re-acquired on arq re-delivery, but
   there is **no independent watchdog/reaper** for a job whose worker vanished
   without arq ever re-queuing it — it stays `RUNNING` until `JOB_TIMEOUT_SECONDS`
   / a manual retry. A reaper is a later increment.
4. Retention pruning is time-based only (`finished_at` age); no per-count cap,
   no archival.
5. CI still has not run on a real GitHub Actions host (no push this batch).
6. The model registry has one status/enabled flag set per model at import time;
   there is no runtime toggle / admin surface (Phase 2).
7. `screenshot_preview` in the **synchronous** path still renders generated HTML
   in `--no-sandbox` Chromium — unchanged baseline, Phase 6 sandbox.
8. Batch 2 follow-ups 3–7 and Batch 3 follow-ups 1–2 still stand.

---

## Final Phase 1 Audit — 2026-09-02

Full requirement-by-requirement sweep of `specs/001-phase-1-core-platform/spec.md`
against the actual code (see `docs/PHASE_1_FINAL_AUDIT.md` for the traceability
matrix + evidence). Gaps found and fixed **within Phase 1 scope**:

| # | Gap (spec ref) | Fix |
|---|---|---|
| A1 | `redis` was a *transitive* dep (via `arq`) though `redis_client.py` / `jobs.events` import it directly | Declared `redis = {version=">=4.2,<6", extras=["hiredis"]}` in `pyproject.toml`; `poetry lock` regenerated (matches arq's own constraint, resolution unchanged). |
| A2 | CI + Dockerfile pinned Poetry **1.8.5**, which cannot read the committed `poetry.lock` (`lock-version = "2.1"`, written by Poetry 2.x) | Bumped both to **2.4.2**. |
| A3 | Health endpoint reported DB + Redis but **not worker liveness** (FR-F2 / SC-006 / OB-5) | `WorkerSettings.health_check_interval = 30`; `queue_client.check_worker()` reads arq's health-check key; `/health` now has `checks.worker` and is `degraded` when `job_queue_enabled` and the worker is down. |
| A4 | No **explicit cancel** trigger for a queued job (FR-F9 / JL-5) — the state machine + `mark_cancelled` existed but nothing called it from the request path | `POST /api/jobs/{id}/cancel`: QUEUED → `cancelled` (worker skips it); RUNNING → `cancelled` + arq abort (`allow_abort_jobs=True`, `execute_job` catches `CancelledError`); terminal → 409. The route uses a channel-backed `JobService` so a connected relay forwards the `cancelled` event and closes. |
| A5 | No **out-of-process watchdog** (JL-4) for a job whose worker was SIGKILLed — it stayed `running` forever (Batch 4 follow-up #3) | `JobService.reap_stuck_running(max_running_seconds)` + a `reap_jobs` cron every 5 min, ceiling `JOB_REAP_AFTER_SECONDS` (default 3600, `0` disables). Fails only `running` rows with an old `started_at`. |
| A6 | Model-selection tests pinned only some key combinations (SC-012 / FR-G5) | Added `gemini+anthropic`, `gemini+openai`, `gemini-only` cases to `test_model_selection.py`. |
| A7 | The **operator-gated eval-review** iframes (`AgentRunsPage`, `EvalComparePage`, `BestOfNEvalsPage` ×2) rendered generated HTML with **no `sandbox`** — same-origin execution of untrusted output in the operator's session | Added `sandbox="allow-scripts"` (no `allow-same-origin`) to all four. |
| A8 | Dead code | Removed the unused `TERMINAL` constant from `routes/jobs.py`. |

`test_batch3_queued_generation.py`, `test_job_service.py`,
`test_batch4_queue_failure_modes.py`, `test_queue_smoke.py`,
`test_health_endpoint.py`, `test_model_selection.py` extended with the matching
tests (incl. a live end-to-end cancel-aborts-a-running-job smoke test).

### Post-audit check results

| Check | Result |
|---|---|
| backend `pytest` (infra) | **632 passed** |
| backend `pyright` | **0 errors, 36 warnings** (pre-existing bs4/test) |
| `alembic upgrade → downgrade base → upgrade` on a **truly empty DB** + `alembic check` | clean, no drift, idempotent |
| frontend `jest` | **44 passed, 6 skipped** |
| frontend `lint:ratchet` / `build` | pass (16/6 baseline) / `✓ built` |
| Playwright (full stack, no keys) | app loads 0 errors · text→QUEUED→worker→controlled fail · **exactly one** error toast · `/api/jobs/{id}` · reconnect replays 1 error · `/health` shows `worker:ok`→`worker:down` · all 5 iframes sandboxed (no `allow-same-origin`) · `/api/models` 51 secret-free · `/agent-runs` → 403 |

### Not fixed — genuinely Phase 2+ (deferred, documented)

- Remaining generation paths (image / multi-image / URL / video / edit) — synchronous.
- Per-tenant provider keys / secret store.
- `screenshot_preview` synchronous-path `--no-sandbox` Chromium — Phase 6.
- Model registry runtime admin toggle.
- `langfuse` is an **unused** upstream dependency (never imported) — left in place
  (removing it is upstream cruft cleanup, not Phase 1 scope).
- Frontend project persistence / browser-refresh recovery — Phase 2.
- CI has still not executed on a real GitHub Actions host.

## Documentation updated (final audit)

- `docs/PHASE_1_FINAL_AUDIT.md` (new — the traceability matrix + verdict).
- `docs/REMEDIATION_LOG.md` (this section).
- `docs/LOCAL_DEVELOPMENT.md` — `worker` health check, `POST /api/jobs/{id}/cancel`,
  `JOB_REAP_AFTER_SECONDS`, `WORKER_HEALTH_INTERVAL_SECONDS`, 632-test count.
- `docs/TECHNICAL_DECISIONS.md` — Poetry 2.4.2, worker liveness + reaper + cancel notes.
- `docs/LG_TELECOMS_APP_BUILDER_ARCHITECTURE.md` — `/health` worker check, cancel endpoint.
- `backend/.env.example` — the new job/worker settings.
