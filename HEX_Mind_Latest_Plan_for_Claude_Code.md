# H.E.X Mind — Project Context and Implementation Plan

> **Purpose of this file:** Give Claude Code the current product vision, architecture, implementation priorities, constraints, and acceptance criteria for H.E.X Mind. Treat this file as the project’s working source of truth unless the team explicitly changes a decision.
>
> **Project name:** H.E.X Mind — Hivemind Execution X  
> **Product:** An agent-native IDE with live multi-agent observability  
> **Demo target:** A to-do application. The IDE and agent workflow are the product; the to-do app is only the demonstration target.

---

## 1. Product Vision

Build an IDE where a developer can describe a software task in natural language and a coordinated group of AI agents can plan, implement, review, and test the changes. The developer should be able to observe the actual agent workflow through a live game-like map and a metrics dashboard.

The IDE must also support **persistent, context-aware coding chat**, similar in workflow to Codex or Claude Code. After an initial task completes, the user can ask follow-up questions or request additional changes without repeating the entire project context.

Example conversation:

1. User: “Build a to-do app with task creation, editing, deletion, filtering, and persistent storage.”
2. H.E.X Mind builds and reviews the app.
3. User: “Change the login page to a dark theme.”
4. H.E.X Mind inspects the existing code, changes the relevant files, tests the changes, and shows a diff.
5. User: “Now remove Google login and add GitHub login.”
6. H.E.X Mind uses the same project and conversation context to make an incremental change.

### Core principles

- The IDE is the product; the demo app is not the product.
- The Router Agent is the first logical agent to receive a new user request.
- The Router Agent classifies complexity using an LLM, with no Jev dependency.
- LangGraph manages workflow state and conditional dispatch.
- CrewAI provides the Planner, Coder, and Reviewer worker roles.
- The workspace files are the source of truth for code; conversation history supplements, but never replaces, inspection of current files.
- The game map must reflect real backend events, not scripted or fake agent activity.
- Keep the first implementation focused and deliver an end-to-end vertical slice before adding polish.

---

## 2. Architecture Overview

H.E.X Mind is an **Electron desktop application**. React + TypeScript is the renderer inside Electron; it is not a browser-only product.

```text
Developer
   |
   v
Electron Desktop Shell
  - Main process and window lifecycle
  - Secure preload bridge / allowlisted IPC
  - Local workspace selection and scoped OS integration
   |
   v
React + TypeScript Renderer (Vite)
  - Persistent chat
  - Monaco code editor
  - File explorer
  - Diff viewer
  - Task / run history
  - Metrics panel
  - Phaser game map
   |
   v
Local FastAPI Backend
  - REST API
  - WebSocket event stream
  - Conversation and project context
   |
   v
Context Manager
  - Recent messages and conversation summary
  - Project metadata and file tree
  - Relevant previous runs and diffs
  - Current source files and relevant code
   |
   v
LLM-powered Router Agent
  - Classifies complexity: low / medium / high
  - Decides: answer / code edit / new workflow / clarification
  - Selects execution strategy
   |
   v
LangGraph Dispatcher
  - Conditional workflow edges
  - Provider selection policy
  - Retry and fallback
   |
   +------------------------------+
   |              |               |
   v              v               v
 Planner         Coder          Reviewer
 (CrewAI)       (CrewAI)        (CrewAI)
   |              |               |
   +--------------+---------------+
                  |
                  v
       Blackboard / execution layer
       - PostgreSQL authoritative task state
       - MCP-controlled tools
       - ChromaDB RAG and searchable self-logs
       - LLM provider adapters
                  |
                  v
       Actual workspace edits + tests
                  |
                  v
       Event publisher -> FastAPI WebSockets
                  |
                  v
       React event store -> Phaser.js game scene
                  |
                  v
       Live agent map, task status, metrics, diffs
```

The diagram is conceptual. Implement one FastAPI backend initially; do not split into microservices unless there is a demonstrated need.

---

## 3. Technology Stack

### Desktop shell
- Electron main process
- Secure preload script using `contextBridge` and a narrow allowlisted API
- `contextIsolation: true` and `nodeIntegration: false`
- The main process owns window lifecycle and, in the packaged application, the lifecycle of any backend process it starts
- Keep shell access, filesystem operations, and privileged APIs out of the renderer

