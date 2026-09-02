# LG Telecoms App Builder — Local Development

> **Status:** Phase 0 discovery. This documents how to run the **inherited
> codebase as-is** on a local machine, and records exactly what was done and
> observed on the discovery machine (Windows 11, `C:\dev\LG_Telecoms_App_Builder`,
> branch `lg-telecoms-app-builder-foundation`). It is not a target-architecture
> setup guide.

---

## 1. Required runtimes & tools

| Tool | Version the repo expects | Notes |
|---|---|---|
| Python | `^3.10` (`backend/pyproject.toml`); upstream Docker uses **3.12.3**; AGENTS.md mentions a `py3.10` venv but also notes 3.12 works | Discovery machine used **CPython 3.13.14** (see §7) — all tests passed, but 3.13 is outside the tested range. **Recommendation: use 3.12.** |
| Poetry | any recent 2.x (or 1.8 as in the Docker image) | Not preinstalled on the discovery machine; installed via `pip install --user poetry` → got **2.4.2** |
| Node.js | `>=14.18.0` (`frontend/package.json` `engines`); Dockerfile uses **node 22** | Discovery machine: node **24.15.0** — worked |
| pnpm | **`pnpm@10.32.1`** (pinned via `packageManager` in both `package.json` files) | Use exactly this; `corepack` will honor it |
| Playwright Chromium | `playwright ^1.61` | Optional — only for the `screenshot_preview` agent tool and `preview_screenshot`; install with `poetry run playwright install chromium` |
| Docker + docker-compose | any recent | Optional; `docker-compose.yml` is **dev-only** (no volumes, no reload) |

**Package managers:** Poetry (backend), pnpm (frontend). The repo also has a
root `package.json` with pnpm `workspaces: ["frontend", "backend"]` and helper
scripts (`pnpm test` → runs frontend jest + backend pytest).

> `frontend/Dockerfile` was repaired in Phase 1 Remediation Batch 1 to use
> `corepack` + `pnpm install --frozen-lockfile` + `pnpm dev` (it previously used
> `yarn` against a non-existent `yarn.lock`). The container build is not yet
> exercised in CI. `backend/Dockerfile` is unchanged (poetry 1.8 / python 3.12.3).

---

## 2. Environment variables

### Backend (`backend/.env`, loaded by `python-dotenv` in `main.py`)

> As of **Phase 1 Remediation Batch 1**, all backend config is read once at
> startup into a validated `Settings` object (`backend/config.py`). Copy
> **`backend/.env.example`** as your starting point. Invalid values (a
> non-boolean flag, a bad `LOG_LEVEL`, a non-http `OPENAI_BASE_URL`) now abort
> startup with a clear message.

