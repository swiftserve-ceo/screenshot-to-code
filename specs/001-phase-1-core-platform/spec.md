# Feature Specification: Phase 1 — Core Platform Architecture

**Feature Branch**: `lg-telecoms-app-builder-foundation` (spec directory: `specs/001-phase-1-core-platform`)

**Created**: 2026-09-02

**Status**: Draft

**Input**: User description: "Create the formal Phase 1 specification (Core Platform Architecture) for LG Telecoms App Builder, using the Phase 0 discovery docs, the ratified constitution, and the existing codebase as authoritative inputs. Scope: CI/baseline, security hardening, typed configuration, observability foundation, PostgreSQL + Alembic foundation, Redis + background worker + job queue for generation with WebSocket as event-streaming, and an AI model registry foundation that mirrors current behavior. Out of scope: auth, orgs/workspaces/teams, billing/credits, project management, Application IR, full-stack generation, new engine, frontend redesign, deployment/K8s, sandbox execution."

## Overview

Phase 1 establishes the production platform foundation that every later phase of the
LG Telecoms App Builder transformation depends on, **without changing the end-user
generation experience**. It is infrastructure and hardening work: continuous integration,
reproducible runtimes, security fixes identified in Phase 0, typed configuration,
structured observability, a database and migration foundation, an asynchronous job
infrastructure for generation, and a model-registry abstraction that initially mirrors
today's behavior exactly.

The inherited system is a single-user, no-auth, no-database, keys-in-browser tool whose
generation engine is mature and worth preserving (constitution Principle II). Phase 1 adds
the platform shell *around* that engine, not *through* it (ROADMAP Principle 2).

This specification defines **what** Phase 1 must deliver and **why**. It does not define the
implementation plan; that is produced by `/speckit-plan`.

---

## User Scenarios & Testing *(mandatory)*

The "users" of Phase 1 are the engineers building and operating the platform, plus the
operators who will eventually run it in production. End users (people generating apps) MUST
observe no behavioral change.

### User Story 1 - CI baseline gate on every change (Priority: P1)

As a platform engineer, when I open a pull request, an automated pipeline runs the full
baseline check suite (backend tests, backend type checking, frontend tests, frontend build,
and lint under the agreed policy) against pinned runtime versions, so that no change merges
without a green, reproducible gate.

**Why this priority**: The constitution (Principle XIII) and every later phase require a
green gate before change is safe. There is no CI today. Nothing else in Phase 1 can be
verified to "not break existing functionality" without it. This is the single highest-value,
lowest-risk deliverable and is a hard prerequisite for the rest.

**Independent Test**: Open a trivial PR (e.g. a comment change) and a PR that deliberately
breaks a backend test; confirm the first passes all checks and the second is blocked with a
clear failure report, both using the pinned Python/Node/pnpm versions.

**Acceptance Scenarios**:

1. **Given** a pull request that changes backend code, **When** CI runs, **Then** backend
   `pytest` and `pyright`, frontend tests, frontend build, and the lint check all execute and
   their pass/fail status is reported on the PR.
2. **Given** a pull request that introduces a failing backend test, **When** CI runs,
   **Then** the pipeline fails and the PR is marked not mergeable.
3. **Given** a pull request that introduces a new type error in a changed file, **When**
   `pyright` runs in CI, **Then** the pipeline fails (no new warnings in changed files, per
   constitution Principle XIII).
4. **Given** the CI configuration, **When** it provisions runtimes, **Then** it uses the
   documented pinned Python version, Node version, and the pnpm version from
   `packageManager`, and these match what `docs/LOCAL_DEVELOPMENT.md` tells a developer to
   install.
5. **Given** the current 19 pre-existing frontend lint errors, **When** the lint policy is
   applied in CI, **Then** the policy is documented, deterministic, and does not silently
   pass new violations.

---

### User Story 2 - Phase 0 security hardening applied (Priority: P1)

As a platform engineer, I need the concrete, standalone security weaknesses catalogued in
Phase 0 to be fixed, so that the platform is not carrying known-unsafe defaults into
multi-tenant phases and so that the generated-code preview cannot read platform secrets.

**Why this priority**: Constitution Principles VII, VIII and IX. These are cheap, isolated
fixes that must land before the platform is exposed more widely. The non-sandboxed preview
iframe currently lets LLM-authored JavaScript run same-origin with the app and read
`localStorage` (which holds API keys) — an active vulnerability.

**Independent Test**: For each hardening item, demonstrate the before/after: the preview
iframe cannot reach `window.parent` or app-origin storage; unauthenticated requests to
eval/telemetry endpoints are rejected in a non-local configuration; CORS rejects an
unlisted origin; a config flag set to `"false"` is treated as false.

**Acceptance Scenarios**:

1. **Given** a generated page rendered in the preview, **When** its script attempts to read
   the host app's storage or call into the parent window, **Then** the browser blocks it
   (the preview iframe carries a restrictive `sandbox` attribute without
   `allow-same-origin`).
2. **Given** the select-and-edit feature, **When** the preview is sandboxed, **Then**
   element selection still works via an explicit, origin-checked message channel between
   preview and host, with no loss of current functionality.
3. **Given** a deployment configured with an allowed-origins list, **When** a request
   arrives from an origin not on the list, **Then** CORS does not grant credentialed access;
   the invalid `allow_origins=["*"]` + `allow_credentials=True` combination is removed.
4. **Given** the evaluation, prompt-report, and agent-run endpoints (`/evals/*`,
   `/eval-sets/*`, `/eval-sessions/*`, `/prompt-reports/*`, `/agent-runs/*`, `/run_evals*`,
   `/models`, `/output_folders`), **When** the platform runs in a non-local (shared)
   configuration, **Then** those endpoints are not reachable without passing an operator
   access gate; **When** it runs locally for development, **Then** they remain available.
5. **Given** any configuration boolean (e.g. debug mode, production mode), **When** it is set
   to the string `"false"` or `"0"`, **Then** it evaluates to false (the
   `bool(os.environ.get(...))` foot-gun is eliminated).
6. **Given** the stale `frontend/Dockerfile` that uses `yarn` against a non-existent
   lockfile, **When** Phase 0 confirms it is unused and unsafe as-is, **Then** it is either
   fixed to use pnpm or removed, with the decision recorded.
7. **Given** the backend headless-Chromium screenshot tool that launches with
   `--no-sandbox`, **When** Phase 1 completes, **Then** its residual risk is documented as a
   known limitation with the explicit remediation deferred to the sandbox phase (it is NOT
   made safe in Phase 1, but it is NOT made worse and its constraints are recorded).

---

### User Story 3 - Centralized typed configuration (Priority: P1)

As a platform engineer, I need all backend configuration to be read once through a single
typed settings object with validation and clear defaults, so that environment-variable
access is controlled, misconfiguration fails fast, and later phases have one place to add
platform settings.

**Why this priority**: Constitution Principle XV (evidence, correctness) and a prerequisite
for the database, queue, and observability work, all of which introduce new configuration.
Scattered `os.environ.get(...)` calls and truthiness bugs are a current source of silent
misbehavior.