### Frontend
- React
- TypeScript
- Vite
- CSS design tokens; Tailwind CSS is optional if it improves consistency and iteration speed
- Monaco Editor for code editing and diff view
- Phaser.js + Canvas for the 2D game map
- WebSocket client for live events
- Vitest and Playwright for frontend/unit and end-to-end tests

### Backend
- Python
- FastAPI
- Pydantic
- SQLAlchemy
- PostgreSQL
- WebSockets (or SSE for chat streaming if preferred; use a consistent event design)
- pytest and HTTPX for backend tests

### Agent orchestration
- LangGraph for Router/Dispatcher state, conditional edges, retry and fallback
- CrewAI for Planner, Coder and Reviewer worker roles
- A conventional LLM provider for Router classification; **do not use Jev**
- Provider adapters for Ollama, Groq and Gemini

### Memory and tools
- ChromaDB for RAG over coding standards and searchable agent self-logs
- MCP for controlled file operations, code inspection and test tools
- PostgreSQL remains the authoritative source for task states, runs, conversations, events and evaluation records

### ML and evaluation
- scikit-learn as a baseline complexity classifier for comparison and to preserve the original course ML-tool requirement
- PostgreSQL evaluation harness
- Repeatable benchmark tasks and a documented quality rubric

### Operations
- Docker Compose for local development and repeatable services
- Git and GitHub for version control
- `.env` for local secrets; commit only `.env.example`, never real credentials

---

## 4. Router Agent and Task Classification

The Router Agent is the first logical agent to receive each user message. LangGraph invokes it and manages subsequent workflow transitions.

The Router uses an LLM to produce structured output such as:

```json
{
  "request_type": "code_edit",
  "complexity": "high",
  "reason": "Multiple dependent components and security requirements",
  "execution_strategy": "decompose",
  "requires_planning": true,
  "requires_review": true
}
```

Supported request types should include:
- `question`: answer using project context without modifying files
- `code_edit`: modify existing project files
- `new_workflow`: start a new feature or build task
- `clarification`: ask a focused question when essential information is missing

Complexity levels:
- `low`: isolated, bounded change
- `medium`: related changes across several components/files
- `high`: architectural changes, multiple dependencies, security-sensitive work, or broad refactoring

Example routing policy:
- Low: direct Coder execution where safe.
- Medium: Planner → Coder → Reviewer.
- High: Planner decomposes the task; independent tasks may run in parallel where dependencies allow; Coder implements; Reviewer validates.

These are initial heuristics, not assumed truths. Tune them with evaluation data.

### Routing safeguards
- Validate Router output with Pydantic schemas.
- If output is invalid or confidence is insufficient, ask for clarification or use a conservative deterministic fallback.
- The Router proposes a route; LangGraph applies policy and guardrails.
- Do not let model-generated text directly authorize dangerous operations.
- Track the classification, rationale, selected provider, fallback and final outcome.

### ML baseline
The original abstract specifies a lightweight ML classifier for the course requirement. Preserve this without making it the primary production router:
- Train a scikit-learn baseline on a labeled set of coding tasks.
- Compare its classification and routing outcomes with the LLM-based Router.
- Clearly report the source of labels and limitations; do not claim reliability without held-out evaluation.

---

## 5. Worker Agents

### Planner
Responsibilities:
- Convert user requirements into structured tasks with unique IDs.
- Identify dependencies and avoid duplicate or overlapping tasks.
- Use the Blackboard as shared state.
- Follow the ReAct-style planning approach specified in the original abstract.
- Do not write application code directly unless explicitly delegated a bounded task.

### Coder
Responsibilities:
- Atomically claim an eligible task.
- Inspect current files and relevant project context before editing.
- Retrieve relevant coding standards from ChromaDB (RAG).
- Use approved MCP tools for file operations and tests.
- Make targeted patches instead of regenerating the entire project unnecessarily.
- Return structured output: changed files, diff references, tests run, results, errors, and task status.
- Use bounded retries and avoid overwriting unrelated user changes.

