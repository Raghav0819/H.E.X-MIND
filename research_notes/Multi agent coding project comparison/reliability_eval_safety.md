# Reliability, Evaluation, Safety and Cost Control for Multi-Agent Coding Systems, compared with H.E.X Mind

Research date: 2026-11-02. Search-tool summaries were used for many items; primary pages were fetched where noted. OpenAI's own post returned HTTP 403, so its claims are cited via a secondary summary. Several arXiv IDs are 26xx (2026). Anything unverified is flagged.

## 1. What measurably improves pass rate with small/free models?

### Takeaway
The best-supported levers are execution-grounded: run real tests and use the failures (or a vote across samples) to select or repair patches. Edit format matters a great deal for weaker models (diff-style formats cut "lazy" output). Hard constrained decoding is not free: it can guarantee valid JSON while lowering correctness. Self-repair alone is often no better than simply sampling more at small budgets. Everything below is mostly evidence from stronger or older models, so expect effect sizes on qwen2.5-coder:7b to differ.

### Cited Findings
- Agentless (localize files, then functions, then edit lines; sample multiple diff-format patches; validate; pick by test results and majority vote) showed a fixed pipeline with no autonomous tool use is competitive with agents — [Agentless arXiv 2407.01489](https://www.arxiv.org/pdf/2407.01489); summary via search tool, selection described as majority voting among candidates.
- SWE-Gym: sampling N trajectories and selecting with a verifier trained on test-labelled trajectories gave roughly log-linear gains as N grew — [SWE-Gym arXiv 2412.21139](https://arxiv.org/pdf/2412.21139v2).
- Edit format (Aider, GPT-4 Turbo, 89 refactoring tasks): SEARCH/REPLACE 20% (lazy comments on 12 tasks) vs unified diffs 61% (lazy on 4), about 3x less lazy. Disabling flexible patch application caused ~9x more editing errors on the Exercism benchmark. Not prompting for "high-level diffs" raised errors 30-50% — [Aider: unified diffs](https://aider.chat/2023/12/21/unified-diffs.html) (dated Dec 2023, GPT-4-era; flagged).
- Aider's polyglot leaderboard (225 problems, 6 languages) reports both percent correct and percent of well-formed edits, so edit-format compliance is itself a tracked metric; the older 133-problem Exercism Python leaderboard was superseded — [Aider leaderboard page](https://aider.chat/docs/leaderboards/edit.html); figures from mirrors, not verified.
- Self-repair: gains are often modest, vary by subset, and sometimes absent once repair cost is counted; plain i.i.d. sampling does as well or better at small budgets; the bottleneck is the quality of the model's feedback on its own code, and a stronger model as feedback source helps — [Olausson et al., ICLR 2024](https://arxiv.org/pdf/2306.09896) (dated; GPT-3.5/4, Code Llama).
- Constrained decoding: a 2026 preprint finds hard schema decoding can keep 100% schema validity but lose substantial executable accuracy (43.5 points in one calendar tool-call analogue) — [The Constraint Tax, arXiv 2605.26128](https://arxiv.org/pdf/2605.26128). A training-free "draft unconstrained, then constrain" approach (DCCD) reports up to +24 points over standard constrained decoding for a 1B model on GSM8K — [arXiv 2603.03305](https://arxiv.org/html/2603.03305v1). Another preprint reports several open-weight models stop calling tools when tool calling and JSON-schema constraints are enabled together — [arXiv 2609.23742](https://arxiv.org/pdf/2609.23742) (as summarised by search tool; unreplicated preprints).
- Repo map: Aider builds a compact AST/call-graph-based summary of the repo for the prompt, with a tunable token budget (`--map-tokens`) — [Aider repo map description via third-party](https://www.promptlayer.com/glossary/repo-map). No controlled pass-rate delta was found.
- Test-first: evidence is suggestive, not clean. An ICSE 2025 user study (15 programmers, tests refined interactively) reported +45.97% absolute pass@1 within 5 interactions — [ICSE 2025](https://conf.researchr.org/details/icse-2025/icse-2025-journal-first-papers/82/LLM-Based-Test-Driven-Interactive-Code-Generation-User-Study-and-Empirical-Evaluatio). TENET reports gains for test-driven repo-level generation — [TENET review](https://liner.com/review/tenet-leveraging-tests-beyond-validation-for-code-generation). Models writing fail-to-pass tests for issues are weak (best GPT-4o: 23.6%) — [TDD-Bench Verified](https://arxiv.org/html/2412.02883v1).

### Inferences
- For H.E.X Mind, the highest-yield order is: (1) make the existing sandbox test run the ground truth for retries with real failure output; (2) a diff/search-replace edit format with fuzzy application for qwen-class models, rather than whole-file rewrites; (3) cheap best-of-N only on the Ollama tier, selected by test results; (4) avoid combining strict JSON-schema mode with tool calling on local models (tool use may silently stop), and prefer parse-then-validate-then-repair over hard constrained decoding.
- Self-repair with the same 7B model as its own critic is unlikely to help; route the critique/repair step to a stronger free model (Gemini/Groq) when quota allows, consistent with the Olausson finding.
- A "lazy output" metric (placeholder comments like "rest unchanged") is cheap to detect and worth a hard reject-and-retry rule.

### Gaps
- No controlled study found of repo-map effect on pass rate, nor of test-first vs code-first isolated, nor any numbers for 7B-class local coder models on these techniques.
- CodeT-style test-based selection numbers were not retrieved.
- "Tool-call repair" (fixing malformed calls after the fact) had no dedicated source; only prevention-by-decoding literature surfaced.

## 2. Evaluation: benchmarks and the minimal credible in-house harness

### Takeaway
Public benchmarks are mostly out of scope for a free-tier student project; SWE-bench Verified is now considered contaminated/saturated. A credible demo needs a small, frozen, hidden-test task suite run repeatedly with pass@1 and a pass^k-style consistency number, reported per provider tier, plus a trace of cost/time. ADK's eval framework can cover trajectory checks but should not be the primary quality signal.

### Cited Findings
- OpenAI (Feb 2026) stopped reporting SWE-bench Verified and recommends SWE-bench Pro; reported flaws: of 138 hard tasks audited, 59.4% had flawed tests or problem statements (35.5% of the flaws were overly narrow tests); top score moved only 74.9% to 80.9% in six months; evidence of memorized fixes — [OpenAI post (403 on fetch)](https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/); figures via [Pebblous summary](https://blog.pebblous.ai/blog/swe-bench-verified-retired/en/). SWE-bench Pro described as 1,865 multilingual tasks; another source gives 731 for the public split (conflict; unresolved).
- SWE-bench-Live (Microsoft): 1,319 instances since 2024 across 93 repos, continuously updated; a setup scoring 43.2% on Verified scored under half that on Live — [arXiv 2505.23419](https://arxiv.org/html/2505.23419v2).
- Multi-SWE-bench: multilingual (Java, Rust, etc.), 1,632 manually curated instances by 68 annotators — via [arXiv 2505.23419 comparison](https://arxiv.org/html/2505.23419v2). SWE-bench Multimodal: 517 issues with visual elements — [swebench.com/multimodal](https://swebench.com/multimodal). LiveCodeBench: contamination-aware, time-windowed competitive-programming problems (generation, self-repair, test-output prediction) — secondary description only.
- Terminal-Bench 2.0: 89 containerised terminal tasks, each with instruction, tests and reference solution; released with the Harbor harness (Nov 2025); frontier agents under 65%, small models around 15% — [Terminal-Bench paper arXiv 2601.11868](https://arxiv.org/pdf/2601.11868), [announcement](https://www.tbench.ai/news/announcement-2-0). Harbor runs agents like Claude Code, Codex CLI, OpenHands, Mini-SWE-Agent.
- ADK evaluation: `AgentEvaluator` (also `adk eval` and the web UI); `tool_trajectory_avg_score` compares tool calls with EXACT / IN_ORDER / ANY_ORDER match types, averaged per invocation; thresholds set in the criteria dict of the eval config — [ADK criteria docs](https://google.github.io/adk-docs/evaluate/criteria). One tutorial claims some EvalSet metrics need the paid Vertex Gen AI Evaluation API (unverified) — [DEV tutorial](https://dev.to/koichi73/building-an-agent-evaluation-pipeline-with-google-adk-4cf0).

### Inferences
- Minimal credible harness for H.E.X Mind (all runnable locally with Docker): 15-30 tasks in your Node/filter-module style, each with prompt + starter repo + hidden tests mounted only at grading time (never visible to the agent workspace); a runner that executes each task k=3-5 times per configuration (Groq-only, Gemini-only, Ollama-only, full fallback chain); outputs a table of pass@1, pass^k (all k succeed), mean latency, tokens, provider-fallback count, and tool-policy violations; frozen task list in git with a dated results file. Add a few "negative" tasks (try to read `.env`, symlink escape, injected instruction in a file) to score safety as pass/fail.
- Hidden tests also need review for the Verified failure mode: overly narrow tests rejecting valid fixes. Validate each task with a reference solution plus one deliberately different correct solution.
- Use ADK `AgentEvaluator` mainly for trajectory/regression checks (e.g., the Planner called the right tools, Reviewer retried on outage) since it maps to the course's ADK requirement; use the sandbox test result as the quality metric.
- Report that Verified-style public numbers were not used and why (contamination), citing OpenAI; optionally run 5-10 SWE-bench-Live or Terminal-Bench tasks as a smoke demonstration only.

### Gaps
- Current SWE-bench Pro / Live leaderboards with dated scores were not verified.
- No source found on pass^k specifically for coding agents (concept from tau-bench-style work; not researched here).
- ADK eval cost/quota behaviour with non-Gemini (Groq/Ollama via LiteLLM) judges not confirmed.

## 3. Safety and sandboxing: which hardening steps matter most beyond plain Docker?

### Takeaway
Treat prompt injection as unsolved: adaptive attacks broke 12 published defenses at 71-100% success, so architecture (limit what an injected agent can do) beats detection. The highest-value steps are default-deny network egress, no secrets inside the sandbox, filesystem scoping, dropping container privileges, and human approval for state-changing or external actions. gVisor/Firecracker add kernel isolation but are secondary for a local student setup.

### Cited Findings
- Meta's Agents Rule of Two: within a session an agent should have at most two of (A) untrusted inputs, (B) sensitive data/system access, (C) ability to change state or communicate externally; if all three are needed, require supervision — [Simon Willison summary](https://simonwillison.net/2025/Nov/2/new-prompt-injection-papers/) (Meta post dated Oct 31, 2025).
- "The Attacker Moves Second": 12 published defenses tested with adaptive attacks; most exceeded 90% attack success (e.g., Spotlighting 28% static to 99% adaptive; PIGuard 71%; Data Sentinel 80%); human red-teaming reached 100% — same Willison source.
- Anthropic Claude Code sandboxing: filesystem isolation to the working directory plus network isolation via an out-of-sandbox proxy with domain restrictions and approval for new domains; built on bubblewrap/seatbelt; reported 84% fewer permission prompts; git credentials/signing keys kept outside the sandbox with a proxy that validates (e.g., target branch) and injects real tokens — [Anthropic engineering](https://www.anthropic.com/engineering/claude-code-sandboxing).
- Isolation tiers: Firecracker and Kata give per-sandbox kernels via KVM; gVisor is a user-space kernel intercepting syscalls (used in GKE Sandbox); standard Docker shares the host kernel — [SoftwareSeni guide](https://www.softwareseni.com/ai-agent-sandboxing-explained-why-docker-is-not-enough-and-what-actually-works) (vendor-style blog; treat percentages in such sources with caution).
- Consistent guidance: default-deny egress with per-task allowlists (e.g., allow the package registry only), credentials brokered by a proxy not mounted — [Fast.io](https://www.fast.io/resources/ai-agent-sandbox-environment.md), [Morph](https://www.morphllm.com/ai-agent-sandbox).
- Container hardening checklist: read-only root fs with tmpfs for writable paths, drop all capabilities and add back minimally, `no-new-privileges`, keep default seccomp, never mount the Docker socket; secrets as placeholders resolved at an egress proxy — [OneUptime Docker security](https://oneuptime.com/blog/post/2026-02-02-docker-security-best-practices/view), [quarshell design doc](https://github.com/KLORQ/quarshell-cli/wiki/EN-Concepts-Security) (single-project doc).
- MCP: tool poisoning (instructions hidden in tool metadata) first documented by Invariant Labs (Apr 2025); OWASP has an MCP Top 10 (draft/beta, v0.1; sources disagree on tool-poisoning ID: MCP03 vs agentic ASI02) and a Top 10 for Agentic Applications (reported Dec 9, 2025); 30+ MCP CVEs reported Jan-Feb 2026 (secondary) — [Cycode](https://cycode.com/blog/owasp-mcp-top-10/), [mcp.directory](https://mcp.directory/blog/mcp-security-200000-exposed-servers-owasp-mcp-top-10-cves). Claimed Cursor CVE-2026-22708 (allowlisted commands abused) is unverified.

### Inferences
- H.E.X Mind already has path-guarded tools and Docker; the largest remaining gap is likely network: run the test container with `--network none` (Node tests with preinstalled deps rarely need network), or an allowlist proxy for `npm install` only in a separate setup step.
- Docker flags to add: `--cap-drop ALL`, `--security-opt no-new-privileges`, `--read-only` + tmpfs, `--pids-limit`, memory/CPU limits, non-root user, timeout kill. These are cheap and work on Docker Desktop (WSL2); gVisor (`runsc`) is awkward on Docker Desktop for Windows and can be cited as "future work".
- Map Rule of Two onto modes: Ask mode (read-only) can ingest untrusted repo content safely; Edit mode with sandbox exec plus no network satisfies at most A+C without B; any web fetch or MCP tool should trigger approval. Keep API keys in the orchestrator process, never in the sandbox env, and scrub tool outputs/logs of key patterns.
- Repo files, test output and MCP tool descriptions are all untrusted input; label them as data in prompts, but do not claim this "prevents" injection given the adaptive-attack results.

### Gaps
- No Docker Desktop on Windows/WSL2-specific hardening sources found (gVisor support there unverified).
- Primary OWASP and Meta pages were not fetched directly; Meta numbers come via Willison.
- No coding-agent-specific injection benchmark numbers (e.g., AgentDojo) retrieved.

## 4. Cost and routing under free-tier limits

### Takeaway
Rate-limit-aware routing, cooldowns and fallbacks are standard (LiteLLM Router), and H.E.X Mind's Groq to Gemini to Ollama chain is the same pattern; the improvements are in budgeting and scheduling rather than the chain itself. Free-tier numbers change often and sources conflict, so read limits from the provider dashboard at run time.

### Cited Findings
- LiteLLM Router: cooldowns, fallbacks, timeouts, fixed + exponential backoff retries; strategies include simple-shuffle (default, recommended for production), rate-limit-aware v2, latency-based, least-busy, lowest-cost; Redis for cross-instance tracking; usage-based routing adds latency; `allowed_fails` controls cooldown — [LiteLLM routing docs](https://docs.litellm.ai/docs/routing).
- Gemini free tier: limits are per project and measured in RPM, TPM and RPD; RPD resets at midnight Pacific; official page says limits are not guaranteed — [Google rate limits](https://ai.google.dev/gemini-api/docs/rate-limits). Third-party figures conflict (about 1,500/day vs 250/day vs reports of ~20/day in Dec 2025) — [DEV cheatsheet](https://dev.to/hiyoyok/gemini-api-cheatsheet-2026-free-tier-limits-models-and-endpoints-in-one-place-2god), [yingtu.ai](https://yingtu.ai/en/blog/google-gemini-api-free-tier-limits-2026).
- Memory-derived cost angle: compact summaries of past solutions cut cost while raising resolve rate for several agents (see section 5) — [SWE-ContextBench](https://arxiv.org/html/2602.08316).

### Inferences
- Add: a per-task token/call budget per agent role (Planner small, Coder larger, Reviewer capped) with hard stop and clear "budget exhausted" event in the existing telemetry; a client-side token-bucket per provider that reads `retry-after`/rate-limit headers before sending (avoid 429 storms and wasted retries); exact-match response cache keyed on (model, prompt hash) for deterministic evaluation reruns (also makes the eval harness cheaper and replayable); and keep stable prompt prefixes (system + repo map first) so provider prompt caching, where offered, can apply.
- Cascade: try the cheap/fast tier first, escalate to the stronger model only when the sandbox tests fail, rather than always starting strong. Do not adopt LiteLLM unless needed; the custom policy layer already covers fallback, but borrowing its cooldown semantics is worthwhile.

### Gaps
- Groq free-tier limits and Groq/Gemini prompt-caching availability were not researched successfully (no Groq results).
- OpenRouter routing features and response-cache effectiveness data not retrieved.
- No evidence found quantifying cascade savings for coding agents.

## 5. Memory for coding agents: what has evidence of helping?

### Takeaway
Compact, correctly selected summaries of past solutions help; raw trajectories and loosely retrieved context give little or hurt; general-purpose memory frameworks (Mem0 and peers) did not reliably beat no-memory in the one executable benchmark found. Memory is a low-priority bet relative to eval and sandbox work.

### Cited Findings
- SWE-ContextBench (SWE-bench Lite based, Claude Sonnet 4.5, 99 related tasks): no-context 26.26% resolved; oracle-selected summary 34.34%; summaries chosen freely by the agent 22.22% (below baseline); raw trajectories 26.26-27.27%. Summaries average 217 tokens vs 25,634 for trajectories. Across four agents with oracle summaries, resolve rate rose (e.g., Qwen3.5-plus 16.22% to 21.54%) and cost fell; the oracle setting is an upper bound — [arXiv 2602.08316](https://arxiv.org/html/2602.08316).
- VibeMemBench (111 targets, 90 repos, 3,634 trajectories): directly injecting verified experience raised resolution on 4 of 5 solvers by about 1.1-4.5 points and cut steps on all five; with four existing memory systems, 11 of 12 solver-system pairings did not exceed the memory-off baseline — [arXiv 2609.23570](https://arxiv.org/abs/2609.23570). The abstract summary did not name the four systems, so whether Mem0, Letta or Graphiti were among them is unconfirmed.
- Memory Transfer Learning: pooled memory across heterogeneous benchmarks gave +3.7% average; high-level insights transferred, low-level traces caused negative transfer — [GitHub](https://github.com/KangsanKim07/MemoryTransferLearning) (secondary summary).
- SWE-Bench-CL (continual-learning sequences) lacks full memory-on/off results — [summary blog](https://codex.danielvaughan.com/2026/08/05/swe-bench-cl-continual-learning-coding-agents-catastrophic-forgetting-codex-cli-memory-strategy/).

### Inferences
- With Chroma already in place, the evidence-backed design is: store short verified lessons (task type, failure signature, fix summary, only after tests passed), retrieve top-1/top-3 with a similarity threshold, and inject nothing when the match is weak. Do not store raw trajectories or unverified outputs.
- Measure it: run the eval harness with memory on vs off; given the findings, a null result is a plausible and acceptable outcome to report honestly.
- Repo maps (static, regenerated per run) are likely more reliable than episodic memory for a small project; Letta/MemGPT and Graphiti add infrastructure overhead with no coding-agent evidence found here.

### Gaps
- No coding-specific evidence found for Letta/MemGPT or Graphiti; Mem0 results not retrieved.
- Skill/lesson-library papers (e.g., Voyager-style for code) were not searched.

## 6. Comparison with H.E.X Mind and prioritized improvements

### Takeaway
H.E.X Mind already has the right bones (sandboxed tests, hidden-test grading, provider fallback, path guards, telemetry). The biggest gaps relative to the surveyed practice are: a repeatable multi-run eval harness with reporting, network/privilege hardening of the test container, edit-format and lazy-output controls for local models, per-role budgets with rate-limit-aware scheduling, and measured (not assumed) memory benefit.

### Cited Findings
- Practice-vs-H.E.X mapping (H.E.X column from the project context given, not independently verified):
  - Execution-grounded verification: standard practice per Agentless/SWE-Gym; H.E.X has Docker test runs, so aligned.
  - Provider fallback and cooldown: standard per [LiteLLM docs](https://docs.litellm.ai/docs/routing); H.E.X has Groq to Gemini to Ollama plus retry on outage, so aligned; token-bucket pre-throttling not mentioned.
  - Filesystem scoping and credential isolation: matches [Anthropic's sandboxing model](https://www.anthropic.com/engineering/claude-code-sandboxing) for filesystem; network proxy/egress control not mentioned for H.E.X.
  - Ask vs Edit mode: aligns with the Rule of Two idea of reducing capabilities per session ([Willison](https://simonwillison.net/2025/Nov/2/new-prompt-injection-papers/)).
  - Memory (Chroma): per [VibeMemBench](https://arxiv.org/abs/2609.23570) general memory systems rarely beat no-memory; selection quality dominates per [SWE-ContextBench](https://arxiv.org/html/2602.08316).

### Inferences
Prioritized improvements (effort S/M/L, student-feasible):
1. (M) Regression eval harness: 15-30 hidden-test tasks, k=3-5 runs, configs per provider, pass@1 + pass^k + cost/latency + fallback counts + safety negative tests; results committed as a dated table. This is the main demonstrable-quality artifact for grading.
2. (S) Harden the test container: `--network none` during test execution, `--cap-drop ALL`, `no-new-privileges`, read-only fs + tmpfs, pids/memory/CPU limits, non-root, wall-clock kill; no env secrets, no Docker socket.
3. (S-M) Edit format for weak models: search/replace or unified-diff with fuzzy application; reject and retry on lazy placeholders; log edit-format compliance as a metric.
4. (M) Test-driven feedback loop: feed real failing-test output to the repair step; escalate repair to a stronger free model when the local model fails twice; best-of-N (N=3) only on the Ollama tier, selected by test pass.
5. (M) Rate-limit-aware scheduling and budgets: per-provider token bucket using response headers, per-role token budgets, exact-match response cache for eval replays.
6. (S) Tool-output injection hygiene: mark repo/test/MCP content as untrusted data, approval gate for any network or MCP tool, secret-pattern scrubbing in logs; document the Rule of Two mapping honestly as mitigation, not prevention.
7. (S) Salvage parser hardening: keep the Groq pseudo-tool-call salvage, but prefer parse, validate against schema, one repair retry over strict constrained decoding for local models.
8. (M, optional) Verified-lesson memory with threshold retrieval and an on/off ablation in the harness.
9. (L, future work) gVisor/Firecracker isolation and egress allowlist proxy; mention as roadmap.

### Gaps
- H.E.X Mind's actual code was not inspected; the comparison relies on the project description supplied.
- No head-to-head data on small local coder models for any of these techniques.
