"""OpenTelemetry (trazas + métricas) hacia el OpenTelemetry Collector del clúster (Tempo/Prometheus).

Se activa solo si `OTEL_EXPORTER_OTLP_ENDPOINT` está definido; sin él no hace nada (desarrollo, tests).
El resto de la configuración usa las variables estándar `OTEL_*` (protocolo, headers, sampler, recursos).
"""

import logging
import os

from fastapi import FastAPI

logger = logging.getLogger(__name__)

_EXCLUDED_URLS = r".*/health$,.*/metrics$"


def setup_telemetry(app: FastAPI, service_name: str) -> bool:
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if not endpoint:
        return False

    from opentelemetry import metrics, trace
    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create(
        {
            "service.name": os.getenv("OTEL_SERVICE_NAME", service_name),
            "service.namespace": "nexus",
            "deployment.environment": os.getenv("SERVICE_ENV", "local"),
        }
    )
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(tracer_provider)

    meter_provider = MeterProvider(resource=resource, metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter())])
    metrics.set_meter_provider(meter_provider)

    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        excluded_urls=_EXCLUDED_URLS,
    )
    logger.info("OpenTelemetry activo: exportando por OTLP a %s", endpoint)
    return True