### Reviewer
Responsibilities:
- Validate implementation against a checklist and original task acceptance criteria.
- Check correctness, regressions, code conventions and test coverage.
- Return one of: `approved`, `changes_requested`, or `blocked`.
- Explain findings with file/line references where possible.
- Track false positives and defects caught as evaluation metrics.
- Limit Coder–Reviewer loops and escalate when retries are exhausted.

---

## 6. Context-Aware Coding Chat

The chat is a persistent interface over the same project workspace and agent workflow.

### User experience
The user can:
- Ask questions about the current project.
- Request changes after an earlier run has completed.
- Refer to earlier messages or changes without restating all context.
- Ask for debugging or explanation.
- Inspect the diff and test results for each change.
- Continue a conversation across multiple runs.

### Context sources
Keep these logically separate:

1. **Conversation context:** recent messages, relevant earlier turns, decisions, rolling summary.
2. **Project context:** project instructions, framework/language, file tree and metadata.
3. **Execution context:** prior run IDs, task results, errors, logs and diffs.
4. **Code context:** current source files, relevant symbols and dependencies.

The current workspace is the source of truth. Always inspect the current relevant files before modifying them; do not assume past messages perfectly describe the current code.

### Suggested database tables
- `projects`: `id`, `name`, `workspace_path`, timestamps
- `conversations`: `id`, `project_id`, `title`, `summary`, timestamps
- `messages`: `id`, `conversation_id`, `role`, `content`, `metadata`, timestamp
- `runs`: include `project_id`, `conversation_id`, `parent_run_id`, `triggering_message_id`, status and timestamps
- `tasks`: include `run_id`, title, description, status, complexity, dependencies
- `agent_executions`: agent role, provider/model, task/run links, status, timestamps
- `file_changes`: run ID, file path, change type, diff or diff reference, status
- `agent_events`: run ID, sequence number, event type, payload and timestamp
- `llm_calls`: provider/model, input/output tokens when available, latency, estimated cost, errors
- `evaluations`: benchmark task, provider, completion, quality score, latency and cost

Use migrations. Avoid storing secrets in messages, logs or model context.

### Chat interaction modes
- **Ask:** answer questions and explain code without modifying files.
- **Edit:** plan and implement code changes.
- The Router can infer intent, but the user should be able to select a mode explicitly.

Every follow-up code change creates a new execution run linked to the existing conversation and project. It should not restart the project from scratch.

### Editing and recovery
- Show changed files and a Monaco diff.
- Run relevant tests and show actual outcomes.
- Use Git checkpoints or a dedicated Git worktree to support recovery.
- Never silently overwrite unrelated user changes.
- Ask for approval for destructive or high-risk operations when appropriate.

---

## 7. Blackboard, Database and Concurrency

PostgreSQL is the authoritative store for task state. ChromaDB is for semantic retrieval and must not be used as the source of truth for task lifecycle or concurrency.

Recommended task lifecycle:

```text
pending -> claimed -> running -> review -> completed
                       |            |
                       v            v
                    failed     changes_requested
                       |            |
                       +-> retry <--+
```

Also support `blocked` and retry exhaustion.

### Atomic task claims
- Use a database transaction with `SELECT ... FOR UPDATE SKIP LOCKED`, or another proven atomic claim-and-update pattern.
- Prevent two workers from successfully claiming the same task.
- Test concurrent claims with multiple workers.
- Track claim owner, claim time, attempt count and lease/recovery policy where useful.

### Initial REST API suggestions
- `POST /api/runs` — start a run
- `GET /api/runs/{run_id}` — retrieve run state
- `POST /api/tasks` — add a Blackboard task
- `GET /api/tasks?run_id={run_id}` — list tasks
- `POST /api/tasks/{task_id}/claim` — claim task safely
- `POST /api/tasks/{task_id}/review` — record review result
- `GET /api/runs/{run_id}/events` — retrieve event history
- `GET /api/runs/{run_id}/metrics` — get metrics
- `WS /ws/runs/{run_id}` — stream live events

Treat these as proposed API contracts; refine them with shared team interfaces before implementation.

---

## 8. Provider Abstraction, Routing and Fallback

Support:
- Ollama for local inference
- Groq API
- Gemini API

All providers must implement a common adapter interface so workers do not depend on provider-specific APIs.

Normalize provider responses into a shared structure containing:
- provider and model identity
- response content / structured result
- token usage where reported
- latency
- estimated cost where applicable
- errors and retry metadata