| Var | Required? | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | one of the three | GPT code-gen variants |
| `ANTHROPIC_API_KEY` | one of the three | Claude code-gen variants |
| `GEMINI_API_KEY` | one of the three — **needed for video mode and asset extraction** | Gemini code-gen + `extract_assets` tool + video input |
| `REPLICATE_API_KEY` | optional (**`.env` only**, not accepted from the UI) | `generate_images`, `edit_images`, `remove_backgrounds` |
| `OPENAI_BASE_URL` | optional | OpenAI proxy; **ignored when `IS_PROD` is truthy**; must start with `http(s)://` |
| `IS_PROD` | optional | `true` = production feature flags. **Strict boolean now** — `1/true/yes/on` vs `0/false/no/off`/unset; anything else aborts startup. |
| `IS_DEBUG_ENABLED` | optional | `true` = sends `variantModels` to the client, enables `debug/` file dumps. **Strict boolean** (the old `bool(os.environ.get(...))` bug where `"false"` was true is fixed). |
| `DEBUG_DIR` | optional | Where `DebugFileWriter` writes |
| `PROMPT_REPORTS_ENABLED` | optional | `true` = full run capture (JSONL + SQLite + HTML/asset snapshots) under `run_logs/agent_runs` |
| `CORS_ALLOWED_ORIGINS` | optional | Comma-separated exact origins allowed to call the API. Default = local dev origins (`localhost`/`127.0.0.1` on `:5173` and `:5180`). **No wildcard.** |
| `OPERATOR_TOKEN` | optional | Shared secret for the internal `/evals*`, `/eval-sets*`, `/eval-sessions*`, `/prompt-reports*`, `/agent-runs*` endpoints. When set, send it as the `X-Operator-Token` request header. |
| `OPERATOR_ENDPOINTS_PUBLIC` | optional | `true` = leave those endpoints open (**local dev only**). Secure default `false` → they return 403 until `OPERATOR_TOKEN` or this is set. |
| `LOG_LEVEL` | optional | `DEBUG` \| `INFO` (default) \| `WARNING` \| `ERROR` \| `CRITICAL` |
| `LOG_FORMAT` | optional | `console` (default, human key=value) \| `json` |
| `DATABASE_URL` | optional (Batch 2) | `postgresql+asyncpg://…` (a plain `postgresql://` is normalised). **Unset ⇒ DB disabled, sync generation still works.** |
| `REDIS_URL` | optional (Batch 2) | Default `redis://127.0.0.1:6379/0`. Needed for the worker. |
| `JOB_QUEUE_ENABLED` | optional (Batch 3) | Strict bool, default `false`. When `true`, the **text → create** generation path runs through the Redis/arq worker (needs a running worker); all other paths stay synchronous. |
| `JOB_MAX_ATTEMPTS` / `JOB_TIMEOUT_SECONDS` | optional (Batch 2) | Worker retry cap (default `3`) and per-job wall-clock watchdog (default `900`, arq in-process). |
| `JOB_REAP_AFTER_SECONDS` | optional (final audit) | Out-of-process watchdog: a job left `running` this long is reaped to `failed` by the worker's `reap_jobs` cron (every 5 min). Default `3600`; `0` disables. |
| `JOB_RETENTION_DAYS` | optional (Batch 4) | Unset ⇒ **no pruning**. A positive integer ⇒ the worker's daily `prune_jobs` cron deletes *terminal* job rows older than N days. Queued/running rows are never pruned. |
| `WORKER_HEALTH_INTERVAL_SECONDS` | optional (final audit) | How often the worker refreshes its arq health-check key (default `30`). `/health` reports `worker: down` once it lapses. |
| `WORKER_NAME` | optional (Batch 2) | Overrides the worker identity string in logs (default `worker@<host>:<pid>`). |
| `REQUIRE_INFRA` | optional (tests only) | `1` in CI: infra-dependent tests that would `skip` become hard failures. |
| `LOGS_PATH` | optional | Base dir for `run_logs/` |
| `LOCAL_ASSET_DIR` | optional | Default `backend/local_assets/`; served at `/local-assets/` |
| `LOCAL_ASSET_BASE_URL` | optional | Default `http://127.0.0.1:7001` |
| `SCREENSHOT_TO_CODE_DATA_DIR` | optional | Default `~/.screenshot-to-code/`; holds `design-systems.json` |
| `NUM_VARIANTS` / `NUM_VARIANTS_VIDEO` / `GENERATION_MAX_COST_USD` | optional | Now env-overridable (defaults `4` / `2` / `3.0`). |

At least one of `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` must be
available (env or Settings dialog) or generation fails fast with
`"No OpenAI, Anthropic, or Gemini API key found"`.

> **`PYTHONUTF8=1` is no longer required** on Windows. Batch 1 made logging
> encoding-safe, so `poetry run uvicorn main:app --port 7001` works on a default
> console. (It was previously needed to avoid a `UnicodeEncodeError` crash in
> `print_prompt_preview` — audit KF-1.)

### Frontend (`frontend/.env.local`, git-ignored)

| Var | Default | Purpose |
|---|---|---|
| `VITE_WS_BACKEND_URL` | same-origin `ws(s)://` | WebSocket backend base |
| `VITE_HTTP_BACKEND_URL` | same-origin `http(s)://` | REST backend base |
| `VITE_IS_DEPLOYED` | unset | `"true"` = hosted mode (ToS dialog, Plausible analytics injected) |
| `VITE_PICO_BACKEND_FORM_SECRET` | null | hosted-only |
| `PROXY_CODEGEN_BACKEND` | `http://127.0.0.1:7001` | Vite dev-server proxy target for `/generate-code`, `/api`, `/local-assets` |

The frontend defaults to **same-origin** and relies on the Vite dev-server proxy,
so with both services on defaults you usually need **no `.env.local` at all**.

---

## 3. Services & ports

| Service | Default port | Bind | Config |
|---|---|---|---|
| Backend (FastAPI + WS) | **7001** | `127.0.0.1` (`start.py`) / `0.0.0.0` (docker-compose, `--host`) | `--port`; docker `BACKEND_PORT`; `start.py` **auto-scans 7001→7020** for a free port |
| Frontend (Vite dev) | **5173** | `host: true` (all interfaces, `vite.config.ts`) | Vite `--port` |
| PostgreSQL (Batch 2) | **5435** → container 5432 | `127.0.0.1` only | compose `POSTGRES_PORT`; container always 5432 |
| Redis (Batch 2) | **6379** | `127.0.0.1` only | compose `REDIS_PORT` |
| Worker (arq, Batch 2) | — (no port) | — | `poetry run arq worker.WorkerSettings` |
| — | — | — | AGENTS.md note: use `http://localhost:5173`, **not** `127.0.0.1:5173` (the latter is refused in some setups) |

