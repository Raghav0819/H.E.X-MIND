# H.E.X Mind

**Hivemind Execution X** is an agent-native desktop IDE with live multi-agent observability. You open a
workspace, ask for a change, and a team of agents plans it, writes it in an isolated Git worktree, checks it in a
network-less Docker sandbox and hands you a diff to review, while a live observability view shows what every agent,
callback and agent-to-agent message is doing.

> **Status:** P2 complete. Orchestration runs on **Google ADK**, the Planner and Coder are **CrewAI** crews served
> over the **A2A** protocol, and the UI has a dedicated observability view with an A2A explorer.
> The plan is in [HEX_Mind_Refined_Plan.md](HEX_Mind_Refined_Plan.md).

## How it works

```
 Electron + React desktop app --REST/SSE (bearer token)--> FastAPI backend (127.0.0.1:8765)
   explorer, Monaco, chat, run viewer                         |
   observability: agents, callbacks, blackboard,              |  Google ADK orchestrator
   schema checks, topology, A2A explorer                      |  Planner -> Coder -> Reviewer (review/retry loop)
                                                              |       |          |
                                          A2A (JSON-RPC, bearer auth, W3C traceparent in metadata)
                                                              v          v
                                             CrewAI crew service (127.0.0.1:8766)
                                             one Agent Card per crew (Planner, Coder)
                                                              |
       PostgreSQL (runs, events, blackboard, llm_calls) <-----+--> MCP workspace server (agents' only tool surface)
       ChromaDB (coding standards, past lessons)        <-----+--> Docker sandbox (checks run offline)
                                                              +--> Groq -> Gemini -> Ollama (policy-driven fallback)
```

- **Orchestration (Google ADK):** a run is an ADK workflow. The orchestrator calls the CrewAI crews through
  `RemoteA2aAgent`, and the Reviewer approves the change or sends it back for another round.
- **Crews (CrewAI over A2A):** the crew service is a separate process. Run, task and worktree ids and a W3C
  `traceparent` travel in A2A request metadata, so one trace spans both sides. Failed A2A tasks are read from the task state.
- **Shared Blackboard:** tasks are claimed atomically (`FOR UPDATE SKIP LOCKED`) with leases, dependencies and
  file-overlap scheduling.
- **Safe workspace access:** agents can only touch files through MCP workspace tools behind a path guard. Work happens
  in a per-run Git worktree created from a snapshot of your current files, so your files are never modified until you apply a change.
- **Sandboxed checks:** the project's `test` check runs in a Docker container with no network and an allowlisted image.
- **Providers:** every call goes through one router with native tool calling, health-gated eligibility, bounded retries,
  cooldown on quota errors and a logged `provider_fallback` event.
- **Observability:** a TelemetryHub turns eight ADK callbacks and the CrewAI hooks into one typed event schema (v3).
  Failed agents are closed with `ok=false` so the UI marks them.

## What is built

| Phase | Delivered |
|---|---|
| M0 | Electron shell, secure preload bridge, React IDE frame, token-protected FastAPI health check |
| M1 | PostgreSQL schema and Alembic migrations, workspace path guard, file explorer, Monaco editor with stale-file protection, per-run event log, Ollama provider |
| M2 | Persistent project conversations with Ask / Edit / Auto modes, budgeted and redacted ContextManager, LLM router with schema-validated output and logged decisions, typed event schema with generated TypeScript types |
| M3 | Blackboard with atomic claims, CrewAI Planner/Coder/Reviewer, per-run Git worktree, MCP workspace server, Docker sandbox for checks, ChromaDB standards and self-logs, read-only diff review |
| M4 | Native tool calling on every provider, Groq and Gemini adapters beside Ollama, configurable provider order, health-gated fallback with cooldowns, cost estimates, provider settings panel, validated 14-task benchmark set |
| P1 | Orchestration migrated from LangGraph to **Google ADK**; TelemetryHub, event schema v2, and the Observability UI (Blackboard, Agents, Callbacks, Schema checks, Topology) |
| P2 | **CrewAI crews served over A2A** (Agent Cards, task lifecycle, bearer auth, run-worktree guard); event schema v3 with A2A trace ids; **A2A explorer** (live agent cards and two-lane exchange timelines with a shared-trace check); failed-agent telemetry |

Applying, rejecting and reverting changes arrive in a later phase. Cloud deployment is the final phase and is deferred; everything runs locally until then.

## Layout