### Routing policy
- Use the Router’s complexity and task requirements to recommend a model.
- Apply deterministic policy for availability, quotas, safety and budget.
- Keep provider selection separate from agent roles.
- Handle HTTP 429, timeouts and provider outages with bounded retry/backoff.
- Automatically fall back to an eligible provider when quota is exhausted or a provider fails.
- Ollama is a fallback only when the local model is installed, available and suitable for the task.
- Test hosted quota exhaustion deliberately before the demo.
- Distinguish zero API charge for local inference from total operating cost; record estimates transparently.

Do not hard-code assumptions that a particular provider is always best for a complexity level. Validate routing quality through experiments.

---

## 9. Live Game Map and Observability

### Product intent
Use Phaser.js + Canvas to render a 2D strategy-game-like map. The visual metaphor may show:
- Planner at a command station
- Coder at a coding workstation
- Reviewer at a testing station
- Blackboard/task tiles
- Model-provider stations
- Completed and blocked task areas

The positions are visual metaphors. Characters must only change state in response to real backend execution events. Do not use prerecorded animations that imply work has happened when it has not.

### Event flow
```text
LangGraph / CrewAI state transition
        -> event publisher
        -> FastAPI WebSocket
        -> frontend event store
        -> Phaser scene and dashboard
```

Example event:

```json
{
  "event_id": "evt_018",
  "run_id": "run_001",
  "sequence_number": 18,
  "agent_id": "coder_01",
  "task_id": "task_002",
  "type": "task_started",
  "status": "working",
  "timestamp": "2026-10-23T10:00:00Z"
}
```

Suggested events:
- `task_created`
- `task_claimed`
- `task_started`
- `llm_call_started`
- `llm_call_completed`
- `review_started`
- `review_completed`
- `task_completed`
- `task_failed`
- `provider_fallback`
- `run_completed`

### Animation rules
- `idle`: agent remains at home station
- `claimed`: task tile becomes highlighted
- `working`: agent moves to the work station and displays working animation
- `reviewing`: agent moves to the review/testing station
- `completed`: agent moves to completed area only after backend confirms completion
- `failed` / `blocked`: display a clear state and allow retry/inspection

Movement duration is visual only and must not control backend task completion.

### Reliability requirements
- Use sequence numbers and idempotent event handling.
- Handle duplicate, delayed and out-of-order events.
- On reconnect, reload a current state snapshot and then resume streaming.
- Keep durable event history in PostgreSQL as appropriate.
- Clicking an agent/task should show real task details, provider/model, logs, token usage, latency, cost and linked code changes.
- Freeze the event schema by Week 4/5 so backend and frontend can develop in parallel.

### Observability metrics
Display:
- agent status and task progress
- current and previous run
- provider/model selection and fallback reason
- input/output tokens where available
- estimated API cost
- latency and retry count
- test and review results
- failures and errors

---

## 10. Security and Execution Safety

Generated code is untrusted. Do not execute arbitrary generated shell commands on the host.

Minimum safeguards:
- Run code/tests in a restricted workspace or isolated container.
- Apply CPU, memory and execution-time limits.
- Restrict network access by default.
- Enforce filesystem boundaries; prevent path traversal and access outside the project.
- Allowlist tools and validate arguments.
- Require approval for destructive operations or elevated permissions.
- Never let model output directly authorize dangerous actions.
- Store API keys only in environment variables or a proper secret store.
- Redact credentials from logs and model context.
- Keep a record of edits and support recovery through Git.

---

## 11. Evaluation and Research Plan

The original project calls for at least 40 benchmark executions across Ollama, Groq and Gemini. The purpose is to determine when a free local model is sufficient versus when a hosted model provides worthwhile improvements.

### Metrics
- completion rate
- elapsed time / latency
- API cost (and clearly labeled estimates)
- test pass rate
- quality / LLM-as-judge score
- rework or retry rate
- defects caught before integration
- reviewer false-positive rate
- fallback rate
- routing decision and provider used

