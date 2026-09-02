# LG Telecoms App Builder — Technical Decisions

> **Status:** Phase 0 discovery. Entries below are either (A) **observed
> decisions already baked into the inherited codebase** — recorded so we
> understand what we're building on — or (B) **proposed decisions for the
> transformation**, marked *PROPOSED* and **not yet ratified**. Proposed
> entries capture the current recommendation, the alternatives, and the
> migration cost so the team can decide in Phase 1.

Format per entry: **Decision · Rationale · Alternatives considered ·
Trade-offs · Migration implications.**

---

## Part A — Decisions inherited from the existing codebase

### A1. Single self-contained HTML file as the generation output

- **Decision (upstream):** every generation produces one standalone `index.html`
  using CDN `<script>` tags; the 6 "stacks" differ only in which CDN libraries
  are referenced (`prompts/system_prompt.py`, `prompts/prompt_types.Stack`).
- **Rationale:** trivial preview (`iframe.srcdoc`), trivial export, no build step,
  no server runtime for the generated artifact.
- **Alternatives:** multi-file project scaffolds; framework CLIs.
- **Trade-offs:** cannot express real full-stack apps, routing, a backend, a
  database, or a dependency graph. No incremental build.
- **Migration implications:** full-stack generation (Roadmap Phase 4) is
  green-field. Keep single-file stacks as first-class IR compile targets;
  add multi-file targets alongside.

### A2. WebSocket-scoped generation lifecycle

- **Decision (upstream):** `/generate-code` accepts params, fans out variant
  tasks, streams events, closes the socket when done. Cancellation = socket
  close (`USER_CLOSE_WEB_SOCKET_CODE`).
- **Rationale:** simplest possible streaming; no infra beyond FastAPI.
- **Alternatives:** job queue + poll/SSE; durable task records.
- **Trade-offs:** no resumability, no multi-device visibility, a dropped
  connection kills the run, long/expensive runs are fragile, no server-side
  history of what was generated.
- **Migration implications:** Phase 1 introduces a queue + worker and demotes the
  socket to an event channel bound to a persisted *AI session*.

### A3. Provider abstraction via `ProviderSession` + canonical tools

- **Decision (upstream, `design-docs/agentic-runner-refactor.md`):** one
  normalized stream loop (`agent/engine.py`) + per-provider adapters
  (`agent/providers/*`) + canonical tool definitions serialized per provider.
- **Rationale:** avoid three copies of streaming/tool logic; consistent UI
  telemetry across providers.
- **Alternatives:** LangChain / LlamaIndex / provider SDKs directly; a single
  provider.
- **Trade-offs:** adapter code must track three fast-moving SDKs; no framework
  support for retries/fallbacks (not built).
- **Assessment:** **strong foundation — keep and extend.** Add model
  capabilities, retries, fallbacks, and a persisted session on top.

### A4. Model selection as deploy-time config keyed by available API keys

- **Decision (upstream):** `routes/model_choice_sets.py` holds hard-coded
  `Llm`-enum tuples (`ALL_KEYS_MODELS_TEXT_CREATE`, `GEMINI_ANTHROPIC_MODELS`,
  …). `ModelSelectionStage` picks a tuple by which keys are present and
  create-vs-update, then cycles it to `NUM_VARIANTS`.
- **Rationale:** the team tunes the mix from manual eval sessions (visible in
  `git log`: "Refresh … model mix from judged evals"); a static list is easy to
  reason about and review.
- **Alternatives:** a capability-and-cost-aware router; user-selectable models.
- **Trade-offs:** no per-org customization; adding a model is a code change;
  selection ignores context-window / vision / structured-output capability.
- **Migration implications:** Phase 1 adds a model **registry** (capabilities +
  pricing); Phase 2 adds a **router** with per-org overrides. The eval tooling
  that produces the judged mixes is kept as the tuning mechanism.

### A5. Client-side, in-memory project state (`commits` / `variants`)

- **Decision (upstream, `design-docs/commits-and-variants.md`):** Zustand holds a
  flat `commits` map; history is the `parentHash` chain; `head` is the active
  commit; variants generate non-blocking and independently.
- **Rationale:** no backend persistence to build; instant UI.
- **Trade-offs:** **all work is lost on refresh**; no sharing, no server history,
  no multi-device.
- **Migration implications:** Phase 2 moves this to `project_versions` +
  `variants` rows; the non-blocking-variant UX is worth preserving.

### A6. API keys supplied by the browser

- **Decision (upstream):** keys entered in a settings dialog, stored in
  `localStorage`, sent as plaintext fields in every `/generate-code` payload;
  `.env` is the fallback. `REPLICATE_API_KEY` is `.env`-only.