**Independent Test**: Start the backend with a valid configuration and confirm identical
behavior to today; start it with an invalid value (e.g. a non-numeric spend ceiling, a
malformed URL) and confirm it fails fast with a precise error naming the offending setting.

**Acceptance Scenarios**:

1. **Given** the backend, **When** it starts, **Then** every configuration value it uses is
   sourced from one typed settings module, not from ad-hoc `os.environ` reads scattered
   across modules.
2. **Given** an existing `.env` that works today, **When** the typed configuration is
   introduced, **Then** the backend's runtime behavior is unchanged (same provider
   selection, same feature-flag effects, same paths).
3. **Given** an invalid or missing-but-required configuration value, **When** the backend
   starts, **Then** startup aborts with a message identifying the setting and the expected
   shape.
4. **Given** the settings module, **When** a developer reads it, **Then** each setting has a
   declared type, a documented purpose, and a safe default (or is explicitly required), and
   the set matches the variables documented in `docs/LOCAL_DEVELOPMENT.md`.
5. **Given** boolean and numeric settings, **When** they are parsed, **Then** parsing is
   strict and unambiguous (no "any non-empty string is true").

---

### User Story 4 - Structured logging and correlation IDs (Priority: P2)

As a platform operator, I need backend logs to be structured (machine-parseable) and every
request and generation run to carry a correlation identifier that appears on all related log
lines, so that I can trace a single user action across the system and so that future AI/job
tracing has a foundation.

**Why this priority**: Constitution Principle X. Not a hard blocker for the queue work, but
required for it to be debuggable, and the earlier it lands the less `print`-based logging
accrues.

**Independent Test**: Issue a generation request, capture logs, and confirm every line
related to that request shares one correlation ID, is emitted as structured records, and
that no new `print`-style logging was added by Phase 1 code.

**Acceptance Scenarios**:

1. **Given** an incoming HTTP or WebSocket request, **When** it is handled, **Then** a
   request/correlation ID is generated (or accepted from a trusted inbound header) and
   attached to all log records produced while handling it.
2. **Given** a generation run, **When** it executes (in-process or via the worker), **Then**
   its logs carry both the request/correlation ID and a run/job identifier.
3. **Given** Phase 1 code, **When** it is reviewed, **Then** it contains no new
   `print`-based logging; new log output goes through the structured logger.
4. **Given** the structured logging foundation, **When** the queue/worker lands, **Then**
   correlation context propagates from the API to the worker so a run's logs on the worker
   can be joined to the originating request.
5. **Given** existing `print` statements in unchanged upstream modules, **When** Phase 1
   completes, **Then** they may remain (no forced rewrite, per Principle II), but a
   documented convention exists for replacing them opportunistically.

---

### User Story 5 - PostgreSQL and migration foundation in the dev stack (Priority: P2)

As a platform engineer, I need PostgreSQL available in the local development stack, a
migration tool wired up and runnable, and a data-access foundation (connection management,
session/transaction handling, health check), so that Phase 2 can add domain tables without
first building plumbing.

**Why this priority**: Constitution Principle III and TECHNICAL_DECISIONS D1. Greenfield —
there is no database to migrate. It is sequenced P2 because the queue work (US6) may depend
on job records, and because it is a precondition for all of Phase 2.

**Independent Test**: Bring up the dev stack, run the migration command to an empty
database, confirm it succeeds and is idempotent, run a "downgrade then upgrade" round trip,
and hit a backend health endpoint that reports database connectivity.

**Acceptance Scenarios**:

1. **Given** the documented dev stack, **When** a developer starts it, **Then** a PostgreSQL
   instance is available and its connection parameters come from the typed configuration
   (US3).
2. **Given** the migration tool, **When** a developer runs the upgrade command against an
   empty database, **Then** it applies cleanly, and running it again is a no-op.
3. **Given** the migration tool, **When** a developer runs a downgrade followed by an
   upgrade, **Then** the schema returns to the same state.
4. **Given** the data-access foundation, **When** the backend serves a request, **Then**
   database connections/sessions are acquired and released safely (no leaks) and a
   connection failure is surfaced as a clear, logged error rather than a crash loop.