### Experiment requirements
- Create a fixed benchmark task set with acceptance criteria and tests.
- Define how at least 40 total runs are distributed across the three providers; do not claim 40 per provider unless that many are actually run per provider.
- Use comparable task prompts and configurations where possible.
- Record all results in PostgreSQL from the beginning.
- Use consistent quality scoring rubrics.
- Consider blinded or independent scoring and human spot checks; an LLM judge alone is not ground truth.
- Report variability, failures, missing data and limitations.
- Link each run to the relevant PEAS agent role/persona and task.
- Compare the LLM Router against the scikit-learn complexity-classifier baseline.
- Do not report performance claims before running the experiment.

### PEAS alignment from the original abstract
- **Planner:** subtask completeness; duplicate/overlapping task rate.
- **Coder:** successful compile/test rate; coding-standard compliance; rework rate.
- **Reviewer:** defects caught pre-integration; false-positive rate.

---

## 12. Team Responsibilities

Use the original ownership split as the starting point and agree on API/event contracts together.

### Harshit Bhatt — Worker Agents
- CrewAI Planner/Coder/Reviewer implementation
- Blackboard claim-execute-log loop
- MCP integration
- ChromaDB self-logs and RAG knowledge base
- Coordinate shared `add_task()` contract

### Raghav Khandelwal — Router and Evaluation
- LangGraph Router/Dispatcher
- Provider abstraction and adapters
- LLM-based complexity classification
- Provider availability, quota tracking, fallback guardrails
- scikit-learn baseline classifier
- PostgreSQL evaluation harness and LLM-as-judge workflow

### Shrey Tiwari — IDE and Observability
- Monaco Editor and file workspace integration
- Persistent chat UI integration with shared API contracts
- WebSocket event feed
- Phaser.js / Canvas game map
- Observability dashboard, event reconciliation and demo scripting

Ownership may be adjusted by the team, but every component needs one clearly accountable owner.

---

## 13. Eight-Week Implementation Plan

### Week 1 — Foundation
- Create repository and agree on directory structure and shared contracts.
- Set up React, FastAPI, PostgreSQL and Docker Compose.
- Embed Monaco Editor and create basic file navigation.
- Create project, conversation, message, run, task and event schemas.
- Implement the Blackboard `add_task()` interface.
- Establish passive execution logging from day one.
- Make one successful model call through a provider adapter.

**Exit criteria:** Frontend talks to backend; tasks and events persist; a basic run can be created.

### Week 2 — Router and Context
- Implement the LLM-powered Router Agent with structured output.
- Classify question vs. edit vs. new workflow vs. clarification.
- Implement low/medium/high complexity and execution strategy.
- Load conversation history, summary, run links and project metadata.
- Create a scikit-learn baseline plan and initial labeled examples.
- Define LangGraph state and conditional edges.

**Exit criteria:** Router decisions are validated and logged; a follow-up message is linked to the existing conversation.

### Week 3 — Worker Swarm
- Implement Planner, Coder and Reviewer with CrewAI.
- Implement the claim-execute-log loop.
- Add atomic task claiming and concurrency tests.
- Add MCP file and test tools with workspace restrictions.
- Populate and test the coding-standards RAG collection.
- Add structured outputs, retries and review loops.

**Exit criteria:** A small to-do app can be built through the agent workflow and reviewed.

### Week 4 — Providers and Stable Contracts
- Integrate Ollama, Groq and Gemini adapters.
- Implement complexity-based provider selection.
- Add quota tracking, bounded retries and automatic fallback.
- Test provider errors and quota exhaustion.
- Freeze the WebSocket event schema and frontend/backend contracts.
- Ensure run, task and LLM-call metrics are logged.

**Exit criteria:** Provider switching works and failure/fallback events are traceable.

### Week 5 — Real-Time Game Map
- Build Phaser.js map with agents, stations and task tiles.
- Stream backend events through FastAPI WebSockets.
- Implement state transitions and movement animations.
- Add sequence-number reconciliation, duplicate handling and reconnect snapshots.
- Test concurrent agents and fast state changes.

**Exit criteria:** The map responds to real task events and accurately represents backend state.

### Week 6 — Context-Aware IDE
- Complete persistent chat and Ask/Edit interaction modes.
- Implement workspace-aware follow-up changes.
- Show changed files, Monaco diffs and actual test results.
- Link each follow-up run to the triggering message and prior conversation.
- Add agent/task detail panels and metrics.
- Add Git checkpoints or a safe recovery mechanism.

