# H.E.X Mind — Plan v2 (organized by evaluation criteria)

> **Status:** Source of truth for the team and for Claude Code. **v2 (2026-11-01)** reorganizes the plan around the 11 criteria the project is graded on. It replaces v1, which is kept in git history. The original brief, `HEX_Mind_Latest_Plan_for_Claude_Code.md`, stays for reference.
>
> **Product:** H.E.X Mind (Hivemind Execution X), an agent-native IDE with live multi-agent observability. The demo target is a to-do app.
>
> **Hard rules:**
> - **Agent frameworks:** CrewAI and Google ADK only. LangGraph is removed. Infrastructure libraries (FastAPI, SQLAlchemy, ChromaDB, the MCP SDK, OpenTelemetry, React, Electron) are not agent frameworks and stay.
> - **No fabrication:** never fabricate agent activity, tokens, cost or latency.
> - **Untrusted code:** generated code is treated as untrusted.

---

## 0. Criteria coverage

| # | Criterion | How H.E.X Mind meets it | Built so far | Phase |
|---|---|---|---|---|
| 1 | **State sharing: Blackboard vs messaging** | Two interchangeable coordination backends: the **Blackboard** (shared Postgres task state) and **messaging** (A2A message passing with no shared store). The same benchmark runs on both and they're compared. | Blackboard built and tested | P3, P6 |
| 2 | **Tools via MCP: 16 tools** | One MCP server exposing 16 tools in 5 groups (§4), used by both ADK (`MCPToolset`) and CrewAI. | 6 of 16 | P3 |
| 3 | **Structured output (Pydantic)** | Every model output that drives a decision (route, plan, review, guardrail verdict, judge score) is a Pydantic model, validated with one repair retry. So are event payloads, API models and settings. | Done | Extended in each phase |
| 4 | **Agentic design patterns: comparison** | Five patterns run on the same benchmark: single agent, sequential pipeline, reflection loop, parallel fan-out, and adaptive routing (§6). | Patterns exist in code, no comparison | P1, P6 |
| 5 | **Monitoring via callbacks** | All 6 ADK callbacks plus CrewAI's step and task callbacks and event listeners feed **one telemetry hub**, which drives live monitoring in the app (§7). | Custom hooks only | P1, P4 |
| 6 | **A2A: ADK ↔ CrewAI** | The ADK orchestrator talks to CrewAI crews served as **A2A agents** (and the reverse for review), with the Agent Card, task and message lifecycle visible in traces. | None | P2 |
| 7 | **Frameworks: only CrewAI + ADK** | **ADK** handles orchestration (routing, workflow, review loop). **CrewAI** handles the worker crews (Planner, Coder). LangGraph is removed. | CrewAI used; LangGraph still present | P1 |
| 8 | **Guardrails + prompt variants** | Guardrails in layers: input, tool, output and execution (§8). A versioned **prompt-variant registry**, where every model call records the variant it used. | Execution and output guardrails built; no variants | P4 |
| 9 | **Observability: tracing, audit, provenance** | OpenTelemetry traces (run → agent → model call → tool), a tamper-evident hash-chained audit log, a provenance graph from every changed line back to the prompt variant, and an in-app trace, metrics and provenance explorer (§7). | Event log, `llm_calls`, linked diffs | P5 |
| 10 | **End-to-end evaluation: cost, time, prompt variance** | The benchmark runner measures pass rate (hidden tests), cost, wall time, tokens and retries across providers × patterns × state-sharing × prompt variants, with repeated runs to measure variance (§9). | 14-task benchmark validated; cost and time logged | P6 |
| 11 | **Cloud deployment** | **Later phase (P8).** Google Cloud Run services for the backend and A2A agents, Cloud SQL, a web build of the UI, and cloud tracing (§11). | Not started (deliberately deferred) | P8 |

---

## 1. Architecture