5. **Given** Phase 1 scope, **When** migrations are inspected, **Then** they contain **no
   business or domain tables** (no users, orgs, projects, billing) — only what the
   infrastructure itself strictly requires (e.g. a job/run table if US6 needs durable job
   state, and the migration tool's own bookkeeping table).
6. **Given** the CI pipeline, **When** it runs, **Then** it can stand up PostgreSQL and
   apply migrations as part of the checks (so migration breakage is caught).

---

### User Story 6 - Asynchronous generation via a job queue with streamed events (Priority: P2)

As a platform engineer, I need generation to be able to run as a background job managed by a
worker process, with observable job status and lifecycle events, retry/failure handling, and
the WebSocket reduced to an event-streaming channel rather than the execution context — with
the new path introduced behind a controlled feature flag and the existing synchronous path
preserved until parity is proven.

**Why this priority**: Constitution Principles III, XII, XVI and TECHNICAL_DECISIONS A2/D3.
This is the largest and riskiest Phase 1 item. It unlocks resumability, multi-device
visibility, long runs, and per-tenant fairness later. It is sequenced after config, DB, and
logging because it depends on all three.

**Independent Test**: With the feature flag off, confirm generation behaves exactly as
today. With the flag on, submit a generation, observe a job created with a queryable status,
watch lifecycle and generation events stream to the client over the WebSocket, kill the
WebSocket mid-run and confirm the job continues and its terminal state is still queryable,
and force a worker error to confirm the failure is recorded and retried per policy.

**Acceptance Scenarios**:

1. **Given** the feature flag is disabled, **When** a user generates code, **Then** the flow,
   outputs, variant behavior, streamed event types, and timing are indistinguishable from
   the pre-Phase-1 behavior.
2. **Given** the feature flag is enabled, **When** a user submits a generation, **Then** a
   job is enqueued, a worker picks it up, and the job has a status that transitions through a
   defined lifecycle (e.g. queued → running → succeeded/failed/cancelled).
3. **Given** an enabled, running job, **When** the client is connected, **Then** generation
   events (the existing event vocabulary: variant count, model list, status, thinking,
   assistant output, tool start/result, set-code, variant complete/error, error) are
   streamed to it over the WebSocket, plus job-lifecycle events.
4. **Given** an enabled, running job, **When** the client WebSocket disconnects, **Then** the
   job is not cancelled by the disconnect alone; it runs to completion and its result and
   status remain retrievable.
5. **Given** an enabled job, **When** the user explicitly cancels, **Then** the job stops
   and its status becomes `cancelled` (preserving today's "close socket to cancel" as one
   trigger, but no longer the only mechanism).
6. **Given** a worker-side transient failure, **When** it occurs, **Then** the job is retried
   according to a documented, bounded retry policy; **When** retries are exhausted, **Then**
   the job is marked `failed` with a captured error and the client is notified (aligns with
   commit "Fail agent runs that finish without producing output").
7. **Given** the queue infrastructure, **When** the dev stack starts, **Then** Redis is
   available and at least one worker process is running and documented in
   `docs/LOCAL_DEVELOPMENT.md`.
8. **Given** the per-variant `$3` spend ceiling that exists today, **When** generation runs
   through the worker, **Then** that ceiling still applies unchanged.
9. **Given** at least one generation path (e.g. a single create variant, or a text-input
   generation), **When** it runs through the queue end to end, **Then** its output matches
   what the synchronous path produces for the same input (parity evidence, per the Migration
   Principle).

---

### User Story 7 - AI model registry foundation (Priority: P3)

As a platform engineer, I need a single abstraction that can represent providers, models,
and their metadata (capabilities, supported tasks, pricing/cost, context limits, modality
support, availability/status), initially populated to mirror the current `Llm` enum,
`MODEL_PROVIDER` map, pricing dict, and `model_choice_sets` behavior exactly — so that
Phase 2's router has something to build on without changing model selection now.

**Why this priority**: Constitution Principle V and TECHNICAL_DECISIONS A4. It is
architecture scaffolding with no user-visible effect; it is lowest risk and can land last.

**Independent Test**: Enumerate the registry and confirm it lists exactly the models the
current enum lists, with provider assignments matching `MODEL_PROVIDER` and cost metadata
matching the current pricing source; run the existing model-selection code paths and confirm
identical model choices for every key combination and create/update/video case.

**Acceptance Scenarios**:

1. **Given** the registry, **When** it is enumerated, **Then** it contains every model
   currently defined, each associated with its provider, and the set is verifiable against
   `llm.py` (a test fails if they diverge).
2. **Given** the registry schema, **When** it is inspected, **Then** it has defined fields
   for provider, model identity, capabilities, supported tasks, pricing/cost metadata,
   context limits, modality support, and availability/status — even if some fields are
   initially sparse or marked unknown.
3. **Given** the current model-selection logic, **When** the registry is introduced,
   **Then** selection behavior is unchanged: the same tuples are chosen for the same
   key-presence and create/update/video conditions (existing tests continue to pass; new
   tests pin the mapping).
4. **Given** cost/usage math that today reads a flat pricing dict, **When** the registry
   exposes pricing, **Then** the numbers are the same and the spend-ceiling behavior is
   unchanged.
5. **Given** the registry, **When** Phase 1 completes, **Then** it is documented as the
   intended single source of model metadata for Phase 2's router, and no routing/policy
   logic is added in Phase 1.

---

### Edge Cases

- **CI flakiness from external providers**: baseline checks MUST NOT call real AI providers;
  provider-dependent tests remain gated/mocked as they are today.
- **Windows vs. Linux dev parity**: Phase 0 ran on Windows with an untested Python; CI pins
  the supported version. Contributors on other versions must be able to follow
  `docs/LOCAL_DEVELOPMENT.md` to get parity.
- **Feature flag half-state**: if the queue flag is toggled while a job is in flight, the
  in-flight job completes under the mode it started in; new submissions use the current mode.
- **Redis unavailable with flag on**: generation submission fails fast with a clear error
  and (if practical) falls back to the synchronous path or surfaces an actionable message;
  it MUST NOT hang.
- **Database unavailable**: the generation experience with the queue flag *off* MUST still
  work if the database is only required by new infrastructure; the health endpoint reports
  the degraded dependency.
- **Correlation ID spoofing**: inbound correlation/trace headers are only trusted from
  configured upstreams; otherwise a fresh ID is minted.
- **Migration applied out of order / dirty state**: the migration tool detects and refuses
  to proceed on an inconsistent schema rather than corrupting it.
- **Sandbox attribute breaks a generated page**: some generated pages may rely on behavior a
  strict sandbox forbids; the acceptance bar is "no regression versus what upstream's
  non-sandboxed iframe allowed for the supported stacks," with any newly-blocked capability
  documented.
- **Existing `print` output parsers**: nothing currently parses stdout; adding structured
  logging alongside existing prints is safe.

---

## Requirements *(mandatory)*

### Functional Requirements

#### FR group A — CI / automated baseline

- **FR-A1**: The repository MUST have a CI pipeline that runs on every pull request targeting
  the main line of development.
- **FR-A2**: CI MUST run backend unit tests (`pytest`) and fail the pipeline on any test
  failure.
- **FR-A3**: CI MUST run backend type checking (`pyright`) and fail on new errors, and on
  new warnings in files changed by the PR (constitution Principle XIII).
- **FR-A4**: CI MUST run frontend unit tests and fail on any failure.
- **FR-A5**: CI MUST run the frontend production build and fail on build errors.
- **FR-A6**: CI MUST run frontend lint under a **documented lint policy** that is
  deterministic and prevents new violations from passing silently (see Assumptions for the
  proposed policy).
- **FR-A7**: CI MUST provision runtimes at pinned versions: a single supported Python
  version, a pinned Node version, and the pnpm version declared in `packageManager`.
- **FR-A8**: The pinned versions in CI MUST match the versions documented for local
  development, and `docs/LOCAL_DEVELOPMENT.md` MUST be updated to state the supported Python
  version authoritatively.
- **FR-A9**: CI MUST NOT require network access to external AI providers; tests needing
  provider keys remain skipped/mocked.
- **FR-A10**: CI MUST be able to stand up PostgreSQL and Redis as needed to run migration
  and queue checks (see FR-E6, FR-F-series).
- **FR-A11**: CI results (per-check pass/fail) MUST be visible on the pull request.

#### FR group B — Security hardening

- **FR-B1**: The frontend preview iframe MUST carry a `sandbox` attribute that excludes
  `allow-same-origin`, so generated scripts cannot access the host origin, its storage, or
  the parent window.
- **FR-B2**: The select-and-edit interaction MUST continue to function with the sandboxed
  preview, using an explicit cross-document message channel with origin/type validation on
  both ends.
- **FR-B3**: Backend CORS MUST be restricted to a configurable allow-list of origins; the
  simultaneous wildcard-origins-plus-credentials configuration MUST be removed.
- **FR-B4**: Evaluation and telemetry endpoints (`/evals/*`, `/eval-sets/*`,
  `/eval-sessions/*`, `/prompt-reports/*`, `/agent-runs/*`, `/run_evals*`,
  `/openai-input-compare`, `/models`, `/output_folders`, `/eval_input_files`) MUST be gated
  by an operator/admin access check when the platform is not in local-development mode.
- **FR-B5**: The access gate in FR-B4 MUST be the **minimum** needed to protect these
  endpoints (e.g. a shared operator token or an allow-list) and MUST NOT constitute a
  general authentication/authorization system (that is Phase 2, explicitly out of scope).
- **FR-B6**: All configuration booleans MUST be parsed such that `"false"`, `"0"`, `""`, and
  unset all evaluate to false, and only explicit truthy values evaluate to true. Existing
  flags `IS_PROD` and `IS_DEBUG_ENABLED` MUST be corrected.
- **FR-B7**: The stale `frontend/Dockerfile` MUST be corrected to use pnpm or removed, based
  on a recorded decision; the fix/removal MUST not break any path that is actually in use.
- **FR-B8**: The existing SSRF protections on `/api/export` and path-traversal guards on
  agent-run asset serving MUST be preserved (no regression).
- **FR-B9**: The `OPENAI_BASE_URL` override guard (disabled when production) MUST be
  preserved and MUST move to the typed configuration without weakening.
- **FR-B10**: Phase 1 MUST produce a written list of security capabilities that remain
  **disabled/unsafe pending the sandbox phase** (see Security Requirements) so that no later
  work assumes they are safe.

#### FR group C — Typed configuration

- **FR-C1**: The backend MUST load all configuration through a single typed settings
  module with per-field types, validation, and documented defaults.
- **FR-C2**: Direct `os.environ` / `os.getenv` reads for configuration outside the settings
  module MUST be eliminated from code paths in scope; any that remain in unchanged upstream
  modules MUST be inventoried.
- **FR-C3**: Introducing typed configuration MUST NOT change runtime behavior for a
  configuration that works today (behavior-preserving refactor).
- **FR-C4**: Invalid or missing required configuration MUST cause fast, explicit startup
  failure naming the offending setting.
- **FR-C5**: The settings module MUST cover, at minimum, the variables enumerated in
  `docs/LOCAL_DEVELOPMENT.md` §2, plus the new database and queue settings.
- **FR-C6**: Constants that are currently non-env (`NUM_VARIANTS`, `NUM_VARIANTS_VIDEO`,
  `GENERATION_MAX_COST_USD`) MUST be represented in the settings module with their current
  values as defaults, without changing effective values.

#### FR group D — Observability foundation

- **FR-D1**: The backend MUST emit logs as structured records (parseable key/value or JSON),
  with a configurable level.
- **FR-D2**: Every HTTP and WebSocket request MUST be assigned a correlation/request ID,
  minted locally unless supplied by a trusted upstream.
- **FR-D3**: The correlation ID MUST be attached to all log records emitted during handling
  of that request, including generation.
- **FR-D4**: Generation runs MUST additionally carry a run/job ID in their log context.
- **FR-D5**: When generation runs on the worker (US6), the correlation context MUST
  propagate from the API to the worker.
- **FR-D6**: Phase 1 code MUST NOT introduce new `print`-based logging.
- **FR-D7**: The logging foundation MUST be structured so that distributed tracing (spans
  across API → queue → worker → provider calls) can be added later without re-architecting
  it — Phase 1 delivers the seam, not the tracing backend.
- **FR-D8**: Correlation/request IDs SHOULD be surfaced to the client on error responses so
  a user-reported problem can be located in logs.

#### FR group E — Database foundation

- **FR-E1**: PostgreSQL MUST be part of the documented local development stack.
- **FR-E2**: Database connection parameters MUST come from the typed configuration.
- **FR-E3**: A migration tool MUST be configured with a runnable upgrade/downgrade workflow
  and its own version-tracking table.
- **FR-E4**: A baseline (possibly empty) migration MUST exist and apply cleanly to a fresh
  database; re-running MUST be a no-op.
- **FR-E5**: A data-access foundation MUST provide safe connection/session lifecycle
  (acquire/release, transaction boundaries) and MUST NOT leak connections.
- **FR-E6**: CI MUST apply migrations against a fresh PostgreSQL instance as a check.
- **FR-E7**: Migrations MUST NOT define business/domain tables. Permitted tables are limited
  to infrastructure needs (migration bookkeeping; and, only if US6 requires durable job
  state, a jobs/runs table with no tenant/user/org columns).
- **FR-E8**: A health endpoint MUST report database connectivity status.
- **FR-E9**: No authentication, authorization, organization, workspace, team, billing,
  subscription, credit, or project tables or logic may be introduced (out of scope).

#### FR group F — Job infrastructure

- **FR-F1**: Redis MUST be part of the documented local development stack.
- **FR-F2**: A background worker process MUST exist, be documented, and be startable
  locally and in CI.
- **FR-F3**: Generation MUST be executable as an asynchronous job dispatched to the worker.
- **FR-F4**: Each job MUST have a durable, queryable status reflecting a defined lifecycle:
  at minimum `queued`, `running`, `succeeded`, `failed`, `cancelled`.
- **FR-F5**: Job state transitions MUST be observable (queryable status and/or emitted
  lifecycle events with timestamps).
- **FR-F6**: The system MUST support a bounded, documented retry policy for transient job
  failures, and MUST mark a job `failed` with captured error detail when retries are
  exhausted.
- **FR-F7**: The WebSocket MUST become an **event-streaming channel**: it relays generation
  events and job-lifecycle events but is not the execution context and its lifetime does not
  bound the job's lifetime.
- **FR-F8**: A client disconnect MUST NOT, by itself, cancel a running job.
- **FR-F9**: Explicit user cancellation MUST stop the job and set status `cancelled`.
- **FR-F10**: The asynchronous path MUST be behind a feature flag (default off) so the
  existing synchronous path remains the default until parity is demonstrated.
- **FR-F11**: With the flag off, end-user generation behavior (event vocabulary, outputs,
  variants, spend ceiling, timing characteristics) MUST be unchanged.
- **FR-F12**: With the flag on, at least one complete generation path MUST run end to end
  through the queue and produce output equivalent to the synchronous path for the same
  input.
- **FR-F13**: The existing per-variant `GENERATION_MAX_COST_USD` ceiling MUST apply
  unchanged on the queued path.
- **FR-F14**: The generation event vocabulary emitted to the client MUST remain
  backward-compatible; new event types (job lifecycle) are additive.
- **FR-F15**: Job records MUST NOT carry tenant, user, organization, or billing fields
  (out of scope).

#### FR group G — AI model registry foundation

- **FR-G1**: A model registry abstraction MUST exist that can represent, per model:
  provider; model identity; capabilities; supported tasks; pricing/cost metadata; context
  limits; modality support; availability/status.
- **FR-G2**: The registry MUST be initially populated to mirror the current model set
  exactly (verifiable against `llm.py`), with provider assignments matching the current
  provider map.
- **FR-G3**: Introducing the registry MUST NOT change model-selection behavior: for every
  API-key-presence combination and for create/update/video, the same models are selected as
  today.
- **FR-G4**: Pricing/cost metadata exposed by the registry MUST equal the current pricing
  source's values; spend-ceiling behavior MUST be unchanged.
- **FR-G5**: Tests MUST pin the registry contents and the selection mapping so future
  drift from `llm.py` or `model_choice_sets.py` fails CI.
- **FR-G6**: No routing engine, capability-based selection, per-tenant overrides, or
  user-selectable models may be implemented in Phase 1 (Phase 2 scope).
- **FR-G7**: The registry MUST be documented as the intended single source of model
  metadata for later phases.

#### FR group H — Cross-cutting / guardrails

- **FR-H1**: The end-user generation experience MUST NOT change in any observable way as a
  result of Phase 1 (with feature flags at their default state).
- **FR-H2**: Existing backend tests (currently 276) and frontend tests (currently 42) MUST
  remain green, or any exception MUST be explicitly documented and approved.
- **FR-H3**: Every subsystem changed in Phase 1 MUST have its current behavior, target
  behavior, and migration strategy documented (Migration Principle).
- **FR-H4**: Risky changes MUST have tests added before or alongside them.
- **FR-H5**: Upstream MIT license, copyright, and attribution MUST remain intact
  (constitution Principle XVII).
- **FR-H6**: No functionality may be deleted or overwritten without evidence, a migration
  note, and tests (constitution Principle XVIII); confirmed-dead infrastructure (e.g. stale
  Dockerfile) is the only exception and still requires a recorded decision.
- **FR-H7**: Phase 1 MUST NOT introduce any capability listed in the Out of Scope section.
- **FR-H8**: New or updated architectural decisions MUST be recorded in
  `docs/TECHNICAL_DECISIONS.md` (constitution Principle XX); the discovery-era *PROPOSED*
  decisions that Phase 1 ratifies (D1 Postgres+Alembic, D3 queue, D6 Python pin, D10 CI, and
  the lint-baseline policy) MUST be marked ratified with their final form.

### Non-Functional Requirements

- **NFR-1 (Reproducibility)**: A second engineer, following `docs/LOCAL_DEVELOPMENT.md`,
  MUST be able to stand up the full dev stack (backend, frontend, PostgreSQL, Redis, worker)
  and run all baseline checks with results matching CI.
- **NFR-2 (Backward compatibility)**: With feature flags default, there MUST be zero
  regression in generation outputs, event stream, latency characteristics, or supported
  inputs.
- **NFR-3 (CI runtime)**: The CI baseline suite SHOULD complete in a timeframe that does not
  discourage frequent PRs (target: under ~15 minutes wall-clock; not a hard gate but a
  tracked metric).
- **NFR-4 (Fail-fast)**: Misconfiguration, missing infrastructure dependencies, and invalid
  migrations MUST fail with clear, actionable errors rather than hangs or silent degradation.
- **NFR-5 (No secret exposure)**: No configuration or logging change may cause secrets
  (provider keys, tokens) to be written to logs, error responses, or client payloads.
- **NFR-6 (Isolation)**: Phase 1 work MUST stay within this repository and its declared dev
  stack; it MUST NOT modify or depend on unrelated repos/services (constitution Principle
  XIX), including the closed-source `screenshot-to-code-saas` wrapper.
- **NFR-7 (Observability overhead)**: Structured logging and correlation-ID propagation MUST
  NOT materially degrade request latency (target: negligible, < a few milliseconds per
  request).
- **NFR-8 (Type safety)**: New backend code MUST be typed and pass `pyright` with no new
  warnings in changed files; new frontend code MUST pass lint under the agreed policy.
- **NFR-9 (Documentation currency)**: Any doc statement contradicted by Phase 1 changes MUST
  be updated in the same change (e.g. "no CI", "no database", "no Redis", recommended Python
  version).

### Security Requirements

- **SEC-1**: Generated code remains **untrusted**. Phase 1 MUST NOT create any new execution
  path for generated code and MUST NOT grant generated applications host filesystem, process,
  Docker, container-runtime, or root access.
- **SEC-2**: The frontend preview MUST be isolated via iframe sandboxing such that generated
  scripts cannot read the host app's storage, cookies, or reach `window.parent`/opener.
- **SEC-3**: Communication between the sandboxed preview and the host MUST be an explicit,
  minimal, origin- and type-validated message contract.
- **SEC-4**: CORS MUST be origin-restricted; credentialed wildcard access MUST be removed.
- **SEC-5**: Internal eval/telemetry/admin endpoints MUST be unreachable without an operator
  gate outside local development.
- **SEC-6**: Secrets MUST continue to be sourced from server-side configuration only for the
  host's own keys; Phase 1 does not add per-tenant secret storage (Phase 2) and does not
  change the existing browser-supplied-key mechanism for end users (that removal is Phase 2)
  — but Phase 1 MUST ensure browser-held keys are not readable by the (now sandboxed)
  preview.
- **SEC-7**: The following capabilities MUST remain **explicitly disabled / documented as
  unsafe until the dedicated sandbox phase (Phase 6)**:
  - executing generated full-stack apps or any generated server-side code;
  - running a real dev server for generated projects;
  - installing arbitrary packages for generated projects;
  - giving generated code network egress;
  - moving backend headless-browser rendering out of an unsafe `--no-sandbox` in-process
    model (its risk is *documented and contained*, not *fixed*, in Phase 1);
  - any visual-QA repair loop that executes generated code.
- **SEC-8**: The operator gate (SEC-5) MUST NOT be represented or reused as a user
  authentication system; it is a stopgap boundary only.
- **SEC-9**: Correlation/trace headers from untrusted clients MUST NOT be trusted for
  security decisions.
- **SEC-10**: A Phase 1 security review MUST confirm no new unsafe execution model was
  introduced and that all SEC-7 items are still closed.

### Architecture Requirements

- **AR-1**: The generation engine, provider adapters, canonical tool definitions, prompt
  pipeline, and cost math MUST be preserved and wrapped, not rewritten (constitution
  Principle II).
- **AR-2**: The job worker MUST wrap the existing engine invocation; the engine MUST remain
  runnable synchronously (flag off).
- **AR-3**: The WebSocket endpoint MUST be refactored toward "event channel bound to a
  run/session" semantics while keeping the existing client event contract.
- **AR-4**: Typed configuration MUST be the single entry point for environment-derived
  settings.
- **AR-5**: The data-access layer MUST be a thin foundation (connection/session/migrations)
  with no domain models.
- **AR-6**: The model registry MUST be a standalone module that the existing selection code
  can consult without inverting control yet (selection logic stays where it is in Phase 1,
  reading from the registry).
- **AR-7**: New infrastructure (DB, queue, worker) MUST be optional enough that
  flag-off local development still works if a developer only wants the generation UI —
  OR the added dependencies MUST be made trivial to run (documented compose stack). The
  chosen approach MUST be recorded.
- **AR-8**: Structured logging and correlation propagation MUST be implemented as
  cross-cutting middleware/context, not scattered per-handler code.
- **AR-9**: All new decisions and interfaces MUST be documented (constitution Principle XX).

### Data Requirements

- **DR-1**: The only persistent data stores introduced are PostgreSQL (schema managed by
  migrations) and Redis (ephemeral queue/coordination state).
- **DR-2**: If durable job state is required, a **jobs/runs** record MAY be stored with
  fields limited to: job ID, job type, status, timestamps (created/started/finished),
  attempt count, error summary, correlation ID, and a reference to input/output artifacts
  as already stored today (e.g. run-capture location). It MUST NOT include user, tenant,
  org, billing, or PII fields.
- **DR-3**: Existing local stores (design-systems JSON file, content-addressed asset dir,
  agent-run JSONL + SQLite telemetry index) MUST continue to work unchanged; migrating them
  to Postgres/object storage is Phase 2.
- **DR-4**: Redis MUST NOT be used as a system of record; losing Redis may lose in-flight
  queue state but MUST NOT corrupt PostgreSQL or completed outputs.
- **DR-5**: No schema element may encode multi-tenancy; Phase 2 introduces tenancy columns
  and isolation.
- **DR-6**: Data retention for job records follows existing telemetry norms (opt-in,
  prunable); Phase 1 does not add new retention obligations.

### API / Event Requirements

- **API-1**: The existing REST endpoints MUST keep their current paths and contracts, except
  for the addition of the operator gate on eval/telemetry endpoints (SEC-5).
- **API-2**: A health/readiness endpoint MUST report the status of new dependencies
  (database, queue/worker) without leaking connection details.
- **API-3**: The generation WebSocket MUST continue to accept the current request payload
  shape and MUST continue to emit the current event types; changes are additive only.
- **API-4**: New job-lifecycle events streamed over the WebSocket MUST have a documented
  schema (event type, job ID, status, timestamp, optional error).
- **API-5**: A way to query a job's current status/result MUST exist (e.g. a REST endpoint
  or a resend-on-connect over the event channel); the mechanism MUST be documented and MUST
  work after a client reconnect.