**Exit criteria:** User can ask for a change after a completed run, and H.E.X Mind incrementally edits the existing project with traceable results.

### Week 7 — Benchmark and Evaluation
- Finalize benchmark tasks, acceptance tests and scoring rubric.
- Run at least 40 total executions across the three providers.
- Compare provider performance and routing decisions.
- Evaluate Router Agent classification against the scikit-learn baseline.
- Record latency, cost, completion, quality, rework and fallback metrics.
- Link results to PEAS roles/personas.

**Exit criteria:** Reproducible results are stored in PostgreSQL and summarized in a report.

### Week 8 — Integration and Delivery
- Run end-to-end tests and fix integration defects.
- Stress-test concurrency, provider failures and WebSocket recovery.
- Review code-execution security and recovery paths.
- Rehearse the complete live demo.
- Finalize README, setup instructions, architecture, evaluation results and limitations.

**Exit criteria:** Reproducible setup and end-to-end demo, documented findings, and complete deliverables.

---

## 14. Repository Structure

Adapt to the repository as it exists. Since the project is starting from scratch, this is the suggested direction; do not create empty folders or unnecessary abstractions just to match it.

```text
hex-mind/
├── apps/
│   ├── desktop/
│   │   ├── electron/
│   │   │   ├── main.ts
│   │   │   ├── preload.ts
│   │   │   └── ipc/
│   │   ├── renderer/
│   │   │   └── src/
│   │   │       ├── app/
│   │   │       ├── components/
│   │   │       ├── features/
│   │   │       │   ├── workspace/
│   │   │       │   ├── editor/
│   │   │       │   ├── agent-chat/
│   │   │       │   ├── task-board/
│   │   │       │   ├── live-map/
│   │   │       │   ├── run-history/
│   │   │       │   └── settings/
│   │   │       ├── styles/
│   │   │       └── main.tsx
│   │   └── package.json
│   └── backend/
│       ├── app/
│       │   ├── api/
│       │   ├── router/
│       │   ├── agents/
│       │   ├── providers/
│       │   ├── blackboard/
│       │   ├── workspace/
│       │   ├── memory/
│       │   ├── evaluation/
│       │   ├── events/
│       │   └── main.py
│       ├── tests/
│       └── pyproject.toml
├── docs/
├── scripts/
├── .env.example
├── .gitignore
└── README.md
```

### Development order

Start with a small runnable vertical slice:
1. Electron shell, secure preload bridge, React renderer, and FastAPI health check.
2. Workspace selection, file explorer, Monaco editor, and safe diff review.
3. Persistent project-aware chat and run history.
4. Router, provider adapters, and complexity classification.
5. Worker agents, Blackboard, MCP, and RAG.
6. WebSocket events, live map, and observability.
7. Benchmarking, release preparation, and documentation.

Do not implement all phases simultaneously. Each phase must run and be tested before the next is added.

---

## 15. Definition of Done / Deliverables

The project is not complete until the following are demonstrated:

- [ ] Agent-native IDE with Monaco Editor and project file navigation.
- [ ] Planner, Coder and Reviewer collaborate through a shared Blackboard.
- [ ] Router Agent classifies task complexity and selects an execution strategy.
- [ ] Ollama, Groq and Gemini work through a provider-abstraction layer.
- [ ] Provider failure and quota fallback are tested.
- [ ] MCP tools operate within explicit workspace and execution restrictions.
- [ ] ChromaDB RAG supplies relevant coding standards to the Coder.
- [ ] Task claims are atomic and concurrent-worker tests pass.
- [ ] Persistent context-aware chat supports follow-up code changes.
- [ ] Code edits produce inspectable diffs and real test results.
- [ ] Phaser.js map reflects real agent state through WebSocket events.
- [ ] Metrics panel displays routing, latency, tokens, costs and outcomes.
- [ ] At least 40 benchmark executions are logged and analyzed.
- [ ] Evaluation includes PEAS metrics and an ML baseline comparison.
- [ ] GitHub repository, setup instructions, final report and live demo are ready.

---

## 16. Desktop App Decision: Electron + React

**Product decision:** H.E.X Mind is an Electron desktop app, not merely a website. React + TypeScript + Vite powers the renderer.

