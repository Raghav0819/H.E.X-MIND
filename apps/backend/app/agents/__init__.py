import os

# CrewAI sends anonymous telemetry and writes state under the user's profile by default. Turn
# its telemetry off and keep its storage inside our data directory. Must run before crewai
# imports. OpenTelemetry itself stays enabled: our own traces (app.telemetry) depend on it.
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")
