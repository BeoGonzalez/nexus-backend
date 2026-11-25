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


def setup_profiling(service_name: str) -> bool:
    """Profiling continuo (CPU) con Pyroscope, hacia el Alloy del clúster (`pyroscope.receive_http`).

    Se activa solo si `PYROSCOPE_SERVER_ADDRESS` está definido. El pod no lleva credenciales de Grafana Cloud:
    Alloy las añade al reenviar. Un fallo aquí nunca impide arrancar el servicio.
    """
    address = os.getenv("PYROSCOPE_SERVER_ADDRESS", "").strip()
    if not address:
        return False
    try:
        import pyroscope

        pyroscope.configure(
            application_name=f"nexus.{os.getenv('OTEL_SERVICE_NAME', service_name)}",
            server_address=address,
            sample_rate=100,
            tags={"service_namespace": "nexus", "environment": os.getenv("SERVICE_ENV", "local")},
        )
    except Exception as exc:  # SDK no disponible (p. ej. Windows) o colector inaccesible
        logger.warning("Pyroscope no disponible: %s", type(exc).__name__)
        return False
    logger.info("Pyroscope activo: perfiles hacia %s", address)
    return True