```
apps/
  desktop/   Electron + React + TypeScript (electron-vite)
    src/main/       main process: window, IPC (folder picker), navigation guards
    src/preload/    contextBridge API (api.ts is the shared contract)
    src/renderer/   React renderer: features/{explorer,editor,chat,runs,observability,settings,workspace}
  backend/   FastAPI (uv)
    app/api/            REST routes (health, projects/files, runs/events, providers, a2a)
    app/orchestration/  ADK orchestrator, run lifecycle, conversation flow
    app/a2a/            CrewAI crew service (python -m app.a2a) and A2A client/protocol
    app/agents/         roles, tools, MCP bridge, ADK LLM adapter
    app/blackboard/     task board with atomic claims and leases
    app/telemetry/      TelemetryHub (ADK callbacks and CrewAI hooks), tracing
    app/providers/      provider interface, Ollama/Groq/Gemini adapters, ProviderRouter
    app/router/         Ask/Edit/Auto routing with schema-validated output
    app/mcp_server/     the agents' only tool surface
    app/sandbox/        Docker check runner and project profile
    app/memory/         ChromaDB coding standards and lessons
    app/workspace/      path guard and file service (the only filesystem access)
    app/events/         per-run, gap-free event log and schema
    app/evaluation/     benchmark task set with hidden acceptance tests
    alembic/            migrations
docs/                 coding standards loaded into memory, routing-label guide
spikes/adk_a2a/       the ADK / A2A / MCP / OpenTelemetry spikes that de-risked P1 and P2
reports/              research report: how comparable projects differ and what to adopt
research_notes/       the notes behind that report
docker-compose.yml    PostgreSQL (127.0.0.1:5433) + test database
```

## Prerequisites

