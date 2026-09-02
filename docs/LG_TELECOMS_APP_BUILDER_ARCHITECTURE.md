# LG Telecoms App Builder — Architecture

> **Status:** Phase 0 (Foundation / Discovery). This document records the **current
> state** of the inherited codebase and a **proposed target architecture** for the
> transformation into a multi-tenant SaaS "AI application development environment".
> Nothing in the "Target" sections has been implemented. Current-state claims are
> sourced from the repository at branch `lg-telecoms-app-builder-foundation`
> (upstream: `github.com/abi/screenshot-to-code`, MIT © 2023 Abi Raja).

---

## 1. Executive summary

The inherited product is **screenshot-to-code**: a single-page React app plus a
FastAPI backend that turns a screenshot / mockup / screen-recording / text prompt
into **one self-contained `index.html` file** using an LLM tool-calling agent.
It is a **single-user, keys-in-browser, no-database, no-auth desktop-style tool**
that happens to be served over the web. There is a separate closed-source hosted
SaaS wrapper (`../screenshot-to-code-saas`, the `hosted` branch) that is **not in
this repository**.

Key structural facts:

| Dimension | Current state |
|---|---|
| Frontend | React 18 + Vite 6 + TypeScript, Zustand state, Tailwind, Radix UI |
| Backend | FastAPI, one WebSocket endpoint for generation + ~10 REST routes |
| Transport | Single `/generate-code` WebSocket; generation streams over it |
| AI providers | OpenAI, Anthropic, Google Gemini (codegen); Replicate (images) |
| AI abstraction | `ProviderSession` protocol + per-provider adapters + canonical tool defs |
| Output artifact | A single HTML string per "variant" (2–4 variants per request) |
| Persistence | **None server-side** for user work. Browser `localStorage` only. Design systems + agent-run logs are local JSON/SQLite files on the backend host |
| Auth / tenancy | **None** |
| Database | **None** (one local SQLite file for agent-run telemetry only) |
| Secrets | User API keys pasted into a browser dialog, stored in `localStorage`, sent per-request over the WebSocket; or `backend/.env` |
| Sandboxing | **None.** Generated HTML renders in a non-sandboxed `<iframe srcdoc>`; the backend also renders it in headless Chromium (`--no-sandbox`) |
| Versioning | Client-side only: a `commits` map in Zustand, lost on refresh |
| Deployment | `docker-compose` (dev only), or manual uvicorn + Vite |
| Tests | 276 backend (pytest) + 42 frontend (jest) — all green on this checkout |

The gap between this and the stated target (organizations, workspaces, projects,
roles, billing, AI credits, sandboxed full-stack generation, an Application IR,
visual QA loops, deployment) is **large**. Essentially every cross-cutting
concern of a SaaS platform is absent and must be added, while the generation
engine itself is relatively mature and worth preserving.

---

## 2. Repository map

