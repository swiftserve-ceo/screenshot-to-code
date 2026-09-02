# LG Telecoms App Builder — Baseline Functional Audit

> **Status:** Complete-as-possible functional baseline of the **inherited** application
> (`screenshot-to-code`, MIT © 2023 Abi Raja) performed on **2026-09-02**, before any
> Phase 1 implementation. This is the **"before" state** — the regression baseline that every
> future LG Telecoms App Builder phase is measured against.
>
> **No application functionality was modified.** Failures are recorded, not fixed.
>
> **This document is frozen as the "before" baseline.** Remediation of its
> findings is tracked in `docs/REMEDIATION_LOG.md`. As of Batch 1 (2026-09-02):
> KF-1, KF-2, KF-5, SF-1, SF-2, SF-3, SF-4, SF-8, SF-9 addressed; the stale
> `frontend/Dockerfile` repaired; structured logging groundwork laid. KF-3, KF-7,
> KF-8, SF-5, SF-6, SF-7 and the rest remain for later batches / phases.
>
> Result classifications: **PASS** / **PARTIAL** / **FAIL** / **NOT TESTABLE** / **NOT IMPLEMENTED**.
> "NOT TESTABLE — MISSING CREDENTIALS" is never reported as PASS.

---

## 1. Executive Summary

**Does the inherited application actually work correctly before we begin transforming it?**

**Partially — and only for the non-AI paths.** The application shell, the four input UIs, the
import-existing-code flow, the preview/editor, settings, and the backend's non-generation
HTTP APIs all work. The **core value proposition — AI code generation — cannot be verified in
this environment**: there are no provider API keys (`backend/.env` absent), so every provider
is **NOT TESTABLE — MISSING CREDENTIALS**. Separately, on a default Windows console the
generation pipeline **crashes before any provider is even contacted** due to a
`UnicodeEncodeError` in unstructured `print` logging (`utils.py::print_prompt_preview`);
setting `PYTHONUTF8=1` works around it and lets the pipeline reach the (correct)
"no API key" error.

**Automated tests match the Phase 0 baseline exactly**: backend `pytest` 276 passed, `pyright`
0 errors / 36 warnings, frontend `jest` 42 passed / 6 skipped, frontend `build` passes,
frontend `lint` **fails** with 19 pre-existing errors.

**The internal eval/telemetry UI (`/evals/*` data pages) is broken in the documented
`pnpm dev` setup** — those pages call backend paths the Vite proxy does not forward, so they
receive the SPA's HTML and fail to parse it.

**Security posture is as Phase 0 documented, now demonstrated live**: the main preview iframe
has **no `sandbox` attribute** and generated page JavaScript can read the host app's
`localStorage` (which holds API keys) — confirmed at runtime (`canReadParent: true`). CORS
reflects any origin with credentials — confirmed (`access-control-allow-origin:
https://evil.example`). All eval/telemetry endpoints are reachable unauthenticated and leak
absolute filesystem paths. There is **no authentication anywhere**.

**Totals:** 63 capabilities assessed — **PASS 18 · PARTIAL 13 · FAIL 5 · NOT TESTABLE 12 ·
NOT IMPLEMENTED 15** (full matrix in §18).

---

## 2. Environment

| Item | Value |
|---|---|
| Repo / branch | `C:\dev\LG_Telecoms_App_Builder` @ `lg-telecoms-app-builder-foundation` |
| OS | Windows 11 Pro 26200 |
| Frontend URL | `http://localhost:5180/` |
| Backend URL | `http://127.0.0.1:7001/` |
| Frontend cmd | `cd frontend && pnpm dev --port 5180 --strictPort` (Vite 6.4.3) |
| Backend cmd | `cd backend && python -m poetry run uvicorn main:app --port 7001 --host 127.0.0.1` — **on Windows also set `PYTHONUTF8=1`** (see §7, KF-1) |
| Node / pnpm | v24.15.0 / 10.32.1 |
| Python | Poetry venv `backend-vz4K55On-py3.13` (CPython **3.13.14**, uv-provided); upstream targets 3.12 |
| Poetry | 2.4.2 (invoked as `python -m poetry`) |
| Provider keys | **none** — `backend/.env` and `frontend/.env.local` absent |
| Playwright Chromium | installed (`chromium-1228`) — required for backend startup (see §7, KF-2) |
| Browser automation | `playwright-cli` v0.1.19 (global), headless Chrome |
| Port note | `:5173` (repo default) is held by an unrelated project (`C:\Dev\Swift_IT_Agents`); this audit pinned `:5180` |

---

## 3. Application Routes

### Frontend routes (`frontend/src/main.tsx`)

| Route | Component | Renders | Data layer | Result |
|---|---|---|---|---|
| `/` | `App` | Full app (input → editor/preview → settings) | in-memory Zustand + `/api/*` (proxied) | **PASS** — loads, 0 console errors |
| `/evals` | `AllEvalsPage` | "Evals Dashboard" shell | calls `/evals` (not proxied) | **PARTIAL** — shell renders, no console error observed, but list data path is not proxied |
| `/evals/run` | `RunEvalsPage` | "Run Evaluations" | `/eval_input_files`, `/eval-sets` (not proxied) | **FAIL** — `SyntaxError: Unexpected token '<'` ×N; selectors stuck |
| `/evals/best-of-n` | `BestOfNEvalsPage` | "Configure Model Comparison" | `/models`, `/eval-sets` (not proxied) | **PARTIAL** — shell renders; data path not proxied |
| `/evals/openai-input-compare` | `OpenAIInputComparePage` | "OpenAI Input Compare" | `/openai-input-compare` (POST) | **PARTIAL** — shell renders |
| `/evals/prompt-reports` | `PromptReportsPage` | "Prompt Reports" | `/prompt-reports` (not proxied) | **FAIL** — `SyntaxError: Unexpected token '<'`; page stuck "Loading…" |
| `/evals/agent-runs` | `AgentRunsPage` | "Agent Runs" | `/agent-runs` (not proxied) | **FAIL** — `SyntaxError: Unexpected token '<'`; page stuck "Loading…" |
| `/evals/sessions` | `EvalSessionsPage` | "Eval Sessions" | `/eval-sets`, `/eval-sessions` (not proxied) | **FAIL** — `SyntaxError: Unexpected token '<'` ×3 |
| `/evals/compare` | `EvalComparePage` | "Compare" | `/eval-sessions/*` (not proxied) | **PARTIAL** — shell renders |

**Root cause of the eval-page failures:** `frontend/vite.config.ts` proxies only
`/generate-code`, `/api`, `/local-assets`. The eval pages fetch `${HTTP_BACKEND_URL}` +
`/agent-runs`, `/prompt-reports`, `/eval-sets`, `/eval-sessions`, `/eval_input_files`,
`/models` — none of which are proxied — so the Vite dev server returns `index.html` and the
JSON parse fails. The backend endpoints themselves are healthy (verified directly, §10).
→ **Target: Phase 1** (proxy/routing) and **Phase 2** (gate behind admin).

### Backend routes

Full inventory in §10. No `/`-level SPA is served by the backend; it is API-only
(`FastAPI(openapi_url=None, docs_url=None, redoc_url=None)` — `/docs`, `/openapi.json`,
`/redoc` all 404, verified).

---

## 4. Feature Inventory

Derived from source. "Exists" ≠ "works" — see result columns in §18.

**Input methods:** screenshot upload (1–5), multi-screenshot, single video/screen-recording,
URL→screenshot (via ScreenshotOne), text prompt, import existing HTML. Figma: **rejected in
UI, not implemented**.