```text
                         ┌──────────────────────── Desktop app (Electron + React) ─────────────────────────┐
                         │ Monaco · Chat (Ask/Edit/Auto) · Diff review · Tasks · Live agents ·             │
                         │ Trace explorer · Metrics · Audit log · Provenance · Prompt variants · Providers │
                         └───────────────▲─────────────────────────────── WebSocket + REST (token) ─────────┘
                                         │
┌────────────────────────────────────────┴──────────────── FastAPI backend ─────────────────────────────────────┐
│ ADK orchestration layer (google-adk)                                                                         │
│   RouterAgent (LlmAgent, Pydantic output) ─► policy ─► AnswerAgent | Clarify | RunOrchestrator              │
│   RunOrchestrator = SequentialAgent[ Prepare, PlanStep, ExecuteStep(Loop: Code ⇄ Review), Finalize ]         │
│   ReviewerAgent (LlmAgent) · callbacks on every agent, model call and tool ─► TelemetryHub                   │
│                                                                                                              │
│ Coordination backend (switchable): Blackboard (Postgres)  |  Messaging (A2A messages, no shared store)       │
│                                                                                                              │
│ ProviderRouter (Groq → Gemini → Ollama; retry, fallback, cost) ◄── HexAdkLlm (ADK BaseLlm)                   │
│                                                              ◄── HexLLM   (CrewAI BaseLLM)                   │
│ Guardrails (input / tool / output / execution) · Prompt-variant registry · TelemetryHub (OTel + events +     │
│ audit chain + provenance)                                                                                    │
└───────────────┬───────────────────────────────────┬─────────────────────────────┬───────────────────────────┘
                │ A2A (JSON-RPC over HTTP)          │ MCP (stdio)                 │
┌───────────────▼─────────────┐   ┌─────────────────▼──────────────┐   ┌──────────▼──────────────────────────────┐
│ CrewAI A2A agent services   │   │ MCP server: 16 tools           │   │ PostgreSQL · ChromaDB · Docker sandbox  │
│  PlannerCrew · CoderCrew    │──►│ workspace · git · checks ·     │   │ OTel collector + Jaeger (local)          │
│  (HexLLM → ProviderRouter)  │   │ blackboard · knowledge         │   │                                          │
└─────────────────────────────┘   └────────────────────────────────┘   └─────────────────────────────────────────┘
```

**Division of work between the frameworks:**

| Concern | Framework | Why |
|---|---|---|
| Routing, conversation, run workflow, review loop | **ADK** (`LlmAgent`, `SequentialAgent`, `LoopAgent`, `ParallelAgent`) | ADK's workflow agents replace LangGraph's graphs. ADK's callbacks and OpenTelemetry tracing are built in. |
| Planning and coding work | **CrewAI** (crews served over A2A) | Already built and tested (M3/M4). Serving the crews over A2A gives a real cross-framework boundary. |
| Reviewer | **ADK** `LlmAgent` | Places the reflection loop across the framework boundary: ADK reviews CrewAI's code. |

**Kept from M0–M4 unchanged:**
- **Workspace and data:** path guard, Git worktrees, the sandbox, the MCP server (extended), the Blackboard, ChromaDB RAG and the event log.
- **Providers:** `ProviderRouter` with fallback and the Groq, Gemini and Ollama adapters.
- **App:** the frontend.

---

## 2. Framework migration: LangGraph → Google ADK (criterion 7)

LangGraph is used in only two files, `app/graph/conversation.py` and `app/graph/run.py`. Both are replaced:

| LangGraph today | ADK replacement |
|---|---|
| Conversation `StateGraph` (context → route → answer/clarify/run) | `RouterAgent` (an `LlmAgent` with `output_schema=RouterDecision`) plus a deterministic `PolicyAgent` (a custom `BaseAgent`, no LLM), then `AnswerAgent` or a run hand-off. |
| Run `StateGraph` (prepare → plan → execute → finalize) | `RunOrchestrator = SequentialAgent([PrepareAgent, PlanStep, ExecuteStep, FinalizeAgent])`. The deterministic steps are custom `BaseAgent`s; the review rounds are a `LoopAgent(max_iterations=review_max_rounds+1)`. |
| State dict passed between nodes | ADK `session.state`, using the **Postgres-backed session service** so runs survive restarts and sessions can be inspected. |
| Conditional edges | Agent transfer and escalation (`EventActions.escalate`), driven by Pydantic policy results. |