```
LG_Telecoms_App_Builder/
├── backend/                     FastAPI app (Python, Poetry, pinned ^3.10)
│   ├── main.py                  App factory: registers routers, CORS(*), startup probes
│   ├── config.py                Env-var config (NUM_VARIANTS=4, spend ceiling $3, flags)
│   ├── start.py                 Dev entrypoint w/ auto free-port scan (7001..7020)
│   ├── llm.py                   `Llm` enum (model registry), MODEL_PROVIDER map, sets
│   ├── agent/
│   │   ├── engine.py            AgentEngine: the tool-calling loop (max 30 steps)
│   │   ├── runner.py            `Agent` = thin alias of AgentEngine
│   │   ├── state.py             AgentFileState (path + content) + seeding from messages
│   │   ├── providers/
│   │   │   ├── base.py          ProviderSession Protocol, StreamEvent, ProviderTurn
│   │   │   ├── factory.py       create_provider_session(model, ...) → routes by provider
│   │   │   ├── openai.py        OpenAI Responses API adapter (~20 KB)
│   │   │   ├── anthropic/       Anthropic Messages adapter + image down-scaling
│   │   │   └── gemini.py        google-genai adapter (~16 KB)
│   │   └── tools/
│   │       ├── definitions.py   canonical_tool_definitions(...) — the tool catalog
│   │       ├── runtime.py       AgentToolRuntime.execute() — dispatch + impls (~23 KB)
│   │       ├── extract_assets.py  Gemini-backed screenshot asset cropping
│   │       ├── screenshot_preview.py  headless-Chromium self-check tool
│   │       └── local_assets.py  /local-assets/ ↔ data-URL helpers
│   ├── routes/
│   │   ├── generate_code.py     THE core: WS pipeline (middleware chain, ~900 lines)
│   │   ├── model_choice_sets.py Hard-coded model mixes per key-combination
│   │   ├── screenshot.py        POST /api/screenshot → screenshotone.com proxy
│   │   ├── export.py            POST /api/export → zip of index.html + inlined assets (SSRF-guarded)
│   │   ├── design_systems.py    CRUD over ~/.screenshot-to-code/design-systems.json
│   │   ├── evals.py, eval_sets.py, prompt_reports.py, agent_runs.py  Internal eval/telemetry UI APIs
│   │   ├── capabilities.py      GET /api/capabilities (screenshot_preview on/off)
│   │   └── home.py              GET / health
│   ├── prompts/                 Prompt assembly pipeline (create/update × image/text/video)
│   ├── image_generation/        Replicate calls (z-image-turbo, flux, p-image-edit, bg-removal)
│   ├── video/                   Video data-URL helpers (moviepy dep)
│   ├── preview_screenshot/      Pluggable screenshot backend (default: local Playwright)
│   ├── costs/                   pricing.py (per-model $/Mtok) + token_usage.py
│   ├── fs_logging/              agent_runs.py (SQLite + JSONL run capture), prompt_reports.py
│   ├── uploaded_assets/         Content-addressed image store under LOCAL_ASSET_DIR
│   ├── evals/                   Eval runner, sets, sessions (internal quality tooling)
│   └── tests/                   39 pytest files, 276 tests
├── frontend/                    React SPA (Vite, pnpm)
│   └── src/
│       ├── App.tsx              Root: orchestrates generation, commits, WS callbacks (~980 lines)
│       ├── generateCode.ts      WebSocket client for /generate-code
│       ├── config.ts            Backend URL resolution (same-origin default + proxy)
│       ├── store/
│       │   ├── project-store.ts Zustand: commits, variants, agent events, inputs (~470 lines)
│       │   └── app-store.ts     Zustand: appState, select-and-edit mode
│       ├── components/
│       │   ├── preview/         PreviewComponent (iframe srcdoc), CodeMirror, PreviewPane
│       │   ├── sidebar/         Chat-style update UI
│       │   ├── variants/        Variant switcher
│       │   ├── agent/           AgentActivity (thinking/tool timeline)
│       │   ├── history/         Version list
│       │   ├── settings/        API keys, stack, design systems, theme
│       │   ├── evals/           ~15 internal eval/telemetry pages (routed at /evals/*)
│       │   ├── recording/       Screen recorder (MediaRecorder → webm)
│       │   ├── select-and-edit/ Click-an-element-to-scope-an-edit
│       │   └── ui/              Radix + shadcn-style primitives
│       └── lib/                 stacks.ts, models.ts, prompt-history.ts, design-systems.ts
├── docker-compose.yml           backend + frontend, dev only (no volumes/reload note)
├── backend/Dockerfile           python:3.12-slim + poetry + playwright chromium
├── frontend/Dockerfile          node:22-bullseye-slim, **uses `yarn` (stale; repo uses pnpm)**
├── design-docs/                 7 upstream design notes (variant system, agentic refactor, …)
├── .specify/                    Spec Kit scaffolding (constitution is still a template)
├── .claude/ .impeccable/ .github/hooks/   Local agent tooling (skills, Impeccable hooks)
└── LICENSE                      MIT © 2023 Abi Raja  (must be preserved)
```

---

## 3. Current architecture (as-is)

### 3.1 Runtime topology

