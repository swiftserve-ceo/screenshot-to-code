# LG Telecoms App Builder — Roadmap

> **Status:** Draft, produced during Phase 0 discovery. Phases after 0 are
> **not approved for implementation**. This is a sequencing proposal, not a
> commitment or a schedule. Estimates are rough order-of-magnitude for a small
> team and exist only to convey relative size.

## Principles

1. **Preserve the working engine.** The agent loop, provider adapters, canonical
   tools, prompt pipeline, cost math and eval tooling are assets. Wrap and
   extend them; do not rewrite them.
2. **Add the platform shell around the engine, not through it.** Auth, tenancy,
   persistence, billing and sandboxing are new layers that the existing
   generation code should barely notice.
3. **Every phase ships something usable** and leaves the app in a runnable state
   with green tests.
4. **Security-relevant capabilities (sandboxing, secrets, auth) land before the
   capabilities that make them urgent** (public multi-tenant use, full-stack
   code execution, deployment).
5. **The Application IR is de-risked with spikes before it becomes load-bearing.**

---

## PHASE 0 — Foundation / Discovery  *(this phase)*

**Goal:** understand the inherited system; establish architecture, decisions,
roadmap and a reproducible local dev baseline. **No product code changes.**

- [x] Full repository inventory and subsystem map
- [x] Baseline checks run and recorded (backend pytest, pyright; frontend lint,
      jest, build) — see summary + LOCAL_DEVELOPMENT.md
- [x] `docs/LG_TELECOMS_APP_BUILDER_ARCHITECTURE.md`
- [x] `docs/ROADMAP.md`
- [x] `docs/TECHNICAL_DECISIONS.md`
- [x] `docs/LOCAL_DEVELOPMENT.md`
- [ ] Team review + sign-off on target architecture and Phase 1 scope
- [ ] Fill in `.specify/memory/constitution.md` (still the stock template)

**Exit criteria:** docs reviewed; Phase 1 scope agreed; a second engineer can
stand the app up locally from LOCAL_DEVELOPMENT.md.

---

## PHASE 1 — Core Platform Architecture

**Goal:** introduce the skeleton every later phase depends on, without changing
the end-user generation experience yet.

- [x] Choose and stand up **Postgres + Alembic**; introduce a data-access layer.
- [x] Introduce a **job queue** (Redis-backed) and a worker process; move a
  single generation path onto it behind a flag, keeping the WebSocket for events.
- [~] Split the realtime channel: **events over WS/SSE per *AI session*;
  resources over REST.** — done for the queued `text→create` path (relay +
  `/api/jobs/{id}` + `/api/models`); the other paths are still WS-scoped.
- [x] Extract config into a typed settings module (`pydantic` v2 `BaseModel`),
  remove implicit `bool(os.environ.get(...))` foot-guns; remaining `os.environ`
  reads in app code moved behind `settings` (Batch 4).
- [x] Introduce **structured logging** + request/trace IDs; runtime `print()`s
  migrated (Batch 4 finished the provider / `fs_logging` / route / eval-core set).
- [x] Stand up **CI**: backend `pytest` + `pyright` + `alembic check` +
  service-container queue smoke test; frontend `test` + `lint:ratchet` + `build`.
- [x] Establish the **model registry** — typed, derived `backend/model_registry/`
  + `GET /api/models` (capability discovery, secret-free); `factory.py` and
  `model_selection.py` consume it. Selection behaviour unchanged.
- [x] Address the cheap standalone **P0 hardening** items: preview `sandbox`,
  CORS allow-list, operator gate on `/evals*` `/agent-runs*` `/prompt-reports*`
  `/eval-sets*`, repaired `frontend/Dockerfile`.
- [x] **Python 3.12** target across `pyproject.toml` / `.python-version` /
  pyright / Dockerfile / CI (local 3.13 still permitted).
- [x] **FastAPI `lifespan`** replaces `@app.on_event`.
- [x] **Job lifecycle** hardening — idempotent terminals, RUNNING re-acquire
  after a worker crash, opt-in `JOB_RETENTION_DAYS` pruning via a daily cron.
- [x] **Queue failure modes** A–F covered by tests.

**Size:** L. **Exit criteria:** a generation can run through the queue/worker
with events streamed to the client; CI green; Postgres in the dev stack.

**Progress (remediation batches — see `docs/REMEDIATION_LOG.md`):**

- **Batch 1 (2026-09-02)** — preview iframe sandboxing + postMessage bridge,
  CORS allow-list, operator gate on `/evals*` `/agent-runs*` …, strict env-bool
  parsing, typed `Settings` (`config.py`, on `pydantic` v2), structured logging +
  request-id correlation, `frontend/Dockerfile` repaired.
- **Batch 2 (2026-09-02)** — GitHub Actions CI (+ lint ratchet), PostgreSQL +
  async SQLAlchemy 2.0 + Alembic (baseline `jobs` table only), Redis, **arq**
  worker (D3 ratified), job model + `JobEventChannel`, `/health`. Generation not
  yet queued.
