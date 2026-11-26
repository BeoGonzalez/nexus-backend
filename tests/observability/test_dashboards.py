"""Los dashboards de Grafana (observability/dashboards) nunca muestran "No data" sin explicar por qué.

- Contadores y tasas: `or vector(0)`. Si no hubo eventos, lo correcto es 0, no un panel vacío.
- Percentiles y paneles sin valor posible: `noValue` con la causa (sin solicitudes, clúster apagado...).
- Variables con valores fijos: un servicio sin tráfico (orders, notifications) sigue apareciendo.
- Un mismo nombre de servicio en todas las señales (aceptando el prefijo antiguo "nexus." en perfiles).
"""

import json
import re
from pathlib import Path

import pytest

DASHBOARDS = sorted((Path(__file__).parents[2] / "observability" / "dashboards").glob("*.json"))
SERVICES = ["auth-service", "catalog-service", "cart-service", "orders-service", "notifications-service",
            "recommendations-service", "ai-agent-service"]
EXPECTED_TITLES = {
    "nexus-overview": "Nexus · 0 · Visión general",
    "nexus-frontend": "Nexus · 1 · Sitio web (Next.js + navegador)",
    "nexus-backend": "Nexus · 2 · Microservicios (FastAPI en EKS)",
    "nexus-ai-model": "Nexus · 3 · Nexus Bot (modelo de IA)",
}
COUNTER = re.compile(r"\b(rate|increase|count_over_time|irate)\s*\(")
QUANTILE = re.compile(r"\b(histogram_quantile|quantile_over_time|topk)\s*\(")


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def panels(dashboard):
    def walk(ps):
        for p in ps:
            yield from walk(p.get("panels") or [])
            if p.get("type") not in ("row", "text"):
                yield p
    return list(walk(dashboard["panels"]))


def exprs(panel):
    for t in panel.get("targets") or []:
        e = t.get("expr") if "expr" in t else None
        if isinstance(e, str) and e.strip():
            yield e


@pytest.fixture(params=DASHBOARDS, ids=lambda p: p.stem)
def dashboard(request):
    return load(request.param)


def test_the_four_dashboards_exist_with_numbered_names():
    titles = {load(p)["uid"]: load(p)["title"] for p in DASHBOARDS}
    assert titles == EXPECTED_TITLES


def test_every_panel_explains_an_empty_result(dashboard):
    missing = [p["title"] for p in panels(dashboard) if not (p.get("fieldConfig", {}).get("defaults", {}).get("noValue"))]
    assert missing == []


def is_ratio(panel):
    return panel.get("fieldConfig", {}).get("defaults", {}).get("unit") in ("percentunit", "percent")


def test_counters_and_rates_fall_back_to_zero(dashboard):
    bad = [(p["title"], e) for p in panels(dashboard) for e in exprs(p)
           if COUNTER.search(e) and not QUANTILE.search(e) and not is_ratio(p) and "or vector(0)" not in e]
    assert bad == []


def test_ratios_never_show_0_percent_when_there_was_no_traffic(dashboard):
    """Un % sin llamadas no es 0 % (en rojo): solo el numerador cae a 0; sin denominador se ve el texto explicativo."""
    for p in panels(dashboard):
        if is_ratio(p):
            for e in exprs(p):
                assert not e.rstrip().endswith("or vector(0)"), (p["title"], e[-80:])
                if " / clamp_min(" in e:
                    # numerador "or total * 0": conserva las etiquetas (p. ej. by (job)), a diferencia de vector(0)
                    assert ") * 0) / clamp_min(" in e, (p["title"], "el numerador debe caer a total * 0")


def test_backend_service_variable_lists_all_seven_services_even_without_traffic():
    backend = load(next(p for p in DASHBOARDS if p.stem == "nexus-backend"))
    var = next(v for v in backend["templating"]["list"] if v["name"] == "service")
    assert var["type"] == "custom"
    assert [o["value"] for o in var["options"]] == ["$__all", *SERVICES]


def test_frontend_faro_app_is_fixed_to_the_app_name_sent_by_the_browser():
    frontend = load(next(p for p in DASHBOARDS if p.stem == "nexus-frontend"))
    var = next(v for v in frontend["templating"]["list"] if v["name"] == "faro_app")
    assert var["type"] == "custom" and var["query"] == "nexus-frontend"


def test_profile_selectors_accept_the_unified_service_names(dashboard):
    for p in panels(dashboard):
        for t in p.get("targets") or []:
            selector = t.get("labelSelector")
            if selector:
                # Acepta "auth-service" y el antiguo "nexus.auth-service"; [.] evita escapes inválidos para Pyroscope.
                assert "\\" not in selector, (p["title"], selector)
                if "nexus" in selector and "nexus-frontend" not in selector.replace("(nexus[.])?", ""):
                    assert "(nexus[.])?" in selector, (p["title"], selector)