- **API-6**: If any new REST endpoints are added (job status, health), they MUST be
  documented and covered by tests.
- **API-7**: No API changes that presuppose auth, projects, orgs, or billing may be
  introduced.
- **API-8**: Correlation ID SHOULD be returned in a response header for HTTP requests.

### Job Lifecycle Requirements

- **JL-1**: Defined states: `queued`, `running`, `succeeded`, `failed`, `cancelled` (a
  `retrying` sub-state or attempt counter is acceptable).
- **JL-2**: Legal transitions: `queued → running`; `running → succeeded|failed|cancelled`;
  `running → queued` (on retry) or `running → retrying → running`; terminal states do not
  transition.
- **JL-3**: Each transition MUST record a timestamp and (for failures) an error summary.
- **JL-4**: A job stuck in `running` beyond a configured maximum MUST be detectable and
  moved to `failed` (watchdog/timeout), consistent with today's engine `max_steps` and
  spend ceiling.
- **JL-5**: Cancellation MUST be cooperative and bounded (a cancelled job stops within a
  documented time budget).
- **JL-6**: Job events MUST be emitted in an order consistent with the state machine.
- **JL-7**: Terminal job state and outputs MUST be retrievable independently of the
  originating WebSocket connection.
- **JL-8**: Retry attempts MUST be bounded and logged; the retry policy (max attempts,
  backoff, which errors are retryable) MUST be documented.