**Generation modes:** create (image / multi-image / video / text), update/edit (chat
instruction, optional reference images, optional selected-element scope), regenerate,
import (no AI).

**AI providers:** OpenAI (Responses API), Anthropic (Messages), Google Gemini (`google-genai`)
for codegen; Replicate for image generation / editing / background removal; Gemini also for
`extract_assets` and video input.

**Model selection:** deploy-time config — `llm.Llm` enum (55 model/effort entries),
`MODEL_PROVIDER` map, `routes/model_choice_sets.py` hard-coded tuples chosen by
*which keys are present* × create/update/video, cycled to `NUM_VARIANTS` (4 create / 2 update
/ 2 video). No capability registry, no router, no user model picker.

**Agent:** `AgentEngine` tool-calling loop, `max_steps = 30`, per-variant spend ceiling
`GENERATION_MAX_COST_USD = $3` (`BudgetExceededError`). 9 canonical tools: `create_file`,
`edit_file` (string-replace), `generate_images`, `remove_backgrounds`, `edit_images`,
`extract_assets`, `screenshot_preview`, `save_assets`, `retrieve_option`.

**Preview:** desktop / mobile / code tabs; non-sandboxed `<iframe srcdoc>` (main) +
`sandbox="allow-scripts allow-same-origin"` iframe (variant thumbnails); "open in new tab"
(blob URL); "refresh preview" (srcdoc reset); backend headless-Chromium `screenshot_preview`
tool (`--no-sandbox`).

**Editing:** read-only code view (CodeMirror; `setCode` is a no-op in `PreviewPane`), chat-style
update, select-and-edit (click element in preview → scoped instruction), regenerate. No
undo/redo of edits; "versions" list is the history mechanism.

**Export / download:** `POST /api/export` → zip (`index.html` + inlined remote assets,
SSRF-guarded); client fallback to raw `index.html` blob; "Open in CodePen" (client POST to
codepen.io).

**Settings:** provider keys (OpenAI/Anthropic/Gemini/Replicate/ScreenshotOne, `localStorage`),
OpenAI base URL, app theme (system/light/dark), editor theme, placeholder-image toggle,
screenshot-preview availability indicator, stack selector, design-system selector/manager.

**Persistence:** browser `localStorage` for `setting` + `app-theme` only; **all project data
(commits/variants/generated code) is in-memory Zustand and lost on refresh**; design systems
in a global `~/.screenshot-to-code/design-systems.json`; agent-run telemetry opt-in
(`PROMPT_REPORTS_ENABLED`, currently off) → SQLite index + JSONL under `run_logs/`.

**Evaluation tooling:** backend image/text eval runner, eval sets/sessions, best-of-N,
OpenAI input compare, prompt-report browser, agent-run browser; ~8 internal `/evals/*` UI
pages.

**Auth / tenancy / billing / DB / queue / sandbox / IR / deploy:** **none — NOT IMPLEMENTED.**

**External integrations:** OpenAI, Anthropic, Gemini, Replicate, ScreenshotOne (`/api/screenshot`
proxy), CodePen (client), Tailwind/Babel/Font-Awesome/Ionic CDNs (referenced by generated
pages), screenshotone.com. `langfuse` is a dependency but not wired.

---

## 5. Input Workflows

| # | Workflow | Opened | Valid input provided | Submitted | Backend request | Result state | Error handling | Verdict |
|---|---|---|---|---|---|---|---|---|
| A | Screenshot upload | ✔ (Upload tab) | dropzone + file input present, `maxSize 20 MB`, `image/png,jpeg,heic`, `MAX_FILES = 5` | — (not driven to generation) | asset upload path (`persist_data_url_as_temporary_asset`) source-verified; `/local-assets` mount works (§10) | n/a | n/a | **PARTIAL** — UI + asset plumbing OK; generation blocked (missing creds / KF-1) |
| B | Multiple screenshots | ✔ | up to 5; "one video OR up to 5 screenshots" guard in source | — | — | n/a | toast guards in `UploadTab` source | **PARTIAL** |
| C | URL → screenshot | ✔ (URL tab) | `https://example.com` | ✔ (no ScreenshotOne key) | `POST /api/screenshot` → screenshotone.com → **500** `{"detail":"Error capturing screenshot: Error taking screenshot"}` (verified) | stays on input; toast "Failed to capture screenshot" | **works** — clear toast, no crash; `file://` and `figma.com` rejected client-side with specific toasts | **NOT TESTABLE — MISSING CREDENTIALS** for the success path; error path **PASS** |
| D | Figma import | ✔ (URL tab detects `figma.com`) | — | — | — | — | shows "Direct Figma import is not supported…" toast + inline hint | **NOT IMPLEMENTED** (intentional rejection) |
| E | Video / screen recording | ✔ (Upload tab; `ScreenRecorder.tsx` MediaRecorder→webm) | `.mp4/.mov/.webm`, single file, 20 MB | — | video uses Gemini only; blocked (no key / KF-1) | n/a | "Upload either one video or up to 5 screenshots" guard | **PARTIAL** (UI); recorder itself **NOT TESTABLE** (needs display-capture permission) |
| F | Text prompt | ✔ (Text tab) | "A simple hello world landing page with a blue header" | ✔ | WS `/generate-code`: `variantCount:4` → 4× `status` → **`error`** | error card + "Click Retry"; **app recovers**, Version 1 kept | empty prompt → toast "Please enter a description" (**PASS**); real prompt → generic **"Error assembling prompt. Contact support at support@getwhimsyworks.com"** on default console (KF-1); with `PYTHONUTF8=1` → correct **"No OpenAI, Anthropic, or Gemini API key found…"** | **FAIL** on default Windows console (KF-1); **NOT TESTABLE — MISSING CREDENTIALS** beyond provider selection |
| G | Import existing HTML | ✔ (Import tab) | pasted `<!doctype html>…` with Tailwind CDN + inline `onclick` | ✔ (stack = HTML + Tailwind) | none (fully client-side) | editor opens, "Imported existing code.", **preview renders the page** (Tailwind CDN executed, header + button visible) | empty code → toast "Please paste in some code"; no stack → toast "Please select your stack" (both **PASS**) | **PASS** — full end-to-end |

Evidence screenshots: `audit-import-preview.png` (imported page rendered),
`audit-selectmode.png` (`<h1>` selected via select-and-edit).

---

## 6. AI Providers / Models

| Provider | Configured in repo | Keys present | Generation tested | Streaming/events | Output | Error handling | Timeout / retry | Verdict |
|---|---|---|---|---|---|---|---|---|
| OpenAI | ✔ (`agent/providers/openai.py`, Responses API; 18 GPT entries) | **no** | no | no | no | "Incorrect OpenAI key" / quota messages exist in source; `openai.AuthenticationError`, `RateLimitError` caught (`generate_code.py`) | per-variant `$3` ceiling (`BudgetExceededError`); **no retries/fallbacks** (source) | **NOT TESTABLE — MISSING CREDENTIALS** |
| Anthropic | ✔ (`agent/providers/anthropic/`, Messages; 16 Claude entries; ephemeral prompt cache) | **no** | no | no | no | generic variant-error path | as above; no retries | **NOT TESTABLE — MISSING CREDENTIALS** |
| Google Gemini | ✔ (`agent/providers/gemini.py`, `google-genai`; 13 entries; also `extract_assets` + video) | **no** | no | no | no | generic; video mode has a specific "Video mode requires a Gemini API key" check (reached only after prompt assembly) | as above; no retries | **NOT TESTABLE — MISSING CREDENTIALS** |
| Replicate (images) | ✔ (`image_generation/replicate.py`; z-image-turbo, flux, p-image-edit, bg-removal) — **`.env`-only, not accepted from UI** | **no** | no | n/a | no | n/a | n/a | **NOT TESTABLE — MISSING CREDENTIALS** |
| ScreenshotOne | ✔ (`routes/screenshot.py` proxy) | **no** | error path only | n/a | n/a | 500 with detail (verified) | `httpx` timeout 60s | **NOT TESTABLE — MISSING CREDENTIALS** (success); error path **PASS** |

