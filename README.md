# H.E.X Mind

**Hivemind Execution X** is an agent-native desktop IDE with live multi-agent observability.
The plan lives in [HEX_Mind_Refined_Plan.md](HEX_Mind_Refined_Plan.md).

**Current milestone: M3 (worker swarm and safe execution).**

| Milestone | Delivered |
|---|---|
| M0 | Electron shell, secure preload bridge, React IDE frame, token-protected FastAPI health check |
| M1 | PostgreSQL schema + Alembic migrations, workspace path guard, file explorer, Monaco editor with tabs and stale-file protection, per-run event log, Ollama provider with logged calls |
| M2 | Persistent project conversations with Ask / Edit / Auto modes; ContextManager (budgeted, redacted, reads files fresh from disk, rolling summary); LLM Router with schema-validated output, one repair retry, deterministic policy and fallback, all decisions logged; LangGraph conversation and run graphs (worker nodes are labeled **stubs** until M3); typed event schema v1 with generated TypeScript types; run event viewer; routing-label tooling |
| M3 | Blackboard with atomic claims (`FOR UPDATE SKIP LOCKED`), leases, dependencies and file-overlap scheduling; CrewAI Planner/Coder/Reviewer whose every model call goes through our ProviderRouter; per-run Git worktree from a snapshot of the user's working state; MCP workspace server as the agents' only tool surface; Docker sandbox for checks; ChromaDB coding standards and self-logs; diff review (read-only); **event schema v1 frozen** |

## Layout

```
apps/
  desktop/   Electron + React + TypeScript (electron-vite)
    src/main/       main process: window, IPC (folder picker), navigation guards
    src/preload/    contextBridge API (api.ts is the shared contract)
    src/renderer/   React renderer: explorer, Monaco editor, status
  backend/   FastAPI (uv)
    app/api/        REST routes (health, projects/files, runs/events, providers)
    app/db/         SQLAlchemy models + async session
    app/workspace/  path guard and file service (the only filesystem access)
    app/events/     per-run, gap-free event log
    app/providers/  provider interface, Ollama adapter, ProviderRouter (logs every call)
    alembic/        migrations
docker-compose.yml  PostgreSQL (127.0.0.1:5433) + test database
```

## Prerequisites

- Node.js 20+ and npm 10+
- Python 3.11+ and [uv](https://docs.astral.sh/uv/)
- Docker Desktop (PostgreSQL, and the sandbox that runs agent checks)
- Git
- [Ollama](https://ollama.com) with the coding and embedding models: `ollama pull qwen2.5-coder:7b` and `ollama pull nomic-embed-text`

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
npm run dev:backend   # FastAPI on http://127.0.0.1:8765
npm run dev           # Electron app (renderer dev server on :5173)
```

The welcome screen shows readiness for the backend, the database and Ollama. Use **Open folder** to choose a workspace, browse it in the explorer, and edit files in Monaco (Ctrl+S saves).

If a file changes on disk after you opened it, saving is refused. The editor then offers **Reload from disk** or an explicit **Overwrite**.

The **Agent Chat** panel works against the open workspace:
- **Ask** answers using the current files and never edits anything.
- **Edit** starts a run.
- **Auto** lets the Router decide, and it asks for clarification when it's unsure.

Each reply shows the route, the confidence, any fallback, and the files used as context.

**Agent runs (Edit mode)** need the workspace to be a Git repository. If it isn't, use the **No Git: initialize** button in the top bar. A run follows these steps:
1. It snapshots your current files, including uncommitted ones, and creates an isolated worktree under `%LOCALAPPDATA%\hexmind\worktrees`.
2. The Planner creates Blackboard tasks.
3. Coders claim tasks and edit files only through the MCP workspace tools.
4. Every change is checked by running the project's `test` check in a Docker container with no network, and the Reviewer approves the change or requests another round.
5. The run ends in `awaiting_approval`.

Follow the run in the **Agent Events** and **Tasks** tabs, then open **Review changes** to see the diff. Your files are not modified. Applying, rejecting and reverting arrive in M6.

**Checks** come from `.hexmind/profile.yaml` in your workspace, for example `image: node:22-alpine` with `checks: {test: node --test}`. Without that file, H.E.X Mind detects a default. Agents can only run checks by name, can't edit the profile, and only allowlisted images are used. Checks run offline, so tests must not need `npm install`; dependency installation is a later, approval-gated step.

To check the model provider end to end (the call is logged in `llm_calls`):

```sh
curl -X POST http://127.0.0.1:8765/api/providers/ollama/test -H "Authorization: Bearer <token>"
```

> If Electron exits immediately with `Cannot read properties of undefined (reading 'whenReady')`, your shell has `ELECTRON_RUN_AS_NODE=1` set (some editor-integrated terminals do this). Unset it before running `npm run dev`.

## Checks

```sh
npm test               # Vitest (renderer) + pytest (backend; needs `npm run db:up`)
npm run typecheck      # tsc for main/preload and renderer
npm run build          # electron-vite production build
npm run lint:backend   # ruff
```

The event contract lives in `apps/backend/app/events/schema.py`. After changing it, run `npm run gen:events` to regenerate `apps/desktop/src/renderer/src/generated/`. A backend test fails if the committed schema is out of date.

Routing labels for the M7 evaluation are described in [docs/routing-labels.md](docs/routing-labels.md).

Backend tests use the `hexmind_test` database and rebuild it from the migrations on every run. The two symlink-escape tests are skipped on Windows unless Developer Mode is enabled, because creating symlinks requires it.

## Security baseline

- The renderer runs with `contextIsolation`, `sandbox` and no `nodeIntegration`. Its only API is `window.hex.getBackend()`, `appInfo()` and `pickWorkspace()`.
- IPC handlers reject calls from frames other than the app's own page. New windows are denied, and only `https:` links open externally.
- The backend binds to loopback only, and every route requires `Authorization: Bearer <HEXMIND_API_TOKEN>`. CORS allows only the renderer origin.
- All file access goes through the backend path guard. It rejects `..`, absolute, drive and UNC paths, alternate data streams, Windows device names, trailing dots and spaces, and symlink escapes, and it refuses writes under `.git/`.
- Saves are compare-and-swap on a content hash, so a save never silently overwrites a newer version on disk.
- Secrets live in `.env`, which is git-ignored. Only `.env.example` is committed.

## Known issues

- `npm audit` reports DOMPurify advisories against `monaco-editor@0.57.0`. Monaco bundles its own copy of DOMPurify 3.4.15 (used to sanitize hover markdown), so the code that runs is unaffected by npm overrides. The affected modes (`IN_PLACE`, `SAFE_FOR_TEMPLATES`, XHTML parsing) are not the ones Monaco uses, and the editor only renders local workspace content. Upgrade Monaco when a patched release is available.