- **JL-9**: The synchronous (flag-off) path is not required to expose the full lifecycle
  API, but MUST not regress from current behavior.

### Observability Requirements

- **OB-1**: Structured logs with configurable level across the backend.
- **OB-2**: Correlation/request ID on every request, propagated to all related log lines and
  to the worker.
- **OB-3**: Run/job ID in generation log context.
- **OB-4**: No new `print` logging in Phase 1 code; a documented convention for replacing
  legacy prints opportunistically.
- **OB-5**: Health endpoint covering DB and queue/worker liveness.
- **OB-6**: Job lifecycle is observable via status query and/or events with timestamps.
- **OB-7**: The logging/context design MUST be tracing-ready (able to carry trace/span IDs
  later) — the hook exists even though no tracing backend is wired in Phase 1.
- **OB-8**: Errors surfaced to clients SHOULD include the correlation ID for support
  triage.
- **OB-9**: The existing opt-in run-capture feature (`PROMPT_REPORTS_ENABLED`) MUST keep
  working on both the sync and queued paths.

### Key Entities

- **Setting**: a single typed configuration value — name, type, default/required, purpose,
  validation rule. Collectively the typed settings object.
- **Job / Run**: an asynchronous unit of generation work — identity, type, status,
  lifecycle timestamps, attempt count, error summary, correlation ID, link to existing
  input/output artifacts. No tenant/user fields.
