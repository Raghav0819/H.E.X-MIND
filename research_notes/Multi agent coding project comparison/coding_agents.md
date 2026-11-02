# State-of-the-art autonomous coding agents vs H.E.X Mind

Research date: 2026-11-02. Sources were fetched or searched this session. Many search-engine summaries are secondary; anything not from an official repo/doc is flagged. Coverage is uneven: OpenHands, mini-SWE-agent/SWE-agent, Aider, Cline, Claude Code (sandbox), Jules and Agentless are covered by primary pages. Devin, Roo Code, Windsurf and Cursor internals are thin (see Gaps).

## 1. Edit formats / tools: what is most reliable with weaker models?

### Takeaway
Search/replace ("diff") blocks are the default for strong models. Weaker, local or quantized models more often break format rules, so Aider falls back to whole-file output and offers architect/editor splits. The reliability-vs-token-cost tradeoff is the central design choice. Bash-only agents sidestep edit formats entirely.

### Cited Findings
- Aider formats: whole (full file; simplest, slow/costly), diff (search/replace blocks, efficient), diff-fenced (path inside fence; mainly for Gemini, which often fails standard fencing), udiff (simplified unified diff; made for GPT-4 Turbo to cut "lazy" placeholder code), editor-diff/editor-whole (for architect mode's editor model). Aider picks a default per model; override with `--edit-format`. — [Aider edit formats](https://aider.chat/docs/more/edit-formats.html)
- Aider's own write-up claims udiff reduced GPT-4 Turbo laziness 3x (2023-24 era, older) — [Aider via search summary](https://aider.chat/docs/more/edit-formats.html)
- Architect mode: an architect model solves the task in plain text; a separate editor model turns it into correctly formatted edits. — [Aider edit formats](https://aider.chat/docs/more/edit-formats.html), [Aider architect post (2024-09-26)](https://aider.chat/2024/09/26/architect.html)
- Aider polyglot leaderboard (225 Exercism exercises, 6 languages), snapshot with entries dated up to 2025-08: gpt-5 (high) 88.0% (diff, $29.08); o3-pro 84.9%; Gemini 2.5 Pro preview 06-05 (32k think) 83.1% with diff-fenced; o3(high)+gpt-4.1 architect 78.2%. "Percent well-formed" ranged ~88% to 100% among top models, i.e. format failures are non-trivial even for frontier models. — [Aider leaderboards](https://aider.chat/docs/leaderboards/)
- Aider troubleshooting guidance: weaker, local and quantized models are more prone to ignoring formatting instructions; recommended fix is `--edit-format whole` and/or architect mode; local (Ollama) context window must be set correctly. — secondary summary of Aider docs, [developersdigest](https://www.developersdigest.tech/errors/aider/llm-did-not-conform-to-edit-format); unverified against primary page
- mini-SWE-agent uses bash as its only tool (no tool-calling interface), each action is an independent `subprocess.run`, history is a linear message list. Scores >74% on SWE-bench Verified per README (undated). — [mini-SWE-agent](https://github.com/SWE-agent/mini-swe-agent)
- SWE-agent's thesis: LMs are a new kind of end user needing a purpose-built Agent-Computer Interface (ACI) for editing, navigation and test running; original result 12.5% pass@1 on SWE-bench (2024). The abstract does not give ACI specifics; commonly cited ACI features (linter-gated edits, windowed file viewer, concise search output) are from my background knowledge, not verified this session. — [SWE-agent paper](https://arxiv.org/abs/2405.15793)
- Agentless: no agent loop; three fixed phases (localization, repair, patch validation); 32.00% on SWE-bench Lite at $0.70/issue (2024). — [Agentless](https://arxiv.org/abs/2407.01489)

### Inferences
- For Groq/Gemini free tiers and Ollama fallback, a per-model edit-format table (diff-fenced for Gemini, whole-file for small local models, diff for Llama-70B-class) is directly supported by Aider's practice.
- Fixed-pipeline approaches (Agentless-style) suit weak models because the model never has to choose actions; H.E.X Mind's Planner->Coder->Reviewer is already closer to this than to a free-form loop.
- Applying edits with a deterministic applier plus fuzzy matching and returning precise error text to the model is likely more valuable than prompt tweaks (inference from Aider's well-formed-rate data).

### Gaps
- No primary data on SWE-agent's linter-gated edit ablation numbers (abstract only fetched).
- Did not verify Aider's fuzzy-matching fallback details or current edit-format defaults for Llama/Qwen.

## 2. Context handling (repo map, condensation, retrieval, long runs)

### Takeaway
Aider uses a graph-ranked repo map under a small token budget; OpenHands uses an LLM-summarizing condenser over an event log; Cursor relies on embedding-based semantic search; mini-SWE-agent keeps everything linear and simple.

### Cited Findings
- Aider repo map: compact map of files and key symbols; graph ranking (files as nodes, dependency edges) selects what fits; `--map-tokens` default 1k, dynamically resized. (The page does not mention tree-sitter/PageRank by name; those come from Aider's other docs/background knowledge.) — [Aider repomap](https://aider.chat/docs/repomap.html)
- OpenHands `LLMSummarizingCondenser`: triggers when events exceed `max_size` (default 120), shrinks to ~60, keeps first `keep_first` (default 4) events verbatim plus recent tail, summarizes the middle with a dedicated (often cheaper) LLM, records a `Condensation` event listing `forgotten_event_ids`; also triggered on context-window errors. — [OpenHands condenser docs](https://docs.openhands.dev/sdk/arch/condenser)
- Cursor: reports semantic search gives 12.5% higher agent accuracy; Composer (Oct 29 2025) trained with RL using semantic search, editors, terminal. Secondary summary. — [search summary of Cursor blog](https://www.morphllm.com/cursor-agent-mode)
- Jules and Cursor read repo instruction files (Jules: `AGENTS.md`). — [Jules docs](https://jules.google/docs)
- Claude Code: subagents have separate context windows (secondary). — [implicator.ai summary](https://www.implicator.ai/claude-codes-quiet-power-play-tooling-not-trophies/)

### Inferences
- H.E.X Mind's Chroma blackboard is retrieval over agent outputs; adding a ranked repo map (symbols + references, ~1-2k tokens) given to Planner and Coder would cut exploration tokens, valuable under free-tier limits.
- An OpenHands-style condenser (keep head + tail, cheap-model summary of the middle) with a hard cap fits small-context local models.

### Gaps
- Claude Code auto-compact internals: no authoritative source found.
- Cursor's indexing design and Devin/Windsurf context engines: only secondary blog coverage.

## 3. Sandboxing, runtime and event-stream design

### Takeaway
OpenHands' event-sourced action/observation log with swappable workspaces (local/Docker/remote) and a mini-SWE-agent-style "one process per action, swap for docker exec" are the two designs closest to H.E.X Mind's Docker sandbox. Claude Code uses OS-level sandboxing (bubblewrap/Seatbelt) plus a network proxy allowlist.

### Cited Findings
- OpenHands SDK (arXiv 2511.03690, MLSys 2026): redesign of V0; event-sourced state, stateless components with immutable config; native sandboxed execution; local->remote execution; REST and WebSocket services; built-in security analysis. V1 reported to substantially reduce system-attributable failures vs V0 with negligible event-sourcing overhead. — [arXiv](https://arxiv.org/abs/2511.03690), [MLSys](https://mlsys.org/virtual/2026/oral/3749)
- Workspaces: LocalWorkspace, DockerWorkspace (container running an agent server), RemoteAPIWorkspace; agent code unchanged across them. Agent server is FastAPI with REST/WebSocket for conversations, bash, files, events. Typed events: actions, observations, user messages, state updates. Security: action risk assessment before execution. — [OpenHands SDK architecture](https://docs.openhands.dev/sdk/arch/overview)
- A secondary report says OpenHands V0 was deprecated April 2026 — [GitHub issue](https://github.com/NousResearch/hermes-agent/issues/477); unverified.
- mini-SWE-agent: independent `subprocess.run` per action; sandbox by swapping to `docker exec`; supports Docker/Podman, Singularity, Bubblewrap. — [mini-SWE-agent](https://github.com/SWE-agent/mini-swe-agent)
- Claude Code sandbox: OS-enforced, built on open-source `@anthropic-ai/sandbox-runtime` (Seatbelt on macOS; bubblewrap + socat on Linux/WSL2); off by default; native Windows unsandboxed. Writes limited to working dir/temp; protected paths (.git/hooks, .gitconfig, shell rc, settings) denied even inside; network via a proxy with domain allow/deny lists; credentials can be denied or masked; built-in Edit/Read tools run outside the sandbox under permission rules; sandboxed commands can auto-allow without prompts. — [Claude Code sandboxing docs](https://code.claude.com/docs/en/sandboxing)
- Jules: each task in an isolated Google Cloud VM that clones the repo, installs deps (setup script optional), edits and runs tests, then opens a PR. — [Jules docs](https://jules.google/docs), [gocodeo](https://www.gocodeo.com/post/jules-inside-googles-asynchronous-coding-agent) (secondary)

### Inferences
- H.E.X Mind already has a Telemetry hub and A2A events; formalizing them as an append-only, typed event log (action/observation/condensation/user-approval) from which agent views are derived would give replay, resume after crash, and deterministic debugging in the UI.
- Network policy is a cheap win: run the node:22-alpine container with network disabled during test runs, or a domain allowlist (npm registry) during install only.
- Protect `.git/hooks` and config inside the worktree mount (read-only) as Claude Code does.

### Gaps
- Did not read the OpenHands paper body for event-stream schema and numbers.
- Devin's sandbox model: no primary source found.

## 4. Approval, undo and checkpoint UX

### Takeaway
Best-practice is: plan approval before edits (Jules, Cursor Plan Mode), per-step snapshot checkpoints independent of the user's git (Cline shadow git, Claude Code rewind, Cursor), auto-approve inside a sandbox boundary.

### Cited Findings
- Cline: shadow Git repo separate from project history; snapshot after each tool use; includes untracked files; persists across sessions; Compare opens diff view; restore options: Files, Task only, or both; pairs with auto-approve. — [Cline checkpoints](https://docs.cline.bot/features/checkpoints)
- Claude Code: automatic checkpoint before each change; Esc-Esc or `/rewind` restores code, conversation, or both; covers Claude's edits not bash commands; kept 30 days by default. Announced Sept 2025. — [Anthropic announcement](https://www.anthropic.com/news/enabling-claude-code-to-work-more-autonomously), [checkpointing docs](https://code.claude.com/docs/de/checkpointing)
- Claude Code "auto mode": a separate classifier model reviews each action (research preview; secondary source). — [implicator.ai](https://www.implicator.ai/claude-codes-quiet-power-play-tooling-not-trophies/)
- Jules: generates a plan and waits for user approval before any code change; notifies when input needed. — [Jules docs](https://jules.google/docs)
- Cursor Plan Mode produces an editable markdown plan; checkpoints separate from git (secondary). — [morphllm](https://www.morphllm.com/cursor-agent-mode)

### Inferences
- Because each H.E.X Mind run already edits a git worktree, per-step commits on the worktree branch give Cline-style restore points nearly free; expose "restore to step N" in the Observability UI.
- A plan-approval gate after the Planner crew (editable plan, then Coder) matches Jules/Cursor and cuts wasted free-tier calls on bad plans.

### Gaps
- Roo Code modes/approval specifics and Windsurf Cascade approval UX not retrieved.

## 5. Strategies for cheap, small and local models

### Takeaway
Evidence favors constrained workflows, simple formats, architect/editor splits, cheap-model summarization, and tight verification loops over free-form autonomy.

### Cited Findings
- Aider architect/editor split and whole-format fallback (see section 1). — [Aider](https://aider.chat/docs/more/edit-formats.html)
- Agentless: $0.70 per issue with fixed pipeline. — [arXiv](https://arxiv.org/abs/2407.01489)
- OpenHands condenser uses a cheaper dedicated model for summaries; SDK advertises multi-LLM routing. — [condenser](https://docs.openhands.dev/sdk/arch/condenser), [arXiv](https://arxiv.org/abs/2511.03690)
- mini-SWE-agent via LiteLLM/OpenRouter/Portkey, linear history. — [repo](https://github.com/SWE-agent/mini-swe-agent)
- Cursor trained its own RL model (Composer) and Cognition built SWE-1.5 / SWE-grep for speed (secondary, naming conflicts between sources: Windsurf reported renamed "Devin Desktop"; SWE-1.5 claimed 13x faster than Sonnet 4.5). — [apidog](https://apidog.com/blog/whats-new-in-devin-2026/), [nxcode](https://www.nxcode.io/fr/resources/news/cognition-windsurf-acquisition-swe-1-5-codemaps-2026) (unverified marketing-adjacent)

### Inferences
- Route by role: strong/long-context model (Gemini) for Planner, fast Groq model for Coder with diff edits, cheapest for summarization/condensation; on Ollama fall back to whole-file edits on small files.
- Cap loop iterations and token spend per run; use test output (not model self-judgment) as the primary success signal.

### Gaps
- No primary data on small-model (<14B) SWE-bench performance.

## 6. Benchmarks (with dates and caveats)

### Takeaway
Numbers are harness- and date-dependent and the search results disagree; treat as indicative. Verified is being called saturated/contaminated by some sources.

### Cited Findings
- mini-SWE-agent: >74% SWE-bench Verified (README; README banner credits Gemini 3 Pro at 74%; undated). Earlier third-party listing: 65% with Claude Sonnet 4. — [repo](https://github.com/SWE-agent/mini-swe-agent)
- Bash-only third-party boards (Vals.ai ~2026-09-01, Steel updated 2026-09-04) list Claude Opus 5 at 97.0%, DeepSeek V4 Pro 96.4%, GPT-5.6 Sol 96.2% on Verified with mini-swe-agent. I could not fetch these pages directly; figures come from a search summary and look unusually high, so treat as unverified. Same source says mini-SWE-agent 1.x and 2.x results are not comparable (2.x uses tool calls) and OpenAI dropped Verified in favour of SWE-bench Pro. — [Vals.ai](https://www.vals.ai/benchmarks/swebench), [Steel](https://leaderboard.steel.dev/leaderboards/swe-bench-verified/)
- OpenHands SDK paper (secondary podcast-style summary): Sonnet 4.5 72.8%, Sonnet 4 68.0%, GPT-5 (high) 68.8%; a GitHub issue cites 77.6% in OpenHands' own harness. Conflicting/unverified. — [search summary](https://arxiv.org/abs/2511.03690v1), [issue](https://github.com/NousResearch/hermes-agent/issues/477)
- SWE-agent original: 12.5% on full SWE-bench (2024). Agentless: 32.0% on Lite (2024). — [SWE-agent](https://arxiv.org/abs/2405.15793), [Agentless](https://arxiv.org/abs/2407.01489)
- Devin: 13.86% at launch on a 25% random SWE-bench subset (2024); a "45.8% Verified" figure appears in one aggregator, unverified. — [komo.ai / search summaries](https://komo.ai/directory/cognition)
- Jules: MIT AI Agent Index lists 52.2% on Verified (Gemini 2.x era); no Google-published Jules breakdown found. An 80.8% figure on the same comparison page belongs to a different (Claude Opus 4.6) tool. — [MIT AI Agent Index](https://aiagentindex.mit.edu/jules), [morphllm](https://www.morphllm.com/comparisons/jules-google-coding-agent)
- Cursor Composer 2.5: 79.8% on SWE-bench Multilingual (not Verified; Cursor-reported via aggregator). Release timeline conflicts across sources. — [apidog](https://apidog.com/blog/whats-new-in-devin-2026/), [howaiworks](https://howaiworks.ai/models/composer)
- Aider polyglot: see section 1 (latest entries seen: Aug 2025).
- No Claude Code, Cline, Roo Code official SWE-bench Verified numbers found.

### Inferences
- H.E.X Mind should not chase SWE-bench; a small custom suite (10-20 Node.js repo tasks run via the Docker sandbox) and Aider-style tracking of pass rate, well-formed-edit rate and cost per run is more informative for its setting.

### Gaps
- Official leaderboard pages (swebench.com) did not render scores; all 2026 numbers are secondary.

## 7. Concrete differences from H.E.X Mind and features to adopt

### Takeaway
H.E.X Mind is unusually strong on multi-agent topology, A2A interop and observability, but lacks the mature single-agent mechanics (edit formats, repo map, condensation, checkpoints, plan approval) that most reliability gains come from.

### Cited Findings
- Differences (each system, from sections above): OpenHands/mini-SWE-agent/Aider/Cline/Claude Code are essentially single-agent loops (Claude Code adds subagents with separate contexts); H.E.X Mind uses a role pipeline with A2A. Agentless shows pipelines without agent loops can be cost-effective. — [Agentless](https://arxiv.org/abs/2407.01489), [OpenHands docs](https://docs.openhands.dev/sdk/arch/overview)

### Inferences (prioritized adoption list for student scale)
1. Edit format layer: search/replace blocks with fuzzy match and error feedback; per-model format table (diff, diff-fenced for Gemini, whole for tiny models). Highest ROI.
2. Per-step checkpointing: commit every Coder step to the worktree branch; "restore to step" and diff view in UI (Cline model).
3. Plan approval gate between Planner and Coder (Jules/Cursor); optional auto-approve inside sandbox (Claude Code model).
4. Aider-style ranked repo map as a Planner/Coder input, ~1k tokens, regenerated per run.
5. OpenHands-style condenser (keep head+tail, cheap-model summary of middle, event with forgotten ids) for long Coder/Reviewer loops and for Ollama's small windows.
6. Typed append-only event log as the single source for the observability UI (OpenHands event-sourcing), enabling replay.
7. Sandbox hardening: network off or allowlisted during tests, read-only protected paths, resource/time limits; one-process-per-command via `docker exec` (mini-SWE-agent).
8. Verification loop: Reviewer should rely on real test/lint/typecheck output; bounded retries then escalate model (Groq -> Gemini) rather than loop.
9. Repo instruction file support (`AGENTS.md`) read by Planner.
10. Own mini benchmark and cost/format-failure metrics in the UI.
Skip: enterprise security analyzers, cloud VM-per-task (Jules-like) until P8, RL model training.

### Gaps
- Not reviewed H.E.X Mind source code in this task; the "differences" assume the architecture as described in the brief.
- Roo Code (modes, custom modes), Windsurf Cascade, Devin Wiki/Search/Playbooks, and Claude Code auto-compact were not covered by primary sources; recommend a follow-up fetch of docs.roocode.com, docs.devin.ai, docs.windsurf.com and Anthropic engineering posts.
