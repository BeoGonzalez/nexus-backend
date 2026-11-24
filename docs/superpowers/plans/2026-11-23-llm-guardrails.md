# Guardrails LLM (OWASP LLM 2026) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Controles deterministas alrededor de NexusBot que cubren LLM01–LLM10 de 2026.

**Architecture:** Paquete `ai_agent_service/security/` (funciones puras + guardias con estado) cableado en
`dtos.py`, `presentation/router.py`, `application/services.py` y `application/graph.py`.

**Tech Stack:** FastAPI, Pydantic v2, LangGraph MemorySaver, pytest/httpx.

**Spec:** `docs/superpowers/specs/2026-11-23-llm-guardrails-owasp-llm-2026-design.md`

## Global Constraints

- Tests con `.venv/Scripts/python.exe -m pytest`; ningún proveedor real (fixture `forbid_real_providers`).
- El frontend existente no debe romperse: historial largo se **recorta**, no se rechaza; `session_id` del frontend
  (`session-<ms>-<7 chars>`) es válido.
- Sin commits.

## Review Focus

1. Un secreto partido entre dos chunks del stream (`gsk_ab` + `cd…`) no debe escapar: ventana retenida. Test Task 3.
2. Delimitador falsificado `</untrusted_data>` dentro de una noticia de Tavily no debe cerrar el bloque. Test Task 1.
3. El mismo `session_id` en dos usuarios no comparte memoria. Test Task 5.
4. Cliente que abre 2 streams a la vez: el segundo recibe 429 y el primero termina. Test Task 4.
5. Texto con caracteres tag-block invisibles que deletrean una orden se normaliza antes del LLM. Test Task 1.

---

### Task 1: `security/sanitize.py` — `sanitize_text`, `neutralize_special_tokens`, `wrap_untrusted`, `detect_injection`, `mask_pii`
### Task 2: `security/prompt.py` — `build_system_prompt() -> str`, `CANARY`; reglas declarativas
### Task 3: `security/output_guard.py` — `StreamingOutputGuard(feed/finish, leaked)`, `redact_secrets`
### Task 4: `security/governor.py` — `UsageGovernor` (rpm, día, concurrencia, global), kill switch
### Task 5: `security/memory.py` — `thread_id_for(sub, session_id)`, `BoundedMemory` (expulsión), saneo de escrituras
### Task 6: `security/tool_policy.py` — `EmailToolPolicy.authorize(user, requested)`; grafo usa solo email verificado
### Task 7: `security/grounding.py` — `ungrounded_amounts(text, allowed)`
### Task 8: DTO + router + servicio: límites, identidad, degradación, cableado de guardias; LLM adapter timeouts; modelos fijados
### Task 9: tests de ataque end-to-end (`tests/api/test_ai_attacks.py`) + suite completa en verde