- **Job Event**: a lifecycle notification — job ID, event type, status, timestamp, optional
  error. Streamed over the event channel; additive to the existing generation event
  vocabulary.
- **Generation Event** (existing, unchanged): variant count, variant models, status,
  thinking, assistant output, tool start/result, set-code, variant complete/error, error.
- **Model Registry Entry**: provider, model identity, capabilities, supported tasks,
  pricing/cost metadata, context limits, modality support, availability/status. Mirrors the
  current `Llm` set on day one.
- **Migration**: a versioned, reversible schema change with an applied/not-applied state
  tracked in a bookkeeping table. Phase 1 ships only infrastructure migrations.
- **Correlation Context**: request/correlation ID plus (when applicable) run/job ID, carried
  through logging and across the API→worker boundary.
- **Operator Access Gate**: the minimal boundary protecting eval/telemetry/admin endpoints
  outside local dev. Not a user identity system.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On every pull request, the CI pipeline executes all five baseline check
  categories (backend tests, backend type check, frontend tests, frontend build, lint) and
  blocks merge on failure — verified by one passing PR and one deliberately failing PR.
- **SC-002**: 100% of backend configuration values consumed at runtime are read through the
  single typed settings module — verified by a code audit / test asserting no stray
  environment reads in in-scope modules.
- **SC-003**: A generation request produces log records that all share one correlation ID,
  and that ID is returned to the client on errors — verified by inspecting logs for a sample
  request.
- **SC-004**: A developer can bring up PostgreSQL in the dev stack and apply all migrations
  to an empty database in a single documented command, idempotently — verified by a
  clean-machine run and by CI.
- **SC-005**: The migration tool performs a downgrade→upgrade round trip returning the schema
  to an identical state — verified by an automated check.
- **SC-006**: Redis is available in the dev stack and at least one worker process starts and
  reports healthy via the health endpoint — verified by a clean-machine run.
- **SC-007**: With the queue feature flag enabled, at least one full generation path runs
  end to end as a background job and yields output equivalent to the synchronous path for
  the same input — verified by a parity test.
- **SC-008**: A job's status and final result remain retrievable after the originating
  WebSocket is forcibly closed mid-run — verified by an automated test.
- **SC-009**: A forced transient worker failure results in bounded retries and a final
  `failed` state with a captured error — verified by an automated test.
- **SC-010**: Generation events stream to the client over the WebSocket for a queued job,
  using the existing event vocabulary plus documented job-lifecycle events — verified by an
  integration test.
- **SC-011**: With all feature flags at default, end-user generation output, event stream,
  and supported inputs are byte-for-byte / event-for-event unchanged versus the pre-Phase-1
  baseline for a fixed set of sample inputs — verified by comparison tests.
- **SC-012**: The model registry enumerates exactly the models in `llm.py` with matching
  provider assignments and pricing, and model selection is identical for every
  key-combination and create/update/video case — verified by pinned tests that fail on
  divergence.
- **SC-013**: The full existing test suite (276 backend + 42 frontend) passes on the pinned
  runtimes, or every exception is listed and approved in writing.
- **SC-014**: Every Phase 0 security-hardening item (preview sandbox, preview↔host messaging,
  CORS restriction, eval/telemetry endpoint gating, config boolean correctness, stale
  Dockerfile resolution) is demonstrably addressed, and a written list of
  sandbox-phase-deferred unsafe capabilities exists — verified against the FR group B and
  SEC-7 checklists.
