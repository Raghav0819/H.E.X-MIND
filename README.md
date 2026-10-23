# H.E.X Mind

**Hivemind Execution X** is an agent-native desktop IDE with live multi-agent observability.
The plan lives in [HEX_Mind_Refined_Plan.md](HEX_Mind_Refined_Plan.md).

**Current milestone: M0 (skeleton).** The Electron shell, secure preload bridge, React IDE frame, and a FastAPI backend with a token-protected health check.

## Layout

```
apps/
  desktop/   Electron + React + TypeScript (electron-vite)
    src/main/       main process: window, IPC, navigation guards
    src/preload/    contextBridge API (api.ts is the shared contract)
    src/renderer/   React renderer
  backend/   FastAPI (uv)
    app/            create_app factory, settings, auth, API routes
    tests/
```

## Prerequisites

- Node.js 20+ and npm 10+
- Python 3.11+ and [uv](https://docs.astral.sh/uv/)

## Setup

```sh
npm install
node node_modules/electron/install.js   # only if Electron reports "Electron uninstall" (its download step was skipped)
uv --directory apps/backend sync

cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(32))"   # paste into HEXMIND_API_TOKEN in .env
```

## Run (development)

Run these in two terminals:

```sh
npm run dev:backend   # FastAPI on http://127.0.0.1:8765
npm run dev           # Electron app (renderer dev server on :5173)
```

The status pill in the top bar shows `Backend connected`. If you stop the backend it changes to `Backend unreachable`, and it reconnects on its own when the backend comes back.

> If Electron exits immediately with `Cannot read properties of undefined (reading 'whenReady')`, your shell has `ELECTRON_RUN_AS_NODE=1` set (some editor-integrated terminals do this). Unset it before running `npm run dev`.

## Checks

```sh
npm test               # Vitest (renderer) + pytest (backend)
npm run typecheck      # tsc for main/preload and renderer
npm run build          # electron-vite production build
npm run lint:backend   # ruff
```

## Security baseline

- The renderer runs with `contextIsolation`, `sandbox` and no `nodeIntegration`. The only API it gets is `window.hex.getBackend()` / `appInfo()`.
- IPC handlers reject calls from frames other than the app's own page. New windows are denied, and only `https:` links open externally.
- The backend binds to loopback only (it refuses to start otherwise) and every route requires `Authorization: Bearer <HEXMIND_API_TOKEN>`. CORS allows only the renderer origin.
- Secrets live in `.env`, which is git-ignored. Only `.env.example` is committed.