- **Batch 3 (2026-09-02)** — ✅ **first generation path queued**: `text → create`
  runs API → job → Redis/arq → independent worker → `JobEventChannel` → WS relay
  → frontend, behind `JOB_QUEUE_ENABLED` (default off). WebSocket disconnect ≠
  cancel; reconnect replays the event backlog; `GET /api/jobs/{id}` for status.
  Missing credentials → controlled failure (no crash, no retry).
- **Batch 4 (2026-09-02)** — Python-3.12 consistency; typed **model registry**
  (`model_registry/` + `GET /api/models`, derived + secret-free);
  `os.environ`/config cleanup; **`lifespan`** migration; job-lifecycle hardening
  (idempotent terminals, RUNNING re-acquire) + **opt-in retention** cron;
  queue failure-mode tests (A–F); CI **`alembic check`** + a **live queue smoke
  test** (real burst worker, no AI); the duplicate-error-toast fix
  (`_Forwarder._error_sent` + `generateCode.test.ts`); security review (worker
  can no longer render generated code — `screenshot_preview` disabled in worker
  context) + logging review (runtime `print()`s migrated). 621 backend tests.

**Still open in Phase 1 → Phase 2:** the remaining generation paths (image /
multi-image / URL / video / **edit**) are still synchronous; the queued path uses
**server** provider keys only (per-tenant secrets = Phase 2); no
watchdog/reaper for a job whose worker vanished without arq re-queueing; CI has
not yet run on a real GitHub Actions host; the model registry has no runtime
admin toggle. **Phase 2 depends on:** the `jobs` table + `JobService` state
machine, the `JobEventChannel` relay contract, the model registry
(`to_public_dict` shape), typed `settings`, and CI being green.

---

## PHASE 2 — Project & Workspace System

**Goal:** the server owns projects. `Organization → Workspace → Project` with
membership and roles.

- Schema + APIs for `organizations`, `workspaces`, `projects`, `memberships`,
  `roles` (Platform Super Admin, Org Owner, Org Admin, Developer, Designer,
  Viewer), `invitations`.
- **AuthN**: OIDC login, session cookies for the SPA; **remove provider keys
  from the browser**.
- **AuthZ**: a policy layer (`can(user, action, resource)`), enforced in the API
  gateway; multi-tenant isolation in Postgres (RLS or schema-per-org — decision
  in TECHNICAL_DECISIONS.md, resolved here).
- **Per-tenant secrets**: provider keys stored server-side in a secrets manager,
  selected by the router at generation time.
- Migrate the client `commits`/`variants` model to server-side
  `project_versions` + `variants`; the frontend becomes project-centric
  (org/workspace/project navigation).
- Move **design systems** from the global JSON file to per-workspace rows.
- Move **assets** to object storage, tenant-scoped, signed URLs.
- **Audit log** table + emit points for membership/role/key/version events.

**Size:** XL. **Exit criteria:** two orgs cannot see each other's projects,
assets, or design systems; refresh no longer loses work; no API key touches the
browser.

---

## PHASE 3 — AI Application Generation (Understanding → Analysis → Planning → IR spike)

**Goal:** turn the implicit "prompt the LLM with a screenshot" flow into explicit,
inspectable stages; de-risk the IR.

- **Understanding** stage: structured extraction from inputs (layout, text,
  components, asset inventory) persisted as an `Understanding` record. Reuse the
  Gemini asset-extraction work.
- **Analysis** stage: design tokens, information architecture, routes, candidate
  data entities → `Analysis` record.
- **Planning** stage: a human-reviewable build plan.
- **URL input**: replace the `screenshotone.com` proxy with an owned crawler +
  sandboxed capture (multi-page, DOM + screenshot).
- **Figma import**: read the Figma file API → Understanding record.
- **IR spike (timeboxed):** prototype the `AppIR` for the *existing* 6 stacks;
  prove compile-IR→HTML and lift-HTML→IR round-trips on 10 reference inputs;
  decide LLM-authored vs. derived. Ship the IR as the source of truth for the
  single-file stacks only.
- Generation targets the IR for those stacks; `edit_file` reframed as a scoped
  IR edit where it pays off.

**Size:** XL. **Exit criteria:** a screenshot produces a reviewable
Understanding + Analysis + Plan; the single-file stacks regenerate from a stored
IR; URL and Figma inputs work end-to-end.

---

## PHASE 4 — Full-Stack Generation

**Goal:** go beyond one HTML file.

- IR extensions for data models, APIs, auth, env vars, dependencies, DB schema.
- One or two **full-stack target stacks** (e.g. Next.js + a DB) with their own
  IR compilers and project scaffolds.
- **Multi-file generation** from the IR; the agent's file tools become
  multi-file aware.
- **Repo import** as an input: lift an existing codebase into an IR + project.
- Package/dependency management and lockfile generation per project.

