"""OpenTelemetry setup. ADK creates its own spans (agent, model and tool calls) on the global
tracer provider; the TelemetryHub adds our attributes to them and opens spans for CrewAI crews.

P1 exports only when `HEXMIND_OTLP_ENDPOINT` is set (e.g. a local collector). P5 adds the
collector + Jaeger to Docker Compose and the `trace_spans` table.
"""

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.config import Settings

_provider: TracerProvider | None = None


def setup_tracing(settings: Settings) -> TracerProvider:
    """Install the global tracer provider once per process (OTel allows a single one)."""
    global _provider
    if _provider is None:
        current = trace.get_tracer_provider()
        if isinstance(current, TracerProvider):  # already set, e.g. by tests
            _provider = current
        else:
            _provider = TracerProvider(resource=Resource.create({"service.name": "hexmind"}))
            trace.set_tracer_provider(_provider)
        if settings.otlp_endpoint:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otlp_endpoint))
            )
    return _provider


def add_span_processor(processor: SpanProcessor) -> None:
    provider = trace.get_tracer_provider()
    if isinstance(provider, TracerProvider):
        provider.add_span_processor(processor)