**Batch 2 added:** PostgreSQL on **`127.0.0.1:5435`** (container 5432) and Redis
on **`127.0.0.1:6379`**, both via `docker-compose.yml`, loopback-only. The
optional **worker** process has no port. Headless Chromium for
`screenshot_preview` still runs in-process in the backend.

`start.py` is the only component with port-conflict handling; `uvicorn
main:app` directly does not scan.

---

## 3a. Infrastructure stack (PostgreSQL + Redis + worker) — Batch 2, extended through Batch 4

### Full stack, copy/paste (four terminals, from the repo root)

```bash
# 0. infra
docker compose up -d postgres redis
docker compose ps                                   # both (healthy)

# 1. migrate  (terminal A, from backend/)
cd backend
export DATABASE_URL=postgresql+asyncpg://appbuilder:appbuilder@127.0.0.1:5435/appbuilder
export REDIS_URL=redis://127.0.0.1:6379/0
poetry run alembic upgrade head
poetry run alembic check                            # must say "No new upgrade operations detected."

# 2. backend  (terminal A, same env)
JOB_QUEUE_ENABLED=true poetry run uvicorn main:app --reload --port 7001

# 3. worker   (terminal B, from backend/)
cd backend
DATABASE_URL=postgresql+asyncpg://appbuilder:appbuilder@127.0.0.1:5435/appbuilder \
REDIS_URL=redis://127.0.0.1:6379/0 \
JOB_QUEUE_ENABLED=true \
poetry run arq worker.WorkerSettings

# 4. frontend (terminal C, from frontend/)
cd frontend && pnpm dev                             # → http://localhost:5173

# 5. health check (terminal D)
curl -s http://127.0.0.1:7001/health
#   → {"status":"ok","checks":{"database":"ok","redis":"ok","worker":"ok"},"job_queue_enabled":true}
#     "worker":"down" (+ status "degraded") when JOB_QUEUE_ENABLED=true and no worker is running.
curl -s http://127.0.0.1:7001/api/models | python -m json.tool | head   # capability catalog (no keys/pricing)
```

Windows: use `127.0.0.1`, **not** `localhost`, for Redis (IPv6 `::1` resolution).

```bash
# from repo root — start just the infra (backend/frontend still run natively):
docker compose up -d postgres redis
docker compose ps          # both should be (healthy)
docker compose down        # stop        (add -v to also wipe the volumes)
```

Point the backend at them (put these in `backend/.env`):

```
DATABASE_URL=postgresql+asyncpg://appbuilder:appbuilder@127.0.0.1:5435/appbuilder
REDIS_URL=redis://127.0.0.1:6379/0
```

The database is **optional** — with no `DATABASE_URL` the backend still starts
and screenshot→code generation works; `GET /health` then shows
`database: disabled`. Redis is only needed to run the worker.

### Migrations (Alembic)

```bash
cd backend
poetry run alembic upgrade head        # apply
poetry run alembic downgrade base      # roll back
poetry run alembic upgrade head        # re-apply (round-trip check)
poetry run alembic check               # model-drift gate (also runs in CI)
poetry run alembic current             # show applied revision
poetry run alembic revision --autogenerate -m "..."   # (later phases)
```

Alembic reads `DATABASE_URL` from the typed settings — nothing is stored in
`alembic.ini`. The only table this phase is `jobs` (infrastructure; no domain
tables yet). `alembic check` fails if the ORM models and the migration history
have drifted — CI runs it on every PR.

### Worker (arq)

```bash
cd backend
poetry run arq worker.WorkerSettings   # foreground; Ctrl-C for a clean shutdown
```