**Models in ADK:** ADK's own model integrations would bypass our provider router, losing fallback, cost tracking and `llm_calls`. So **`HexAdkLlm`**, a subclass of ADK's `BaseLlm`, delegates `generate_content_async` to `ProviderRouter`, converting ADK's `LlmRequest`/`LlmResponse` (including function calls and Gemini thought signatures) to and from our types. Every model call by every agent in either framework therefore goes through one router and one log.

**Exit for this phase:** `grep -ri langgraph apps/` returns nothing, `langgraph` is removed from `pyproject.toml`, and all current behaviour tests pass.

---

## 3. State sharing: Blackboard vs messaging (criterion 1)

A `CoordinationBackend` interface with two implementations, selected per run (`coordination: blackboard | messaging`):

| | **Blackboard** (built) | **Messaging** (new) |
|---|---|---|
| Shared state | Postgres `tasks` table: atomic claims (`FOR UPDATE SKIP LOCKED`), leases, dependencies, file-overlap scheduling | None. Each agent holds only what it received in messages. |
| Task hand-off | Workers poll and claim | The orchestrator sends an A2A `message/send` with the task and its context. The worker replies with an artifact. |
| Dependencies | Database query | The orchestrator orders messages topologically |
| Failure recovery | Lease reaper re-queues the task | Orchestrator timeout plus resend (at-least-once delivery, with an idempotency key) |
| Visibility | Any agent can read the board | Only the orchestrator has the full picture |

**Measured on the benchmark:** pass rate, wall time, tokens and cost, message or query counts, duplicated work, context size per agent, and recovery after an injected worker failure. Results go into the evaluation report (§9).

---

## 4. MCP tools: 16 (criterion 2)

One MCP server (`app/mcp_server`), bound per run to that run's worktree, applying the agent path policy and argument validation to every call. ADK consumes it via `MCPToolset` and CrewAI via its MCP tool adapter.

| Group | Tools (✅ = already built) |
|---|---|
| Workspace (7) | ✅ `list_files`, ✅ `read_file`, ✅ `search_code`, ✅ `write_file`, ✅ `replace_in_file`, `delete_file`, `move_file` |
| Git (3) | `git_status`, `git_diff`, `git_log` (worktree-scoped, read-only) |
| Checks (2) | ✅ `run_check`, `list_checks` |
| Blackboard (2) | `list_tasks`, `add_task_note` (agents can read the board and leave notes; claims stay with the orchestrator) |
| Knowledge (2) | `search_standards` (ChromaDB coding standards), `recall_lessons` (self-logs) |

Every tool has Pydantic argument and result models. Each tool's role allow-list (for example, the Reviewer can't write) is enforced by an ADK `before_tool_callback` and a CrewAI tool guardrail. Each tool has unit tests plus one stdio round-trip test.

---

## 5. Structured output (criterion 3)

Done, and extended in each phase. Every new artifact is Pydantic:
- Guardrail verdicts
- Prompt-variant definitions
- A2A task and message payloads
- Trace and provenance records
- Judge scores
- Evaluation results

ADK agents use `output_schema`, CrewAI tasks use `output_pydantic` or our validator, and every model output gets one repair retry before a deterministic fallback.

---

## 6. Agentic design patterns: comparison (criterion 4)

All patterns are built from the same agents and tools, so they differ only in structure:

