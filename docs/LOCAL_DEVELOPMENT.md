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

> ⚠️ `frontend/Dockerfile` still uses `yarn install` / `yarn dev` and references
> a non-existent `yarn.lock`. The repo migrated to pnpm; the Dockerfile is
> stale. Use `pnpm` directly for local dev; fix the Dockerfile before relying on
> the container path.

---

## 2. Environment variables

### Backend (`backend/.env`, loaded by `python-dotenv` in `main.py`)

| Var | Required? | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | one of the three | GPT code-gen variants |
| `ANTHROPIC_API_KEY` | one of the three | Claude code-gen variants |
| `GEMINI_API_KEY` | one of the three — **needed for video mode and asset extraction** | Gemini code-gen + `extract_assets` tool + video input |
| `REPLICATE_API_KEY` | optional (**`.env` only**, not accepted from the UI) | `generate_images`, `edit_images`, `remove_backgrounds` |
| `OPENAI_BASE_URL` | optional | OpenAI proxy; **ignored when `IS_PROD` is truthy** |
| `IS_PROD` | optional | Truthy = production feature flags (disables base-URL override, changes error copy). Any non-empty value is truthy. |
| `IS_DEBUG_ENABLED` | optional | Truthy = sends `variantModels` to the client, enables `debug/` file dumps. Note: `bool(os.environ.get(...))` — **any non-empty string is true, including `"false"`**. |
| `DEBUG_DIR` | optional | Where `DebugFileWriter` writes |
| `PROMPT_REPORTS_ENABLED` | optional | `1/true/yes/on` = full run capture (JSONL + SQLite + HTML/asset snapshots) under `run_logs/agent_runs`; browsable at `/evals/prompt-reports` and `/evals/agent-runs` |
| `LOGS_PATH` | optional | Base dir for `run_logs/` (see `fs_logging/prompt_reports.get_run_logs_directory`) |
| `LOCAL_ASSET_DIR` | optional | Default `backend/local_assets/`; content-addressed image store served at `/local-assets/` |
| `LOCAL_ASSET_BASE_URL` | optional | Default `http://127.0.0.1:7001`; used by the evals path which has no request to infer host from |
| `SCREENSHOT_TO_CODE_DATA_DIR` | optional | Default `~/.screenshot-to-code/`; holds `design-systems.json` |

Config constants **not** env-driven: `NUM_VARIANTS = 4`, `NUM_VARIANTS_VIDEO = 2`,
`GENERATION_MAX_COST_USD = 3.0` (all in `backend/config.py`).

At least one of `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` must be
available (env or Settings dialog) or generation fails fast with
`"No OpenAI, Anthropic, or Gemini API key found"`.

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
| — | — | — | AGENTS.md note: use `http://localhost:5173`, **not** `127.0.0.1:5173` (the latter is refused in some setups) |

**No ports are used for:** a database, Redis, generated-app previews, or a
browser-automation service — none of those exist yet. Headless Chromium for
`screenshot_preview` runs in-process in the backend (no port).

`start.py` is the only component with port-conflict handling; `uvicorn
main:app` directly does not scan.

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
| Backend unit tests | `cd backend && poetry run pytest` | **276 passed** (~77 s) on Python 3.13 |
| Backend type check | `cd backend && poetry run pyright` | **0 errors, 36 warnings** (all `reportUnknownVariableType`, which `pyrightconfig.json` sets to `warning`) |
| Frontend lint | `cd frontend && pnpm lint` | **FAILS**: 19 errors + 6 warnings, all pre-existing (see §6) |
| Frontend unit tests | `cd frontend && pnpm test` | **42 passed, 6 skipped, 1 suite skipped** (`qa.test.ts`, gated by `RUN_E2E`) |
| Frontend E2E/QA | `cd frontend && pnpm test:qa` (needs `RUN_E2E=true`, a running app, provider keys) | **not run** during discovery (requires live services + keys) |
| Frontend build | `cd frontend && pnpm build` (`tsc && vite build`) | **passes**; emits one ~1.4 MB JS chunk (no code-splitting; Vite warns >500 kB) |
| Root convenience | `pnpm test` (root) | runs frontend jest + backend pytest |
| Backend eval runner | `cd backend && poetry run python run_evals.py` | needs an eval dataset in `backend/evals_data/inputs` (not in repo) + keys — not run |

pytest config: `backend/pytest.ini` (`testpaths = tests`, `asyncio_mode = auto`).
There is **no CI** (`.github/` has only issue templates + a local Impeccable
hook; no workflows).

---

## 6. Known pre-existing check failures (documented, not fixed in Phase 0)

### `pnpm lint` — 19 errors, 6 warnings

Runs with `--max-warnings 0`, so any finding fails. All are pre-existing
(AGENTS.md explicitly calls this out). Breakdown:

| Rule | Count | Files |
|---|---|---|
| `@typescript-eslint/no-explicit-any` | 18 | `components/agent/AgentActivity.tsx`, `components/commits/types.ts`, `generateCode.ts` |
| `no-case-declarations` | 1 | `components/evals/BestOfNEvalsPage.tsx:215` |
| `react-hooks/exhaustive-deps` | 4 (warnings) | `BestOfNEvalsPage.tsx`, `CodeMirror.tsx`, `Variants.tsx` |
| `react-refresh/only-export-components` | 2 (warnings) | `ui/badge.tsx`, `ui/button.tsx` |

**Severity:** low. Cosmetic/type-hygiene; no runtime impact. **Cause:** upstream
never enforced lint in CI. **Action:** decide the lint-baseline policy when CI
lands (fix-forward the `any`s, or start lint non-blocking and ratchet) — see
TECHNICAL_DECISIONS.md D10.

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