Needs `REDIS_URL` (and `DATABASE_URL` for durable job state). Tasks: `ping`
(health), `execute_job` (runs a persisted job's handler) and the `prune_jobs`
cron. Handlers: `noop` (tests) and **`generation`** (the queued text→create
path). `GET /health` reports `job_queue_enabled`.

The worker **hard-disables `screenshot_preview`** at startup — it must never
render (execute) generated code. The synchronous backend still offers that tool.

**Job retention (opt-in):** set `JOB_RETENTION_DAYS=<N>` and the worker's daily
`prune_jobs` cron (03:17) deletes terminal (`succeeded`/`failed`/`cancelled`)
job rows older than `N` days. Queued/running rows are never pruned. Unset = no
pruning.

### Queued generation (Batch 3 — the migrated `text → create` path)

Set `JOB_QUEUE_ENABLED=true` in `backend/.env`, start the **worker** alongside
the backend, then use the app's **Text** tab → *Generate*. That request now:

1. creates a durable `generation` job (Postgres) — **browser-entered provider
   keys are stripped; the worker uses server-env keys only**;
2. enqueues it (Redis/arq) and returns a `job_id` over the WebSocket
   (`jobCreated` message) — the UI shows `Queued...` → `Generating code...`;
3. runs in the **independent worker**; a dropped WebSocket does **not** cancel
   it (`frontend/src/generateCode.ts` transparently re-attaches with `{jobId}`,
   or you can poll `GET /api/jobs/{job_id}`);
4. streams generation events back through the WebSocket relay in the existing
   vocabulary (`variantCount` / `status` / `setCode` / `variantComplete` /
   `error`), plus additive `jobStatus`.

**Explicit cancel:** `POST /api/jobs/{job_id}/cancel` — QUEUED → `cancelled`
immediately (the worker skips it); RUNNING → `cancelled` + a best-effort arq
abort (raises `CancelledError` in the worker task); terminal → `409`. A connected
relay forwards the `cancelled` event and closes the socket.

Without server provider keys the queued path ends in the **controlled**
"No OpenAI, Anthropic, or Gemini API key found" error (not a crash). Every other
generation path (image / URL / video / **edit**, and text→create when the flag
is off) is unchanged and synchronous.

### Full-stack via Docker (demo, no hot reload)

```bash
docker compose --profile app up -d --build   # postgres + redis + backend + worker + frontend
```

---

## 4. Startup commands

### Backend

```bash
cd backend
# first time:
poetry install
poetry run playwright install chromium        # optional: enables screenshot_preview
# create backend/.env with at least one provider key (see §2)

# run (reload dev server):
poetry run uvicorn main:app --reload --port 7001
#   or, with auto free-port selection:
poetry run python start.py --port 7001
```

### Frontend

```bash
cd frontend
pnpm install
pnpm dev            # → http://localhost:5173
# hosted mode: pnpm dev-hosted
```

### Docker (dev only — no hot reload, no volumes)

```bash
echo "OPENAI_API_KEY=sk-..." > .env      # repo root
docker-compose up -d --build             # frontend :5173, backend :7001
```

`backend/Dockerfile` = `python:3.12.3-slim` + poetry 1.8 +
`playwright install --with-deps chromium`. `frontend/Dockerfile` is **stale**
(yarn) — see §1.

---

## 5. Test / lint / type-check / build commands

| Scope | Command | Baseline result on this checkout |
|---|---|---|
| Backend unit tests | `cd backend && poetry run pytest` | **632 passed** with infra (`DATABASE_URL`+`REDIS_URL`+`REQUIRE_INFRA=1`); without infra the DB/Redis/queue tests `skip`. |
| Backend type check | `cd backend && poetry run pyright` | **0 errors, 36 warnings** (all `reportUnknownVariableType` / bs4 typing, which `pyrightconfig.json` sets to `warning`) |
| Backend migrations | `poetry run alembic upgrade head && poetry run alembic check` | applies + **no drift** |
| Frontend lint | `cd frontend && pnpm run lint:ratchet` | **passes** at the baseline in `frontend/.lint-baseline.json` (currently 16 errors / 6 warnings, all pre-existing — see §6). Raw `pnpm lint` still fails `--max-warnings 0`. |
| Frontend unit tests | `cd frontend && pnpm test` | **44 passed, 6 skipped** (+`generateCode.test.ts`) |
| Frontend build | `cd frontend && pnpm build` (`tsc && vite build`) | **passes**; one ~1.4 MB JS chunk (Vite warns >500 kB) |
| Root convenience | `pnpm test` (root) | runs frontend jest + backend pytest |

pytest config: `backend/pytest.ini` (`testpaths = tests`, `asyncio_mode = auto`).
**CI exists** — `.github/workflows/ci.yml` runs the backend job (Python 3.12,
Poetry, pyright, alembic upgrade/downgrade/upgrade + `alembic check`, pytest
against postgres+redis service containers incl. the live queue smoke test) and
the frontend job (Node 22, pnpm, test, `lint:ratchet`, build) on every PR.

---

## 6. Known pre-existing check failures (documented, not fixed in Phase 0)

### `pnpm lint` — 16 errors, 6 warnings (ratcheted baseline)

Raw `pnpm lint` runs with `--max-warnings 0`, so any finding fails. CI instead
runs **`pnpm run lint:ratchet`**, which passes as long as the counts stay at or
below `frontend/.lint-baseline.json` (`{"maxErrors": 16, "maxWarnings": 6}`).
The baseline started at 19 errors (Batch 2) and has been lowered as pre-existing
issues were fixed — **never raised**. Remaining are pre-existing
`@typescript-eslint/no-explicit-any` (`AgentActivity.tsx`, `commits/types.ts`),
one `no-case-declarations` (`BestOfNEvalsPage.tsx`), and `react-hooks` /
`react-refresh` warnings. **Severity:** low; cosmetic/type-hygiene.

### `pnpm build` — large-bundle warning

Single 1.41 MB (446 kB gzip) JS chunk; Vite suggests code-splitting. **Severity:**
low now, medium for a growing IDE-style app. Not a failure.

### `ts-jest` — `esModuleInterop` warning

Cosmetic; tests pass. Setting `esModuleInterop: true` in `tsconfig.json` would
silence it.

### `pyright` — 36 `reportUnknownVariableType` warnings

Expected: `pyrightconfig.json` opts into this as `warning` mode. **0 errors.**
Not a regression.

---

## 7. Windows-specific issues observed during discovery

| Issue | Detail | Workaround used |
|---|---|---|
| **No Poetry / no backend venv preinstalled** | Fresh checkout; `poetry` not on PATH | `python -m pip install --user poetry` (got 2.4.2); Poetry Scripts dir (`%APPDATA%\Python\Python314\Scripts`) is **not on PATH** — invoke as `python -m poetry ...` |
| **Only untested Python versions present** | System Python is **3.14.4**; a uv-managed **CPython 3.13.14** also present. Project targets `^3.10`, upstream tests on 3.12 | Pointed Poetry at the 3.13 interpreter: `python -m poetry env use "<uv>/cpython-3.13.14-.../python.exe"` → venv `backend-vz4K55On-py3.13`; `poetry install` + all tests **passed**. **Still recommend installing 3.12** for parity. |
| **`frontend/Dockerfile` uses yarn** | References `yarn.lock` (absent) and `yarn dev` | Use `pnpm` locally; Dockerfile needs fixing before container use |
| **`pnpm install` "Ignored build scripts" warning** | `esbuild`, `puppeteer` post-install scripts skipped | Harmless (AGENTS.md confirms); Vite build/dev/tests work without `pnpm approve-builds` |
| **UTF-8 `.env` on Windows** | README/FAQ: Notepad can save `.env` as non-UTF-8 → backend read errors | Save `.env` as UTF-8 (VS Code / Notepad++) |
| **`localhost` vs `127.0.0.1` for Vite** | Vite `host: true` but AGENTS.md: `127.0.0.1:5173` is refused in some setups | Use `http://localhost:5173` |
| Bash tool `cd` vs PowerShell CWD | The Bash and PowerShell tools keep independent working directories; `cd backend` in one doesn't affect the other | Use absolute paths |

Line endings: `.gitattributes` exists (68 bytes) — check its contents before bulk
edits on Windows.

---

## 8. Browser & Docker requirements summary

- **Browser (Chromium):** only needed for the optional `screenshot_preview`
  agent tool and the `preview_screenshot` module. Installed via
  `poetry run playwright install chromium`. On Linux use
  `playwright install --with-deps chromium` (needs apt/sudo). Backend launches it
  headless with `--no-sandbox`. If absent, the tool is silently disabled and
  `/api/capabilities` reports `screenshot_preview: false`.
- **Docker:** entirely optional for local dev. The compose stack is for a quick
  demo run, not development (no bind mounts, no reload). `.playwright/` and
  `.playwright-cli/` dirs exist locally (the latter is git-ignored as it "may
  contain credentials").

---

## 9. Quick reference — minimal working setup

```bash
# 1. Python 3.12 (recommended) via pyenv-win / uv / python.org
# 2. Backend
cd backend
python -m pip install --user poetry           # if poetry missing
python -m poetry env use python3.12            # or a full path to 3.12
python -m poetry install
printf 'GEMINI_API_KEY=...\nANTHROPIC_API_KEY=...\n' > .env
python -m poetry run playwright install chromium   # optional
python -m poetry run uvicorn main:app --reload --port 7001

# 3. Frontend (new terminal)
cd frontend
pnpm install
pnpm dev
# open http://localhost:5173

# 4. Sanity checks
cd backend && python -m poetry run pytest && python -m poetry run pyright
cd frontend && pnpm test && pnpm build     # (pnpm lint currently fails — see §6)
```
