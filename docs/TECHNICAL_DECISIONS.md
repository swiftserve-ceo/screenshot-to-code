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

### D3. *PROPOSED* — Job queue: Redis + a Python task runner (Celery or Dramatiq/arq)

- **Decision:** Redis-backed queue; generation, QA, and deploy run as jobs on
  worker processes; the API only enqueues and streams events.
- **Rationale:** decouples run lifetime from the socket; enables retries,
  concurrency limits, priority, and per-tenant fairness; Redis is also needed for
  caching/pub-sub/rate-limits.
- **Alternatives considered:** keep everything in the request (status quo —
  fragile); a cloud queue (SQS/PubSub — vendor lock, harder local dev);
  Temporal (great fit for the multi-stage pipeline, but heavy to introduce now —
  revisit at Phase 5).
- **Trade-offs:** a new moving part; exactly-once vs. at-least-once semantics to
  design around; local dev needs Redis + a worker.
- **Migration implications:** introduced in Phase 1 behind a flag for one code
  path, expanded per phase.

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

### D6. *PROPOSED* — Pin Python 3.12 for dev + CI

- **Decision:** standardize on CPython 3.12 (matches upstream Docker); document
  it in LOCAL_DEVELOPMENT.md; add a CI matrix entry.
- **Rationale:** the codebase is pinned `^3.10` and *tested* by upstream on 3.12;
  3.13/3.14 are untested (3.13 happened to pass here — not a guarantee, e.g.
  `moviepy 1.0.3`).
- **Alternatives considered:** adopt 3.13 now (works today, risk later);
  stay on whatever is installed (non-reproducible).
- **Trade-offs:** contributors on 3.13/3.14 need pyenv/uv to get 3.12.
- **Migration implications:** none code-wise; a dev-environment + CI change.

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

### D10. *PROPOSED* — CI from Phase 1: GitHub Actions running the existing baseline checks

- **Decision:** a CI workflow runs `poetry run pytest`, `poetry run pyright`
  (backend) and `pnpm lint && pnpm test && pnpm build` (frontend) on every PR,
  Python pinned to 3.12, Node to 22, pnpm to the `packageManager` version.
- **Rationale:** there is **no CI today**; the checks already exist and pass;
  every later phase needs a green gate.
- **Alternatives considered:** none reasonable.
- **Trade-offs:** `pnpm lint` currently fails on 19 pre-existing errors (see
  discovery summary) — CI must either fix-forward those first or start with lint
  non-blocking and ratchet.
- **Migration implications:** decide the lint-baseline policy when CI lands.

---

## Decisions explicitly deferred

- Hosting/cloud provider and IaC tool (Terraform vs. Pulumi vs. CDK).
- Payment processor.
- Deploy targets for generated full-stack apps (own infra vs. partner).
- Whether the closed-source `screenshot-to-code-saas` wrapper is reused,
  referenced, or fully superseded.
- Telemetry backend (self-hosted vs. vendor) for OpenTelemetry.
- Real-time transport for project collaboration (WS vs. SSE vs. CRDT layer).
