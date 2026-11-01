"""A2A spike: a CrewAI crew served over A2A (a2a-sdk 0.3), called by an ADK RemoteA2aAgent,
with trace context carried in A2A message metadata."""
import asyncio, os, threading, time, warnings
warnings.filterwarnings("ignore")
for k, v in {"CREWAI_DISABLE_TELEMETRY": "true", "CREWAI_TRACING_ENABLED": "false",
             "OTEL_SDK_DISABLED": "true"}.items():
    os.environ.setdefault(k, v)

import httpx, uvicorn
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.apps import A2AStarletteApplication
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from a2a.utils import new_agent_text_message
from crewai import Agent, Crew, Process, Task
from crewai.llms.base_llm import BaseLLM
from google.adk.agents import SequentialAgent
from google.adk.agents.remote_a2a_agent import RemoteA2aAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

PORT = 8811
received = {}

class ScriptedCrewLLM(BaseLLM):
    def call(self, messages, tools=None, callbacks=None, available_functions=None,
             from_task=None, from_agent=None, response_model=None):
        return "Thought: done\nFinal Answer: PLAN: 1) add filterTodos in src/filter.js 2) add tests"
    def supports_function_calling(self): return False

planner = Agent(role="Planner", goal="Plan small tasks", backstory="test",
                llm=ScriptedCrewLLM(model="scripted"), allow_delegation=False, verbose=False)

class CrewExecutor(AgentExecutor):
    """Runs the CrewAI crew for each A2A message."""
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        request = context.get_user_input()
        received["request"] = request
        received["metadata"] = dict(context.message.metadata or {}) if context.message else {}
        received["request_metadata"] = dict(getattr(context, "metadata", None) or {})
        task = Task(description=f"Plan this request: {request}", expected_output="A plan", agent=planner)
        result = await Crew(agents=[planner], tasks=[task], process=Process.sequential,
                            memory=False, verbose=False).kickoff_async()
        await event_queue.enqueue_event(new_agent_text_message(result.raw))
    async def cancel(self, context, event_queue) -> None:
        raise NotImplementedError

card = AgentCard(
    name="planner_crew", description="CrewAI Planner crew served over A2A",
    url=f"http://127.0.0.1:{PORT}/", version="0.1.0",
    capabilities=AgentCapabilities(streaming=False),
    default_input_modes=["text/plain"], default_output_modes=["text/plain"],
    skills=[AgentSkill(id="plan", name="Plan", description="Break a request into tasks", tags=["planning"])],
)
app = A2AStarletteApplication(
    agent_card=card,
    http_handler=DefaultRequestHandler(agent_executor=CrewExecutor(), task_store=InMemoryTaskStore()),
).build()

server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning"))
threading.Thread(target=server.run, daemon=True).start()
for _ in range(50):
    try:
        if httpx.get(f"http://127.0.0.1:{PORT}/.well-known/agent-card.json").status_code == 200: break
    except httpx.HTTPError:
        time.sleep(0.2)
print("agent card served:", httpx.get(f"http://127.0.0.1:{PORT}/.well-known/agent-card.json").json()["name"])

TRACEPARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
remote = RemoteA2aAgent(
    name="planner_crew",
    agent_card=f"http://127.0.0.1:{PORT}/.well-known/agent-card.json",
    description="Remote CrewAI planner",
    a2a_request_meta_provider=lambda ctx, msg: {"traceparent": TRACEPARENT, "hexmind_run_id": "run-123"},
)
root = SequentialAgent(name="orchestrator", sub_agents=[remote])

async def main():
    sessions = InMemorySessionService()
    runner = Runner(agent=root, app_name="spike", session_service=sessions)
    session = await sessions.create_session(app_name="spike", user_id="u")
    replies = []
    async for event in runner.run_async(user_id="u", session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part(text="Create src/filter.js")])):
        for part in (event.content.parts if event.content else []):
            if part.text: replies.append((event.author, part.text))
    print("ADK received:", replies)
    print("CrewAI server received request:", received.get("request"))
    print("CrewAI server received metadata:", received.get("metadata"))
    print("CrewAI server request-level metadata:", received.get("request_metadata"))

asyncio.run(main())
server.should_exit = True