- **Rationale:** lets the open-source app work with zero server config; the user
  pays their own provider bills.
- **Trade-offs:** keys in `localStorage` are reachable by the non-sandboxed
  preview iframe (see A7); keys transit the app server; unsuitable for a managed
  multi-tenant service.
- **Migration implications:** Phase 2 removes browser keys entirely; per-tenant
  keys live in a server-side secrets manager and are selected by the router.

### A7. Generated code rendered without an iframe sandbox

- **Decision (upstream):** `PreviewComponent.tsx` sets `iframe.srcdoc = html`
  with **no `sandbox` attribute**; the backend also renders generated HTML in a
  shared headless Chromium launched with `--no-sandbox`.
- **Rationale (inferred):** the "select an element to edit" feature and preview
  interactions need same-origin DOM access; simplicity.
- **Trade-offs:** LLM-authored JS runs with the app's origin and can read
  `localStorage` (API keys), reach `window.parent`, and make same-origin
  requests. On the backend it executes with network access in the API process.
- **Migration implications:** add `sandbox="allow-scripts allow-forms ..."`
  (without `allow-same-origin`) as a Phase 1 quick win; rework select-and-edit to
  `postMessage`; move backend rendering into the sandbox tier (Phase 6).

### A8. No database; local files for the few things that persist

- **Decision (upstream):** design systems → one JSON file in `$HOME`; agent-run
  telemetry → JSONL + a SQLite index with an ad-hoc `ALTER TABLE` migration shim;
  assets → content-addressed files in `LOCAL_ASSET_DIR`.
- **Rationale:** zero-infra local tool.
- **Trade-offs:** not multi-tenant, not durable across container redeploys, no
  real migration story, no backups.
- **Migration implications:** Phase 1 introduces Postgres + Alembic; these local
  stores migrate to tenant-scoped tables / object storage in Phase 2.

### A9. Per-variant hard spend ceiling (`GENERATION_MAX_COST_USD = $3`)

