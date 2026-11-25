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


# ------------------------------------------------------------------ Pyroscope (profiling continuo)
import sys
import types

from nexus_core.infrastructure.telemetry import setup_profiling


class FakePyroscope(types.ModuleType):
    def __init__(self):
        super().__init__("pyroscope")
        self.calls = []

    def configure(self, **kwargs):
        self.calls.append(kwargs)


def test_without_pyroscope_address_profiling_is_a_noop(monkeypatch):
    monkeypatch.delenv("PYROSCOPE_SERVER_ADDRESS", raising=False)
    fake = FakePyroscope()
    monkeypatch.setitem(sys.modules, "pyroscope", fake)
    assert setup_profiling("svc") is False
    assert fake.calls == []


def test_with_pyroscope_address_profiles_are_pushed_to_the_collector(monkeypatch):
    monkeypatch.setenv("PYROSCOPE_SERVER_ADDRESS", "http://alloy.observability:4040")
    monkeypatch.setenv("SERVICE_ENV", "aws")
    fake = FakePyroscope()
    monkeypatch.setitem(sys.modules, "pyroscope", fake)
    assert setup_profiling("catalog-service") is True
    [call] = fake.calls
    assert call["application_name"] == "nexus.catalog-service"
    assert call["server_address"] == "http://alloy.observability:4040"
    assert call["tags"] == {"service_namespace": "nexus", "environment": "aws"}
    # Sin credenciales en el pod: el token de Grafana Cloud vive solo en Alloy.
    assert "basic_auth_password" not in call and "auth_token" not in call


def test_profiling_never_breaks_startup_when_the_sdk_is_missing(monkeypatch):
    monkeypatch.setenv("PYROSCOPE_SERVER_ADDRESS", "http://alloy.observability:4040")
    monkeypatch.setitem(sys.modules, "pyroscope", None)  # import pyroscope -> ImportError
    assert setup_profiling("svc") is False