**Model-selection mechanism:** source-verified + **10 passing unit tests**
(`tests/test_model_selection.py`) cover every key-combination and create/update/video branch.
Cannot be exercised via UI without keys. **PARTIAL** (verified by tests + source, not by live run).

---

## 7. Generation Workflow

**Pipeline (`routes/generate_code.py`):** `WebSocketSetup → ParameterExtraction →
StatusBroadcast → PromptCreation → CodeGeneration → PostProcessing(no-op)`. `CodeGeneration`
fans out N `asyncio` tasks (one `AgentEngine.run()` per variant), `asyncio.gather`.

**Observed on this environment (no keys):**

1. WS connects, accepts JSON params. ✔
2. `variantCount` (4 create / 2 update / 2 video) + per-variant `status` "Generating code…". ✔
3. **PromptCreation** calls `utils.print_prompt_preview()` which `print`s box-drawing characters
   (`┌─ ├─ │`). On a non-UTF-8 stdout (Windows cp1252, and any redirected stdout) this raises
   `UnicodeEncodeError: 'charmap' codec can't encode characters…`, which propagates out of the
   middleware and surfaces to the client as **`error`: "Error assembling prompt. Contact
   support at support@getwhimsyworks.com"**, WS close code `4332`. **This blocks ALL
   generation modes before any provider call.** → **KF-1**, Target **Phase 1** (structured
   logging / no `print`).
4. With `PYTHONUTF8=1`: prompt assembly completes, **ModelSelection** runs and correctly emits
   **`error`: "No OpenAI, Anthropic, or Gemini API key found…"**, close `4332`.

