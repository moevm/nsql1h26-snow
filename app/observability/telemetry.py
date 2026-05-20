from __future__ import annotations

import logging

from fastapi import FastAPI

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

def setup_telemetry(app: FastAPI) -> None:
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource

        resource = Resource.create({"service.name": settings.otel_service_name})
        provider = TracerProvider(resource=resource)

        exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        FastAPIInstrumentor.instrument_app(app)
        logger.info("OpenTelemetry instrumentation active → %s", settings.otel_exporter_otlp_endpoint)

    except Exception as exc:
        logger.warning("OTEL setup skipped (install opentelemetry packages): %s", exc)