```
Browser (SPA)
  │  localStorage: settings incl. API keys, no project data
  │
  ├─ WebSocket  ws://<host>/generate-code   ← all generation traffic
  │      client sends: {generatedCodeConfig, inputMode, generationType,
  │                     prompt{text,images[],videos[]}, history[], fileState,
  │                     openAiApiKey?, anthropicApiKey?, geminiApiKey?, replicateApiKey?,
  │                     designSystem?, optionCodes[]}
  │      server streams: variantCount, variantModels, status, thinking,
  │                      assistant, toolStart, toolResult, setCode,
  │                      variantComplete, variantError, error
  │
  └─ HTTP  http://<host>/api/*   screenshot proxy, export zip, design systems,
                                 capabilities, evals/telemetry

FastAPI process (single, stateless per request)
  ├─ generate_code.py  Pipeline middleware chain:
  │     WebSocketSetup → ParameterExtraction → StatusBroadcast →
  │     PromptCreation → CodeGeneration → PostProcessing(no-op)
  │  CodeGeneration fans out N asyncio tasks (one per variant/model),
  │  awaits them with asyncio.gather, each task = one AgentEngine.run()
  │
  ├─ AgentEngine.run(model, prompt_messages)
  │     create_provider_session(model) → OpenAI | Anthropic | Gemini adapter
  │     loop ≤30 turns:  session.stream_turn() → emit deltas →
  │                      execute tool_calls via AgentToolRuntime →
  │                      session.append_tool_results()
  │     stop when a turn has no tool calls; final HTML = file_state.content
  │
  ├─ AgentToolRuntime tools:
  │     create_file, edit_file (string-replace), generate_images (Replicate),
  │     edit_images / remove_backgrounds (Replicate), extract_assets (Gemini),
  │     screenshot_preview (local headless Chromium), save_assets, retrieve_option
  │
  ├─ Outbound: OpenAI / Anthropic / Gemini / Replicate / screenshotone.com
  │
  └─ Local host state (NOT per-user, NOT durable across redeploys):
        LOCAL_ASSET_DIR/                 content-addressed generated/uploaded images
        run_logs/agent_runs/{run_id}/    full run capture (if PROMPT_REPORTS_ENABLED)
        run_logs/agent_runs/index.db     SQLite telemetry index
        ~/.screenshot-to-code/design-systems.json
        $TMP/screenshot-to-code-assets/  staged uploads pending save_assets
```

### 3.2 Generation pipeline (current)

`INPUT → PROMPT ASSEMBLY → MODEL SELECTION → PARALLEL AGENT RUNS → STREAM → (client-side) COMMIT`

1. **Input** — image(s), one video, or text; optional reference images on updates;
   optional "selected element" HTML for scoped edits. Uploaded images are
   content-addressed and served from `/local-assets/`.
2. **Prompt assembly** (`prompts/pipeline.py`) — a small planner
   (`derive_prompt_construction_plan`) picks one of: `create_from_input`,
   `update_from_history`, `update_from_file_snapshot`. Each builds an
   OpenAI-style `messages[]` list with a large static system prompt
   (`prompts/system_prompt.py`) + stack policy + optional design-system block.
3. **Model selection** (`routes/model_choice_sets.py`) — **no capability
   registry**; a hard-coded tuple of `Llm` enum members is chosen purely by
   *which API keys are present* and create-vs-update, then cycled to fill
   `NUM_VARIANTS` (4 for create, 2 for update, 2 for video).
4. **Parallel agent runs** — `AgenticGenerationStage.process_variants` creates
   one `asyncio.Task` per variant and `asyncio.gather`s them. Each variant is a
   full independent `AgentEngine.run()` with its own `AgentRunRecorder`.
5. **Streaming** — every variant multiplexes onto the one WebSocket, tagged with
   `variantIndex`. The client keeps the socket open until the server closes it
   (all variants done or error).
6. **Commit** — purely client-side. `App.tsx` creates a `Commit` object holding
   `variants[]`, appends it to the Zustand `commits` map, and points `head` at
   it. History is the `parentHash` chain. **Refreshing the page loses everything.**

### 3.3 AI provider abstraction (current — the strongest part)

- **Canonical tool definitions** (`agent/tools/definitions.py`) — one schema per
  tool, serialized per-provider (`serialize_openai_tools`,
  `serialize_anthropic_tools`, `serialize_gemini_tools`).
- **`ProviderSession` Protocol** (`agent/providers/base.py`) —
  `stream_turn(on_event) → ProviderTurn`, `append_tool_results(...)`,
  `total_cost_usd()`, `close()`. Normalized `StreamEvent` types:
  `assistant_delta`, `thinking_delta`, `tool_call_delta`.
