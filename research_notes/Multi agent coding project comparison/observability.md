# Agent observability and tracing platforms vs H.E.X Mind's observability UI

Research date: 2026-11-02. Roughly 20 tool calls; several vendor pages were thin or rate-limited (see Gaps). Many comparison blogs are vendor-affiliated.

## 1. What are the current OTel GenAI semantic-convention attribute names for agent/tool/model spans, and are they stable?

### Takeaway
Still NOT stable: all `gen_ai.*` spans, attributes and metrics are at "Development" level. As of v1.42.0 (12 June 2026) the GenAI conventions moved to a separate repo, `open-telemetry/semantic-conventions-genai`. Core names (`gen_ai.operation.name` = `chat` / `invoke_agent` / `execute_tool` / `create_agent`, `gen_ai.agent.*`, `gen_ai.tool.*`, `gen_ai.usage.*`) have been stable in shape since about v1.37, so it is safe to build on them if you pin versions and use the opt-in env var.

### Cited Findings
- GenAI conventions moved to the `semantic-conventions-genai` repo in v1.42.0 on 12 June 2026, together with MCP; the repo has no tagged release and ships from `main` against schema `gen-ai/1.42.0`; its README schema URL is still "TODO" — [Dash0](https://www.dash0.com/knowledge/opentelemetry-genai-semantic-conventions-explained), [GitHub repo](https://github.com/open-telemetry/semantic-conventions-genai). The old opentelemetry.io page says it is no longer maintained and points to the new repo — [OTel docs](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans/).
- Stability: all `gen_ai.*` spans, metrics and attributes are at Development level; the only Stable attributes on GenAI spans are `error.type`, `server.address`, `server.port` (from core conventions) — [Dash0](https://www.dash0.com/knowledge/opentelemetry-genai-semantic-conventions-explained). Another source (v1.40.0, Feb 2026) says churn is concentrated in multimodal content, agent graphs and MCP, while core attributes have kept their shape since v1.37.0 — [DEV Community](https://dev.to/gabrielanhaia/opentelemetry-genai-semantic-conventions-your-llm-traces-should-look-like-this-in-2026-3ff6).
- Agent span: `gen_ai.operation.name` SHOULD be `invoke_agent`; span name `invoke_agent {gen_ai.agent.name}`; span kind CLIENT (MAY be INTERNAL) — [search summary of OTel spec](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans).
- Agent attributes (on `create_agent` / `invoke_agent`): `gen_ai.agent.id`, `.name`, `.description`, `.version`, `gen_ai.tool.definitions` — [DEV Community](https://dev.to/gabrielanhaia/opentelemetry-genai-semantic-conventions-your-llm-traces-should-look-like-this-in-2026-3ff6). Also `gen_ai.workflow.name`, retrieval (`gen_ai.data_source.id`, `gen_ai.retrieval.top_k`), memory (`gen_ai.memory.store.id`, `gen_ai.memory.record.count`) — [Dash0](https://www.dash0.com/knowledge/opentelemetry-genai-semantic-conventions-explained).
- Tool span `execute_tool`: `gen_ai.tool.name`, `gen_ai.tool.type` (`function`, `retrieval`, `extension`), `gen_ai.tool.call.id` (links to the tool_call_id of the preceding chat turn) — [DEV Community](https://dev.to/gabrielanhaia/opentelemetry-genai-semantic-conventions-your-llm-traces-should-look-like-this-in-2026-3ff6).
- Model (`chat`) span: required `gen_ai.operation.name`, `gen_ai.provider.name` (replaces `gen_ai.system`); `gen_ai.request.model`, `gen_ai.response.model`, `gen_ai.response.id`, `gen_ai.response.finish_reasons`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.usage.cache_read.input_tokens`, `gen_ai.usage.cache_creation.input_tokens`, `gen_ai.usage.reasoning.output_tokens`, request params (`gen_ai.request.temperature`, `.max_tokens`, `.top_p` ...), `gen_ai.conversation.id`, `error.type` on failure — [Dash0](https://www.dash0.com/knowledge/opentelemetry-genai-semantic-conventions-explained), [DEV Community](https://dev.to/gabrielanhaia/opentelemetry-genai-semantic-conventions-your-llm-traces-should-look-like-this-in-2026-3ff6).
- Typical tree: one `invoke_agent` parent with `chat` and `execute_tool` children; sub-agents are nested `invoke_agent` spans — [search summary](https://dev.to/gabrielanhaia/opentelemetry-genai-semantic-conventions-your-llm-traces-should-look-like-this-in-2026-3ff6) (via WebSearch result of the same article cluster).
- Events: `gen_ai.client.inference.operation.details` (carries `gen_ai.input.messages`, `gen_ai.output.messages`) and `gen_ai.evaluation.result` — [Dash0](https://www.dash0.com/knowledge/opentelemetry-genai-semantic-conventions-explained).
- Metrics: `gen_ai.client.token.usage`, `gen_ai.client.operation.duration`, `gen_ai.client.operation.time_to_first_chunk`; agent/tool: `gen_ai.invoke_agent.duration`, `.tool_calls`, `.inference_calls`, `gen_ai.invoke_workflow.duration`, `gen_ai.execute_tool.duration` — [Dash0](https://www.dash0.com/knowledge/opentelemetry-genai-semantic-conventions-explained).
- Opt-in: `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental`; content capture via `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` (values `true`/`SPAN_ONLY`/`EVENT_ONLY`/`SPAN_AND_EVENT`/`NO_CONTENT`, varies by library) — [Dash0](https://www.dash0.com/knowledge/opentelemetry-genai-semantic-conventions-explained), [Logfire ADK](https://pydantic.dev/docs/logfire/integrations/llms/google-adk/).

### Inferences
- H.E.X Mind's v3 event schema maps almost 1:1 onto these names (model call -> `chat`, tool call -> `execute_tool`, agent start/end -> `invoke_agent`); adopting `gen_ai.*` names as aliases in the event schema or an OTLP exporter is cheap and defensible in a report as "aligned with OTel GenAI semconv (Development status)".
- Sources disagree on version numbers (v1.40/1.41/1.42) because they were written at different dates; cite "v1.42.0, June 2026" with the Dash0 source and call it experimental.

### Gaps
- I could not fetch the actual spec YAML/docs from the new repo (landing page only), so exact requirement levels (Required vs Recommended) for agent attributes are unverified. OTel span status/error handling for `invoke_agent` not confirmed.
- OpenInference spec (Arize's `openinference.span.kind` = AGENT/CHAIN/LLM/TOOL, `llm.token_count.*` etc.) was not fetched; no cited facts here.

## 2. How do ADK and CrewAI export OpenTelemetry/OpenInference today (config, versions)?

### Takeaway
ADK emits native OTel spans (`call_llm`, `execute_tool`, agent spans) via the global tracer provider; you either set a provider (Logfire, Cloud Trace via `adk web --otel_to_cloud`) or add the OpenInference ADK instrumentor for Phoenix/Langfuse. CrewAI has no native OTel; use `openinference-instrumentation-crewai` (or OpenLIT/Traceloop), or CrewAI's own AMP tracing (`tracing=True`).

### Cited Findings
- ADK + Google Cloud: `google-adk>=2.12.0` (page also says it assumes 1.17.0+, inconsistent), `opentelemetry-instrumentation-google-genai>=0.7b1`, `opentelemetry-exporter-otlp-proto-grpc/http>=1.42.1`; env `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental`, `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=EVENT_ONLY`, `ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=false`; run `adk web --otel_to_cloud`; Trace Explorer: filter span name `call_llm`, tabs Inputs/Outputs and Logs & Events; IAM roles Cloud Trace User etc. — [Google Cloud docs](https://docs.cloud.google.com/stackdriver/docs/instrumentation/ai-agent-adk).
- ADK docs (Python/Go/Kotlin all "v0.1.0" on that page) describe built-in logging, metrics, traces; Kotlin example uses OTLP gRPC on `localhost:4317`, `BatchSpanProcessor`, `captureMessageContent` — [adk.dev observability](https://adk.dev/observability/). Go `web` has `-otel_to_cloud`, `api` has `-trace_capacity` (default 10000 in-memory traces) — [ADK web interface](https://adk.dev/runtime/web-interface/).
- ADK + Logfire: no instrumentor needed; `logfire.configure()` sets the global tracer provider and ADK's native spans flow; env vars as above (`SPAN_ONLY` to put content on spans) — [Logfire ADK](https://pydantic.dev/docs/logfire/integrations/llms/google-adk/).
- ADK + Langfuse (and Phoenix pattern): `pip install langfuse "google-adk>=2" openinference-instrumentation-google-adk`; `GoogleADKInstrumentor().instrument()` before running agents; ADK 2.x needs Python 3.10+ — [Langfuse ADK](https://langfuse.com/integrations/frameworks/google-adk.md).
- Third-party ADK instrumentors exist (`otel-instrumentation-google-adk`, `loongsuite-instrumentation-google-adk`); span naming differs between sources (`invoke_agent`/`chat`/`execute_tool` vs `agent_run`/`call_llm`/`execute_tool`) and LoongSuite has a setting to disable ADK's native agent span to avoid double instrumentation — [PyPI otel-instrumentation-google-adk](https://pypi.org/project/otel-instrumentation-google-adk/), [OpenObserve](https://openobserve.ai/docs/integration/ai/frameworks/google-adk.md), [LoongSuite](https://pypi.org/project/loongsuite-instrumentation-google-adk/).
- CrewAI + OpenInference: `openinference-instrumentation-crewai` (releases 0.1.8 ... 0.1.14+ seen), `CrewAIInstrumentor().instrument(tracer_provider=...)`, OTLP to Phoenix at `http://localhost:6006` — [PyPI](https://pypi.org/project/openinference-instrumentation-crewai/), [Langfuse CrewAI](https://langfuse.com/integrations/frameworks/crewai).
- CrewAI observability page lists integrations: LangDB, OpenLIT, MLflow, Langfuse, Langtrace, Arize Phoenix, Portkey, Opik, Weave, Patronus AI (AgentOps has its own page) — [CrewAI docs](https://docs.crewai.com/en/observability/overview), [CrewAI AgentOps](https://docs.crewai.com/observability/agentops).
- With Logfire, the OpenInference CrewAI instrumentor gives a nested trace (kickoff -> task -> agent) but no separate model-call spans, so token/model/cost columns are empty — [Logfire CrewAI/agent frameworks](https://pydantic.dev/docs/logfire/integrations/agent-frameworks/).
- CrewAI AMP tracing: `tracing=True` on `Crew`, or `CREWAI_TRACING_ENABLED=true`; requires AMP account and `crewai login`; Traces tab shows agent decisions, task timelines, tool usage, LLM calls, execution time, token usage and cost — [CrewAI tracing docs](https://docs.crewai.com/en/observability/tracing.md).
- Traceloop (OpenLLMetry) was acquired by ServiceNow (est. $60-80M, reported closed by May 2026); said OpenLLMetry stays open source — [Traceloop blog](https://traceloop.com/blog/traceloop-is-joining-servicenow), [Calcalist](https://www.calcalistech.com/ctechnews/article/sjghwiqf11e) (price is press-estimated; terms undisclosed).

### Inferences
- Since H.E.X Mind already propagates W3C traceparent over A2A, a CrewAI crew in another process and ADK agents can share one trace in Phoenix if both export OTLP to the same collector; this is the strongest "observability" story.
- Risk: double instrumentation (ADK native spans + OpenInference instrumentor) may duplicate spans; test one at a time.
- Arize publishes instrumentors under `openinference-instrumentation-*` (ADK and CrewAI both available per sources above); AMP tracing is cloud-only, so Phoenix is the local alternative.

### Gaps
- Exact current ADK native span names and attributes (`invoke_agent` vs `agent_run`) not confirmed from ADK source; verify by running `adk web` with a console exporter.
- Phoenix ADK tracing page fetched without setup details; latest versions of `arize-phoenix-otel` / OpenInference packages unverified.

## 3. Platform survey: what is captured and key UI views

### Takeaway
All major tools share trace tree + token/cost + evals + sessions; differentiators are agent graph (Langfuse, LangSmith/LangGraph), time-travel (LangGraph Studio, AgentOps claims), and OTel openness (Phoenix, Langfuse, Logfire, OpenLLMetry).

### Cited Findings
- Langfuse: Apache 2.0 per ZenML (cloud from $29/mo); hierarchical trace timelines with nested spans, session grouping, dedicated Agent Graph view (DAG of agents/tools), OTLP endpoint, 100+ integrations, cost tracking; prompt versioning/playground; LLM-as-judge limited in self-host/free per ZenML — [ZenML](https://www.zenml.io/blog/langfuse-vs-phoenix), [comparison search](https://andrew.ooo/answers/arize-phoenix-vs-langfuse-vs-langsmith-2026/). Ownership (ClickHouse) from one October 2026 source, unconfirmed.
- Arize Phoenix: open source (Elastic License 2.0 per one source), OTel via OpenInference with `register()`, chronological trace timelines, heatmaps, clustering, RAG retrieval views, LLM-as-judge and dataset evals included in OSS, playground with replay of past traces; ZenML says no graph view in OSS (sources conflict, one says graph is in Arize AX) — [ZenML](https://www.zenml.io/blog/langfuse-vs-phoenix). Ownership (Dynatrace) from one unconfirmed source.
- LangSmith: node-level graph execution, state transitions, branch decisions for LangGraph; LangSmith Chat (formerly Polly) analyzes traces, helps write evaluators, annotation queues, thread analysis; self-host is enterprise-only (sources differ) — [LangSmith Polly docs](https://docs.langchain.com/langsmith/polly.md), [comparison](https://latitude.so/blog/langsmith-alternatives-for-ai-agents).
- LangGraph Studio: agent IDE with graph visualization, interaction, thread management, time-travel debugging (go back to a step, edit state, rerun/fork) — [LangGraph Studio docs](https://langchain-ai.github.io/langgraph/concepts/langgraph_studio), [LangChain Studio](https://docs.langchain.com/langsmith/studio.md).
- AgentOps: session drilldowns, timelines of LLM/tool calls and errors, step-by-step replay graph, token/latency/success-rate analytics, claimed rewind/time-travel from checkpoints; free tier 5,000 events, Pro $40/mo per aggregator; maturity of time travel disputed (npm README says "coming soon") — [CrewAI AgentOps docs](https://docs.crewai.com/observability/agentops), [AG2 docs](https://docs.ag2.ai/latest/docs/ecosystem/agentops/), [AgentOps dashboard docs](https://docs.agentops.ai/v2/usage/dashboard-info).
- Pydantic Logfire: OTel-native SQL-queryable backend; curated Agents view for both ADK and CrewAI — [Logfire integrations](https://pydantic.dev/docs/logfire/integrations/agent-frameworks/).
- AutoGen Studio: Team Builder (drag/drop + JSON), Playground with live streaming of inter-agent messages, turn count and token usage; explicitly a prototyping tool — [AutoGen Studio guide](https://microsoft.github.io/autogen/stable/user-guide/autogenstudio-user-guide/).
- Google Cloud Trace (via ADK): Trace Explorer filtering by `call_llm`, Inputs/Outputs and Logs & Events tabs — [Google Cloud docs](https://docs.cloud.google.com/stackdriver/docs/instrumentation/ai-agent-adk).
- ADK dev UI: sessions with editable state, Event history, agent-structure graph view, eval-set creation (listed as tracked UI features); trace tab not described on the page — [ADK web interface](https://adk.dev/runtime/web-interface/).
- Weave (W&B) is an ADK/CrewAI-listed integration — [CrewAI docs](https://docs.crewai.com/en/observability/overview); no feature detail found.

### Inferences
- Unsourced background knowledge (verify before citing): Weave auto-patches libs and offers trace tree + evals/leaderboards; Helicone is a proxy/gateway with sessions and cost dashboards; OpenHands UI shows an event stream/trajectory with terminal/browser/diff panes.
- H.E.X Mind's A2A explorer with two-lane timelines and traceparent is comparable to Langfuse/Phoenix trace views for cross-agent calls and is unusual in being A2A-specific; none of the surveyed pages mention A2A-aware views.

### Gaps
- No usable sources for Helicone, Weave feature details, OpenHands UI, CrewAI Studio, or Phoenix's current agent-graph status.

## 4. Which UI views do users find most valuable for debugging multi-agent runs?

### Takeaway
Evidence from sources is mainly vendor-framed: nested trace tree, agent graph (who called whom), per-step input/output with token/latency, session grouping, and time-travel/replay to re-run from a step. No independent user study found.

### Cited Findings
- Comparisons repeatedly highlight agent graph views (Langfuse), node-level state/branch decisions (LangSmith), and time-travel (LangGraph Studio, AgentOps) as the differentiators — [comparison search](https://andrew.ooo/answers/arize-phoenix-vs-langfuse-vs-langsmith-2026/), [LangGraph Studio](https://langchain-ai.github.io/langgraph/concepts/langgraph_studio).
- Review caveat: replay depth degrades for long runs with hundreds of nested tool calls — [AgentOps search result aggregation](https://docs.crewai.com/observability/agentops).

### Inferences
- For students: trace tree + waterfall, per-agent token/cost table, failure view, and replay of the event log are the highest-value views.

### Gaps
- No user-survey data; ranking is inference.

## 5. Comparison with H.E.X Mind and cheapest high-impact additions

### Takeaway
H.E.X Mind already has the hard part (typed events, traceparent across A2A, topology and A2A views). Cheapest wins: (1) OTLP export to local Phoenix, (2) per-agent token/cost table, (3) latency waterfall from existing start/end events, (4) event-log replay scrubber, (5) failure grouping, (6) LLM-as-judge via Phoenix or a small in-house evaluator, (7) file-edit diff view.

### Cited Findings
- Needed tooling is available locally: Phoenix runs at `http://localhost:6006` and accepts OTLP from OpenInference instrumentors — [PyPI openinference-instrumentation-crewai](https://pypi.org/project/openinference-instrumentation-crewai/).
- OTel defines `gen_ai.evaluation.result` event and `gen_ai.client.token.usage` / `gen_ai.invoke_agent.duration` metrics, which can be reused as the schema for eval and cost panels — [Dash0](https://www.dash0.com/knowledge/opentelemetry-genai-semantic-conventions-explained).

### Inferences (ranked, effort in days for a student project)
1. OTLP export (0.5-1 d): add an exporter in TelemetryHub mapping v3 events to `gen_ai.*` spans (`invoke_agent`, `chat`, `execute_tool`; use `gen_ai.conversation.id` = run id, reuse existing trace id/traceparent). Send to Phoenix on localhost; or enable ADK native spans + `GoogleADKInstrumentor` / `CrewAIInstrumentor` and let Phoenix show them. Demonstrates standards compliance; keep your own UI for A2A and topology. Mark as experimental semconv.
2. Token/cost accounting (0.5 d): aggregate `usage` from model-call events by agent, model, run; static price table; show tab or column in Agents grid with totals and top-spend agent. CrewAI via OpenInference may lack model-call spans, so rely on your own CrewAI hooks.
3. Latency waterfall (1 d): render agent/model/tool spans as Gantt bars from start/end timestamps, nested by parent; highlight critical path and a2a hops (you already have two-lane timelines).
4. Run replay/time-travel lite (1-2 d): scrubber over persisted event log that reconstructs Blackboard and Agents state at time t. True re-execution from a step (LangGraph-style fork) is much costlier; skip or restrict to read-only replay.
5. Failure clustering (0.5-1 d): group `ok=false` events by normalized error message/type and agent, with counts and first/last seen; optionally TF-IDF grouping.
6. LLM-as-judge (1-2 d): after each run, one judge call scores task success / plan quality / tool-use correctness, emitted as `gen_ai.evaluation.result`-shaped events and shown in a run header; or use Phoenix evals.
7. Diff view of agent file edits (1 d): capture before/after on file-write tool calls and render unified diff attributed to agent and step, linked to the span.
8. Deep links: store the Phoenix trace URL on each run so graders can click from H.E.X Mind to Phoenix.

### Gaps
- Effort estimates are my judgement, not sourced. No benchmark for what graders value; evaluation criteria memory only notes observability is graded.