| Pattern | Structure | Built from |
|---|---|---|
| **P-single** | One Coder agent with all tools, no plan and no review | CrewAI Coder |
| **P-sequential** | Plan → Code → single review | ADK `SequentialAgent` |
| **P-reflection** | Code ⇄ Review loop until approved (max N rounds) | ADK `LoopAgent` (today's default) |
| **P-parallel** | Planner fan-out, with independent tasks coded in parallel | ADK `ParallelAgent` + Blackboard |
| **P-adaptive** | The Router picks the pattern by complexity | ADK `RouterAgent` + policy |

Each run records its `pattern`. The evaluation compares pass rate, cost, time, tokens and reviewer catch rate per pattern, overall and per complexity band.

---

## 7. Monitoring via callbacks (criterion 5) and observability (criterion 9)

### 7.1 Callbacks feed one TelemetryHub
| Source | Hooks used |
|---|---|
| ADK | `before_agent_callback`, `after_agent_callback`, `before_model_callback`, `after_model_callback`, `before_tool_callback`, `after_tool_callback` |
| CrewAI | `step_callback` (each agent step), `task_callback` (task done), crew `before_kickoff` / `after_kickoff`, and the CrewAI event bus (`crewai_event_bus`) for LLM and tool events |
| Ours | `ProviderRouter` (retries, fallback, cost), sandbox, guardrails, Blackboard |

`TelemetryHub.record(...)` writes four things from each callback:
1. **Event-log entries:** the existing ordered event stream, extended with `agent_started`, `agent_finished`, `guardrail_triggered`, `a2a_message` and `prompt_variant_selected`.
2. **OpenTelemetry spans,** with parent/child links.
3. **Metrics:** counters and histograms.
4. **Audit records.**

Callbacks are also where guardrails and live monitoring attach, so one mechanism serves monitoring, guardrails and observability.

### 7.2 Tracing
- **Span tree:** OpenTelemetry spans run → agent → (model call | tool call | A2A call | sandbox check | guardrail), with context propagated **across A2A** (W3C `traceparent` in message metadata). One trace therefore spans ADK and CrewAI, even across process boundaries.
- **Span attributes:**
  - `agent.name`, `agent.framework` (adk/crewai), `llm.provider`, `llm.model`
  - token counts, `cost.usd`, `prompt.variant`
  - `tool.name` and argument hash
  - `guardrail.verdict`
- **Export:** to a **local OTel collector + Jaeger** (added to Docker Compose) and to Postgres (`trace_spans`), so the app can render traces offline.

### 7.3 Audit log (tamper-evident)
- `audit_log` is append-only. Each record holds `prev_hash` and `hash = sha256(prev_hash + canonical(record))`.
- **What's recorded:** every model call (request/response hashes and redacted content), tool call, file write, guardrail decision, approval, apply and revert.
- **Verification:** `GET /api/audit/verify?run_id=` re-checks the chain, and the UI shows verified or broken at a given record.

### 7.4 Provenance
A provenance graph per run:
```
changed file/hunk → tool call (write_file) → agent step → model call → prompt variant + provider/model
                 → task → plan → router decision → user message
```
- **In the app:** select a diff hunk to see why it exists and which model wrote it with which prompt.
- **Export:** a PROV-style JSON file per run.

### 7.5 In-app observability (replaces the earlier map-only idea)
- **Trace explorer:** a waterfall of spans, with model and tool details, redacted prompts and responses, timings, tokens and cost.
- **Live agents:** agent status, now driven by callbacks, plus the attention board (Working / Needs you / Ready). The Phaser map is optional polish.
- **Metrics dashboard:** cost, latency (p50/p95), tokens, error and fallback rate by provider, agent, pattern and prompt variant.
- **Audit log viewer** with chain verification.
- **Provenance view** on the diff.
- **Stream:** WebSocket push of events (replacing the 1 s polling), with snapshot and reconnect (seq-based, already designed).

---

## 8. Guardrails and prompt variants (criterion 8)

### 8.1 Guardrails in layers
| Layer | Guardrail | Where | Built? |
|---|---|---|---|
| Input | Prompt-injection screening of user messages and of file contents passed to models (heuristics plus an LLM classifier with Pydantic verdict); secret redaction | ADK `before_model_callback` | Redaction ✅ |
| Input | Ask mode can't write; low confidence triggers clarification | Policy agent | ✅ |
| Tool | Per-role tool allow-list; path and argument validation; rate limit per run | ADK `before_tool_callback`, CrewAI tool guardrail, MCP server | Path policy ✅ |
| Output | Pydantic schema with one repair retry; CrewAI task `guardrail=` functions (for example, the plan must name files, the review must cite file and line) | `after_model_callback`, CrewAI tasks | Schema ✅ |
| Execution | Isolated worktree; Docker sandbox with no network; allow-listed checks; no-change and zero-test rejection; no approval without an accepted task | Run workflow | ✅ |
| Budget | Per-run token and cost ceiling, with a hard stop and a `guardrail_triggered` event | `before_model_callback` | New |

Every trigger is recorded (event, span attribute and audit record), and the UI lists them in **Needs you**.

### 8.2 Prompt-variant registry
- **Files:** prompts move into `app/prompts/<role>/<variant>.yaml`. Each file has an id and version, the template, a description, and the date it was introduced.
- **Variants per role:** at least 3 for the Router, Planner, Coder and Reviewer. For example:
  - `v1-baseline` (current)
  - `v2-stepwise` (explicit step-by-step reasoning instructions)
  - `v3-fewshot` (worked examples)
  - optionally `v4-terse`
- **Assignment:** a fixed variant per role, or a seeded random A/B assignment for experiments.
- **Recording:** the variant id is recorded on every model call, span and run.
- **In the app:** a Prompt variants panel to view variants, choose the active ones, and compare results.

---

## 9. End-to-end evaluation (criterion 10)

- **Benchmark:** the 14 tasks with hidden acceptance tests (built and validated: each test fails on the seed and passes on the reference).
- **Runner:** `python -m app.evaluation.run` grows a fresh workspace per run, runs the full agent pipeline, grades with the hidden test, and writes `eval_runs`.
- **Experiment axes:** provider (Groq / Gemini / Ollama) × pattern (§6) × coordination (§3) × prompt variant (§8.2). Not the full grid; these designs:

| Experiment | Varies | Fixed | Runs |
|---|---|---|---|
| E1 Providers | Groq, Gemini, Ollama | reflection, Blackboard, v1 | 14 × 3 = 42 |
| E2 Patterns | 5 patterns | best provider, Blackboard, v1 | 14 × 5 = 70 |
| E3 State sharing | Blackboard vs messaging | best provider and pattern, v1 | 14 × 2 = 28 |
| E4 Prompt variance | 3 variants of each role | best provider, pattern and coordination | 14 × 3 × 3 repeats = 126 |

- **Metrics per run:**
  - pass rate (hidden test)
  - wall time and time per phase
  - tokens in/out and cost (with verified prices)
  - retries and fallbacks
  - review rounds
  - guardrail triggers
  - LLM-judge quality score, with human spot checks on at least 20% of runs
- **Prompt variance:** repeated runs per variant give mean, standard deviation and coefficient of variation for pass rate, cost and time, plus significance testing between variants.
- **Output:** report tables and charts produced by a script from Postgres, plus the Router-vs-scikit-learn baseline comparison on the labeled set.
- **Free-tier limits:** Groq's per-minute token limit is reached after about 6 agent calls and Gemini's quota is small. The runner paces requests (`--rpm` budget) and resumes after cooldowns, or a paid tier is used for E2–E4.

---

## 10. Phases (from the current state)

**Already built (M0–M4):**
- Electron IDE (editor, chat, diff review)
- Postgres and the event log
- Router and context manager
- CrewAI agents, Blackboard, worktrees, sandbox, 6 MCP tools and RAG
- Groq, Gemini and Ollama providers with fallback
- Native tool calling
- The 14-task benchmark

M4 must be committed before P1 starts.

| Phase | Goal | Criteria | Exit check |
|---|---|---|---|
| **P1 — ADK core** | Replace LangGraph with ADK agents; `HexAdkLlm`; TelemetryHub; all ADK and CrewAI callbacks wired | 7, 5, 3 | No LangGraph anywhere; every existing behaviour test passes; each callback type produces events and spans; one live run end to end |
| **P2 — A2A** | Serve the CrewAI Planner and Coder crews as A2A agents; ADK orchestrator uses them as remote agents; trace context propagated | 6, 9 | A run whose CrewAI work happens over A2A, traced as one tree across processes |
| **P3 — 16 MCP tools + messaging backend** | Add 10 tools; `CoordinationBackend` with Blackboard and messaging | 2, 1 | 16 tools with tests; the same benchmark task passes on both backends |
| **P4 — Guardrails + prompt variants** | Layered guardrails (§8.1), variant registry and UI | 8, 5 | Each guardrail has a triggering test; variant ids appear on every call |
| **P5 — Observability** | OTel collector + Jaeger, `trace_spans`, hash-chained audit log, provenance graph, WebSocket stream, trace, metrics, audit and provenance views | 9, 5 | Select a diff hunk to see its full provenance chain; the audit chain verifies; the trace waterfall renders a live run |
| **P6 — Evaluation** | Runner + experiments E1–E4 + report | 10, 1, 4, 8 | Reproducible report with cost, time and prompt-variance results and the pattern and state-sharing comparisons |
| **P7 — Product loop** | Apply, reject and revert diffs; follow-up runs; attention queue; reliability tests | — | The demo script runs end to end on the to-do app |
| **P8 — Cloud deployment (later)** | §11 | 11 | The deployed system runs the demo |

---

## 11. Cloud deployment (criterion 11): later phase

This is planned now and built last. Target: **Google Cloud**, which fits ADK.
- **Backend:** FastAPI plus the ADK orchestrator as one **Cloud Run** service. The CrewAI A2A agents run as separate Cloud Run services, which keeps the A2A boundary real.
- **Data:** **Cloud SQL for PostgreSQL**. ChromaDB moves to a persistent volume or managed alternative, with embeddings switched to a hosted embedding model.
- **Sandbox:** **Cloud Run Jobs** (gVisor-isolated, no egress) replace local Docker for running checks.
- **Models:** Groq and Gemini, with keys in **Secret Manager**. Ollama isn't available in the cloud, so hosted models only.
- **UI:** the React renderer gets a web build (served by Cloud Run or Firebase Hosting) with real authentication. The desktop app remains for local use.
- **Observability:** the OTel exporter is pointed at **Cloud Trace / Cloud Logging**.
- **Workspaces:** repositories are cloned into per-run storage instead of local folders.

---

## 12. Decisions carried over (still valid)

- **Model calls:** every one goes through `ProviderRouter`, with configurable order (default Groq → Gemini → Ollama), retry honouring Retry-After, immediate fallback with cooldown on quota/auth/model errors, and one `llm_calls` row per attempt.
- **Agent claims are not evidence:**
  - a round with no file changes is rejected
  - a check that ran zero tests isn't a pass
  - a run with no accepted task can't be approved
  - hidden acceptance tests grade the benchmark
- **Isolation:** each run gets an isolated worktree from a snapshot that includes uncommitted and untracked files. The user's files change only on explicit apply.
- **Tool calls:** native by default, with recovery of tool calls a model writes as JSON text (qwen2.5-coder), limited to offered tools.
- **Leases:** worker leases renew via heartbeat, and a worker that loses its lease stops.
- **Provider quirks found live:**
  - Llama 3.3 and gemini-2.5-flash are retired, so the defaults are `openai/gpt-oss-120b` and `gemini-3.5-flash`.
  - Gemini 3 needs thought signatures on replayed tool calls; they're preserved by call ID, and other providers' calls get a placeholder.
  - Groq per-minute 429s are rate limits, even though the message mentions billing.
  - Reasoning models need larger output budgets.
- **Testing:** never run two pytest sessions at once, because they share the test database.

---

## 13. Risks

| Risk | Mitigation |
|---|---|
| ADK `BaseLlm` subclassing or A2A APIs differ from the docs in the pinned version | **Spike first in P1/P2** (as with the CrewAI R1 spike), and record the findings. |
| A2A adds latency and failure modes | Timeouts, idempotent resends, and A2A traced as spans. Messaging-backend recovery is part of the comparison. |
| Free-tier quotas make the experiments slow | Paced runner, resumable experiments, cached seeds; a paid tier if needed for E2–E4. |
| Too much observability UI | Build in the order trace explorer → metrics → audit → provenance; the Phaser map is optional. |
| Cloud migration (P8) is large | Keep services stateless from P1 on, with config via env vars. The sandbox and storage abstractions already isolate the parts that change. |

---

## 14. Working instructions for Claude Code

1. Read this file and inspect the repo before changing anything.
2. Work **one phase at a time** (§10). Spike unfamiliar framework APIs before building on them.
3. Run all tests, type checks and builds. Report only verified results, including live findings.
4. Never run two pytest sessions at once.
5. Ask before adding significant dependencies or changing a recorded decision.
6. Don't commit or push without the user's go-ahead.
