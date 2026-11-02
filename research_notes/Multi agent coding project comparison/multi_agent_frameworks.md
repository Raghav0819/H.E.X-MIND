# Multi-agent orchestration frameworks and "software company" systems vs H.E.X Mind

Research date: 2026-11-02. About 17 tool calls; WebSearch returns summaries and several pages were only partly read (noted). Versions are stated per claim.

## Q0. What do the surveyed frameworks and systems do (pattern, communication, state, failure handling, results)?

### Takeaway
Role-based "software company" systems (MetaGPT, ChatDev) use fixed SOP or chat-chain pipelines. Newer systems (ChatDev 2.0, ADK 2.x, Microsoft Agent Framework, CrewAI Flows) move to configurable graph or event-driven workflows with checkpointing and human-in-the-loop. Lean pipelines (AgentCoder, Agentless) report strong results at lower cost than heavy role-play.

### Cited Findings
- MetaGPT: core idea is "Code = SOP(Team)". It models a software company (product manager, architect, project manager, engineer) from a one-line requirement and produces user stories, requirements, APIs and docs. Repo ~71k stars, requires Python >=3.9 and <3.12, no release number on the page. 2025 news: MGX product (Feb 19, 2025), AFlow (ICLR 2025 oral, automated workflow generation), SPO/AOT papers. No 2026 news items listed. — [MetaGPT repo](https://github.com/FoundationAgents/MetaGPT)
- MetaGPT paper reports HumanEval Pass@1 85.9% (third-party overview), and SoftwareDev executability 3.75/4 vs ChatDev 2.25 (overview) while the paper appendix gives 3.9 vs 2.1. Sources disagree on the numbers. — [MetaGPT paper](https://arxiv.org/pdf/2308.00352), [alphaxiv overview](https://www.alphaxiv.org/overview/2308.00352)
- ChatDev timeline: initial release Jun 2023; Experiential Co-Learning integrated Jan 25, 2024; MacNet (DAG-organised collaboration, claims >1000 agents) Jun 12, 2024; puppeteer-style orchestration proposed May 2025 and accepted at NeurIPS 2025; ChatDev 2.0 released Jan 7, 2026, with classic v1.x moved to branch `chatdev1.0`. — [ChatDev repo](https://github.com/OpenBMB/ChatDev)
- ChatDev 2.0 ("DevAll") is a zero-code platform: FastAPI backend, Vue 3 web console with a visual workflow canvas, YAML workflow configs, Python SDK (`run_workflow`, PyPI `chatdev` 0.1.0), real-time logs and intermediate artifacts, human feedback in the Launch tab, Docker Compose. Requires Python 3.12+. The page does not say whether experiential co-learning is retained in 2.0. — [ChatDev repo](https://github.com/OpenBMB/ChatDev)
- Experiential Co-Learning (ACL 2024): instructor and assistant agents accumulate "shortcut-oriented" experiences to reuse on new tasks. Per a secondary summary, overall quality 0.7304 vs ChatDev 0.4267 vs MetaGPT 0.1439, and ~122.8 s vs ~148.2 s for ChatDev; the summary should be checked against the paper. — [Paper](https://arxiv.org/pdf/2312.17025), [summary](https://liner.com/review/experiential-colearning-softwaredeveloping-agents)
- Magentic-One (Nov 2024): Orchestrator plus Coder, Computer Terminal, File Surfer, Web Surfer agents; reported 38% GAIA, 32.8% WebArena, 27.7% AssistantBench (per a summary of the paper). Originally on autogen-core, later ported to autogen-agentchat. AutoGenBench is the evaluation tool. — [Magentic-One paper](https://arxiv.org/html/2411.04468v1), [CIO summary](https://www.cio.com/article/3600262/microsoft-joins-multi-ai-agent-fray-with-magnetic-one.html)
- Microsoft Agent Framework (docs): built-in orchestration patterns Sequential, Concurrent, GroupChat, Handoff, Magentic; checkpointing with FileCheckpointStorage (dev) and CosmosCheckpointStorage (prod); Python offers a graph `WorkflowBuilder` and an experimental functional `@workflow/@step` API. — [MS Learn workflows](https://learn.microsoft.com/en-us/agent-framework/workflows), [checkpoints](https://learn.microsoft.com/en-gb/agent-framework/workflows/checkpoints?pivots=programming-language-python)
- AgentCoder: three agents (programmer, test designer, test executor) in a test-feedback loop. GPT-4 pass@1 96.3% HumanEval and 91.8% MBPP, with 56.9K/66.3K token overhead vs prior SOTA 90.2%/78.9% at 138.2K/206.5K tokens. — [arXiv 2312.13010](https://arxiv.org/abs/2312.13010)
- MapCoder: four agents (recall examples, plan, code, debug). pass@1 HumanEval 93.9%, MBPP 83.1%, APPS 22.0%, CodeContests 28.5%, xCodeEval 45.3%. — [arXiv 2405.11403](https://arxiv.org/abs/2405.11403)
- Agentless: no agent loop; three phases (localization, repair, patch validation), the LLM does not choose actions. 32.00% (96 fixes) on SWE-bench Lite at $0.70 per issue, best among open-source agents at the time of the paper (2024). — [arXiv 2407.01489](https://arxiv.org/abs/2407.01489)
- SWE-Search (ICLR 2025): MCTS over a SWE-Agent, plus a Value Agent (iterative feedback) and a Discriminator Agent (multi-agent debate); 23% relative improvement across five models over the same agents without MCTS. Absolute numbers not retrieved. — [arXiv 2410.20285](https://export.arxiv.org/pdf/2410.20285), [ICLR page](https://www.iclr.cc/virtual/2025/poster/30299)
- OpenAI Agents SDK (third-party descriptions, not official docs): primitives are agents, tools, handoffs (exposed to the model as a `transfer_to_<agent>` tool), guardrails (run in parallel with execution, fail fast; output guardrails apply to the last agent only), sessions (conversation memory), tracing (on by default). Python version 0.24.0 around Oct 2026, with sandboxed workspaces, compaction-backed sessions, durable approvals and MCP v2 (dates differ across sources). — [developersdigest](https://www.developersdigest.tech/blog/openai-agents-sdk-whats-new-2026), [claw concepts](https://claw.aguidetocloud.com/openai/agents-sdk/concepts/)
- MAST failure taxonomy (NeurIPS 2025): 14 failure modes in 3 categories (specification issues, inter-agent misalignment, task verification), from 1642 annotated traces over 7 MAS frameworks. Failures stem mainly from system design and inter-agent misalignment, not only model capability. — [arXiv 2503.13657](https://arxiv.org/html/2503.13657v2)

### Inferences
- H.E.X Mind's Planner -> Coder -> Reviewer with retries is closest to AgentCoder (programmer + executor feedback loop) and a slim MetaGPT SOP. Its main structural gap vs AgentCoder is an independent test-designer role.
- MAST's "task verification" category supports spending effort on real execution checks (which H.E.X Mind already has via Docker) rather than more LLM-only roles.

### Gaps
- LangGraph: not researched in this pass (out of budget, and it is disallowed for the course). Only needed as a conceptual reference (graph state, checkpoints, interrupts).
- Microsoft Agent Framework GA date and AG2 status: not found.
- Absolute SWE-Search and Magentic-One coding numbers, and ChatDev 2.0 benchmark results: not found. I found no published benchmark for ChatDev 2.0.

## Q1. Which orchestration patterns measurably improve code quality?

### Takeaway
Evidence favours execution-grounded feedback loops (tests run, errors fed back) and search or sampling with a verifier over extra role-playing. The MAST paper says multi-agent gains over single-agent baselines are often minimal.

### Cited Findings
- AgentCoder: an independent test designer plus executor feedback loop beat prior SOTA on HumanEval/MBPP at about 40-70% lower token cost (see Q0 numbers). — [arXiv 2312.13010](https://arxiv.org/abs/2312.13010)
- SWE-Search: MCTS with value-agent feedback and debate gave 23% relative improvement on SWE-bench across five models. — [ICLR 2025](https://www.iclr.cc/virtual/2025/poster/30299)
- Agentless: a fixed localize -> repair -> validate pipeline matched or beat autonomous agents at $0.70 per issue (2024). — [arXiv 2407.01489](https://arxiv.org/abs/2407.01489)
- Experiential co-learning (reuse of past shortcuts) improved quality and speed over base ChatDev (secondary summary). — [summary](https://liner.com/review/experiential-colearning-softwaredeveloping-agents)
- MAST: performance gains from MAS are often minimal vs single-agent or best-of-N baselines; verification-stage failures are a major class. — [arXiv 2503.13657](https://arxiv.org/html/2503.13657v2)

### Inferences
- Ranked by evidence in this research: (1) test-execution feedback loop, (2) search/best-of-N with a verifier (MCTS), (3) debate/critic as part of a value function, (4) hierarchical manager roles (no measured benefit found).
- For free-tier models, best-of-N is limited by rate limits; a bounded Loop (2-3 iterations) with real test output is the cheapest measurable win.

### Gaps
- No controlled head-to-head of hierarchical manager vs flat pipeline for coding was found. Debate-specific ablations (beyond SWE-Search's Discriminator) not found.

## Q2. Underused CrewAI and ADK capabilities for a Planner/Coder/Reviewer pipeline

### Takeaway
Both frameworks moved quickly in 2026. ADK 2.x (latest seen 2.13.0, 2026-10-22) deprecates the templated workflow agents in favour of graph workflows; CrewAI (latest seen 1.15.31, 2026-10-27) added checkpointing, execution hooks, planning, trained-agent files and a `crewai eval` command. Check which version H.E.X Mind is pinned to.

### Cited Findings
ADK:
- LoopAgent runs sub-agents in order until `max_iterations` or until a sub-agent sets `escalate = True` (e.g. via an `exit_loop` tool); sub-agents communicate through session state using `output_key` and `{key}` placeholders. Starting in ADK 2.0 (Python and Go), templated workflows such as LoopAgent are superseded by graph-based and dynamic workflows. — [ADK Loop docs](https://adk.dev/agents/workflow-agents/loop-agents/) (old google.github.io URL redirects to adk.dev)
- ADK changelog highlights (v2.10.0 2026-09-24 to v2.13.0 2026-10-22; earlier entries not read): graph workflow nodes with `require_confirmation`, tool confirmation via RequestInput, `abort_signal` on Runner/Workflow, DEFAULT_ROUTE fan-out, TypesafeClassifier/ClassifierNode routing, JoinNode fix in loops; built-in SQLite memory service via `sqlite://` URI (2.11.0), MongoDB memory/session services and `delete_memory` (2.13.0); ToolCallIntegrityPlugin (2.11.0), ForceEscalationPlugin (2.13.0), BigQuery logging plugin; eval efficiency metrics (duration, tokens, model calls) in `AgentEvaluator` and Dev UI (2.10-2.12), and `AgentEvaluator.evaluate` raising ValueError if no cases run; context compaction improvements; A2A: resume a remote agent when a human answers its pause (2.11.0), tool call/response parts in the A2A converter (2.12.0), all artifacts kept on task-to-event conversion (2.13.0). 2.13.0 README marks Sequential/Parallel/Loop agents deprecated. — [adk-python CHANGELOG](https://raw.githubusercontent.com/google/adk-python/main/CHANGELOG.md) (only 2.10.0-2.13.0 read)
- 2.6.0 (2026-07-29) fixed ParallelAgent cancelled-task handling on pre-3.11 Python. — [search summary of Dependabot PR](https://github.com/AISecurityLab/hackagent/pull/550)

CrewAI (from changelog, v1.8.0 to v1.15.31):
- Flows: production-ready Flows and Crews, HITL for Flows (1.8.0, Jan 8); `FlowFailedEvent` (1.15.9); conversational flows stable (1.15.18); flow context compaction (1.15.31, Oct 27).
- Guardrails: `guardrail_type`/`name` in traces (1.14.0); result/error exclusivity and `LLMGuardrailCompletedEvent` on malformed results (1.15.31).
- Memory: automatic `root_scope` for hierarchical memory isolation (1.12.0, Mar 25); pluggable default backends for memory, knowledge, rag (1.14.7); fix so private memories do not leak to every recall (1.15.29).
- Knowledge: pluggable backends (1.14.7).
- Planning: plan-execute pattern (1.11.0rc1, Mar 15); planning config/observation handling (1.14.6).
- Training: trained-agents file honoured at inference, replay and test (1.14.4, 1.14.7).
- Testing: `crewai eval` with `--models` and `llm_overlay` to swap models per role, per-run cost and time (1.15.24-1.15.27), crew-run verdict and file export (1.15.29).
- Checkpoints: runtime checkpointing with SQLite storage (1.14.0), resume/diff/prune/fork (1.14.2), standalone-agent checkpoints (1.14.3).
- Hooks/events: `@on` execution hooks with interception points (1.15.3); improved EventListener (1.8.0).
- A2A: native async, poll/stream/push updates (1.8.0), agent card generation (1.8.1).
- MCP tool resolution improvements (1.10.0 onward).
— [CrewAI changelog v1.15.31](https://docs.crewai.com/v1.15.31/en/changelog.md) (first 100k of 161k chars read)

### Inferences
- Likely underused in a typical pipeline (verify against the H.E.X Mind code):
  1. ADK: exit via `escalate` plus real test results as the loop exit condition, and `AgentEvaluator` eval sets as a regression suite for the pipeline (with efficiency metrics, useful on free tiers).
  2. ADK: plugins (ToolCallIntegrityPlugin, logging/BigQuery-style plugins) and callbacks as guardrails around Coder tool calls (for example block writes outside the worktree).
  3. ADK: artifacts for patches and test logs rather than stuffing them into state; session state key prefixes for scoping; memory service (SQLite URI) for cross-run lessons.
  4. ADK graph workflows (2.x) for conditional routing (e.g. route "tests failed" back to Coder, "plan invalid" back to Planner) if the project is on 2.x; otherwise LoopAgent still works on 1.x.
  5. CrewAI: task `guardrail` functions (validate that the Coder output applies cleanly or the plan has required fields) instead of only the Reviewer; `crewai eval`/test and training for the Planner crew; planning mode; knowledge sources for repo conventions; checkpointing for resumable crews; execution hooks and event listeners to feed the existing telemetry hub.
  6. CrewAI Flows as the in-crew control layer (typed state, router steps) instead of ad-hoc Python.
- Because ADK now deprecates Sequential/Parallel/Loop agents, a note in the course report on migration path is worthwhile.

### Gaps
- The CrewAI guardrail API semantics (retry counts, string vs LLM guardrails) and the ADK 2.0 introduction date and migration guide were not retrieved. ADK entries before 2.10.0 and CrewAI entries after v1.15.x page offset 100000 were not read.
- I did not inspect H.E.X Mind's code, so "underused" is a judgment about typical pipelines.

## Q3. How do systems keep a shared blackboard/memory consistent and useful?

### Takeaway
Findings are thin. The strongest cited evidence: scoped/hierarchical memory (CrewAI root_scope), explicit session-state keys via `output_key` (ADK), checkpointed workflow state (MS Agent Framework, CrewAI), and experience reuse (ChatDev co-learning).

### Cited Findings
- ADK agents share data via session state keys written with `output_key` and read by `{key}` placeholders. — [ADK Loop docs](https://adk.dev/agents/workflow-agents/loop-agents/)
- CrewAI added automatic `root_scope` for hierarchical memory isolation (1.12.0) and fixed private memories leaking into every recall (1.15.29), which shows consistency and leakage are real issues. — [CrewAI changelog](https://docs.crewai.com/v1.15.31/en/changelog.md)
- Microsoft Agent Framework and CrewAI both checkpoint workflow state so runs can resume; CrewAI adds fork with lineage. — [MS Learn](https://learn.microsoft.com/en-gb/agent-framework/workflows/checkpoints?pivots=programming-language-python), [CrewAI changelog](https://docs.crewai.com/v1.15.31/en/changelog.md)
- ChatDev experiential co-learning stores shortcut-oriented experiences from past tasks for later reuse. — [paper](https://arxiv.org/pdf/2312.17025)
- MAST lists inter-agent misalignment as a main failure category. — [arXiv 2503.13657](https://arxiv.org/html/2503.13657v2)

### Inferences
- For the Chroma blackboard: namespace entries per run, role and iteration; write structured entries (plan, diff summary, failing test, reviewer verdict) rather than free text; mark superseded entries instead of leaving stale ones; keep per-run scratch separate from cross-run "lessons" (the co-learning analogue). Large artifacts (diffs, logs) belong in ADK artifacts or the git worktree, with only references in memory.
- Using one source of truth per kind of data (ADK session state for control flow, Chroma for retrieval) avoids the two stores diverging.

### Gaps
- No empirical study of blackboard consistency for coding agents was found; MetaGPT's shared message pool and AutoGen/AG2 shared-context details were not retrieved.