**Size:** XL. **Depends on:** Phase 6 sandboxing for any build/run step.
**Exit criteria:** a prompt produces a running multi-file full-stack app inside a
sandbox.

---

## PHASE 5 — Visual QA & Repair

**Goal:** close the generate → preview → screenshot → compare → diagnose →
repair → re-run loop.

- Promote `preview_screenshot` into a **QA service**: capture at multiple
  viewports, structural + pixel diff against the target design, discrepancy
  localization.
- Map QA findings to IR nodes; generate scoped **repair tasks** with their own
  budget caps (extend the `$3` ceiling concept to a repair budget).
- Convergence controls: max repair iterations, "good enough" thresholds,
  human override.
- Surface QA results and diffs in the UI as a first-class project tab.

**Size:** L. **Depends on:** Phases 3 (IR) and 6 (sandboxed preview).

---

## PHASE 6 — Sandboxed Execution

**Goal:** treat all generated code as untrusted; never run it with ambient
privileges.

- A **sandbox pool** (Docker first; evaluate Firecracker/gVisor) hosting:
  preview dev servers, Playwright QA runs, generated test runs.
- Hard **CPU / memory / PID / wall-clock** limits; **no network egress by
  default** (allowlist per run); read-only base FS + scratch volume;
  **secrets injected per-run**, never in images or layers.
- **Approval gates** for dangerous operations (outbound network, package
  install from non-allowlisted registries, shell in a running app).
- The frontend preview iframe points at a **sandbox-hosted URL** and carries a
  `sandbox` attribute.
- Backend headless-Chromium screenshotting moves into the sandbox tier (out of
  the API process).

**Size:** XL. **Note:** the P0 iframe-`sandbox` fix lands in Phase 1; this phase
is the full isolation tier for *executing* generated apps.

---

## PHASE 7 — Collaboration & Versioning

**Goal:** teams work on projects together with a real history.

- `project_versions`, **snapshots**, **checkpoints**, **rollback**, branch/merge
  semantics for the IR.
- **AI session history** as a durable, browsable aggregate (turns, tool calls,
  tokens, cost) — replaces per-run JSONL as the primary store.
- Comments / review on versions; presence; per-project activity feed.
- Change history diffing at the IR level.

**Size:** L. **Depends on:** Phases 2–3.

---

## PHASE 8 — Deployment

**Goal:** ship the generated app.

- Export targets: **zip** (exists), **GitHub** (create repo + push via a GitHub
  App installation), **managed deploy** (static/edge for single-file & SPA
  stacks; container host for full-stack).
- Per-project environments (preview / production), env-var management tied to
  the secrets manager.
- Deploy history + rollback; custom domains.

**Size:** L. **Depends on:** Phases 4, 6.

---

## PHASE 9 — Billing / Usage / Enterprise

**Goal:** monetize and gate.

- Subscription tiers; **AI credits** metered from `TokenUsage` × `MODEL_PRICING`
  (the math already exists).
- Storage quotas, seat limits, per-org spend caps with soft/hard enforcement and
  alerts.
- Payment integration (Stripe or equivalent), invoices, dunning.
- Enterprise: SSO/SAML, SCIM provisioning, audit-log export, IP allowlists,
  data-residency options.
- Admin console for Platform Super Admins (usage, abuse, impersonation with
  audit).

**Size:** L. **Depends on:** Phase 2 (audit, orgs), Phase 6 (spend is real once
code executes).

---

## PHASE 10 — Production Hardening

**Goal:** run it for real.

- Full OpenTelemetry tracing; SLOs + alerting; error tracking.
- Load/perf testing of the generation queue and sandbox pool; autoscaling.
- Backup/restore + disaster-recovery drills for Postgres and object storage.
- Security review + penetration test; dependency-scanning in CI; SBOM.
- Data-retention + deletion (GDPR-style) workflows.
- Runbooks, on-call, incident process.
- Rate-limit tuning, abuse detection, cost anomaly detection.

**Size:** M–L, ongoing.

---

## Suggested near-term sequence (first 3 increments after sign-off)

| Increment | Content | Why first |
|---|---|---|
| 1 | Phase 1 skeleton: Postgres + Alembic, CI, structured logging, typed settings, queue+worker for one variant, **P0 hardening quick wins** | Nothing else is safe or testable without CI, a DB, and the isolation quick-wins |
| 2 | Phase 2 core: orgs/workspaces/projects/roles + OIDC auth + server-side versions + keys out of the browser + tenant isolation | Multi-tenancy is the defining requirement; every later phase assumes it |
| 3 | Phase 3 stages + IR spike (single-file stacks only) | De-risks the IR — the single biggest architectural unknown — before Phases 4–8 depend on it |

Full-stack generation (4), the visual-QA loop (5) and deployment (8) should not
start until the sandbox tier (6) has a working prototype, because all three
require executing untrusted generated code.