- **SC-015**: A reviewer confirms no Out-of-Scope capability (auth, orgs, workspaces, teams,
  billing, credits, project management, Application IR, full-stack generation, new engine,
  frontend redesign, deployment infra, sandboxed/unrestricted generated-code execution,
  visual repair loops) was introduced — verified by a scoped diff review against the Out of
  Scope list.
- **SC-016**: A second engineer stands up the entire dev stack and reproduces CI results
  locally following `docs/LOCAL_DEVELOPMENT.md`, with no undocumented steps — verified by a
  fresh-environment walkthrough.
- **SC-017**: No secret value appears in any log record, error response, or client payload
  across the sync and queued paths — verified by a secret-scanning test over captured output.

---

## Migration Constraints

Per the Migration Principle, each subsystem changed in Phase 1 carries a documented
current → target → strategy record. The binding constraints:

- **MC-1**: Prefer incremental migration over rewrite for every subsystem (constitution
  Principle II).
- **MC-2**: For each changed subsystem, document: current behavior, target behavior,
  migration strategy, backward-compatibility approach, and the tests that protect the
  transition.
- **MC-3**: The synchronous generation path MUST remain fully functional until the queued
  path has demonstrated parity; removal of the sync path is **not** in Phase 1.
- **MC-4**: The client-facing generation event contract is frozen for Phase 1 — additive
  changes only.
- **MC-5**: Configuration migration MUST be behavior-preserving; a working `.env` keeps
  working.
- **MC-6**: The `Llm` enum, `MODEL_PROVIDER`, pricing source, and `model_choice_sets`
  remain the authoritative inputs the registry mirrors; the registry does not replace them
  in Phase 1.
- **MC-7**: Legacy `print` logging is migrated opportunistically, not in a big-bang sweep.
- **MC-8**: Any removed artifact (e.g. stale Dockerfile) requires a recorded decision and
  confirmation it is unused.
- **MC-9**: Risky changes get tests first or alongside (constitution Principle XIII, FR-H4).
- **MC-10**: Existing local data stores are untouched; their migration is Phase 2.

---

## Dependencies