- **Cost/usage** — `costs/token_usage.py` (`TokenUsage` with cache read/write) +
  `costs/pricing.py` (a flat `MODEL_PRICING` dict keyed by API model-name
  string). Per-variant hard spend ceiling `GENERATION_MAX_COST_USD = $3`
  enforced in the engine loop (`BudgetExceededError`).
- **What's missing vs. target:** model *capabilities* (context window,
  vision, structured-output, max tokens), task→model *routing* policy, retries,
  fallbacks, provider-level rate limiting, a persisted *AI session* entity,
  and per-tenant key vaulting. Model choice is config-as-code, refreshed
  manually from eval runs (see commit history).

### 3.4 State management (current)

| State | Where | Durability |
|---|---|---|
| Settings, API keys | `localStorage` (`usePersistedState`) | Per-browser |
| Project / commits / variants / agent events | Zustand `project-store.ts` (in-memory) | **Lost on refresh** |
| App/UI state (appState, select mode) | Zustand `app-store.ts` | In-memory |
| Design systems | Backend JSON file in `$HOME` | Host disk, shared by all users |
| Agent-run telemetry | Backend SQLite + JSONL | Host disk, opt-in |
| Uploaded/generated assets | Backend `LOCAL_ASSET_DIR` | Host disk, content-addressed |

There is **no server-side notion of a "project"**. `fileState` (the current HTML)
is round-tripped from the client on every update request.

### 3.5 API surface (current)

| Method | Path | Purpose | Auth |
|---|---|---|---|
| WS | `/generate-code` | All code generation | none |
| GET | `/` | Health string | none |
| GET | `/api/capabilities` | Feature flags | none |
| POST | `/api/screenshot` | Proxy to screenshotone.com (key in body) | none |
| POST | `/api/export` | Zip export, fetches + inlines remote assets (SSRF-guarded) | none |
| GET/POST/PATCH/DELETE | `/api/design-systems[/{id}]` | Design-system CRUD (global file) | none |
| GET/POST | `/eval*`, `/run_evals*`, `/best-of-n-evals`, `/models`, `/output_folders` | Internal eval tooling | none |
| GET/POST/PUT | `/eval-sets*`, `/eval-sessions*` | Eval set/session mgmt | none |
| GET/POST | `/prompt-reports*` | Prompt-report browser + prune | none |
| GET/POST | `/agent-runs*` | Agent-run browser + prune (filesystem-backed) | none |
| GET | `/local-assets/*` | Static asset serving (mounted `StaticFiles`) | none |

CORS is `allow_origins=["*"]` with `allow_credentials=True`
(`main.py:43`). OpenAPI/Swagger is disabled (`openapi_url=None`).

### 3.6 Persistence & storage (current)

- No RDBMS. The only SQLite DB (`run_logs/agent_runs/index.db`) is a telemetry
  index with `runs`, `llm_calls`, `eval_sessions`, `eval_session_models` tables
  and an ad-hoc `_migrate_runs_table` migration shim (no Alembic).
- Assets: content-addressed (`asset_<sha256[:24]>.<ext>`) on local disk, served
  unauthenticated from `/local-assets/`. `_finalize_asset_bytes` takes an unused
  `user_id` parameter — an explicit hook left by upstream for the hosted backend
  to key per-user storage.
- Design systems: a single JSON file at `~/.screenshot-to-code/design-systems.json`
  (or `$SCREENSHOT_TO_CODE_DATA_DIR`), shared globally.

### 3.7 Browser / visual QA (current)

- `preview_screenshot/playwright_backend.py`: one shared headless Chromium
  (`--no-sandbox`), lazily launched, reused. `page.set_content(html,
  wait_until="networkidle", 15 s timeout)` then full-page PNG at desktop
  (1280×832) and mobile (≈342 wide) viewports.
- Exposed to the agent as the `screenshot_preview` tool; the system prompt tells
  the model to call it after `create_file`/`edit_file` and self-correct.
- This is a **one-shot self-check**, not a QA loop: no baseline comparison, no
  diffing against the input screenshot, no automated pass/fail, no repair
  iteration driven by QA results.
- `probe_screenshot_preview()` runs on startup and gates the tool; capability is
  surfaced to the UI via `/api/capabilities`.

### 3.8 Security boundaries (current)

