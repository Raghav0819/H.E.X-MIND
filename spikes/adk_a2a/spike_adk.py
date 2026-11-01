"""ADK spike: custom BaseLlm (stand-in for ProviderRouter), tools, workflow agents,
Pydantic output_schema, and all callbacks."""
import asyncio, json, os, warnings
from collections import Counter
warnings.filterwarnings("ignore")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

from google.adk.agents import LlmAgent, LoopAgent, SequentialAgent
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import FunctionTool
from google.genai import types
from pydantic import BaseModel

fired = Counter()
seen_requests = []

class Verdict(BaseModel):
    verdict: str
    findings: int

class ScriptedLlm(BaseLlm):
    """Plays a coder (tool call, then text) and a reviewer (JSON)."""
    model: str = "hexmind-scripted"
    async def generate_content_async(self, llm_request, stream=False):
        tools = list(llm_request.tools_dict) if getattr(llm_request, "tools_dict", None) else []
        has_tool_result = any(p.function_response for c in llm_request.contents for p in (c.parts or []))
        sys = (llm_request.config.system_instruction or "") if llm_request.config else ""
        seen_requests.append({"tools": tools, "has_tool_result": has_tool_result,
                              "schema": bool(llm_request.config and llm_request.config.response_schema),
                              "sys_start": str(sys)[:40]})
        if "write_file" in tools and not has_tool_result:
            part = types.Part(function_call=types.FunctionCall(id="call_1", name="write_file",
                                                                args={"path": "src/a.js", "content": "x"}))
        elif "write_file" in tools:
            part = types.Part(text="Implemented src/a.js.")
        else:
            part = types.Part(text=json.dumps({"verdict": "approved", "findings": 0}))
        yield LlmResponse(content=types.Content(role="model", parts=[part]),
                          usage_metadata=types.GenerateContentResponseUsageMetadata(
                              prompt_token_count=10, candidates_token_count=5, total_token_count=15))

written = {}
def write_file(path: str, content: str) -> str:
    """Create or overwrite a file."""
    written[path] = content
    return f"created {path}"

def cb(name):
    def f(*args, **kwargs):
        fired[name] += 1
        return None
    return f

callbacks = {k: cb(k) for k in ("before_agent_callback", "after_agent_callback", "before_model_callback",
                                 "after_model_callback", "before_tool_callback", "after_tool_callback")}
llm = ScriptedLlm()
coder = LlmAgent(name="coder", model=llm, instruction="You are the Coder.", tools=[FunctionTool(write_file)],
                 output_key="coder_summary", **callbacks)
reviewer = LlmAgent(name="reviewer", model=llm, instruction="You are the Reviewer. Reply with JSON.",
                    output_schema=Verdict, output_key="review", **callbacks)
loop = LoopAgent(name="code_review_loop", sub_agents=[coder, reviewer], max_iterations=2)
run = SequentialAgent(name="run", sub_agents=[loop])

async def main():
    sessions = InMemorySessionService()
    runner = Runner(agent=run, app_name="hexmind-spike", session_service=sessions)
    session = await sessions.create_session(app_name="hexmind-spike", user_id="u1")
    authors = []
    async for event in runner.run_async(user_id="u1", session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part(text="Create src/a.js")])):
        authors.append(event.author)
    final = await sessions.get_session(app_name="hexmind-spike", user_id="u1", session_id=session.id)
    print("event authors:", authors)
    print("state keys:", sorted(final.state))
    print("review in state:", final.state.get("review"), type(final.state.get("review")).__name__)
    print("tool executed:", written)
    print("callbacks fired:", dict(fired))
    print("model requests:", seen_requests)

asyncio.run(main())