- **DEP-1**: A CI provider (GitHub Actions, per the repo's existing `.github/` usage).
- **DEP-2**: A pinned, supported Python version (Phase 0 recommends 3.12 to match upstream
  Docker — TECHNICAL_DECISIONS D6).
- **DEP-3**: Node (pinned) and pnpm at the `packageManager` version.
- **DEP-4**: PostgreSQL (local via the dev stack; ephemeral in CI).
- **DEP-5**: A migration tool (Alembic, per TECHNICAL_DECISIONS D1).
- **DEP-6**: Redis (local via the dev stack; ephemeral in CI).
- **DEP-7**: A Python task/queue runner (choice among Celery / Dramatiq / arq deferred to
  the plan — TECHNICAL_DECISIONS D3).
- **DEP-8**: The existing provider SDKs and generation engine (unchanged).
- **DEP-9**: Decisions to be ratified from discovery: D1 (Postgres+Alembic), D3 (queue),
  D6 (Python pin), D10 (CI), and the lint-baseline policy.
- **DEP-10**: `docs/LOCAL_DEVELOPMENT.md`, `docs/TECHNICAL_DECISIONS.md`,
  `docs/LG_TELECOMS_APP_BUILDER_ARCHITECTURE.md`, `docs/ROADMAP.md`, and
  `.specify/memory/constitution.md` as authoritative inputs.
- **DEP-11**: No dependency on the closed-source `screenshot-to-code-saas` wrapper
  (NFR-6).

---

## Risks

- **RISK-1 (Queue scope creep)**: The job infrastructure is large; it could absorb Phase 2
  concerns (projects, persistence of user work). *Mitigation*: strict feature-flag boundary,
  no tenant/user fields, parity-only success bar, single generation path in scope.
- **RISK-2 (Preview sandbox regressions)**: A strict `sandbox` attribute may break generated
  pages or select-and-edit. *Mitigation*: build the origin-checked message channel first;
  acceptance bar is "no regression vs. upstream's non-sandboxed behavior for supported
  stacks"; document any newly-blocked capability.
- **RISK-3 (Prompt-cache disruption)**: Refactoring config/logging near prompt assembly can
  silently hurt Anthropic prompt-cache hit rates. *Mitigation*: do not touch prompt assembly
  ordering; add a cache-hit-rate check to the parity tests.
- **RISK-4 (Runtime pin churn)**: Contributors on Python 3.13/3.14 (as on the discovery
  machine) must switch to the pinned version. *Mitigation*: document clearly; keep `^3.10`
  compatibility; provide uv/pyenv guidance.
- **RISK-5 (Lint policy stall)**: The 19 pre-existing lint errors could block CI adoption.
  *Mitigation*: adopt the ratchet policy (see Assumptions) so CI can land immediately.
- **RISK-6 (CI fl/ provider calls)**: Tests that hit providers would make CI flaky/costly.
  *Mitigation*: keep provider tests gated/mocked; assert no network in CI.
- **RISK-7 (Dev-stack friction)**: Adding Postgres + Redis + a worker raises the barrier to
  local development. *Mitigation*: a one-command compose stack; keep flag-off generation
  working with minimal dependencies where feasible (AR-7).
- **RISK-8 (Correlation-ID trust)**: Accepting inbound trace headers naively is a spoofing
  vector. *Mitigation*: only trust configured upstreams; otherwise mint fresh.
- **RISK-9 (Accidental Phase 2 leakage)**: A jobs table or health endpoint could grow
  tenant/auth fields. *Mitigation*: explicit DR-2/DR-5 constraints and a scoped diff review
  (SC-015).
- **RISK-10 (Behavioral drift undetected)**: Without good parity tests, subtle regressions
  slip through. *Mitigation*: fixed sample-input comparison suite covering outputs, events,
  and cache behavior (SC-011).
- **RISK-11 (`--no-sandbox` browser misread as "fixed")**: Someone may assume Phase 1 made
  backend rendering safe. *Mitigation*: SEC-7 explicitly lists it as deferred; security
  review checks (SC-014, SEC-10).

---

## Out of Scope

Phase 1 MUST NOT implement any of the following (each is a later phase):

- Authentication (user login, sessions, OIDC/OAuth) — *Phase 2*.
- Authorization system beyond the minimal operator gate on internal endpoints — *Phase 2*.
- Organizations, workspaces, teams, memberships, roles, invitations — *Phase 2*.
- Billing, subscriptions, usage billing, AI credit system, spend budgets beyond the
  existing per-variant ceiling — *Phase 9*.
- Full project management (server-owned projects, project versions replacing client
  `commits`, sharing) — *Phase 2 / 7*.
- Application IR (any implementation; the registry is not an IR) — *Phase 3*.
- Full-stack application generation, multi-file generation, repo import — *Phase 4*.
- A new generation engine or a rewrite of the existing engine/adapters/tools/prompt
  pipeline — *never (Principle II); evolution only*.
- Frontend redesign / IDE re-scoping / multi-project navigation — *Phase 2+*.
- Deployment infrastructure, IaC, production Kubernetes, managed deploy targets — *Phase 8 /
  10*.
- Any unrestricted or privileged execution of generated code; running generated dev servers;
  package installation for generated projects; network egress for generated code — *Phase
  6*.
- Visual QA comparison and repair loops — *Phase 5*.
- Production sandbox architecture (Docker/Firecracker/gVisor isolation tier) — *Phase 6*.
- Per-tenant secrets management; removal of browser-supplied provider keys — *Phase 2*.
- Migration of existing local data stores (design systems, assets, telemetry) to
  Postgres/object storage — *Phase 2*.
- A capability-based model router, per-org model overrides, user-selectable models — *Phase
  2*.
- Distributed tracing backend / metrics platform / error-tracking integration (only the
  logging seam is in scope) — *Phase 10*.

---

## Phase 1 Completion Gate

Phase 1 is **complete only when every item below is true and evidenced**:

1. **CI runs the baseline** — backend tests, `pyright`, frontend tests, frontend build, and
   lint (under the documented policy) execute on every PR and block merge on failure, on
   pinned runtimes. *(SC-001, SC-013, FR-A*)*
2. **Configuration is centralized and typed** — one typed settings module; no scattered
   environment reads in in-scope code; invalid config fails fast; behavior preserved.
   *(SC-002, FR-C*)*
3. **Structured logging & trace foundations exist** — structured logs, correlation IDs per
   request propagated to logs and the worker, run/job IDs in generation context, no new
   `print` logging, tracing-ready context. *(SC-003, FR-D*, OB-*)*
4. **PostgreSQL is available in the dev stack** — documented, config-driven, health-checked.
   *(SC-004, SC-006, FR-E1/E2/E8)*
5. **Alembic infrastructure is functional** — runnable upgrade/downgrade, clean apply to
   empty DB, idempotent, round-trip verified, exercised in CI, no domain tables.
   *(SC-004, SC-005, FR-E3–E7)*
6. **Redis is available** — documented, config-driven, in the dev stack and CI. *(SC-006,
   FR-F1)*
7. **A worker process is operational** — documented, startable locally and in CI, health
   reported. *(SC-006, FR-F2)*
8. **At least one generation path executes through the job queue without breaking existing
   functionality** — behind a default-off flag; parity demonstrated; sync path intact.
   *(SC-007, SC-011, FR-F3/F10–F13, MC-3)*
9. **Job lifecycle/status is observable** — defined state machine, queryable status,
   timestamped transitions, bounded retries, terminal state retrievable after disconnect.
   *(SC-008, SC-009, FR-F4–F9, JL-*)*
10. **Generation events can be streamed to the client** — existing event vocabulary
    preserved, job-lifecycle events additive and documented, works on reconnect. *(SC-010,
    FR-F7/F14, API-3–API-5)*
11. **Existing model-selection behavior is unchanged** — verified across all key
    combinations and create/update/video. *(SC-012, FR-G3)*
12. **The AI provider/model registry architecture is defined** — a registry abstraction with
    all required metadata fields, populated to mirror `llm.py`, pinned by tests, documented
    as the Phase 2 router's source. *(SC-012, FR-G1–G7)*
13. **Existing tests are green or exceptions are documented and approved.** *(SC-013,
    FR-H2)*
14. **Phase 0 security hardening is addressed** — preview sandbox, origin-checked
    preview↔host messaging, restricted CORS, gated eval/telemetry endpoints, corrected
    config booleans, resolved stale Dockerfile — and a written list of
    sandbox-phase-deferred unsafe capabilities exists; a Phase 1 security review confirms no
    new unsafe execution model. *(SC-014, SC-017, FR-B*, SEC-*)*
15. **No Phase 2+ functionality was introduced** — confirmed by a scoped diff review against
    the Out of Scope list. *(SC-015)*
16. **Reproducibility** — a second engineer reproduces the full stack and CI results from
    the docs; all affected docs are updated. *(SC-016, NFR-1, NFR-9)*
17. **Decisions recorded** — D1, D3, D6, D10 and the lint policy are marked ratified in
    `docs/TECHNICAL_DECISIONS.md`; new interfaces (settings, job lifecycle, event schema,
    registry) are documented. *(FR-H8, AR-9)*

---

## Assumptions

- **A-1 (Python pin)**: Phase 1 pins CPython **3.12** for dev and CI, matching the upstream
  Docker image, per TECHNICAL_DECISIONS D6. `pyproject.toml` keeps `^3.10` compatibility.
- **A-2 (CI provider)**: GitHub Actions, consistent with the repo's existing `.github/`
  contents and TECHNICAL_DECISIONS D10.
- **A-3 (Lint policy — "ratchet")**: CI adopts lint immediately with the current 19
  errors / 6 warnings captured as a frozen baseline; the pipeline fails if the count
  increases or new rule violations appear, and the baseline may only shrink. The 19
  `no-explicit-any` / `no-case-declarations` errors are scheduled for fix-forward but do not
  block CI landing. This is the "clear lint policy" the scope asks for. (Alternative —
  fix all 19 first — is acceptable if the team prefers; the plan decides.)
- **A-4 (Queue runner)**: The specific task runner (Celery vs. Dramatiq vs. arq) is a
  plan-level decision; the spec only requires the capabilities in FR group F / JL.
- **A-5 (Operator gate form)**: A shared operator token (from typed config) or an
  IP/origin allow-list is sufficient for SEC-5; it is explicitly a stopgap, not auth.
- **A-6 (Dev stack delivery)**: New infrastructure (Postgres, Redis, worker) is delivered as
  a documented one-command local stack (e.g. an updated compose file); the exact tooling is
  a plan decision.
- **A-7 (Generation path for parity)**: "At least one generation path" through the queue
  means one representative end-to-end flow (e.g. a single-variant create from a text prompt
  or a screenshot); covering all input modes/variants through the queue is not required in
  Phase 1.
- **A-8 (Job persistence)**: Durable job state lives in PostgreSQL; Redis carries only
  transient queue/coordination state (DR-1, DR-4).
- **A-9 (Health endpoint)**: A single readiness endpoint reports DB and queue/worker
  status; it does not expose credentials or internal topology.
- **A-10 (Backend headless browser)**: The `--no-sandbox` in-process screenshot tool is left
  functionally as-is; Phase 1 only documents its risk and constraints and defers the fix to
  Phase 6.
- **A-11 (Frontend changes)**: Frontend work is limited to the preview `sandbox` attribute
  and the preview↔host message channel; no other frontend changes are in scope.
- **A-12 (No behavior change visible to end users)**: All new paths ship behind flags
  defaulted off; the "no observable change" bar (FR-H1, NFR-2, SC-011) is measured with
  flags at default.
- **A-13 (Existing local stores)**: Design-systems JSON, content-addressed assets, and
  agent-run telemetry remain file/SQLite-based in Phase 1.
- **A-14 (Correlation header trust)**: Only requests from a configured trusted proxy list
  may supply their own correlation/trace IDs.
