"""ADK spike: McpToolset over stdio + OpenTelemetry spans from ADK's built-in tracing."""
import asyncio, os, sys, warnings
from collections import Counter
warnings.filterwarnings("ignore")
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

exporter = InMemorySpanExporter()
provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(exporter))
trace.set_tracer_provider(provider)

from google.adk.agents import LlmAgent
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from google.genai import types
from mcp import StdioServerParameters

fired = Counter()
class ScriptedLlm(BaseLlm):
    model: str = "scripted"
    async def generate_content_async(self, llm_request, stream=False):
        tools = sorted(llm_request.tools_dict or {})
        fired["tools_offered:" + ",".join(tools)] += 1
        done = any(p.function_response for c in llm_request.contents for p in (c.parts or []))
        part = (types.Part(text="Status checked.") if done else
                types.Part(function_call=types.FunctionCall(id="c1", name="git_status", args={})))
        yield LlmResponse(content=types.Content(role="model", parts=[part]))

def before_tool(tool, args, tool_context):
    fired[f"before_tool:{tool.name}"] += 1
def after_tool(tool, args, tool_context, tool_response):
    fired[f"after_tool:{tool.name}={str(tool_response)[:40]}"] += 1

toolset = McpToolset(connection_params=StdioConnectionParams(
    server_params=StdioServerParameters(command=sys.executable, args=[os.path.abspath("mini_mcp.py")]),
    timeout=30))
agent = LlmAgent(name="coder", model=ScriptedLlm(), instruction="Check git.", tools=[toolset],
                 before_tool_callback=before_tool, after_tool_callback=after_tool)

async def main():
    sessions = InMemorySessionService()
    runner = Runner(agent=agent, app_name="spike", session_service=sessions)
    s = await sessions.create_session(app_name="spike", user_id="u")
    async for _ in runner.run_async(user_id="u", session_id=s.id,
            new_message=types.Content(role="user", parts=[types.Part(text="status?")])):
        pass
    await toolset.close()
    print("events:", dict(fired))
    spans = exporter.get_finished_spans()
    by_id = {s.context.span_id: s for s in spans}
    print("spans (child <- parent):")
    for sp in spans:
        parent = by_id.get(sp.parent.span_id).name if sp.parent and sp.parent.span_id in by_id else "-"
        keys = [k for k in sp.attributes if k.startswith(("gen_ai", "gcp", "adk"))][:6]
        print(f"  {sp.name:<34} <- {parent:<30} attrs={keys}")
    print("one trace:", len({sp.context.trace_id for sp in spans}) == 1)

asyncio.run(main())