def test_dashboards_link_to_each_other(dashboard):
    assert any(link.get("tags") == ["nexus"] for link in dashboard.get("links", []))


FIXED_WINDOW = re.compile(r"\[(5m|15m)\]")


def test_windows_follow_the_time_picker_instead_of_fixed_5m(dashboard):
    """Con [5m] fijo, en "Last 7 days" Grafana muestrea cada ~25 min y la serie queda vacía aunque haya datos."""
    bad = [(p["title"], e) for p in panels(dashboard) for e in exprs(p) if FIXED_WINDOW.search(e)]
    assert bad == []


def test_summary_stats_cover_the_whole_selected_range(dashboard):
    for p in panels(dashboard):
        for t in p.get("targets") or []:
            e = t.get("expr") or ""
            # Los paneles que declaran su ventana en el título ("1 h", "hoy") la mantienen fija a propósito.
            if t.get("instant") and COUNTER.search(e) and not re.search(r"1 h\)|24 h\)|\bhoy\b", p["title"]):
                assert "$__range" in e, (p["title"], e)


def test_traceql_metrics_panels_stay_within_the_25h_limit_of_grafana_cloud(dashboard):
    """Las métricas TraceQL (| rate(), quantile_over_time) fallan con rangos > 25 h ("exceeds the maximum")."""
    for p in panels(dashboard):
        traceql_metrics = any(
            t.get("queryType") == "traceql" and re.search(r"\|\s*(rate|quantile_over_time|count_over_time)\(", t.get("query", ""))
            for t in p.get("targets") or [])
        if traceql_metrics:
            assert p.get("timeFrom") == "24h" and "24 h" in p["title"], p["title"]


LLM_COUNTER = re.compile(r"\b(rate|increase)\((nexus_llm_\w+)")


def test_llm_counters_also_count_series_born_inside_the_window(dashboard):
    """Un contador de OpenTelemetry nace con el valor del primer chat (no en 0) y cada reinicio del pod crea una
    serie nueva: rate()/increase() solos no lo ven y el Nexus Bot quedaba en 0 aunque hubiera chats."""
    bad = [(p["title"], e) for p in panels(dashboard) for e in exprs(p)
           if LLM_COUNTER.search(e) and "unless on(" not in e]
    assert bad == []


def test_assistant_log_panel_shows_every_chat_not_only_warnings():
    ai = load(next(p for p in DASHBOARDS if p.stem == "nexus-ai-model"))
    logs = [p for p in panels(ai) if p["type"] == "logs" and p["title"].startswith("Eventos del asistente")]
    assert logs and all("llm" in t["expr"] for p in logs for t in p["targets"])


def test_logql_regex_filters_use_backticks_to_avoid_invalid_escapes(dashboard):
    """`|~ "llm\."` es un escape inválido en LogQL ("invalid char escape"); con backticks no hace falta escapar."""
    for p in panels(dashboard):
        for e in exprs(p):
            assert not re.search(r'\|~\s*"[^"]*\[.]', e), (p["title"], e)


def test_timeseries_add_the_birth_value_instead_of_choosing_it_with_or(dashboard):
    """`rate(x) or nacimiento` falla si el pod ya exportó 2 muestras iguales: rate() da 0 y gana el `or`.
    Hay que sumar ambos: (rate + nacimiento) or rate or nacimiento."""
    for p in panels(dashboard):
        for e in exprs(p):
            chosen = e.count("$__rate_interval]) or ((nexus_llm")
            added = e.count("$__rate_interval]) + ((nexus_llm")
            assert chosen <= added, (p["title"], e[:160])


def test_nexus_bot_dashboard_shows_whether_each_external_api_works():
    """Tavily, CheapShark y Wikipedia fallaban en silencio (DEBUG): ahora cada una tiene su tasa de éxito y latencia."""
    ai = load(next(p for p in DASHBOARDS if p.stem == "nexus-ai-model"))
    rows = [p["title"] for p in ai["panels"] if p["type"] == "row"]
    assert "APIs externas (Tavily, CheapShark, Wikipedia)" in rows
    assert rows.index("APIs externas (Tavily, CheapShark, Wikipedia)") == rows.index("Seguridad y cuotas") + 1
    exprs_all = [e for p in panels(ai) for e in exprs(p)]
    for source in ("tavily", "cheapshark", "wikipedia"):
        assert any(f'source="{source}"' in e and "nexus_llm_external_calls_total" in e for e in exprs_all), source
    assert any("nexus_llm_external_call_duration_seconds_bucket" in e for e in exprs_all)
    ys = [(p["gridPos"]["y"], p["gridPos"]["x"]) for p in ai["panels"]]
    assert len(ys) == len(set(ys)), "dos paneles en la misma posición"