**Frontend handling of the failure (verified):** toast with the server message + an error card
("Error generating code. Check the Developer Console AND the backend logs…", "Click Retry to
run this version's request again."), a "Version 1" commit is created, and the app remains
fully usable (**recoverable**). Retry re-issues the same request.

**Known startup failures:**

- **KF-2 — backend will not start if Playwright Chromium is missing.** `probe_screenshot_preview()`
  runs at startup; the failure-logging `print` in `PlaywrightBackend.available()` hits the same
  `UnicodeEncodeError` on box-drawing chars, so the caught browser-launch error is *re-raised*
  through the FastAPI lifespan and uvicorn exits code 3. The repo docs claim graceful
  degradation; **it does not degrade on Windows.** Fixed for this audit by
  `poetry run playwright install chromium` (a documented setup step).

**Verdict:** generation end-to-end is **FAIL on a default Windows console** (KF-1) and
**NOT TESTABLE — MISSING CREDENTIALS** beyond provider selection.

---

## 8. Preview Workflow

| Check | Result | Evidence |
|---|---|---|
| Preview loads | **PASS** | imported page rendered in `#preview-desktop` |
| Generated application renders | **PASS** (via import) | Tailwind CDN executed; header + button visible (`audit-import-preview.png`) |
| Desktop / Mobile / Code tabs | **PASS** | all three switch; code tab shows CodeMirror + Copy + "Open in CodePen" |
| Refresh preview | **PASS** (source + UI) | button clears then restores every `iframe.srcdoc` (`PreviewPane.tsx:219`) |
| "Open in new tab" (blob URL, injects `<base>`) | **NOT TESTED** (browser popup in automation) — code present |
| Iframe ↔ host communication | **PASS** | select-and-edit reads `iframe.contentDocument`; `<h1>` selected, sidebar switched to "Describe changes for the selected `<h1>` element…" (`audit-selectmode.png`) |
| Console errors captured into UI | **NOT IMPLEMENTED** | the "execution console" only shows backend `status` lines; the preview iframe's own `console`/errors are not surfaced |
| Runtime errors surfaced | **PARTIAL** | generated-page JS errors are not caught/shown; only generation-level errors are |
| Preview reset / reload | **PASS** | refresh button; also full re-mount on version switch |
| Preview state | **PASS** | throttled (200 ms) code updates; version navigation re-renders |
| **Security — iframe sandbox** | **FAIL** (see §15) | `#preview-desktop` `sandbox` attribute = **`null`**; `iframe.contentWindow.parent.localStorage` reachable → **`canReadParent: true`** (live) |

---

## 9. Asset Workflow

| Capability | Exists | Testable here | Result | Notes |
|---|---|---|---|---|
| Image extraction (`extract_assets`, Gemini) | ✔ | no | **NOT TESTABLE — MISSING CREDENTIALS** | 8 passing unit tests (`test_asset_extraction*`) |
| Image generation (`generate_images`, Replicate) | ✔ | no | **NOT TESTABLE — MISSING CREDENTIALS** | 9 passing unit tests (`test_image_generation_replicate`) |
| Image editing (`edit_images`, Replicate p-image-edit) | ✔ | no | **NOT TESTABLE — MISSING CREDENTIALS** | |
| Background removal (`remove_backgrounds`, Replicate) | ✔ | no | **NOT TESTABLE — MISSING CREDENTIALS** | |
| Uploaded-asset store (content-addressed, `_finalize_asset_bytes` has unused `user_id`) | ✔ | partial | **PASS** | `/local-assets/` mount serves; path traversal `../config.py`, `..%2fconfig.py` → all **404** (verified) |
| Asset references in generated code | ✔ | via import | **PASS** | imported page's `<script src="https://cdn.tailwindcss.com">` loaded and executed in preview |
| Asset display in preview | ✔ | via import | **PASS** | |
| Asset download in export | ✔ | via API | **PASS** | `/api/export` inlines remote assets into the zip (SSRF-guarded); minimal case returns valid zip with `index.html` (verified) |

---

## 10. Backend API

Base `http://127.0.0.1:7001`. **Authentication: none on any endpoint** (no `Depends`, no
security scheme anywhere in `backend/`). All results below are from direct `curl` this session.

| Method | Path | Purpose | Auth | Input | Output | Used by FE | Reachable | Functional test |
|---|---|---|---|---|---|---|---|---|
| WS | `/generate-code` | all code generation | none | JSON params | streamed events (§11) | ✔ (via proxy) | ✔ | **PARTIAL** — connects, streams `variantCount`/`status`/`error`; full run FAIL/NOT TESTABLE (§7) |
| GET | `/` | health string | none | — | `<h3>Your backend is running…</h3>` | ✖ | ✔ | **PASS** (200) |
| GET | `/api/capabilities` | feature flags | none | — | `{"screenshot_preview":true}` | ✔ | ✔ | **PASS** (200) |
| POST | `/api/screenshot` | ScreenshotOne proxy | none | `{url, apiKey}` | `{url: data-URL}` | ✔ | ✔ | **PARTIAL** — bad key → `500` `{"detail":"Error capturing screenshot: Error taking screenshot"}`; success NOT TESTABLE |
| POST | `/api/export` | zip export (SSRF-guarded) | none | `{code, baseUrl}` | `application/zip` | ✔ | ✔ | **PASS** — 200, valid zip, `index.html` inside |
| GET | `/api/design-systems` | list | none | — | `[]` | ✔ | ✔ | **PASS** (200) |
| POST | `/api/design-systems` | create | none | `{name, content}` | `DesignSystem` | ✔ | ✔ | **PASS** — created (writes global `~/.screenshot-to-code/design-systems.json`) |
| PATCH | `/api/design-systems/{id}` | update | none | `{name?, content?}` | `DesignSystem` | ✔ | ✔ | **PASS** — 200, `updatedAt` changes |
| DELETE | `/api/design-systems/{id}` | delete | none | — | `204` | ✔ | ✔ | **PASS** — 204; repeat → **404** (correct) |
| GET | `/local-assets/*` | static asset serving | none | — | file bytes | ✔ | ✔ | **PASS** — traversal attempts → 404 |
| GET | `/evals` | eval list | none | `?folder=` | JSON | ✔ (`/evals` page) | ✔ | **PARTIAL** — `422` without params; **not proxied** so FE call fails (§3) |
| GET | `/eval_input_files` | eval inputs | none | — | JSON | ✔ | ✔ | **FAIL (env)** — `500` (no `evals_data/inputs` dir); FE call not proxied |
| GET | `/models` | model list | none | — | `{...}` | ✔ | ✔ | **PASS** (200) — **unauthenticated** (finding SF-4) |
| GET | `/output_folders` | eval output dirs | none | — | `[]` | ✔ | ✔ | **PASS** (200) — unauthenticated |
| GET | `/eval-sets` | eval sets | none | — | `[]` | ✔ | ✔ | **PASS** (200) — unauthenticated |
| GET/POST/PUT | `/eval-sessions*` | session mgmt | none | — | JSON | ✔ | ✔ | **PASS** list (200) — unauthenticated; FE not proxied → page FAIL |
| GET/POST | `/prompt-reports*` | prompt-report browser + prune | none | — | JSON | ✔ | ✔ | **PASS** list (200) — unauthenticated; **leaks abs paths**; FE not proxied → page FAIL |
| GET/POST | `/agent-runs*` | agent-run browser + prune | none | — | `{"runs":[],"runs_directory":"C:\\Dev\\...\\run_logs\\agent_runs"}` | ✔ | ✔ | **PASS** list (200) — unauthenticated; **leaks abs paths**; FE not proxied → page FAIL |
| GET | `/best-of-n-evals` | best-of-N view | none | — | JSON | ✔ | ✔ | **FAIL (env)** — `500` without data |
| POST | `/run_evals`, `/run_evals_stream` | run evals | none | JSON | JSON / SSE | ✔ | ✔ | **NOT TESTED** (would spend money; no keys) |
| POST | `/openai-input-compare` | input diff tool | none | JSON | JSON | ✔ | ✔ | **NOT TESTED**; 2 passing unit tests |
| GET | `/docs`, `/openapi.json`, `/redoc` | API docs | — | — | — | — | — | **404** (disabled — good) |

CORS: `allow_origins=["*"]` + `allow_credentials=True` + `allow_methods=["*"]` +
`allow_headers=["*"]` (`main.py:43`). Verified: an `OPTIONS` preflight with
`Origin: https://evil.example` returns `access-control-allow-origin: https://evil.example`
and `access-control-allow-credentials: true`. → **SF-3**.

---

## 11. WebSocket / Streaming

**Endpoint:** `ws://127.0.0.1:7001/generate-code` (single endpoint; all generation).

| Check | Result | Evidence |
|---|---|---|
| Connection establishment | **PASS** | `websockets.connect` succeeds; server `accept`s |
| Params transport | **PASS** | client sends one JSON blob on open (`generateCode.ts`): `generatedCodeConfig, inputMode, generationType, prompt{text,images[],videos[]}, history[], fileState?, openAiApiKey?, anthropicApiKey?, geminiApiKey?, replicateApiKey?, designSystem?, optionCodes[]` |
| Progress events | **PASS** | `variantCount`, `status` observed |
| Generation events (defined) | source-verified, not exercised end-to-end | `chunk`, `setCode`, `thinking`, `assistant`, `toolStart`, `toolResult`, `variantComplete`, `variantModels` (only when `IS_DEBUG_ENABLED`) |
| Completion events | **NOT TESTABLE** | requires a successful generation |
| Error events | **PASS** | `{"type":"error","value":"…"}` then close code **`4332`** (`APP_ERROR_WEB_SOCKET_CODE`); invalid stack / invalid inputMode → clean per-message errors |
| Disconnect handling | source-verified | server catches `WebSocketDisconnect` / `ConnectionClosed*`; client close `4001` (`USER_CLOSE_WEB_SOCKET_CODE`) = user cancel |
| Reconnect / resume | **NOT IMPLEMENTED** | each generation is a fresh socket; generation lifetime == socket lifetime; a dropped socket kills the run; no server-side run record (telemetry is opt-in and off) |
| Backpressure / multiplexing | source-verified | N variants multiplex on one socket tagged by `variantIndex` |

**What currently travels over the WS:** client→server: a single settings+prompt JSON
(including **plaintext provider keys** when set in the UI). server→client: the event types
above, streamed, terminated by socket close (1000 = success, 4332 = app error, 4001 = user
cancel, other = connection error).

---

## 12. Error Handling

Safe, non-destructive scenarios only.

| Scenario | Frontend | Backend | Feedback | Recoverable | Verdict |
|---|---|---|---|---|---|
| Empty text prompt | toast "Please enter a description" | not contacted | ✔ | ✔ | **PASS** |
| Empty import code | toast "Please paste in some code" | n/a | ✔ | ✔ | **PASS** |
| Import without stack | toast "Please select your stack" | n/a | ✔ | ✔ | **PASS** |
| Invalid URL scheme (`file://`) | specific toast, blocks submit | not contacted | ✔ | ✔ | **PASS** |
| Figma URL | specific toast + inline hint | not contacted | ✔ | ✔ | **PASS** (intentional) |
| URL screenshot, no ScreenshotOne key | toast "Please add a ScreenshotOne API key…" | not contacted | ✔ | ✔ | **PASS** |
| URL screenshot, bad key | toast "Failed to capture screenshot" | `500` w/ detail | ✔ | ✔ | **PASS** |
| Invalid stack over WS | — | `error` event + close 4332 | ✔ | ✔ | **PASS** |
| Invalid inputMode over WS | — | `error` event + close 4332 | ✔ | ✔ | **PASS** |
| Malformed WS request (missing prompt) | — | `error` (assembling / no-key) + close 4332 | partial (generic message) | ✔ | **PARTIAL** |
| Text generation, no keys | error card + Retry, Version kept | `error` event | ✔ (message is generic on default console — KF-1) | ✔ | **PARTIAL** |
| Video generation, no Gemini key | (not driven via UI) | `error` (assembling on default console; would be "Video mode requires a Gemini API key" post-assembly) | partial | ✔ | **PARTIAL** |
| Backend unavailable (stopped mid-session) | toast "Error generating code…"; WS `error`/`close` handlers fire | n/a | ✔ | ✔ | **PASS** |
| Oversized file (>20 MB) | `react-dropzone` `maxSize` rejects client-side | n/a | ✔ | ✔ | **PASS** (source; uploaded-asset store also caps 20 MB + MIME allowlist) |
| Delete non-existent design system | — | `404` "Design system not found" | ✔ | ✔ | **PASS** |

**No crash of the frontend or backend was observed in any scenario.** The generation error
message on a default Windows console is misleading (KF-1) but the app stays usable.

---

## 13. Automated Test Results

Run this session on CPython 3.13.14 / Node 24 / pnpm 10.32.1.

| Suite | Command | Result | Phase 0 baseline | Delta |
|---|---|---|---|---|
| Backend unit | `poetry run pytest` | **276 passed** in ~134 s | 276 passed (~77 s) | ✅ same pass count; slower (machine under load) |
| Backend types | `poetry run pyright` | **0 errors, 36 warnings** | 0 errors, 36 warnings | ✅ identical |
| Frontend unit | `pnpm test` (jest) | **42 passed, 6 skipped, 1 suite skipped** (`qa.test.ts`) | 42 passed, 6 skipped | ✅ identical |
| Frontend lint | `pnpm lint` (`--max-warnings 0`) | **FAIL — 19 errors, 6 warnings**, exit 1 | 19 errors, 6 warnings | ✅ identical (pre-existing) |
| Frontend build | `pnpm build` (`tsc && vite build`) | **PASS** in ~37 s; 1 chunk **1.41 MB** (446 kB gz) — Vite >500 kB warning; `DEP0190` node deprecation warning (shell child process) | passes; same chunk warning | ✅ same |
| Frontend E2E | `pnpm test:qa` (`RUN_E2E=true`) | **NOT TESTABLE** — needs live app + provider keys | not run | — |
| Backend eval runner | `poetry run python run_evals.py` | **NOT TESTED** — needs `evals_data/inputs` + keys | not run | — |

**Lint errors (all pre-existing, unchanged):** 18× `@typescript-eslint/no-explicit-any`
(`components/agent/AgentActivity.tsx` ×13, `components/commits/types.ts` ×2,
`generateCode.ts` ×3), 1× `no-case-declarations` (`BestOfNEvalsPage.tsx:215`).
**Warnings:** 4× `react-hooks/exhaustive-deps`, 2× `react-refresh/only-export-components`.

**No CI exists** (`.github/` has issue templates + a local Impeccable hook; no workflows).

---

## 14. Performance / Resource Observations

| Metric | Observation |
|---|---|
| Backend cold start | ~4 s to healthy (Chromium present + warmed). **Instant crash (exit 3)** if Chromium missing (KF-2). |
| Frontend Vite ready | 4.8 s idle; **up to 19 s under CPU contention** (concurrent pyright + build). Slow first paint under load — `playwright-cli` hit a 60 s `domcontentloaded` timeout once during the test-suite run. |
| Frontend build | ~37 s (`tsc && vite build`), ~92 s wall under load |
| Backend pytest | ~134 s under load (Phase 0 measured ~77 s idle on 3.13) |
| Generation latency | **N/A** — cannot generate (KF-1 / missing keys) |
| Browser console (main app `/`) | **0 errors**, 2 warnings (React Router v7 `v7_startTransition`, `v7_relativeSplatPath`), 1 info (React DevTools) |
| Browser console (eval pages) | **JSON `SyntaxError`** on every data page (§3) |
| Failed network requests | eval pages: `GET /agent-runs`, `/prompt-reports`, `/eval-sets`, `/eval-sessions`, `/eval_input_files` → 200 but HTML body (Vite fallthrough) → parse error |
| Bundle | single 1.41 MB JS chunk, no code-splitting — medium concern for an IDE-style app |
| Long-running processes | one shared headless Chromium in the API process (lazy, reused); no worker/queue |
| Obvious bottlenecks | (1) generation lifetime bound to a socket; (2) no job queue → long runs fragile; (3) `asyncio.gather` of N full agent runs in one process; (4) unstructured `print` logging on the hot path (and it crashes — KF-1) |

---

## 15. Security Observations

Non-destructive review; source + live probes. **Nothing fixed.**

| ID | Finding | Evidence | Severity | Target phase |
|---|---|---|---|---|
| **SF-1** | **Main preview iframe has no `sandbox`.** Generated/imported page JS runs same-origin with the app; can read the host's `localStorage` (provider keys), `window.parent`, `document.cookie`, and issue same-origin requests. | `PreviewComponent.tsx:309-318` (no `sandbox` attr); live: `document.querySelector('#preview-desktop')` → `sandbox: null`, `contentWindow.parent.localStorage` → **`canReadParent: true`** | **Critical** | **Phase 1** (quick win: add `sandbox` without `allow-same-origin`; rework select-and-edit to `postMessage`) + **Phase 6** (full isolation) |
| **SF-2** | **Variant-thumbnail iframe uses `sandbox="allow-scripts allow-same-origin"`** — the "an iframe which has both … can escape its sandboxing" anti-pattern (effectively unsandboxed). | `Variants.tsx:73`; browser console warning at `about:srcdoc` | High | **Phase 1** |
| **SF-3** | **CORS reflects any origin with credentials.** `allow_origins=["*"]` + `allow_credentials=True` (invalid per spec, permissive). | `main.py:43`; live preflight from `https://evil.example` reflected | High | **Phase 1** |
| **SF-4** | **All eval/telemetry/admin endpoints unauthenticated** (`/models`, `/output_folders`, `/eval-sets`, `/eval-sessions*`, `/prompt-reports*`, `/agent-runs*`, `/run_evals*`, `/evals`, `/best-of-n-evals`). Several **leak absolute host filesystem paths** (`C:\Dev\LG_Telecoms_App_Builder\backend\run_logs\agent_runs`). `/run_evals` can spend money. | live 200s; `/agent-runs` body | High | **Phase 1** (operator gate) + **Phase 2** (real authz) |
| **SF-5** | **No authentication anywhere.** Anyone reaching the backend can generate (spending host keys if set), CRUD design systems, browse telemetry, trigger evals. | no `Depends`/security scheme in `backend/` | Critical (for a hosted product) | **Phase 2** |
| **SF-6** | **Provider keys in the browser.** Entered in Settings, stored in `localStorage`, sent as plaintext fields in every `/generate-code` payload. Reachable by SF-1. | `App.tsx` settings, `generateCode.ts` `ws.send(JSON.stringify(params))` | High | **Phase 2** (server-side secrets; remove browser keys) |
| **SF-7** | **Backend headless Chromium launched `--no-sandbox`, in the API process, with network access.** Renders generated HTML. | `preview_screenshot/playwright_backend.py:39` | Medium–High | **Phase 6** (move to sandbox tier) — must remain **documented as unsafe until then** |
| **SF-8** | **Config boolean foot-guns.** `IS_PROD = os.environ.get("IS_PROD", False)`, `IS_DEBUG_ENABLED = bool(os.environ.get(...))` — the string `"false"` is truthy. | `config.py:16,37` | Medium | **Phase 1** |
| **SF-9** | **Upstream support address / copy exposed to end users** in a live error path: "Contact support at `support@getwhimsyworks.com`". | WS `error` value (verified) | Low (cosmetic / rebrand / info-leak) | **Phase 1** |
| **SF-10** | **Unstructured `print` logging crashes on non-ASCII stdout** (`print_prompt_preview`, `screenshot_preview` error path). Reliability + it dumps full prompt/asset payloads to stdout when it doesn't crash. | KF-1, KF-2; `utils.py:151` | Medium | **Phase 1** (structured logging) |
| **SF-11** | **`/api/screenshot` returns `500` for a client-supplied bad key** and echoes upstream error text; also a user-controlled outbound request to `screenshotone.com`. | live | Low | Phase 1 (error mapping) / Phase 3 (owned crawler) |

**Confirmed SAFE (no finding — preserve in Phase 1):**

- `/api/export` SSRF protection (`is_public_http_url` blocks private/loopback/link-local, caps
  redirects/size/count) — 3 passing tests.
- `/agent-runs/{id}/assets/{filename}` path-traversal guard (`basename` + realpath containment).
- `/local-assets/*` traversal — `../config.py`, `..%2fconfig.py` → 404 (verified).
- Uploaded assets: 20 MB cap + MIME allowlist.
- `OPENAI_BASE_URL` override disabled when `IS_PROD` truthy (SSRF/exfil guard).
- **No `subprocess` / `os.system` / `shell=True` / `docker` / `eval()` / `exec()` anywhere in
  `backend/`** (verified) — the only child process is Playwright's Chromium.
- OpenAPI/Swagger disabled (`/docs`, `/openapi.json`, `/redoc` → 404).
- No secrets committed to the repo; `.env`, `frontend/.env.local`, `.playwright-cli/`
  git-ignored.

---

## 16. Automated Test Results (delta vs Phase 0)

See §13. **Summary: identical pass/fail profile to the Phase 0 baseline.** No regression, no
improvement. The only differences are wall-clock times (machine under load) and that this run
explicitly confirmed the frontend E2E suite and backend eval runner are **NOT TESTABLE**
without a live app + provider keys.

---

## 17. Security Observations (Phase mapping)

| Finding | Phase 1 | Phase 2 | Phase 6 | Later |
|---|---|---|---|---|
| SF-1 preview sandbox | add `sandbox` (quick win) + `postMessage` select-and-edit | — | full preview isolation tier | — |
| SF-2 variant iframe sandbox | fix attribute | — | — | — |
| SF-3 CORS | restrict to allow-list | — | — | — |
| SF-4 open eval/telemetry endpoints | operator gate + stop path leakage | domain RBAC | — | — |
| SF-5 no auth | — | OIDC + policy layer | — | — |
| SF-6 browser keys | — | server-side secrets, remove browser keys | — | — |
| SF-7 `--no-sandbox` backend Chromium | **document as unsafe-until-Phase-6** | — | move screenshotting into sandbox tier | — |
| SF-8 config booleans | typed settings (Pydantic) | — | — | — |
| SF-9 support copy | rebrand pass | — | — | — |
| SF-10 print logging | structured logging | — | — | Phase 10 tracing |
| SF-11 screenshot proxy | error mapping | — | — | Phase 3 owned crawler |

---

## 18. Feature Matrix

| Feature | Exists | Tested | Result | Evidence | Failure / Risk | Target Phase |
|---|---|---|---|---|---|---|
| App shell loads (`/`) | ✔ | ✔ | **PASS** | title "Screenshot to Code", 0 console errors | — | — |
| Navigation / tabs / dialogs / dropdowns | ✔ | ✔ | **PASS** | Upload/URL/Text/Import tabs, Settings dialog, stack Radix select all operable | — | — |
| Settings — provider keys (localStorage) | ✔ | ✔ | **PASS** | 5 key fields render & persist; "Only stored in your browser" | SF-6 | Phase 2 |
| Settings — theme (system/light/dark) | ✔ | ✔ | **PASS** | `app-theme` persisted | — | — |
| Settings — editor theme / image-gen toggle | ✔ | ✔ | **PASS** | Cobalt default; switch checked | — | — |
| Settings — screenshot-preview indicator | ✔ | ✔ | **PASS** | shows "Available" (reflects `/api/capabilities`) | — | — |
| Input — screenshot upload (1–5) | ✔ | partial | **PARTIAL** | dropzone + Choose File; `MAX_FILES=5`, 20 MB | generation blocked (KF-1/keys) | Phase 3 |
| Input — multi-screenshot | ✔ | partial | **PARTIAL** | source guards | as above | Phase 3 |
| Input — URL → screenshot | ✔ | ✔ (error path) | **NOT TESTABLE** (success) | `500` on bad key; no ScreenshotOne key | needs key | Phase 3 (owned crawler) |
| Input — Figma | ✖ | ✔ | **NOT IMPLEMENTED** | figma.com URLs rejected with toast | — | Phase 3 |
| Input — video / screen recording | ✔ | partial | **PARTIAL** | `.mp4/.mov/.webm`, `ScreenRecorder.tsx`; recorder itself NOT TESTABLE | Gemini-only; blocked | Phase 3 |
| Input — text prompt | ✔ | ✔ | **FAIL** (default console) / **NOT TESTABLE** beyond | reaches "no API key" only with `PYTHONUTF8=1` | KF-1; keys | Phase 1 / Phase 3 |
| Input — import existing HTML | ✔ | ✔ | **PASS** | import → editor → preview renders (`audit-import-preview.png`) | — | — |
| Generation — create (image/text/video) | ✔ | ✔ | **FAIL** (default console) + **NOT TESTABLE** (keys) | §7 | KF-1, missing creds | Phase 1 (logging) |
| Generation — update / edit (chat) | ✔ | partial | **NOT TESTABLE** | needs a base generation | keys | Phase 3 |
| Generation — regenerate / retry | ✔ | ✔ (UI only) | **PARTIAL** | "Click Retry" card appears after failure | can't confirm success | Phase 1 |
| Generation — variants (2–4, multiplexed) | ✔ | partial | **PARTIAL** | `variantCount` event = 4/2 observed | full variant lifecycle NOT TESTABLE | Phase 1 |
| AI provider — OpenAI | ✔ | ✖ | **NOT TESTABLE — MISSING CREDENTIALS** | no `.env` | — | — |
| AI provider — Anthropic | ✔ | ✖ | **NOT TESTABLE — MISSING CREDENTIALS** | — | — | — |
| AI provider — Gemini | ✔ | ✖ | **NOT TESTABLE — MISSING CREDENTIALS** | — | — | — |
| AI provider — Replicate (images) | ✔ | ✖ | **NOT TESTABLE — MISSING CREDENTIALS** | `.env`-only | — | — |
| Model selection (keys × mode → tuple) | ✔ | tests | **PARTIAL** | 10 passing unit tests; source | no live run | Phase 1 (registry) / Phase 2 (router) |
| Agent loop (`max_steps=30`, `$3` ceiling) | ✔ | tests | **PARTIAL** | `test_agent_engine` passes; source | no live run | Phase 1 (worker wrap) |
| Agent tools (9 canonical) | ✔ | tests | **PARTIAL** | `test_agent_tools`, `test_agent_tool_runtime` pass | no live run | Phase 3+ |
| Preview — render generated app | ✔ | ✔ (via import) | **PASS** | `audit-import-preview.png` | — | — |
| Preview — desktop / mobile / code tabs | ✔ | ✔ | **PASS** | all switch | — | — |
| Preview — refresh / reset | ✔ | ✔ | **PASS** | srcdoc reset button | — | — |
| Preview — open in new tab (blob) | ✔ | ✖ | **NOT TESTED** | code present | popup in automation | — |
| Preview — iframe ↔ host comms | ✔ | ✔ | **PASS** | select-and-edit selects `<h1>` (`audit-selectmode.png`) | depends on no-sandbox (SF-1) | Phase 1 |
| Preview — console/runtime error capture | ✖ | ✔ | **NOT IMPLEMENTED** | only backend status lines shown | — | Phase 5 |
| Preview — **iframe sandboxing** | ✖ | ✔ | **FAIL** | `sandbox: null`, `canReadParent: true` | **SF-1** | Phase 1 + 6 |
| Code — display (CodeMirror) | ✔ | ✔ | **PASS** | code tab shows imported HTML | — | — |
| Code — copy / open-in-CodePen | ✔ | ✖ | **NOT TESTED** | buttons present | external POST | — |
| Code — in-editor editing | ✔ (editor) ✖ (wired) | ✔ | **NOT IMPLEMENTED** (effective) | `PreviewPane` passes `setCode={() => {}}` — edits don't propagate | edits silently lost | Phase 3 |
| Edit — select-and-edit (target element) | ✔ | ✔ | **PARTIAL** | selection + scoped-instruction UI work | the edit itself needs generation | Phase 1/3 |
| Edit — undo/redo | ✖ | ✔ | **NOT IMPLEMENTED** | no undo; "Versions" is the mechanism | — | Phase 7 |
| Versions — list / navigate / switch | ✔ | ✔ | **PASS** | "Version 1 / Latest", prev/next nav | in-memory only | Phase 7 |
| Versions — persistence across refresh | ✖ | ✔ | **FAIL** (by design) | reload → back to Upload screen; only `setting`+`app-theme` in localStorage | all work lost on refresh | Phase 2 |
| Export — zip (`/api/export`) | ✔ | ✔ | **PASS** | valid zip w/ `index.html` | — | Phase 8 (GitHub/deploy) |
| Export — client `index.html` fallback | ✔ | ✖ | **NOT TESTED** | code present | — | — |
| Download button (UI) | ✔ | partial | **PARTIAL** | wired to `/api/export` (which passes) | browser download not exercised | — |
| Asset — extraction (Gemini) | ✔ | tests | **NOT TESTABLE — MISSING CREDENTIALS** | 8 passing unit tests | — | Phase 3 |
| Asset — generation/edit/bg-removal (Replicate) | ✔ | tests | **NOT TESTABLE — MISSING CREDENTIALS** | 9 passing unit tests | — | — |
| Asset — uploaded-asset store + `/local-assets` | ✔ | ✔ | **PASS** | traversal → 404; serves files | `_finalize_asset_bytes` `user_id` ignored | Phase 2 (object storage) |
| Backend — `/` health | ✔ | ✔ | **PASS** | 200 | — | — |
| Backend — `/api/capabilities` | ✔ | ✔ | **PASS** | `{"screenshot_preview":true}` | — | — |
| Backend — `/api/screenshot` | ✔ | ✔ (error) | **PARTIAL** | `500` on bad key | success NOT TESTABLE; `500` for client error | Phase 3 |
| Backend — `/api/export` | ✔ | ✔ | **PASS** | valid zip | SSRF guard present | Phase 8 |
| Backend — `/api/design-systems` CRUD | ✔ | ✔ | **PASS** | create/patch/delete/404 all correct | global file, no tenancy | Phase 2 |
| Backend — `/local-assets/*` | ✔ | ✔ | **PASS** | traversal 404 | unauthenticated | Phase 2 |
| Backend — eval endpoints (`/eval-sets`, `/models`, …) | ✔ | ✔ | **PASS** (reachable) | 200 unauthenticated | **SF-4** path leak | Phase 1/2 |
| Backend — `/eval_input_files`, `/best-of-n-evals` | ✔ | ✔ | **FAIL (env)** | `500` (no eval data dir) | needs `evals_data/` | — |
| Eval UI pages (`/evals/run`, `/prompt-reports`, `/agent-runs`, `/sessions`) | ✔ | ✔ | **FAIL** | JSON `SyntaxError` — backend paths not proxied by Vite | unusable in `pnpm dev` | Phase 1 (proxy) + Phase 2 (gate) |
| Eval UI — `/evals` dashboard / `/best-of-n` / `/compare` / `/openai-input-compare` | ✔ | ✔ | **PARTIAL** | shell renders; data paths not proxied | as above | Phase 1/2 |
| WebSocket — connect / params / events | ✔ | ✔ | **PASS** | `variantCount`, `status`, `error`, close 4332 | — | Phase 1 |
| WebSocket — completion / streaming code | ✔ | ✖ | **NOT TESTABLE** | needs successful generation | — | Phase 1 |
| WebSocket — reconnect / resume | ✖ | ✔ | **NOT IMPLEMENTED** | run == socket lifetime | dropped socket kills run | Phase 1 (queue) |
| Screenshot-preview tool (backend Chromium) | ✔ | ✔ (startup probe) | **PASS** (available) | `/api/capabilities` true; startup log | **SF-7** `--no-sandbox`, in-process; **KF-2** crashes startup if browser missing | Phase 1 (KF-2) / Phase 6 (SF-7) |
| Auth / users | ✖ | ✔ | **NOT IMPLEMENTED** | no code | **SF-5** | Phase 2 |
| Orgs / workspaces / teams / roles | ✖ | ✔ | **NOT IMPLEMENTED** | no code | — | Phase 2 |
| Billing / subscriptions / AI credits | ✖ | ✔ | **NOT IMPLEMENTED** | only `$3`/variant ceiling + cost math | — | Phase 9 |
| Server-side projects / durable versions | ✖ | ✔ | **NOT IMPLEMENTED** | client Zustand only | — | Phase 2 / 7 |
| Database / migrations | ✖ | ✔ | **NOT IMPLEMENTED** | one SQLite telemetry index, ad-hoc `ALTER TABLE` | — | Phase 1 |
| Job queue / worker / Redis | ✖ | ✔ | **NOT IMPLEMENTED** | in-process `asyncio.gather` | — | Phase 1 |
| Structured logging / tracing / metrics | ✖ | ✔ | **NOT IMPLEMENTED** | `print()` throughout (105 call sites) | **SF-10** | Phase 1 / Phase 10 |
| Model registry (capabilities / routing) | ✖ | ✔ | **NOT IMPLEMENTED** | config-as-code tuples | — | Phase 1 (registry) / Phase 2 (router) |
| Application IR | ✖ | ✔ | **NOT IMPLEMENTED** | HTML string is the only source of truth | — | Phase 3 |
| Full-stack / multi-file generation | ✖ | ✔ | **NOT IMPLEMENTED** | single `index.html` per variant | — | Phase 4 |
| Repo import | ✖ | ✔ | **NOT IMPLEMENTED** | — | — | Phase 4 |
| Sandboxed execution of generated code | ✖ | ✔ | **NOT IMPLEMENTED** | — | **SF-1/SF-7** | Phase 6 |
| Visual QA / repair loop | ✖ (one-shot `screenshot_preview` only) | ✔ | **NOT IMPLEMENTED** | no diff/compare/repair | — | Phase 5 |
| Deployment (GitHub push / managed) | ✖ (only zip export) | ✔ | **NOT IMPLEMENTED** | — | — | Phase 8 |
| CI | ✖ | ✔ | **NOT IMPLEMENTED** | no workflows | — | Phase 1 |

**Tally (63 rows):** PASS **18** · PARTIAL **13** · FAIL **5** · NOT TESTABLE **12** ·
NOT IMPLEMENTED **15**.
(FAIL = text-input generation on default console, preview iframe sandbox, versions persistence,
eval UI data pages, `/eval_input_files`+`/best-of-n-evals` env. NOT TESTABLE rows are dominated
by MISSING CREDENTIALS.)

---

## 19. Known Failures

| ID | Failure | Impact | Root cause | Fix owner |
|---|---|---|---|---|
| **KF-1** | Generation crashes at prompt-assembly on a default Windows console → user sees "Error assembling prompt. Contact support at support@getwhimsyworks.com" | **All generation modes unusable** on Windows without `PYTHONUTF8=1` | `utils.print_prompt_preview()` `print`s box-drawing chars to a cp1252 stdout → `UnicodeEncodeError` propagates through middleware | **Phase 1** — structured logging / remove hot-path `print` |
| **KF-2** | Backend exits code 3 on startup if Playwright Chromium is not installed | Backend won't boot; docs wrongly claim graceful degradation | same `UnicodeEncodeError` class in `PlaywrightBackend.available()`'s error `print` re-raises the caught browser-launch failure | **Phase 1** — make the probe truly non-fatal + logging |
| **KF-3** | Eval/telemetry UI data pages fail in `pnpm dev` (`/evals/run`, `/prompt-reports`, `/agent-runs`, `/sessions`) | Internal tooling unusable in the documented dev setup | Vite proxy only forwards `/api`, `/generate-code`, `/local-assets`; eval pages call `/agent-runs` etc. | **Phase 1** — proxy/routing; **Phase 2** — gate behind admin |
| **KF-4** | Preview iframe not sandboxed; generated JS reads host `localStorage` | Provider keys and app origin exposed to LLM-authored code | `PreviewComponent.tsx` iframe has no `sandbox` attr (select-and-edit depends on same-origin DOM) | **Phase 1** quick win + **Phase 6** |
| **KF-5** | CORS reflects any origin + credentials | Any website can call the API with the user's cookies | `allow_origins=["*"]` + `allow_credentials=True` | **Phase 1** |
| **KF-6** | Eval/telemetry endpoints unauthenticated + leak absolute paths | Info disclosure; `/run_evals` can spend money | no auth layer | **Phase 1** gate + **Phase 2** authz |
| **KF-7** | In-editor code edits are silently discarded | User edits code in the Code tab, nothing happens | `PreviewPane` passes `setCode={() => {}}` to `CodeTab` | **Phase 3** (editing model) |
| **KF-8** | All project work lost on browser refresh | No durable projects/versions | client-only in-memory Zustand store | **Phase 2** |
| **KF-9** | `pnpm lint` fails (19 errors) | No clean lint gate | upstream never enforced lint | **Phase 1** (lint policy) |
| **KF-10** | `/api/screenshot` returns HTTP 500 for a client-supplied bad key | Wrong status class; leaks upstream error text | `except Exception → HTTPException(500)` | Phase 1 (error mapping) |

---

## 20. Missing Functionality (NOT IMPLEMENTED)

Authentication · authorization · users · organizations · workspaces · teams · roles ·
invitations · billing · subscriptions · usage billing · AI credit system · server-side
projects · durable/rollback version history · database + migrations · job queue / worker /
Redis · structured logging / tracing / metrics · model registry (capabilities/routing) ·
per-tenant secrets · Figma import · repo import · full-stack / multi-file generation ·
Application IR · sandboxed generated-code execution · visual QA compare/repair loop ·
deployment (GitHub push / managed / custom domains) · WebSocket reconnect / resumable
generation · in-editor code editing that propagates · preview console/error capture ·
undo/redo · CI.

---

## 21. Recommended Fixes (not applied — for Phase 1 planning)

**Blockers to a usable local baseline:**
1. **KF-1 / KF-2 / SF-10** — replace hot-path `print` with structured logging; make the
   screenshot probe genuinely non-fatal. (Interim: document `PYTHONUTF8=1` + `playwright
   install chromium` — already in `docs/local-baseline` notes.)
2. **KF-3** — add `/agent-runs`, `/prompt-reports`, `/eval-sets`, `/eval-sessions`,
   `/eval_input_files`, `/models`, `/evals` to the Vite proxy (or move the eval UI behind
   `/api`), then gate them.

**Phase 1 security quick wins:**
3. **KF-4 / SF-1 / SF-2** — add `sandbox` (no `allow-same-origin`) to both preview iframes;
   port select-and-edit to `postMessage`.
4. **KF-5 / SF-3** — restrict CORS to a configured origin list; drop wildcard+credentials.
5. **KF-6 / SF-4** — operator gate on `/evals/*`, `/eval-*`, `/prompt-reports*`,
   `/agent-runs*`, `/run_evals*`; stop returning absolute paths.
6. **SF-8** — typed settings (Pydantic); fix `IS_PROD` / `IS_DEBUG_ENABLED` parsing.
7. **SF-9** — remove `support@getwhimsyworks.com` and upstream support copy from user-facing
   strings.

**Phase 1 platform foundation (per ROADMAP / spec `specs/001-phase-1-core-platform`):**
8. CI (pytest + pyright + jest + build + lint policy); pin Python 3.12.
9. Postgres + Alembic; Redis + worker + job queue (generation behind a flag); WS → event
   channel.
10. AI model registry scaffold (mirror current behavior).

**Deferred (must stay unsafe/disabled until their phase):**
- Executing generated full-stack code, dev servers, package installs, network egress,
  moving backend Chromium out of `--no-sandbox` — **Phase 6**.
- Visual repair loops — **Phase 5**. Auth/tenancy/billing — **Phase 2 / 9**.

---

## 22. Phase Mapping (summary)

| Phase | Picks up from this audit |
|---|---|
| **Phase 1 — Core Platform** | KF-1, KF-2, KF-3, KF-5, KF-9, SF-2, SF-3, SF-8, SF-9, SF-10; CORS; operator gate (SF-4/KF-6); typed config; structured logging; CI; Postgres/Alembic; Redis/worker/queue; WS as event channel; model registry; **quick-win** preview `sandbox` (SF-1/KF-4 partial) |
| **Phase 2 — Project & Workspace** | SF-5 (auth), SF-6 (browser keys), KF-8 (persistence), design-systems & assets → per-tenant, full authz for SF-4 endpoints |
| **Phase 3 — Understanding/Analysis/Planning + IR spike** | URL input (owned crawler), Figma import, Application IR, `edit_file`→IR; KF-7 (editing model) |
| **Phase 4 — Full-Stack Generation** | multi-file generation, repo import |
| **Phase 5 — Visual QA & Repair** | preview console/error capture, compare/diagnose/repair loop |
| **Phase 6 — Sandboxed Execution** | SF-1 (full), SF-7 (backend Chromium), untrusted generated-code execution |
| **Phase 7 — Collaboration & Versioning** | durable versions, checkpoints, rollback, undo/redo |
| **Phase 8 — Deployment** | GitHub push, managed deploy, custom domains |
| **Phase 9 — Billing / Usage / Enterprise** | credits, quotas, SSO/SCIM |
| **Phase 10 — Production Hardening** | OTel tracing, metrics, bundle code-splitting, load testing |

---

## Appendix A — Commands & Evidence

**Services (left running for the baseline):**
- backend: `PYTHONUTF8=1 python -m poetry run uvicorn main:app --port 7001 --host 127.0.0.1`
- frontend: `pnpm dev --port 5180 --strictPort`

**Automated suite:** `cd backend && poetry run pytest` · `poetry run pyright` ·
`cd frontend && pnpm test` · `pnpm lint` · `pnpm build`

**Browser automation:** `playwright-cli` — home, Settings dialog, Text tab (empty + real
prompt), Import tab (end-to-end), select-and-edit, 8 `/evals/*` routes, refresh-persistence.

**Direct API probes:** `curl` against every endpoint in §10; `OPTIONS` CORS preflight;
`/local-assets` traversal; a Python `websockets` script (`ws_probe.py`) for 5 WS scenarios.

**Evidence artifacts (session scratchpad, not committed):** `baseline-home.png`,
`baseline-settings.png`, `audit-import-preview.png`, `audit-selectmode.png`, `ws_probe.py`,
backend logs.

## Appendix B — Files Changed

**Committed to the repo by this audit:** `docs/BASELINE_FUNCTIONAL_AUDIT.md` (this file) —
**only**. No application source, config, test, or infrastructure file was modified.
(`git status` also shows `.specify/memory/constitution.md` and `specs/` from prior tasks, not
this one.)

**Out-of-repo / environment state touched (no repo effect):**
- Playwright Chromium browsers installed under `%LOCALAPPDATA%\ms-playwright\` (a documented
  setup step; required for backend startup — KF-2).
- `~/.screenshot-to-code/design-systems.json` created and left as `[]` by the design-system
  CRUD probe (§10); `[]` is equivalent to absent for the read path.
- Backend restarted with `PYTHONUTF8=1` for root-cause confirmation of KF-1.
- `.playwright-cli/` automation artifacts (git-ignored).
- Transient stray file `text-tab.yaml` created by a snapshot command and **removed**.