- Node.js 20+ and npm 10+
- Python 3.11+ and [uv](https://docs.astral.sh/uv/)
- Docker Desktop (PostgreSQL, and the sandbox that runs agent checks)
- Git
- [Ollama](https://ollama.com) with the coding and embedding models: `ollama pull qwen2.5-coder:7b` and `ollama pull nomic-embed-text`
- Optional but recommended: free [Groq](https://console.groq.com) and [Gemini](https://aistudio.google.com) API keys. Local models alone give noticeably weaker code.

## Setup

```sh
npm install                          # also downloads the Electron binary (postinstall)
uv --directory apps/backend sync

cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(32))"   # paste into HEXMIND_API_TOKEN in .env

npm run db:up                        # start PostgreSQL
npm run db:migrate                   # apply migrations
docker pull node:22-alpine           # sandbox image for agent checks (pulled on first use otherwise)
```

## Run (development)

Run these in two terminals:

```sh
npm run dev:backend   # FastAPI on http://127.0.0.1:8765, and it starts the CrewAI crew service on :8766
npm run dev           # Electron app (renderer dev server on :5173)
```

In development the backend starts the crew service itself (`HEXMIND_CREW_SERVICE_AUTOSTART`). To run it on its own, use
`uv --directory apps/backend run python -m app.a2a`.

The welcome screen shows readiness for the backend, the database and Ollama. Use **Open folder** to choose a workspace, browse it in the explorer, and edit files in Monaco (Ctrl+S saves).

If a file changes on disk after you opened it, saving is refused. The editor then offers **Reload from disk** or an explicit **Overwrite**.

The **Agent Chat** panel works against the open workspace:
- **Ask** answers using the current files and never edits anything.
- **Edit** starts a run.
- **Auto** lets the Router decide, and it asks for clarification when it's unsure.

Each reply shows the route, the confidence, any fallback, and the files used as context.

**Agent runs (Edit mode)** need the workspace to be a Git repository. If it isn't, use the **No Git: initialize** button in the top bar. A run follows these steps:
1. It snapshots your current files, including uncommitted ones, and creates an isolated worktree (under `%LOCALAPPDATA%\hexmind\worktrees` by default, or under `HEXMIND_DATA_DIR`).
2. The Planner crew creates Blackboard tasks over A2A.
3. The Coder crew claims tasks and edits files only through the MCP workspace tools.
4. Every change is checked by running the project's `test` check in a Docker container with no network, and the Reviewer approves the change or requests another round.
5. The run ends in `awaiting_approval`.

Follow the run in the **Agent Events** and **Tasks** tabs and in the **Observability** view, then open **Review changes** to see the diff. Your files are not modified.

**Observability view:** Blackboard (live task board), Agents (per-agent state, with failures marked), Callbacks (the ADK
callback stream), Schema checks (live validation of the event contract), Topology (the orchestration pattern) and the
**A2A explorer** (agent cards and two-lane request/response timelines that check both sides share one trace id).

**Checks** come from `.hexmind/profile.yaml` in your workspace, for example `image: node:22-alpine` with `checks: {test: node --test}`. Without that file, H.E.X Mind detects a default. Agents can only run checks by name, can't edit the profile, and only allowlisted images are used. Checks run offline, so tests must not need `npm install`; dependency installation is a later, approval-gated step.

To check the model provider end to end (the call is logged in `llm_calls`):

```sh
curl -X POST http://127.0.0.1:8765/api/providers/ollama/test -H "Authorization: Bearer <token>"
```

> If Electron exits immediately with `Cannot read properties of undefined (reading 'whenReady')`, your shell has `ELECTRON_RUN_AS_NODE=1` set (some editor-integrated terminals do this). Unset it before running `npm run dev` (for example `env -u ELECTRON_RUN_AS_NODE npm run dev`).

## Configuration

Everything is set through `HEXMIND_*` variables in `.env` (see [.env.example](.env.example)). The ones you are most likely to change:

| Variable | Default | Purpose |
|---|---|---|
| `HEXMIND_API_TOKEN` | required | shared secret between the app, the backend and the crew service |
| `HEXMIND_DATA_DIR` | `%LOCALAPPDATA%\hexmind` | run worktrees, memory store, crew storage. Point it at a roomy drive if your system drive is small |
| `HEXMIND_PROVIDER_ORDER` | `["groq","gemini","ollama"]` | fallback order |
| `HEXMIND_CREW_SERVICE_AUTOSTART` | `true` | start the CrewAI crew service with the backend in development |
| `HEXMIND_OTLP_ENDPOINT` | unset | optional OpenTelemetry export target |
| `HEXMIND_REVIEW_MAX_ROUNDS` | `2` | review/retry rounds before a run stops |

## Model providers

H.E.X Mind can use three providers. Each model call tries them in `HEXMIND_PROVIDER_ORDER`, which defaults to Groq, then Gemini, then Ollama.

| Provider | Setup |
|---|---|
| Ollama (local) | `ollama pull qwen2.5-coder:7b`. No key needed. Used whenever the hosted providers aren't configured or have failed. |
| Groq | Put `HEXMIND_GROQ_API_KEY=...` in `.env`. The model is `HEXMIND_GROQ_MODEL`. |
| Gemini | Put `HEXMIND_GEMINI_API_KEY=...` in `.env`. The model is `HEXMIND_GEMINI_MODEL`. |

A provider without a key is skipped. A provider that hits its quota, or whose key is rejected, falls back to the next provider straight away and is skipped for a cooldown period; the run records this as a `provider_fallback` event. **Settings** (the gear in the activity bar) shows each provider's status, cooldown and remaining rate limit, and has a **Test** button. Keys stay in the backend and are never shown.

Cost estimates come from `apps/backend/app/providers/pricing.yaml`. Those prices are **unverified**, so check them against the providers' pricing pages before reporting costs.

## Benchmarks

`apps/backend/app/evaluation/benchmarks/` holds the fixed task set for the M7 evaluation: 14 tasks on a small to-do code base, each with a hidden acceptance test and a reference solution.

```sh
cd apps/backend
uv run python -m app.evaluation.benchmarks validate   # each hidden test fails on the seed and passes on the reference
uv run python -m app.evaluation.benchmarks sync       # load the tasks into eval_tasks
```

## Checks

```sh
npm test               # Vitest (renderer) + pytest (backend; needs `npm run db:up`)
npm run typecheck      # tsc for main/preload and renderer
npm run build          # electron-vite production build
npm run lint:backend   # ruff
```

The full backend suite takes about 10 minutes (256 passed, 2 skipped at P2). Do not run two pytest sessions at once, because they share the test database. Docker-based tests need free disk space on the system drive.

The event contract lives in `apps/backend/app/events/schema.py`. After changing it, run `npm run gen:events` to regenerate `apps/desktop/src/renderer/src/generated/`. A backend test fails if the committed schema is out of date.

Routing labels for the evaluation are described in [docs/routing-labels.md](docs/routing-labels.md).

Backend tests use the `hexmind_test` database and rebuild it from the migrations on every run. The two symlink-escape tests are skipped on Windows unless Developer Mode is enabled, because creating symlinks requires it.

## Research

[reports/Multi agent coding project comparison.md](reports/Multi%20agent%20coding%20project%20comparison.md) compares H.E.X Mind with OpenHands,
SWE-agent, Aider, Cline, MetaGPT, ChatDev and the observability tools, and ranks what to adopt next. The notes behind it are in
`research_notes/`. Its findings were produced without reading this repository's code, so treat its "missing feature" claims as hypotheses to verify.

## Security baseline

- The renderer runs with `contextIsolation`, `sandbox` and no `nodeIntegration`. Its only API is `window.hex.getBackend()`, `appInfo()` and `pickWorkspace()`.
- IPC handlers reject calls from frames other than the app's own page. New windows are denied, and only `https:` links open externally.
- The backend binds to loopback only, and every route requires `Authorization: Bearer <HEXMIND_API_TOKEN>`. CORS allows only the renderer origin.
- All file access goes through the backend path guard. It rejects `..`, absolute, drive and UNC paths, alternate data streams, Windows device names, trailing dots and spaces, and symlink escapes, and it refuses writes under `.git/`.
- Saves are compare-and-swap on a content hash, so a save never silently overwrites a newer version on disk.
- Secrets live in `.env`, which is git-ignored. Only `.env.example` is committed.

## Known issues

- `npm audit` reports DOMPurify advisories against `monaco-editor@0.57.0`. Monaco bundles its own copy of DOMPurify 3.4.15 (used to sanitize hover markdown), so the code that runs is unaffected by npm overrides. The affected modes (`IN_PLACE`, `SAFE_FOR_TEMPLATES`, XHTML parsing) are not the ones Monaco uses, and the editor only renders local workspace content. Upgrade Monaco when a patched release is available.
