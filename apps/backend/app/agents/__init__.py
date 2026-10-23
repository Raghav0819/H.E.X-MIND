import os

# CrewAI sends anonymous telemetry and writes state under the user's profile by default. Turn
# telemetry off and keep its storage inside our data directory. Must run before crewai imports.
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