- **No authentication or authorization anywhere.** Anyone who can reach the
  backend can generate (spending the host's keys if set in `.env`), read/write
  design systems, browse all prompt reports and agent runs, and trigger evals.
- **Generated code is treated as trusted.** The frontend preview iframe has
  **no `sandbox` attribute** (`PreviewComponent.tsx:290`, `iframe.srcdoc = html`),
  so LLM-authored JS runs same-origin with the app and can read the app's
  `localStorage` (which holds API keys). The backend renders the same HTML in
  headless Chromium with network access.
- **API keys from the browser** are sent as plaintext fields in the WebSocket
  JSON payload on every request (`openAiApiKey`, etc.), and stored in
  `localStorage`.
- **`OPENAI_BASE_URL` override** is disabled when `IS_PROD` is truthy
  (`generate_code.py:320`) — a deliberate SSRF/exfil guard.
- **Good:** `/api/export` has real SSRF protection (`is_public_http_url` blocks
  private/loopback/link-local IPs, caps redirects, size, and count).
  `/agent-runs/{id}/assets/{filename}` guards path traversal via `basename` +
  realpath containment. Uploaded assets are size-capped (20 MB) and
  MIME-allowlisted.
- **Secrets hygiene:** `.env`, `frontend/.env.local`, `.playwright-cli/` are
  git-ignored. No secrets found committed. `pyproject.toml` still carries the
  upstream author's email; `routes/generate_code.py` contains a
  `support@getwhimsyworks.com` address and `Troubleshooting.md` upstream support
  language — cosmetic, out of scope for discovery.

### 3.9 Observability (current)

- `print()`-based logging throughout (no structured logger, no log levels).
- Rich **opt-in** run capture (`PROMPT_REPORTS_ENABLED=1`): every LLM request
  payload, every tool call + result, every stream delta, token usage, cost, and
  a self-contained HTML+assets snapshot per run, indexed in SQLite and browsable
  at `/evals/agent-runs` and `/evals/prompt-reports`.
- `langfuse` is a dependency but no active integration was found in the codebase.
- No metrics, no tracing spans, no health/readiness beyond `GET /`.

---

## 4. Target architecture (to-be) — proposed

> This is the destination the roadmap builds toward. It is deliberately more
> conservative than "rewrite everything": the generation engine, provider
> adapters, canonical tools, prompt pipeline, and eval tooling are **kept and
> extended**; the platform shell around them is **new**.

### 4.1 Target pipeline

```
INPUT ─▶ UNDERSTANDING ─▶ ANALYSIS ─▶ PLANNING ─▶ APPLICATION IR ─▶ GENERATION
                                                                        │
        EXPORT/DEPLOY ◀─ VERSIONING ◀─ ITERATION/REPAIR ◀─ VISUAL QA ◀─ PREVIEW
                                            ▲                   │
                                            └── AUTOMATED TESTING ┘
```

| Stage | Current coverage | Target |
|---|---|---|
| Input | image / multi-image / video / text | + URL crawl, Figma import, asset bundles, repo import |
| Understanding | implicit in the LLM prompt | explicit: OCR/layout/DOM extraction, component detection, asset inventory → structured `Understanding` record |
| Analysis | none | design tokens, IA, routes, data entities, integrations inferred → `Analysis` record |
| Planning | none | an explicit build plan (pages, order, dependencies) reviewable by the user |
| Application IR | none (raw HTML is the only source of truth) | a versioned, typed intermediate representation (see §4.4) |
| Generation | mature single-file agent | multi-file / multi-stack generation from IR; keep the agent, target the IR |
| Preview | client iframe + backend screenshot | sandboxed per-project preview environment with a real dev server for full-stack apps |
| Visual QA | one-shot `screenshot_preview` | generate → preview → screenshot → diff vs. target → diagnose → repair → re-run loop |
| Automated testing | none for generated apps | Playwright smoke + interaction tests generated from the plan |
| Iteration / repair | manual chat updates | QA-driven automatic repair passes with budget caps |
| Versioning | client-side `commits` map | server-side project versions, snapshots, checkpoints, rollback, AI-session history |
| Export / deploy | zip download | zip, GitHub push, one-click deploy to a hosting target |

### 4.2 Target runtime topology

```
                         ┌───────────────────────────────────────────────┐
Browser SPA ──HTTPS/WSS──▶│ API Gateway / BFF (FastAPI)                    │
  (session cookie/JWT,    │  authN (OIDC), authZ (RBAC), tenant context,   │
   no provider keys)      │  rate limits, usage metering, audit log emit   │
                         └───────┬───────────────────────────────┬────────┘
                                 │                               │
                    ┌────────────▼───────────┐        ┌──────────▼──────────┐
                    │ Platform services      │        │ AI Orchestration    │
                    │  orgs / workspaces /    │        │  provider registry, │
                    │  projects / members /   │        │  model capabilities,│
                    │  roles / subscriptions /│        │  task routing,      │
                    │  credits / audit        │        │  retries/fallbacks, │
                    └────────┬───────────────┘        │  AI-session store,  │
                             │                        │  cost/usage tracking│
                    ┌────────▼────────┐               └──────────┬──────────┘
                    │ Postgres        │                          │
                    │ (multi-tenant,  │        ┌─────────────────▼───────────────┐
                    │  RLS or         │        │ Generation workers (queue)      │
                    │  schema-per-org)│        │  prompt pipeline, agent engine, │
                    └────────┬────────┘        │  IR compile/apply               │
                             │                 └─────────────────┬───────────────┘
        ┌────────────────────┼─────────────────┐                 │
        ▼                    ▼                 ▼                  ▼
   Object storage       Redis (cache,      Secrets manager   Sandbox pool
   (assets, snapshots,  queues, pub/sub,   (per-tenant       (Docker/Firecracker:
    exports, versions)  rate limits)        provider keys)    preview + QA + tests,
                                                              CPU/mem/net/time caps)
```

### 4.3 Target subsystems

- **Frontend** — evolve the current SPA into a project-centric IDE shell
  (org/workspace switcher, project list, per-project editor + preview + QA +
  versions + deploy tabs). Keep Zustand for ephemeral UI; move project data to
  server state (React Query / RTK Query) backed by REST + a per-project event
  stream. Preview iframe becomes `sandbox`-attributed and points at a
  sandbox-hosted preview URL.
- **Backend / API** — split the monolithic `generate_code.py` WebSocket into:
  (a) a thin realtime channel per *AI session* (events only), and (b) REST
  resources for projects/inputs/versions/plans. Introduce a job queue so
  generation is not tied to a socket lifetime.
- **AI orchestration** — promote today's `Llm` enum + `MODEL_PROVIDER` +
  `model_choice_sets` into a real **model registry** with capabilities, a
  **router** (task → model policy, overridable per org), retries/fallbacks, and
  a persisted **AISession** aggregate (turns, tool calls, tokens, cost) that
  replaces per-run JSONL files as the source of truth.
- **Application IR** — see §4.4.
- **Project system** — `Organization → Workspace → Project`, with a Project
  owning `Inputs, Understanding, Analysis, Plan, IR, GeneratedCode, Versions,
  Preview, Tests, AISessions, Deployment` (all as first-class rows/blobs).
- **Storage** — Postgres for metadata; object storage (S3-compatible) for
  assets, version snapshots, exports; Redis for cache/queues/pubsub/rate-limits.
- **Database** — Postgres + Alembic migrations, multi-tenancy via row-level
  security or schema-per-org (decision deferred — see TECHNICAL_DECISIONS.md).
- **Authentication** — OIDC/OAuth2 (hosted IdP or self-managed), session cookies
  for the SPA, service tokens for CI/deploy. **No provider keys in the browser.**
- **Billing / usage** — subscription tiers, metered AI credits (derived from the
  existing `TokenUsage`/`MODEL_PRICING` cost math), storage quotas, usage limits
  with soft/hard enforcement, Stripe (or equivalent) for payment.
- **Sandboxing** — a pool of resource-capped containers (or microVMs) that host
  (1) the preview dev server, (2) Playwright QA runs, (3) generated test runs.
  No network egress by default; secrets injected per-run, never baked in.
- **Browser / Visual QA** — a dedicated service wrapping Playwright: capture,
  compare (pixel + structural diff against the target design), diagnose
  (localize discrepancies), and feed a repair task back to the orchestrator.
- **Deployment** — export targets: zip, GitHub repo (create/push via an App
  installation), and a managed deploy to a static/edge host or a container host
  for full-stack apps.
- **Observability** — structured JSON logging, OpenTelemetry traces spanning
  API → queue → worker → provider calls, metrics (generation latency, success
  rate, cost per project, queue depth), and error tracking. Keep the run-capture
  feature as a debugging superpower, backed by object storage.
- **Audit logging** — an append-only `audit_events` stream for every
  security-relevant action (membership changes, key access, deploys, exports,
  role changes, spend).

### 4.4 Application IR (investigation notes, not a commitment)

Today the **only source of truth is the LLM-generated HTML string**. That blocks
reliable regeneration, targeted repair, migration between stacks, and diffable
versioning. An IR should sit between PLANNING and GENERATION and be able to
describe, at minimum:

```
AppIR
├── meta            name, description, target stack(s), IR schema version
├── design          tokens (color/type/space/radius/shadow), themes, breakpoints
├── assets          id, kind (logo/photo/icon), source (extracted/generated/uploaded),
│                   content hash, dimensions, usage sites
├── pages[]         route, layout ref, sections[], SEO meta
├── layouts[]       slots, responsive rules
├── components[]    id, kind, props schema, variants, bound data, a11y contract
├── data            models[] (fields, relations), seed/mock data
├── apis[]          endpoint, method, request/response schema, auth requirement
├── auth            strategy, roles, protected routes
├── integrations[]  third-party services + required config
├── env[]           name, scope (build/runtime), secret? , description
├── dependencies[]  package + version + why
├── config          framework/build configuration
└── database        schema (tables, columns, indexes, migrations)
```

Design constraints the IR must satisfy:

- **Round-trippable** with generated code for the supported stacks (compile IR →
  code; and, for imports, lift code → IR best-effort).
- **Diffable and versioned** — each project version stores the IR; a version diff
  is an IR diff, not a text diff.
- **Partially regenerable** — "regenerate this component/page" touches only its
  IR subtree and re-emits only affected files.
- **Repair-friendly** — visual-QA findings map to IR nodes so repair is a scoped
  IR edit, not a whole-file rewrite.
- **Stack-agnostic core, stack-specific compilers** — start with the 6 stacks
  already supported (`prompts/prompt_types.Stack`), add full-stack targets later.

Open questions carried into Phase 1: is the IR authored by the LLM (as structured
output) or derived deterministically from the plan? How much of the current
single-file-HTML flow is kept as a "stack" vs. superseded? Can the existing
`edit_file` string-replace tool be reframed as an IR-node edit? These are
resolved during PHASE 1 spikes, not now.

---

## 5. Current vs. target responsibility split

| Concern | Current owner | Target owner |
|---|---|---|
| Who is the user | *nobody* | AuthN service + `users` table |
| Tenancy / project scoping | *none* | Platform services + Postgres RLS/schema |
| Which model runs | `model_choice_sets.py` (keys present → tuple) | Model registry + router policy (per-org overridable) |
| Provider keys | browser `localStorage` → WS payload / `.env` | per-tenant secrets manager, server-only |
| The generation loop | `AgentEngine` | **unchanged** (kept, wrapped by a job worker) |
| Provider adapters | `agent/providers/*` | **unchanged / extended** (add capabilities, retries) |
| Tool catalog | `agent/tools/definitions.py` | **extended** (IR tools, deploy tools) |
| Source of truth for an app | HTML string in client Zustand | Application IR + generated files in object storage, versioned in Postgres |
| Version history | client `commits` map (volatile) | `project_versions` (durable, rollback) |
| Preview | non-sandboxed client iframe | sandboxed preview environment + `sandbox` iframe |
| Visual QA | one-shot `screenshot_preview` tool | QA service with compare/diagnose/repair loop |
| Cost control | `$3`/variant ceiling | per-org credit budgets, per-project caps, alerts |
| Assets | local content-addressed dir | object storage, tenant-scoped, signed URLs |
| Design systems | one global JSON file | per-workspace design systems in Postgres |
| Telemetry | opt-in local JSONL + SQLite | always-on structured logs + OTel + object-storage run capture |
| Deployment | manual / docker-compose | IaC + managed deploy targets |
| Audit | *none* | `audit_events` append-only log |

---

## 6. Major subsystem inventory (quick reference)

| Subsystem | Current file(s) | Maturity | Target action |
|---|---|---|---|
| Frontend shell | `App.tsx`, `store/*` | Solid for single project | Re-scope to multi-project IDE |
| WebSocket generation | `routes/generate_code.py` | Works; monolithic; socket-bound | Split events vs. resources; add queue |
| Agent engine | `agent/engine.py` | **Mature, keep** | Wrap in worker; target IR |
| Provider abstraction | `agent/providers/*` | **Good, keep** | Add capabilities, retries, fallbacks |
| Tool system | `agent/tools/*` | **Good, keep** | Add IR + deploy tools |
| Prompt pipeline | `prompts/*` | Good, stack-specific | Feed from Plan/IR, not raw input |
| Model selection | `routes/model_choice_sets.py` | Config-as-code, manual | Registry + router |
| Cost/usage | `costs/*` | Good primitives | Wire to billing/credits |
| Image generation | `image_generation/*` | Works (Replicate) | Keep; add provider options |
| Asset extraction | `asset_extraction.py`, `agent/tools/extract_assets.py` | Works (Gemini) | Keep; move to understanding stage |
| Screenshot/preview | `preview_screenshot/*` | One-shot self-check | Grow into QA service |
| URL → screenshot | `routes/screenshot.py` | Thin proxy (screenshotone.com) | Replace w/ owned crawler + sandboxed capture |
| Video input | `video/*`, `prompts/create/video.py` | Works (Gemini only) | Keep |
| Figma import | **absent** | — | New (Phase 3+) |
| Repo import | **absent** | — | New (Phase 4+) |
| Uploaded assets | `uploaded_assets/*` | Content-addressed, local | Move to object storage, tenant-scoped |
| Run capture / telemetry | `fs_logging/*` | Rich, opt-in, local | Always-on, object-storage backed |
| Eval tooling | `backend/evals/*`, `routes/evals*.py`, `/evals/*` pages | Extensive internal tooling | Keep internal; gate behind admin role |
| Export | `routes/export.py` | Works, SSRF-guarded | Extend (GitHub, deploy) |
| Design systems | `routes/design_systems.py` | Global JSON file | Per-workspace, Postgres |
| Auth / tenancy / billing / sandbox / IR / deploy | **absent** | — | New platform work |

---

## 7. Key architectural constraints inherited

1. **The output is one HTML file.** Every stack (`html_tailwind`, `html_css`,
   `react_tailwind`, `bootstrap`, `vue_tailwind`, `ionic_tailwind`) compiles to a
   single standalone page using CDN scripts. Full-stack generation is a
   green-field capability, not an extension.
2. **Generation lifetime = WebSocket lifetime.** Cancel = close socket. Long
   runs, resumability, and multi-device visibility are impossible without a queue
   + persisted session.
3. **The client is the database.** All project structure lives in
   `project-store.ts`. Server-side project modelling is entirely new.
4. **Model choice is deploy-time config.** Updating the model mix is a code
   change informed by manual eval sessions (see `git log`). Fine for one team,
   not for per-org customization.
5. **Single-tenant assumptions everywhere** — global design-systems file, global
   asset dir, global eval/telemetry endpoints, `user_id` params that are accepted
   but ignored locally.
6. **Python `^3.10`** pinned; upstream Docker uses 3.12; this Windows checkout
   ran clean on 3.13 (see LOCAL_DEVELOPMENT.md). `moviepy 1.0.3`, `pillow`,
   `openai 2.16.0` (exact pin), `anthropic ^0.84`, `google-genai ^1.16`.
7. **MIT license and upstream attribution must be preserved** (LICENSE,
   `pyproject.toml` author field, README credits).

---

## 8. Where to be careful (architecture risks)

- The `generate_code.py` middleware pipeline is elaborate but the `next_func`
  chaining + `PostProcessingStage` being a no-op suggests earlier iterations were
  removed; changes there need close reading.
- `AgentEngine._run_with_session` has a hard `max_steps = 30` and re-checks the
  spend ceiling each turn — any move to longer/full-stack builds must revisit both.
- Anthropic requests set `"cache_control": {"type": "ephemeral"}` at the top
  level and rely on message ordering for prompt caching; restructuring prompt
  assembly can silently destroy cache hit rates (which the code logs).
- Gemini video uses the same `image_url` message shape as images; several code
  paths special-case this (`_extract_input_images`, asset-extraction gating).
- `design-docs/general.md` claims "Gemini client only uses messages[0]" — this
  is **stale**; `gemini.py` now converts full history. Treat `design-docs/` as
  historical intent, not current spec.