### Electron responsibilities
- Manage the application window and lifecycle in the main process.
- Use a preload script and a small allowlisted API via `contextBridge`.
- Keep `contextIsolation: true` and `nodeIntegration: false`.
- Validate IPC payloads and workspace paths in the main process.
- Do not expose unrestricted `ipcRenderer`, Node APIs, filesystem access, or shell execution to React components.
- Open external links safely.
- Keep provider secrets out of renderer code and logs.
- Bind the local backend to loopback by default.
- In development, Electron and FastAPI may run as separate processes.
- In the packaged app, the main process should start and monitor only the backend process it owns, wait for health readiness, and shut it down gracefully on exit.
- Use bounded startup timeouts and show actionable diagnostics for backend failures or port conflicts. Do not add complex packaging or dynamic port discovery before the basic vertical slice works.

### Workspace safety
- Let the user choose a workspace through a native folder picker.
- Scope all file operations to the selected workspace.
- Reject path traversal and writes outside the workspace; guard against symlink escapes where feasible.
- Detect stale file versions before applying agent edits.
- Show a Monaco diff before changes are applied and provide undo/restore.
- Offer an optional Git checkpoint before broad or multi-file changes.
- Never execute LLM-generated terminal commands without policy checks and explicit user approval.

## 17. UI/UX Direction: Clean, Modern Developer Software

### Design goal
Build a polished, high-quality developer tool—not a generic admin dashboard, a marketing page, or a game-themed toy. Use modern IDEs as usability inspiration without copying their branding or exact layout.

The IDE workspace is the product. The game map is a secondary observability view.

### Design system
- Dark-first theme with an optional light theme when practical.
- Layered charcoal/slate surfaces, subtle borders, restrained elevation, and one primary accent color such as indigo or blue-violet.
- Use semantic colors sparingly: green for success, amber for waiting/warnings, red for failures/destructive actions, and blue/purple for active work.
- Use consistent 4px/8px spacing, restrained corner radii, readable typography, and a monospace font for code and telemetry.
- Use a consistent icon set such as Lucide; avoid emoji as interface icons.
- Avoid excessive gradients, glassmorphism, glowing borders, oversized cards, decorative animations, and unnecessary motion.
- Provide keyboard navigation, visible focus states, readable contrast, tooltips for icon-only buttons, and reduced-motion support.
- Design loading, empty, disconnected, error, success, and confirmation states intentionally.
- Do not display fabricated agent progress, task status, token counts, cost, or latency.

### Main IDE layout
- **Top bar:** app/workspace identity, branch or status when available, run controls, and settings.
- **Left activity bar/sidebar:** Explorer, Agents, Runs, and Settings.
- **Center:** editor tabs, breadcrumbs, and Monaco Editor; diff view for proposed changes.
- **Right panel:** persistent agent chat with Ask/Edit modes, context indicators, plan, and run details.
- **Bottom panel:** Problems, Tasks, Agent Events, Logs, and Evaluation.
- Panels should be resizable, collapsible, and reopenable. Do not show every panel at full size simultaneously.
- Welcome screen should prioritize opening a project and showing backend/provider readiness, not marketing content.

### Core interaction requirements
1. **Workspace:** open a folder, browse files, and clearly show the active project.
2. **Agent plan:** display complexity, selected strategy/provider, subtasks, and task ownership; allow review before execution when appropriate.
3. **Chat:** Ask mode answers without editing; Edit mode proposes code changes. Show project/file/run context where relevant.
4. **Diff review:** show file-by-file changes, tests, reviewer findings, and whether changes are proposed, applied, rejected, or reverted.
5. **Run history:** searchable records for task, status, duration, provider/model, token usage and estimated cost when available, retries, and outcomes.
6. **Live agents:** provide a compact status list in addition to the Phaser map; the map must reflect real backend events and never be the only way to understand state.
7. **Settings:** provider connectivity, Ollama model/health, secret status without revealing keys, theme, reduced motion, workspace safety, and diagnostics.

