from fastapi import FastAPI

from nexus_core.infrastructure.telemetry import setup_telemetry


def test_without_otlp_endpoint_telemetry_is_a_noop(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    app = FastAPI()
    assert setup_telemetry(app, "svc") is False
    assert not getattr(app, "_is_instrumented_by_opentelemetry", False)


def test_with_otlp_endpoint_the_app_is_instrumented(monkeypatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector.observability:4317")
    app = FastAPI()
    assert setup_telemetry(app, "svc") is True
    assert getattr(app, "_is_instrumented_by_opentelemetry", False) is True
