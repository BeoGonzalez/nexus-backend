"""Métricas del modelo de IA (OpenTelemetry): consumo de tokens, resultados, latencia, RAG y seguridad.

Se exportan por OTLP al Alloy del clúster y llegan a Mimir como (nombres Prometheus):
    nexus_llm_tokens_total{type="input|output", model}
    nexus_llm_requests_total{outcome="ok|fallback|timeout|leak_blocked", intent}
    nexus_llm_request_duration_seconds_bucket{outcome}
    nexus_llm_rag_results_bucket
    nexus_llm_quota_rejections_total{reason}
    nexus_llm_security_events_total{event}
    nexus_llm_external_calls_total{source="tavily|cheapshark|wikipedia", outcome="ok|empty|timeout|error"}
    nexus_llm_external_call_duration_seconds_bucket{source}

Atributos de cardinalidad acotada y SIN datos personales (nunca sub, email ni texto del prompt).
Sin MeterProvider configurado (desarrollo/tests) las llamadas son no-ops del API de OpenTelemetry.
"""

from __future__ import annotations

from opentelemetry import metrics as otel_metrics

_MAX_LABEL = 40

EXTERNAL_SOURCES = ("tavily", "cheapshark", "wikipedia")
EXTERNAL_OUTCOMES = ("ok", "empty", "timeout", "error")


def _label(value: str) -> str:
    return (value or "unknown")[:_MAX_LABEL]


class LLMMetrics:
    def __init__(self, meter_provider: otel_metrics.MeterProvider | None = None) -> None:
        meter = (meter_provider or otel_metrics.get_meter_provider()).get_meter("nexus.ai_agent")
        self._tokens = meter.create_counter("nexus_llm_tokens", unit="{token}", description="Tokens del proveedor LLM")
        self._requests = meter.create_counter("nexus_llm_requests", description="Peticiones al asistente por resultado")
        self._duration = meter.create_histogram("nexus_llm_request_duration", unit="s",
                                                description="Duración de una respuesta del asistente")
        self._rag = meter.create_histogram("nexus_llm_rag_results", description="Juegos recuperados del vector store")
        self._quota = meter.create_counter("nexus_llm_quota_rejections", description="Peticiones rechazadas por cuota")
        self._security = meter.create_counter("nexus_llm_security_events", description="Eventos de seguridad del LLM")
        self._external = meter.create_counter("nexus_llm_external_calls",
                                              description="Llamadas a APIs externas del asistente por resultado")
        self._external_duration = meter.create_histogram("nexus_llm_external_call_duration", unit="s",
                                                         description="Duración de una llamada a una API externa")
        # Cada serie arranca en 0: si naciera con el primer valor, rate()/increase() no verían esa primera llamada.
        for source in EXTERNAL_SOURCES:
            for outcome in EXTERNAL_OUTCOMES:
                self._external.add(0, {"source": source, "outcome": outcome})

    def tokens(self, *, input_tokens: int, output_tokens: int, model: str) -> None:
        if input_tokens > 0:
            self._tokens.add(int(input_tokens), {"type": "input", "model": _label(model)})
        if output_tokens > 0:
            self._tokens.add(int(output_tokens), {"type": "output", "model": _label(model)})

    def request(self, *, outcome: str, intent: str, seconds: float) -> None:
        self._requests.add(1, {"outcome": _label(outcome), "intent": _label(intent)})
        self._duration.record(max(0.0, seconds), {"outcome": _label(outcome)})

    def rag_results(self, count: int) -> None:
        self._rag.record(max(0, int(count)))

    def quota_rejected(self, reason: str) -> None:
        self._quota.add(1, {"reason": _label(reason)})

    def security_event(self, event: str) -> None:
        self._security.add(1, {"event": _label(event)})

    def external_call(self, *, source: str, outcome: str, seconds: float) -> None:
        """Resultado de una llamada a Tavily, CheapShark o Wikipedia (ok | empty | timeout | error)."""
        self._external.add(1, {"source": _label(source), "outcome": _label(outcome)})
        self._external_duration.record(max(0.0, seconds), {"source": _label(source)})


_DEFAULT: LLMMetrics | None = None


def default_metrics() -> LLMMetrics:
    """Instancia del proceso sobre el MeterProvider global (lo configura setup_telemetry)."""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = LLMMetrics()
    return _DEFAULT
