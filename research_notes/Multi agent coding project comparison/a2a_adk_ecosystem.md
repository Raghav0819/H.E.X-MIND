# A2A protocol and Google ADK ecosystem (as of 2026-11-02) vs H.E.X Mind

Research basis: ~17 web calls; mostly primary docs (a2a-protocol.org, adk.dev, GitHub release pages, aaif.io). Where only secondary sources exist this is flagged. I did not read H.E.X Mind source; its description is taken from the assignment.

## 1. Current state of the A2A spec, SDKs and governance

### Takeaway
A2A reached a stable 1.0 spec in March 2026 and the Python SDK is at 1.3.0 (2026-10-27). H.E.X Mind's a2a-sdk 0.3.x is the previous generation: it still works through ADK's compatibility mode and the SDK's 0.3 compat layer, but graders reading 2026 docs will expect 1.0 vocabulary (SendMessage, supportedInterfaces, TASK_STATE_*). A2A is now hosted under the Agentic AI Foundation (AAIF), itself under the Linux Foundation.

### Cited Findings
- Spec: latest released version 1.0.0; previous 0.3.0, 0.2.6, 0.1.0. Version is identified as Major.Minor; clients send the `A2A-Version` header and an empty value is read as 0.3. — [A2A spec](https://a2a-protocol.org/latest/specification/)
- v1.0 is "the first stable specification", shipped March 2026; added multi-protocol bindings, version negotiation, multi-tenancy, signed agent cards. — [AAIF, 2026-08-17](https://aaif.io/blog/a2a-joins-aaif). A secondary source dates 1.0 to 12 March 2026 and mentions a v1.0.1 patch in May 2026 (unverified) — [search summary](https://a2a-protocol.org/latest/whats-new-v1/)
- v0.3 to v1.0 breaking changes: enums become `TASK_STATE_*` / `ROLE_*`; `kind` discriminator removed (events identified by wrapper `statusUpdate`/`artifactUpdate`); Part types merged into one `Part` with `text|raw|url|data`, `mimeType` -> `mediaType`; `final` flag removed from status updates (stream close signals completion); `AgentCard.url/preferredTransport/additionalInterfaces` replaced by `supportedInterfaces[]` with per-interface protocolVersion; `supportsAuthenticatedExtendedCard` -> `capabilities.extendedAgentCard`; `tasks/resubscribe` -> `SubscribeToTask`; `message/send` -> `SendMessage`, `message/stream` -> `SendStreamingMessage`; new `ListTasks` with cursor pagination; `tenant` field added; `/v1` prefix removed from REST; errors use google.rpc.Status; implicit and password OAuth flows removed; DeviceCode flow and `pkceRequired` added; `A2A-Version` and `A2A-Extensions` headers added. — [What's new in v1](https://a2a-protocol.org/latest/whats-new-v1/)
- Card well-known path is `/.well-known/agent-card.json` (changed from agent.json in 0.3, July 2025). — [AAIF migration guide](https://aaif.io/blog/a2a-v1-0-a-builder-s-guide-part-2-migration-security-and-production)
- Task states (1.0): UNSPECIFIED, SUBMITTED, WORKING, INPUT_REQUIRED, AUTH_REQUIRED (interrupted); COMPLETED, FAILED, CANCELED, REJECTED (terminal). — [spec](https://a2a-protocol.org/latest/specification/)
- AgentCard required fields: name, description, supportedInterfaces, version, capabilities, defaultInputModes, defaultOutputModes, skills. Optional: provider, documentationUrl, securitySchemes, securityRequirements, signatures, iconUrl. Capabilities (all optional): streaming, pushNotifications, extensions, extendedAgentCard. Skill required: id, name, description, tags; optional examples, inputModes, outputModes, securityRequirements. — [spec 4.4](https://a2a-protocol.org/latest/specification/)
- Security schemes listed: APIKey, HTTPAuth (bearer/basic), OAuth2 (AuthorizationCode, ClientCredentials, DeviceCode), OpenIdConnect, MutualTls. — [spec](https://a2a-protocol.org/latest/specification/)
- Signed cards: JWS (RFC 7515) over JCS-canonicalized (RFC 8785) card excluding `signatures`; signature object has `protected` + `signature` (+ optional `header`); protected header MUST include `alg`, `kid`, SHOULD `typ: JOSE`, MAY `jku`. — [spec 8.4](https://a2a-protocol.org/latest/specification/), [What's new](https://a2a-protocol.org/latest/whats-new-v1/)
- Bindings: JSON-RPC, gRPC, HTTP+JSON/REST (custom allowed); all must be functionally equivalent; `a2a.proto` is normative. SSE: HTTP 200 `text/event-stream` for SendStreamingMessage, `POST /message:stream`, SubscribeToTask. — [spec](https://a2a-protocol.org/latest/specification/)
- Streaming requires `capabilities.streaming=true` else UnsupportedOperationError; StreamResponse holds exactly one of task/message/statusUpdate/artifactUpdate; ordered delivery; multiple concurrent streams allowed; SubscribeToTask sends current Task first. Artifact update events carry `append` and `lastChunk`. — [spec](https://a2a-protocol.org/latest/specification/)
- Push notifications: Create/Get/List/Delete TaskPushNotificationConfig; need `capabilities.pushNotifications`; webhooks are plain HTTP JSON; delivery is at-least-once, use per-config tokens and idempotent handlers. — [spec](https://a2a-protocol.org/latest/specification/), [AAIF guide](https://aaif.io/blog/a2a-v1-0-a-builder-s-guide-part-2-migration-security-and-production)
- Extensions: requested via `A2A-Extensions` header; AgentExtension has a `required` flag; server returns ExtensionSupportRequiredError if a required extension is unsupported; messages and artifacts carry `extensions[]`. — [spec](https://a2a-protocol.org/latest/specification/)
- CancelTask: attempt, success not guaranteed, returns updated Task; errors TaskNotCancelableError / TaskNotFoundError; idempotent. — [spec](https://a2a-protocol.org/latest/specification/)
- Python SDK a2a-python: v1.3.0 (2026-10-27) latest; 1.2.0 (2026-09-29) served REST as `application/a2a+json`, card caching headers, cluster mode; 1.1.4 (2026-09-07) push-URL SSRF validation and owner-scoped cancel/subscribe; 1.2.x: operations on terminal tasks return UnsupportedOperationError and mismatched contextId is rejected; v0.3 compat retained. — [a2a-python releases](https://github.com/a2aproject/a2a-python/releases)
- SDK restructure in 1.x: Pydantic types replaced by protobuf-generated classes; `a2a.server.apps` replaced by `a2a.server.routes` route factories mounted in your own Starlette/FastAPI app; `ClientFactory` -> `await create_client(...)`; compat via `a2a.compat.v0_3`; in-memory task store is sample-only, use SQL stores plus DB push-config store. — [AAIF guide](https://aaif.io/blog/a2a-v1-0-a-builder-s-guide-part-2-migration-security-and-production), [bedrock-agentcore issue](https://github.com/aws/bedrock-agentcore-sdk-python/issues/509) (secondary)
- Six language SDKs; JS SDK reached 1.0 GA on 2026-07-22 (spec froze ~4 months earlier), so mixed-version fleets occur. — [AAIF guide](https://aaif.io/blog/a2a-v1-0-a-builder-s-guide-part-2-migration-security-and-production); [a2a-js v1.0.0](https://github.com/a2aproject/a2a-js/releases/tag/v1.0.0)
- Governance: Google launched A2A April 2025 and donated it to the Linux Foundation (founding: AWS, Cisco, Google, Microsoft, Salesforce, SAP, ServiceNow); IBM's ACP merged Aug 2025; on 2026-08-17 A2A joined AAIF (LF-hosted); Technical Steering Committee with public meetings; 150+ supporting orgs. — [AAIF](https://aaif.io/blog/a2a-joins-aaif); [Linux Foundation one-year release, Apr 2026](https://www.linuxfoundation.org/press/a2a-protocol-surpasses-150-organizations-lands-in-major-cloud-platforms-and-sees-enterprise-production-use-in-first-year)
- A2A vs MCP: MCP = agent-to-tool/data; A2A = agent-to-agent discovery, delegation, results; framed as layers, not competitors. — [AAIF](https://aaif.io/blog/a2a-joins-aaif)
- Skeptical view: real cross-vendor production is thinner than headlines; most production is single-vendor. — [Glukhov analysis](https://www.glukhov.org/ai-systems/comparisons/a2a-protocol-2026-adoption/) (blog, secondary)

### Inferences
- Mandatory in practice: an Agent Card with the 8 required fields at the well-known path, SendMessage/GetTask/CancelTask on at least one binding, task lifecycle states, Message/Task/Artifact/Part model. Streaming, push, extensions, extended card and signatures are optional capability flags.
- A grader checking "correct use of A2A" will most likely look for: valid card, skills, honestly declared capabilities, task-state handling (including failed/input-required), artifacts for outputs, auth declared in the card (securitySchemes matching bearer auth), and trace/context propagation. H.E.X Mind covers card, auth, failed state and metadata; weaker (to verify) on artifacts, streaming, securitySchemes declaration.
- Staying on 0.3.x is defensible (ADK supports it) but should be documented as a deliberate choice, or the crew service migrated to 1.x.

### Gaps
- Exact v1.0 release date from the spec itself (only secondary: 12 March 2026) and whether v1.0.1 exists.
- Spec sections 9-12 (binding details) and the last ~56k characters of the spec were not read.
- AAIF says Google donated to LF in April 2025; the LF donation is commonly dated June 2025 (not verified here). AAIF governance rule details not found.

## 2. Reference implementations: streaming, long-running, cancel, input-required

### Takeaway
The spec defines the mechanics (same taskId continues an input-required task; SubscribeToTask re-attaches; push for very long jobs; CancelTask best effort) and the SDK adds parked-interrupted-task handling. I found no primary documentation of how ADK itself handles input-required, so that is a gap.

### Cited Findings
- Multi-turn: on INPUT_REQUIRED the client sends a new message with the same `taskId` to continue. — [spec 6.3](https://a2a-protocol.org/latest/specification/)
- a2a-python 1.3.0 added a configurable timeout for releasing "parked" interrupted tasks; 1.2.2 added SSE shutdown grace periods; 1.1.2 added `aclose()` to drain ActiveTask background tasks. — [a2a-python releases](https://github.com/a2aproject/a2a-python/releases)
- AUTH_REQUIRED guidance: credentials should travel out of band, not through the agent chain; the state itself grants no permission. Handlers should not distinguish "task does not exist" from "not yours". — [AAIF guide](https://aaif.io/blog/a2a-v1-0-a-builder-s-guide-part-2-migration-security-and-production)
- ADK A2A extension (`use_legacy=False`, ADK Python >= 1.27.0) fixes three streaming defects in the legacy executor: message duplication in task history, remote ADK output misclassified as thoughts, data loss with nested sub-agents. Travels in `X-A2A-Extensions`, advertised in `AgentCapabilities.extensions` with `required: false`. — [ADK A2A extension](https://adk.dev/a2a/a2a-extension/)
- A2A Inspector continues conversations and tasks waiting for input across messages. — [a2a-inspector](https://github.com/a2aproject/a2a-inspector)

### Inferences
- A visible strength would be one input-required round trip (Planner asks a clarifying question, UI shows it, resume on same taskId).
- Map the UI cancel to CancelTask and display the resulting state, since success is not guaranteed.

### Gaps
- How ADK RemoteA2aAgent maps INPUT_REQUIRED / AUTH_REQUIRED to ADK events (adk.dev pages do not cover it; read ADK source `a2a_agent_executor_impl.py`).
- Whether CrewAI samples in a2a-samples demonstrate input-required (not checked).

## 3. A2A Inspector vs H.E.X Mind's A2A explorer

### Takeaway
The Inspector adds spec validation, v1.0/v0.3 detection, raw wire-traffic view, raw message sending, task and push-config management and a webhook receiver. H.E.X Mind's explorer (cards + two-lane run timelines) is run-centric, which the Inspector is not.

### Cited Findings
- Inspector: fetches card, detects v1.0 vs v0.3, lists interfaces, validates against spec; chat with text/files/data/metadata or raw message; send or stream; shows every HTTP/gRPC exchange on the wire and validates each response; bearer/basic/API-key presets with secrets kept in backend; manages tasks and push configs, receives push at its own webhook; JSON-RPC, HTTP+JSON, gRPC. — [a2a-inspector](https://github.com/a2aproject/a2a-inspector)
- A2A TCK checks MUST/SHOULD/MAY conformance across three transports (only a Gitee fork seen; upstream a2aproject/a2a-tck is authoritative). — [fork](https://gitee.com/hy_song/a2a-tck)
- a2a-samples ships a CLI for card read and chat (per Google Cloud docs). — [Cloud Run A2A verify](https://cloud.google.com/run/docs/verify-deployment-a2a-agents)
- adk web: chat, sessions, state view/edit, event history, execution trace viewer, event log, agent graph, eval set creation, Visual Builder (Python). — [adk web docs](https://adk.dev/runtime/web-interface/) (trace details not described on page)

### Inferences
- Explorer gaps vs Inspector: card validation panel, raw JSON-RPC payload view, task list/get/cancel controls, probe message, push-config view. Vs adk web: per-event trace tree/graph, state inspection, eval creation from a session.

### Gaps
- Inspector support for card signature verification not confirmed.

## 4. ADK feature set, samples and version differences

### Takeaway
ADK reached 2.0 (Python GA 2026-05-19; Go 2026-06-30; TypeScript 2026-08-21) with a graph Workflow Runtime and event-schema changes; Python was at 2.12.0 (2026-10-13) per search. H.E.X Mind should state which line it pins.

### Cited Findings
- ADK 2.0: Workflow Runtime (graph, dynamic, collaborative), `RetryConfig`, human-in-the-loop pauses; breaking: new Event fields (`node_info`, `output`), agents subclass `BaseNode`, do not append events to session directly, do not catch broad exceptions in tools (breaks retries/HITL); 1.x pin `~=1.0`. — [ADK 2.0](https://adk.dev/2.0/index.md)
- Releases: 2.6.0 (2026-07-29), 2.12.0 (2026-10-13; `adk run --state_file`, workflow approvals, Python 3.15). Listings are inconsistent (a 1.39.0 dated 2026-08-17 also appears), so verify. — [adk-python releases](https://github.com/google/adk-python/releases)
- ADK A2A is marked experimental; Python, Go, Java supported (consuming also Kotlin). RemoteA2aAgent takes name + agent_card (object, URL or file path). ADK supports a2a-sdk 0.3.x (compat mode) and 1.x, auto-detected; new integrations should target 1.x. — [ADK A2A](https://adk.dev/a2a/), [consuming quickstart](https://adk.dev/a2a/quickstart-consuming/)
- Eval: `*.test.json` and `*.evalset.json`; criteria `tool_trajectory_avg_score`, `response_match_score`, `final_response_match_v2`, rubric-based, `hallucinations_v1`, `safety_v1`, multi-turn criteria; user simulation; run via adk web Eval tab, `adk eval`, pytest `AgentEvaluator.evaluate`, and `adk conformance record/replay`. Some judges need Vertex Gen AI Evaluation Service. — [ADK evaluate](https://adk.dev/evaluate/)
- MCP Toolbox for Databases: `pip install google-adk[toolbox]`, `ToolboxToolset`; covers AlloyDB, BigQuery, Cloud SQL, Spanner, Firestore, Postgres, MySQL etc. — [ADK toolbox docs](https://adk.dev/integrations/mcp-toolbox-for-databases)
- Agent Engine: managed runtime for ADK/LangChain/LangGraph/CrewAI; A2A on Agent Engine was in preview in an older post (needs a2a-sdk >= 0.3.4); a secondary source claims renaming to "Agent Runtime" (unverified). — [Google dev post](https://discuss.google.dev/t/building-bridges-deploy-agents-with-a2a-on-vertex-ai-agent-engine/264044), [codelab](https://codelabs.developers.google.com/codelabs/create-multi-agents-adk-a2a)
- Samples: a2aproject/a2a-samples has python, go, dotnet, java dirs; Python samples include LangGraph, CrewAI and ADK agents (expense reimbursement, birthday planner); Java includes an MCP-integrated weather agent. A Google Next 26 codelab covers CrewAI + LangGraph + A2A + ADK together, directly relevant to our stack. — [a2a-samples](https://docsearch.algolia.com/mcp/docs/repo/a2aproject/a2a-samples), [codelab](https://codelabs.developers.google.com/next26/scale-agents?hl=es-419)

### Inferences
- With ADK 1.x + a2a-sdk 0.3: `use_legacy` defaults True so the streaming fixes are off unless enabled; ADK picks behaviour from the installed sdk version. Upgrading to ADK 2.0 changes the Event schema (node_info/output), which could affect TelemetryHub event schema v2 and any custom session storage.
- ADK eval sets with tool_trajectory scoring and `adk conformance` replay are cheap, gradeable wins; reference-based metrics cost no LLM calls (relevant to free-tier limits), LLM-judged ones do.

### Gaps
- adk-samples repo contents not fetched; adk web trace tab specifics; verified ADK Python version history; Agent Engine current GA status for A2A.

## 5. Discovery, registries, marketplaces, notable projects

### Takeaway
The spec only requires well-known URL discovery; registries and marketplaces are third-party. Real-world use is dominated by vendor platforms.

### Cited Findings
- Agents publish (signed) cards at a well-known URL, no central registry required; third-party registries exist (e.g. OpenAgora, not part of AAIF). — [AAIF](https://aaif.io/blog/a2a-joins-aaif), [OpenAgora listing](https://www.producthunt.com/products/agora-14/launches/openagora) (weak source)
- Community lists: awesome-a2a, a2a-directory; card auditors (A2Apex on PyPI, an Apify actor). — [awesome-a2a](https://github.com/ai-boost/awesome-a2a), [a2a-directory](https://github.com/sing1ee/a2a-directory)
- Adopters named by AAIF: Google Cloud, Microsoft Azure AI Foundry, AWS Bedrock AgentCore, Huawei, Tencent WeChat, PayPal; LF cites production in supply chain, finance, insurance, IT operations. — [AAIF](https://aaif.io/blog/a2a-joins-aaif), [LF](https://www.linuxfoundation.org/press/a2a-protocol-surpasses-150-organizations-lands-in-major-cloud-platforms-and-sees-enterprise-production-use-in-first-year)
- Signed-card threats: shadowing and context poisoning via card descriptions; treat unsigned cards as untrusted. — [AAIF guide](https://aaif.io/blog/a2a-v1-0-a-builder-s-guide-part-2-migration-security-and-production)

### Gaps
- No notable open-source multi-agent coding project using A2A was verified; no registry with confirmed traction beyond listings.

## 6. Comparison and recommended additions for H.E.X Mind

### Takeaway
Present (per assignment): ADK orchestrator + RemoteA2aAgent, separate crew process, per-crew cards, bearer auth, metadata with traceparent, failed-task handling, A2A explorer. The items below are likely missing and would strengthen "correct A2A use".

### Inferences (grounded in findings above; repo not inspected, so verify each is truly absent)
1. Declare `securitySchemes`/`securityRequirements` in each card matching the bearer auth.
2. Streaming: set `capabilities.streaming=true`, emit status/artifact updates from crews, render live in the two-lane timeline.
3. Artifacts: return Coder diff/patch and Planner plan as Artifacts (artifactId, parts, `append`/`lastChunk` for chunks) rather than only text.
4. input-required HITL: Planner asks a clarifying question; resume on same taskId; surface in UI.
5. CancelTask wired to UI cancel; GetTask/ListTasks views in the explorer.
6. Declare a custom A2A extension (URI in `capabilities.extensions`) for hexmind trace/worktree metadata instead of ad hoc metadata; consider ADK `use_legacy=False` (ADK >= 1.27).
7. Signed Agent Cards (JWS + JCS) verified by the orchestrator (a2a-python docs mention a card-signing sample, v1.2.0).
8. Explorer upgrades: card validation panel, raw payload view, version detection, push-config view; mention A2A Inspector.
9. ADK eval sets (`adk eval`, pytest) for orchestrator trajectory, `adk conformance`; run the A2A TCK against the crew service.
10. Version decision: document 0.3 vs 1.x; upgrading means protobuf types, route-factory server API, `kind` removal, uppercase enums, `supportedInterfaces`.
11. Durability: SQL task store and push-config store in the crew service instead of in-memory.

### Gaps
- H.E.X Mind code not inspected.