### Chat continuity
- Keep conversation history associated with the project.
- Follow-up edits create a new run linked to the same conversation and project.
- Workspace files remain the source of truth; re-inspect relevant files before each change.
- Preserve previous runs and diffs.
- Summarize affected files and plan before non-trivial edits.
- After execution, show a summary, diff, tests, reviewer status, and useful next steps.
- Support stopping active runs and cancelling pending work.

### UI implementation guidance
- Use React + TypeScript + Vite.
- Create reusable components for buttons, icon buttons, tabs, split panes, status indicators, dialogs, command palette, toasts, tooltips, and tables as needed.
- Keep design values in CSS variables/design tokens.
- Keep the component library lightweight; add a larger UI framework only for a demonstrated need.
- Use Monaco for code and diffs, Phaser.js/Canvas only for the map, and WebSockets for live events.
- Reconcile events by ID/sequence and request an authoritative snapshot after reconnecting.
- Keep frontend task/run/agent state derived from backend truth.

## 18. Security, Reliability, and Implementation Rules

- Validate model-generated structured output with Pydantic schemas.
- The Router proposes a route; deterministic policy and guardrails control execution.
- Do not allow model output to directly authorize destructive or dangerous operations.
- Keep API keys in backend environment variables or an appropriate secure store, never in the renderer bundle or source control.
- Commit `.env.example`, never real secrets.
- Validate workspace paths and tool arguments.
- Use atomic database-level task claims (for example, PostgreSQL transactions with `SELECT ... FOR UPDATE`) to prevent duplicate claims.
- Treat WebSocket events as a stream of real backend state; handle duplicates, gaps, out-of-order delivery, and reconnect snapshots.
- Introduce dependencies only when a phase needs them. Avoid unused packages and premature microservices.
- Preserve working code and existing repository conventions if implementation begins in a non-empty repository.
- Build and test in small milestones; do not rewrite the entire application or implement every feature at once.
- Ask before major architectural changes or significant new dependencies.
- Do not use Jev anywhere in the architecture or implementation.

## 19. Claude Code Working Instructions

1. Read this file completely before making changes.
2. Inspect the repository, package manager, existing code, tests, and available environment before deciding what to change.
3. If the repository is empty, begin with the smallest end-to-end vertical slice: Electron shell + secure preload + React/TypeScript/Vite renderer + FastAPI health endpoint and connection status.
4. Present a concise plan and proposed files, then implement that milestone only.
5. Do not implement the Router, agents, providers, databases, workspace editing, Phaser map, or evaluation harness until their later milestones.
6. Run the relevant tests, type checks, and builds; report only results actually verified.
7. At the end of each milestone, summarize changed files, commands run, test/build results, known limitations, and the next recommended milestone.
8. Never claim a feature is complete unless it runs and has been verified.

## 20. Final Definition of Done

The complete H.E.X Mind project is ready when:
- [ ] Electron desktop app launches reliably with clear startup and failure states.
- [ ] React + TypeScript renderer has a consistent, modern, accessible IDE interface.
- [ ] Electron security boundaries are correctly configured.
- [ ] Users can open a workspace and safely inspect/edit project files.
- [ ] Monaco supports editing, tabs, and diff review.
- [ ] Persistent project-aware Ask/Edit chat supports follow-ups and links each run to its project/conversation.
- [ ] The LLM-powered Router is the first orchestration component; Jev is not used.
- [ ] The scikit-learn complexity baseline is evaluated alongside the LLM Router.
- [ ] Planner, Coder, and Reviewer perform their specified roles.
- [ ] Blackboard claims are atomic under concurrent execution.
- [ ] Ollama, Groq, and Gemini use a consistent provider-adapter interface.
- [ ] Quota exhaustion triggers a tested fallback to Ollama when available.
- [ ] Agent-generated changes are reviewed as diffs and can be reverted.
- [ ] WebSocket events drive the live agent map and observability UI honestly.
- [ ] PostgreSQL stores run traces and evaluation results.
- [ ] At least 40 benchmark runs compare all three backends on completion, time, cost, and LLM-as-judge accuracy, with PEAS-linked metrics.
- [ ] Tests cover routing, fallback, atomic claims, workspace safety, conversation/run linkage, event reconciliation, and critical UI states.
- [ ] README documents setup, environment variables, commands, architecture, limitations, and demo flow.
- [ ] The demo shows H.E.X Mind as the IDE; the to-do app is only the target application.