- **Decision (upstream, commit "Abort generations that exceed a $3 spend
  ceiling"):** the engine aborts a variant whose running priced cost exceeds $3;
  unpriced models are unbounded.
- **Rationale:** protect against runaway tool loops.
- **Assessment:** **keep the mechanism**, generalize it — per-org credit budgets,
  per-project caps, and a separate repair budget (Phase 5/9).

### A10. Python `^3.10`, exact/narrow pins, Poetry

- **Decision (upstream):** `pyproject.toml` pins `python = "^3.10"`,
  `openai = "2.16.0"` (exact), `moviepy = "^1.0.3"` (old), plus playwright,
  pillow-heif, langfuse, google-genai.
- **Observed:** upstream Docker uses `python:3.12.3`; this Windows checkout
  installed and passed all tests on a **uv-provided CPython 3.13.14** (the only
  usable interpreter present; system Python is 3.14, untested).
- **Trade-offs:** 3.13/3.14 are outside the tested range; `moviepy 1.0.3` is
  effectively unmaintained.
- **Migration implications:** pick a supported Python (recommend pinning 3.12 in
  CI and dev to match upstream) — see *PROPOSED* D6.

### A11. CORS wide open; docs disabled

- **Decision (upstream):** `allow_origins=["*"]`, `allow_credentials=True`;
  `FastAPI(openapi_url=None, docs_url=None, redoc_url=None)`.
- **Trade-offs:** the CORS combination is invalid per spec and permissive;
  fine for a local tool, not for a hosted API.
- **Migration implications:** Phase 1 scopes CORS to known origins.

---

## Part B — Proposed decisions for the transformation (NOT RATIFIED)

### D1. *PROPOSED* — Relational database: PostgreSQL + Alembic

- **Decision:** PostgreSQL as the system of record; SQLAlchemy 2.x + Alembic for
  schema and migrations.
- **Rationale:** relational integrity for orgs/projects/memberships/billing;
  mature multi-tenancy options (RLS); JSONB for semi-structured IR/analysis
  blobs; ubiquitous ops knowledge.
- **Alternatives considered:** stay file-based (fails multi-tenancy); MySQL
  (weaker JSONB, no RLS); MongoDB (loses relational guarantees billing needs);
  SQLite in prod (no concurrency story).
- **Trade-offs:** an operational dependency the project doesn't have today;
  requires a data-access layer where there is none.
- **Migration implications:** greenfield — no existing DB to migrate. The
  SQLite telemetry index can be left as-is initially or folded into Postgres
  later.

### D2. *PROPOSED* — Multi-tenancy isolation: Postgres Row-Level Security, tenant-id column

- **Decision:** every tenant-scoped table carries `organization_id`; enforce
  isolation with RLS policies keyed off a session variable set by the API from
  the authenticated context.
- **Rationale:** one schema to migrate; defense-in-depth (a missing `WHERE`
  can't leak data); good tooling support.
- **Alternatives considered:** schema-per-org (heavy migration fan-out, connection
  churn); database-per-org (strong isolation, heavy ops, poor for many small
  tenants); app-layer filtering only (one bug = cross-tenant leak).
- **Trade-offs:** RLS adds query-planning overhead and a learning curve; noisy
  neighbours share resources.
- **Migration implications:** decided **in Phase 2**; revisit for enterprise
  customers who require physical isolation (could offer database-per-org as a
  tier).

### D3. RATIFIED (Batch 2) — Job queue: Redis + **arq** (asyncio-native task runner)

- **Decision:** Redis-backed queue via **arq**. Generation (later), QA, and
  deploy run as jobs on worker processes started with
  `arq worker.WorkerSettings`; the API only enqueues and (later) streams events
  via a Redis pub/sub `JobEventChannel`. Durable job state (`jobs` table) is in
  Postgres; Redis carries only transient queue/coordination + event fan-out.
- **Rationale for arq over Celery / Dramatiq:** the generation engine is fully
  `async` (`AgentEngine.run()` awaits; `asyncio.gather` fans out variants). arq
  is asyncio-native — the worker `await`s the existing engine directly with no
  sync/async bridging. It is Redis-only (already required), minimal, pinned to
  the pydantic family. Celery / Dramatiq are sync-first and would force
  `asgiref`/thread bridging of the async engine.
- **Alternatives considered:** Celery (heavy, sync-first, needs a result
  backend); Dramatiq (lighter but sync-first); a cloud queue (vendor lock,
  harder local dev); Temporal (great fit for the multi-stage pipeline, heavy to
  introduce now — revisit at Phase 5).
- **Trade-offs:** arq is smaller-community than Celery; at-least-once semantics
  (a handler must be idempotent-safe); local dev needs Redis + a worker process.
- **Migration implications:** Batch 2 built the worker + job model + event
  channel with a `noop` test handler only. Generation moves onto it in the next
  batch behind `JOB_QUEUE_ENABLED` (default false).

### D4. *PROPOSED* — Object storage: S3-compatible (MinIO in dev)

- **Decision:** assets, version snapshots, run captures, and exports go to
  S3-compatible object storage; DB stores metadata + keys; access via signed URLs.
- **Rationale:** the current local `LOCAL_ASSET_DIR` / `run_logs` don't survive
  redeploys and aren't tenant-scoped; object storage is the standard answer.
- **Alternatives considered:** DB large-objects (bloats Postgres, poor for
  images); a network filesystem (ops burden, no signed URLs).
- **Trade-offs:** eventual-consistency edge cases; another credential to manage;
  local dev runs MinIO.
- **Migration implications:** `uploaded_assets/store.py` already isolates the
  finalize step (`_finalize_asset_bytes`) and carries an unused `user_id` — a
  clean seam to swap the backend.

### D5. *PROPOSED* — Authentication: OIDC / OAuth2 with an external IdP

- **Decision:** delegate identity to an OIDC provider (managed IdP or a
  self-hosted Keycloak/Ory); the API validates tokens and manages
  authorization + membership itself.
- **Rationale:** don't build password storage, MFA, SSO, or SCIM from scratch;
  enterprise SSO is a listed requirement.
- **Alternatives considered:** roll-your-own auth (security liability); a
  full auth SaaS that also owns RBAC (lock-in, RBAC needs to be domain-aware).
- **Trade-offs:** an IdP dependency; local dev needs a dev IdP or a stub.
- **Migration implications:** none existing — but **removing browser-held
  provider keys (A6) is a prerequisite** and lands in the same phase.

### D6. RATIFIED (Batch 4) — Python 3.12 is the target for dev + CI

- **Decision:** CPython 3.12 is the standard. `backend/pyproject.toml` requires
  `python = "^3.12"`; `backend/.python-version` pins `3.12`;
  `pyrightconfig.json` sets `pythonVersion` `3.12`; `backend/Dockerfile` is
  `python:3.12-slim-bookworm`; CI (`.github/workflows/ci.yml`) runs the backend
  job on `3.12` (`PYTHON_VERSION`).
- **Not forced locally.** `^3.12` also admits 3.13/3.14, so a contributor's
  existing 3.13 venv keeps working — no uninstall/reinstall required. CI is the
  authority: it always runs 3.12, so 3.12 is what must stay green.
- **Lock impact:** regenerating `poetry.lock` under `^3.12` only dropped the
  now-unreachable backports (`async-timeout`, `exceptiongroup`, `tomli`); no
  runtime dependency changed.

### D7. *PROPOSED* — Sandbox tier: Docker containers first, evaluate microVMs later

- **Decision:** Phase 6 starts with hardened Docker (read-only rootfs, dropped
  caps, seccomp, no-new-privileges, cgroup CPU/mem/PID limits, network `none` +
  per-run allowlist); evaluate gVisor/Firecracker if the threat model or
  multi-tenant density demands stronger isolation.
- **Rationale:** Docker is already in the stack; fastest path to *some*
  isolation; microVMs add real ops complexity.
- **Alternatives considered:** microVMs from day one (stronger, slower to build);
  running generated code in the API process (status quo — unacceptable for the
  target);  third-party code-execution sandboxes (cost, data-residency).
- **Trade-offs:** container escapes are a live risk class; kernel is shared.
- **Migration implications:** the Phase 1 iframe-`sandbox` fix is independent and
  ships first; this decision is about *executing* generated apps.

### D8. *PROPOSED* — Application IR: LLM-authored structured output, validated against a schema, with deterministic compilers

- **Decision (tentative, pending the Phase 3 spike):** the planning stage emits
  the `AppIR` as provider structured output; a JSON-Schema/Pydantic model
  validates it; per-stack **deterministic compilers** turn IR → code. Imports do
  a best-effort code → IR lift.
- **Rationale:** keeps the LLM doing what it's good at (design intent) while
  making regeneration/repair/versioning operate on a typed, diffable structure
  rather than an HTML blob.
- **Alternatives considered:** no IR (status quo — blocks Phases 5/7/8); a
  fully deterministic IR derived from Analysis without an LLM (brittle for
  visual nuance); AST-per-stack (couples IR to one framework).
- **Trade-offs:** schema churn early; the LLM can emit invalid IR (needs
  repair-on-validate); two representations to keep in sync.
- **Migration implications:** **must be de-risked with a timeboxed spike in
  Phase 3 before Phases 4–8 depend on it.** Ship it for the single-file stacks
  first; the current `edit_file` string-replace tool stays as a fallback.

### D9. *PROPOSED* — Frontend: keep React/Vite/Zustand, add server state via a query library

- **Decision:** do **not** rewrite the frontend. Keep Zustand for ephemeral UI
  state; introduce React Query (or RTK Query) for server-owned project data;
  restructure routing around org/workspace/project.
- **Rationale:** the SPA is in good shape (tests, componentized, Radix); a
  rewrite is pure risk. The gap is "no server state", which a query layer fills.
- **Alternatives considered:** full rewrite (Next.js app router, RSC) — large,
  unjustified now; Redux Toolkit throughout — heavier than needed.
- **Trade-offs:** two state systems to reason about (already true today).
- **Migration implications:** incremental, screen by screen.

### D10. RATIFIED (Batch 2, hardened Batch 4) — CI on GitHub Actions

- **Decision:** `.github/workflows/ci.yml` runs on every PR + pushes to `main` /
  the foundation branch. **backend** job: Python 3.12, Poetry 2.4.2 (pipx),
  `.venv` cache, `pyright`, `alembic upgrade → downgrade base → upgrade`,
  `alembic check` (model-drift gate, added Batch 4), then `pytest -q` with
  `REQUIRE_INFRA=1` against `postgres:16-alpine` + `redis:7-alpine` service
  containers — which makes `tests/test_queue_smoke.py` a real
  API→Redis→burst-worker→terminal-state check (added Batch 4). **frontend** job:
  Node 22, Corepack pnpm (pinned via `packageManager`), `pnpm test`,
  `pnpm run lint:ratchet`, `pnpm build`.
- **Credentials:** only throwaway values (`appbuilder`/`appbuilder`, loopback
  URLs). No provider API keys, no real secrets — the queued path's controlled
  "no key" failure is what the tests exercise.
- **Lint policy:** ratchet against `frontend/.lint-baseline.json`
  (`maxErrors`/`maxWarnings`), lowered as pre-existing issues are fixed — never
  raised.

---

## Part C — Decisions made during remediation

> These were implemented in **Phase 1 Remediation Batch 1 (2026-09-02)**. See
> `docs/REMEDIATION_LOG.md` for the full problem → root cause → change record.

### C1. DECIDED — Preview iframe sandboxing + postMessage bridge

- **Decision:** the preview iframe is sandboxed with
  `allow-scripts allow-forms allow-modals allow-popups allow-popups-to-escape-sandbox`
  (**no `allow-same-origin`**). All host ↔ preview interaction (element
  selection for select-and-edit, overlays) goes through an injected bridge
  script (`preview-bridge.js`) and a validated `postMessage` channel; the host
  never touches the iframe's DOM. `selectedElement` is a serialized
  `{ tagName, outerHTML, context }` snapshot, not a live node.
- **Rationale:** closes audit SF-1/SF-2 — sandboxed generated code could read the
  host's `localStorage` (API keys). This is the Phase 1 "quick win"; full
  execution isolation is Phase 6.
- **Alternatives:** keep same-origin preview (status quo — unsafe); build the
  bridge as a separate Vite entry loaded by URL (heavier; network dependency for
  the preview).
- **Trade-offs:** the bridge carries a hand-kept plain-JS mirror of
  `select-and-edit/overlays.ts` + `utils.ts` (can't import TS into an injected
  string).

### C2. DECIDED — CORS is an explicit allow-list

- **Decision:** `CORS_ALLOWED_ORIGINS` (comma-separated), defaulting to the local
  dev origins. No wildcard; `allow_credentials=True` is retained (now safe).
- **Rationale:** closes audit SF-3.
- **Migration implications:** non-default deployments set `CORS_ALLOWED_ORIGINS`.

### C3. DECIDED — Minimal operator gate on internal endpoints

- **Decision:** `/evals*`, `/eval-sets*`, `/eval-sessions*`, `/prompt-reports*`,
  `/agent-runs*` require an `X-Operator-Token` header when `OPERATOR_TOKEN` is
  set; are open when `OPERATOR_ENDPOINTS_PUBLIC=true`; otherwise return 403
  (closed by default).
- **Rationale:** closes audit SF-4 ("accidental unrestricted exposure"). This is
  **not** authentication/authorization — the real per-user/per-org model is
  Phase 2.
- **Trade-offs:** local use of the eval UI now needs an env var. (Those pages
  were already broken via `pnpm dev` — audit KF-3 — so no working feature
  regresses.)

### C4. DECIDED — Strict environment-variable boolean parsing

- **Decision:** `env_bool()` accepts only `1/true/yes/on/y/t` (true) and
  `0/false/no/off/n/f`/empty/unset (false); anything else raises at startup.
- **Rationale:** closes audit SF-8 — `bool(os.environ.get(...))` made `"false"`
  truthy for `IS_PROD` / `IS_DEBUG_ENABLED`.

### C11. *PROPOSED* — Typed config on `pydantic` v2 `BaseModel` (not `pydantic-settings`) for now

- **Decision:** `backend/config.py` builds a validated `Settings` model via
  `Settings.from_env()`, keeping the existing module-level constant names for
  backward compatibility. Env reading is a thin helper layer (`env_bool`,
  `env_int`, `env_float`, `env_list`, `env_str`).
- **Rationale:** `pydantic` v2 is already a dependency; this adds **no new
  runtime dependency** and is offline-safe. Satisfies spec FR-C1..C6 (typed,
  validated, single module, fail-fast, no scattered `os.environ`).
- **Alternatives:** `pydantic-settings` (the "standard" choice; adds a dependency;
  swap later is mechanical); a bespoke dataclass loader (reinvents validation).
- **Trade-offs:** no `.env` nested parsing / `SettingsConfigDict` niceties yet.
- **Migration implications:** a few scattered `os.environ` reads remain
  (`evals/config.py`, `routes/design_systems.py`, `routes/screenshot.py`) — moved
  to `Settings` in a later batch. Adopting `pydantic-settings` remains open.

### C14. DECIDED (Batch 2) — PostgreSQL dev harness: async SQLAlchemy 2.0 + asyncpg + Alembic

- **Decision:** `backend/db/` is an async SQLAlchemy 2.0 layer (`asyncpg`
  driver): a lazy engine with `pool_pre_ping`, a `session_scope()` transactional
  context manager, `dispose_engine()`, and a non-fatal `check_database()` probe.
  Alembic (`backend/alembic.ini` + `backend/migrations/`, async `env.py`) reads
  the URL from the typed settings — **no credentials in a committed file**. One
  baseline migration creates only the `jobs` infrastructure table.
- **Rationale:** FastAPI + the health route + arq are all async; async DB avoids
  thread-pool bridging. The DB is **optional** this phase — no `DATABASE_URL` →
  the app still starts and the sync generation path works.
- **Alternatives:** sync SQLAlchemy + `psycopg` (simpler Alembic, but forces
  `to_thread` in async handlers); no ORM (reinvents migrations).
- **Trade-offs:** async Alembic env is slightly more code; `asyncpg` is a
  compiled dependency.
- **Migration implications:** Phase 2 adds domain tables (users, orgs, projects,
  …) and tenancy columns via new migrations; `db/` is the foundation they build
  on. `evals/config.py` and a couple of route modules still read `os.environ`
  directly — folded into `Settings` in a later batch.

### C15. DECIDED (Batch 2) — Job model in Postgres, event fan-out in Redis

- **Decision:** the `jobs` table (`backend/jobs/models.py`) holds durable
  lifecycle state (`queued|running|succeeded|failed|cancelled`, timestamps,
  `attempt`/`max_attempts`, `error` summary, `request_id`, `worker`, `params`
  JSONB, `result_ref`). `JobService` enforces the transition table (spec JL-2).
  `JobEventChannel` publishes `JobEvent`s over Redis pub/sub (`jobs:events:<id>`).
- **Scope guard:** **no tenant / user / org / billing columns** (spec FR-E7 /
  FR-F15) — a test asserts this. `result_ref` is a *pointer* to where output
  lives, never the output; `error` is a truncated summary, never a payload.
- **Rationale:** Postgres for durability + queryability (spec JL-7, "terminal
  state retrievable independently of the socket"); Redis for cheap transient
  event fan-out (spec A-8, DR-4 — losing Redis loses in-flight queue state but
  never corrupts Postgres).
- **Migration implications:** additive-only. Phase 2 adds `project_id` /
  tenancy columns via migration; Phase 7 adds AI-session linkage.

### C16. DECIDED (Batch 2) — CI on GitHub Actions + a lint ratchet

- **Decision:** `.github/workflows/ci.yml` — a `backend` job (Python 3.12,
  Poetry 2.4.2, pyright, Alembic up/down/up round trip, pytest against Postgres
  + Redis service containers with `REQUIRE_INFRA=1`) and a `frontend` job
  (Node 22, pnpm 10.32.1 via corepack, `pnpm test`, `pnpm build`, lint ratchet),
  with dependency caching keyed on the lockfiles.
- **Lint policy (resolves KF-9 / D10's open question):** a **ratchet**, not a
  freeze and not a fix-all-first. `frontend/.lint-baseline.json` records the
  current debt (`maxErrors: 19, maxWarnings: 6`); `scripts/lint-ratchet.mjs`
  prints the full report, **fails on any increase**, and nags to lower the
  baseline when the count drops. Move toward 0/0 incrementally.
- **Rationale:** blocking CI on 19 inherited errors would stall the project or
  invite blanket `// eslint-disable`. The ratchet prevents new debt immediately
  while keeping the path to clean.
- **Trade-offs:** the baseline file is a small piece of state to keep honest;
  CI not yet verified on a real GitHub run (no push this batch).

### C17. DECIDED (Batch 2) — WebSocket transition boundary

- **Decision:** `JobEventChannel` (Redis pub/sub) is the seam between *job
  execution* and *event delivery*. The existing `/generate-code` WebSocket is
  **unchanged** this batch. Next batch: the API enqueues a generation job, the
  worker runs the existing `AgentEngine` and publishes events to the channel, and
  a WebSocket subscribes to the channel and relays them — so the socket lifetime
  no longer bounds the job (spec FR-F7/F8). Terminal state is always readable
  from the `jobs` table.
- **Rationale:** separating the two concerns is the whole point of the queue
  work; defining the boundary now lets the next batch be a focused, reversible
  change behind `JOB_QUEUE_ENABLED`.
- **Deferred:** the real-time transport choice for *collaboration* (WS vs SSE vs
  CRDT) stays deferred; this is only about generation event delivery.

### C18. DECIDED (Batch 3) — First migrated generation path: text → create

- **Decision:** only `inputMode="text"` + `generationType="create"` runs through
  the Redis/arq worker, and only when `JOB_QUEUE_ENABLED=true` (default false).
  Everything else — image / multi-image / URL / video / **update/edit** — stays
  on the synchronous `routes/generate_code.py` pipeline.
- **Rationale:** smallest real path (no screenshots / video / asset extraction /
  file-state), so the API→job→queue→worker→event→WS architecture can be proven
  with a minimal, reversible change. `AgenticGenerationStage` and model selection
  were *extracted* (behaviour-preserving), not rewritten — one implementation
  serves both paths.
- **Migration implications:** later batches move the remaining paths the same
  way; the sync pipeline is retired only once every path has a queued equivalent
  and parity is proven.

### C19. DECIDED (Batch 3) — Generation result = the Redis event backlog, not a table

- **Decision:** the worker publishes every generation event (`setCode`,
  `variantComplete`, …) to `jobs:eventlog:<id>` (a TTL'd, capped Redis list). A
  reconnecting client replays that list to rebuild the output. `jobs.result_ref`
  is just the pointer string `eventlog:<id>`. **No `job_results` / `job_events`
  table was added.**
- **Rationale:** the generated code is already carried by the existing `setCode`
  event; persisting it a second time in Postgres would duplicate data and force a
  schema addition this batch explicitly tries to avoid. The 2 h TTL matches the
  "recover from a transient disconnect" use case; durable project persistence is
  Phase 2.
- **Trade-offs:** a job's output is unavailable after the TTL (the `jobs` row
  still records that it succeeded/failed). Phase 2's project store is the durable
  home for generated code.

### C20. DECIDED (Batch 3) — Queued path uses server-configured provider keys only

- **Decision:** `build_generation_request` strips `openAiApiKey` / `anthropicApiKey`
  / `geminiApiKey` / `replicateApiKey` / `openAiBaseURL` / `screenshotOneApiKey`
  from the browser payload before anything is persisted or enqueued. The worker
  resolves credentials from `settings` (server env) at execution time via
  `ProviderCredentials.from_settings` and never serialises them.
- **Rationale:** spec §5 — no secrets in Redis jobs, DB job params, WS payloads,
  logs, or frontend state. A short-lived secret store keyed by job id is a
  Phase 2 (per-tenant secrets manager) concern.
- **Trade-off / limitation:** a developer who only sets provider keys in the
  browser Settings dialog gets the controlled "No API key" error on the queued
  text→create path (the sync path still honours browser keys). Documented in
  LOCAL_DEVELOPMENT.md.

### C12. DECIDED — Structured logging + request/trace correlation groundwork

- **Decision:** `backend/logging_config.py` provides one configured `app` logger
  with structured output (`console` key=value or `json`, via `LOG_FORMAT`), a
  level from `LOG_LEVEL`, a UTF-8-safe stream (`errors="backslashreplace"` — can
  never raise on content), and a `contextvars` `request_id` injected into every
  record. `RequestContextMiddleware` assigns/propagates the id per HTTP request
  and echoes `X-Request-ID`; the WebSocket generation handler binds its own.
- **Rationale:** spec FR-D1..D8 / constitution Principle X. Also fixes audit
  KF-1/KF-2: `print` of box-drawing characters on a cp1252 stdout raised
  `UnicodeEncodeError` and crashed generation / startup.
- **Scope:** highest-risk paths migrated this batch (generation pipeline, agent
  tools, startup probe); non-hot routes, `fs_logging/*`, provider debug dumps and
  intentional CLI/eval stdout deferred to later batches.
- **Not adopted yet:** a distributed-tracing backend (Phase 10) — only the
  correlation seam is in place. `structlog` was not added; stdlib `logging`
  suffices.
- **Batch 4 follow-through:** the remaining runtime `print()`s were migrated —
  provider token-usage accounting (`_log_token_usage` in
  `agent/providers/base.py`), `fs_logging/*`, `routes/export.py` (incl. the
  SSRF-guard "asset skipped" lines), `routes/agent_runs.py`,
  `image_generation/generation.py`, `evals/core.py` + `evals/sets.py` (both
  reachable from operator routes), and `debug/DebugFileWriter.py`. Genuine CLI
  scripts (`evals/runner.py`, `evals/asset_extraction_benchmark.py`) keep their
  stdout.

### C21. DECIDED (Batch 4) — Typed model registry as a *derived* layer

- **Decision:** `backend/model_registry/` exposes a typed, frozen `ModelEntry`
  per model (provider, `api_name`, capabilities, input modalities, status,
  enabled flag, default flag, reasoning effort, pricing ref) plus lookups and a
  frontend-safe `frontend_model_catalog()` served at `GET /api/models`. Every
  field is **derived** from the existing sources of truth (`llm.Llm`,
  `OPENAI_MODEL_CONFIG`, `ANTHROPIC_MODEL_CONFIG`, the Gemini api-name rules,
  `costs.pricing.MODEL_PRICING`) — not re-declared.
- **Rationale:** spec model-registry requirement + constitution "no config as
  code". A derived layer cannot silently drift; `tests/test_model_registry.py`
  pins every entry's `api_name`/provider against the legacy resolver functions
  (244 parametrised assertions).
- **Explicitly not in the registry:** API keys, per-user/org config, billing,
  usage accounting, a marketplace (all Phase 2). `to_public_dict()` omits
  `api_name` and `pricing`; a test asserts the `/api/models` payload is
  secret-free.
- **Migration:** `agent/providers/factory.py` now dispatches on
  `provider_of(model)`; `generation/model_selection.py` drops registry-disabled
  models before selection. Other call sites migrate opportunistically.

### C22. DECIDED (Batch 4) — FastAPI `lifespan` replaces `@app.on_event`

- **Decision:** a single `@asynccontextmanager lifespan()` in `main.py` owns
  startup (log config, operator-gate status, screenshot-preview probe) and
  shutdown (`close_arq_pool`, `dispose_engine`, `close_redis`). The deprecated
  `on_event("startup"/"shutdown")` hooks are gone.
- **Rationale:** the `on_event` API is deprecated; lifespan is the supported
  seam and makes ordered, awaited resource teardown explicit. No behaviour
  change; the startup probe stays non-fatal.

### C23. DECIDED (Batch 4) — Job lifecycle hardening: idempotent terminals + RUNNING re-acquire

- **Decision:** `JobService._transition` treats *terminal → same terminal* as a
  no-op (returns the row, emits nothing) so a re-delivered worker message or a
  double `mark_*` call is idempotent, not an `InvalidJobTransition`. `RUNNING →
  RUNNING` is now legal so a fresh worker can re-acquire a job whose previous
  worker was killed before recording a terminal state (arq `max_tries` still
  bounds attempts). Cancelled/succeeded/failed jobs still reject re-runs.
- **Rationale:** spec queue failure modes C/E — a crashed worker must never
  leave a job falsely `succeeded`, and the backlog must remain drainable.
- **Final-audit addition (JL-4):** the RUNNING-re-acquire only helps when arq
  re-delivers the job. A worker SIGKILLed with the job popped-and-unacked leaves
  the row `running` forever. `JobService.reap_stuck_running` + a `reap_jobs` cron
  (every 5 min, ceiling `JOB_REAP_AFTER_SECONDS`, default 3600, `0` disables)
  fails such rows out-of-process. arq's in-process `job_timeout` still handles a
  merely-hung job on a live worker.
- **Final-audit addition (FR-F9 / JL-5):** `POST /api/jobs/{id}/cancel` is the
  explicit-cancel trigger. QUEUED → `cancelled` (the worker's `mark_running`
  guard keeps it from starting); RUNNING → `cancelled` + arq abort
  (`allow_abort_jobs=True`; `execute_job` catches `CancelledError`, records it,
  re-raises); terminal → 409. The route uses a channel-backed `JobService` so a
  relay watching the job forwards the `cancelled` event and closes the socket.

### C24. DECIDED (Batch 4) — Job retention: opt-in, cron-driven, conservative

- **Decision:** `JOB_RETENTION_DAYS` (unset = disabled). When set, a daily arq
  `cron` (`prune_jobs`, 03:17) deletes **terminal** job rows whose `finished_at`
  is older than the window. Queued/running rows are never touched; there is no
  new DB column and no tenant/owner filter.
- **Rationale:** spec DR-6 ("opt-in, prunable; Phase 1 adds no new retention
  obligation"). Kept deliberately minimal — not a GC subsystem.

### C25. DECIDED (Batch 4) — The worker cannot render generated code

- **Decision:** `worker._on_startup` calls
  `preview_screenshot.disable_screenshot_preview()`, hard-disabling the
  `screenshot_preview` agent tool in worker context. Rendering generated HTML in
  headless Chromium *executes* untrusted markup/JS; the worker must remain
  incapable of executing generated code (spec SEC / constitution). The
  synchronous API process is unchanged — it still offers the tool.
- **Rationale:** closes the one path by which the queued generation flow could
  have executed model output. A real sandbox for generated code is Phase 6 and
  explicitly out of scope here.

### C26. DECIDED (final audit) — `/health` reports worker liveness; `redis` is a direct dependency

- **Decision:** `/health` gained `checks.worker` (`ok` / `down`), read from arq's
  own health-check key (`arq:queue:health-check`, refreshed every
  `WORKER_HEALTH_INTERVAL_SECONDS`, default 30). Overall status is `degraded`
  when `job_queue_enabled` is on and no worker is live. `redis[hiredis]` is now
  an explicit `pyproject.toml` dependency (it was only transitive via `arq`,
  though `redis_client.py` / `jobs.events` import it directly). CI + Dockerfile
  Poetry pinned to **2.4.2** to read the committed `lock-version 2.1` lockfile.
- **Rationale:** spec FR-F2 / SC-006 / OB-5 require worker health to be reported
  via the health endpoint; a directly-imported package should be a declared
  dependency.
- **Also (final audit):** the four operator-gated eval-review iframes
  (`AgentRunsPage`, `EvalComparePage`, `BestOfNEvalsPage` ×2) that render
  generated HTML gained `sandbox="allow-scripts"` (no `allow-same-origin`),
  consistent with FR-B1's intent for the primary preview.

---

## Decisions explicitly deferred

- Hosting/cloud provider and IaC tool (Terraform vs. Pulumi vs. CDK).
- Payment processor.
- Deploy targets for generated full-stack apps (own infra vs. partner).
- Whether the closed-source `screenshot-to-code-saas` wrapper is reused,
  referenced, or fully superseded.
- Telemetry backend (self-hosted vs. vendor) for OpenTelemetry.
- Real-time transport for project collaboration (WS vs. SSE vs. CRDT layer).
