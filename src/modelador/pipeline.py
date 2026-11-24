"""Orquestación de los flujos de diseño relacional."""

import time
from copy import copy
from datetime import datetime, timezone
from functools import partial

from .adapters import default_client
from .adapters.base import LLMError
from .agents import (
    analyst,
    coder_agent,
    dictionary_agent,
    name_tables,
    single_agent,
    validate_coder,
    validate_dictionary,
    validate_single_response,
)
from .core import ModelError, audit_model, parse_fds, synthesize_3nf
from .sql import render_ddl


def _agent(client, trace, role, system, prompt, schema):
    start = time.perf_counter()
    entry = {"agent": role, "status": "running"}
    trace.append(entry)
    if getattr(client, "progress", None):
        client.progress({"event": "started", "agent": role})
    try:
        answer, usage = client.ask(system, prompt, schema=schema)
    except BaseException as exc:
        entry.update({"status": "cancelled" if isinstance(exc, KeyboardInterrupt) else "error", "seconds": round(time.perf_counter() - start, 3), "error": str(exc)})
        if getattr(exc, "partial", ""):
            entry["partial_response"] = exc.partial
        if getattr(exc, "usage", None):
            entry["usage"] = exc.usage
        raise
    entry.update({"status": "ok", "seconds": round(time.perf_counter() - start, 3), "usage": usage, "output": answer})
    if getattr(client, "progress", None):
        client.progress({"event": "completed", "agent": role, "seconds": entry["seconds"]})
    return answer


def _reject(trace, role, reason):
    for entry in reversed(trace):
        if entry.get("agent") == role and "output" in entry:
            entry.update({"status": "rejected", "validation_error": reason})
            break


def _retry_stage(role, operation, trace, client, retries):
    feedback = None
    for attempt in range(retries + 1):
        try:
            return operation(feedback)
        except (ModelError, KeyError, TypeError) as exc:
            reason = str(exc)
            _reject(trace, role, reason)
            trace.append({"agent": "auditor", "stage": role, "attempt": attempt + 1, "error": reason})
            if getattr(client, "progress", None):
                client.progress({"event": "rejected", "agent": role, "reason": reason})
            feedback = reason
    raise ModelError(f"{role}: no se obtuvo una respuesta válida tras {retries + 1} intentos; último error: {feedback}")


def _design_multi(client, requirements, trace, retries):
    call = partial(_agent, client, trace)

    def analyze_and_audit(feedback):
        analysis = analyst(call, requirements, feedback)
        attrs = analysis["attributes"]
        fds = parse_fds(analysis["functional_dependencies"], attrs)
        tables = name_tables(synthesize_3nf(attrs, fds), analysis["entities"])
        audit = audit_model(attrs, analysis["functional_dependencies"], tables)
        if not audit["valid_3nf"] or audit["missing_attributes"] or audit["unpreserved_dependencies"] or audit["contains_candidate_key"] is False:
            raise ModelError(f"Auditoría de 3FN fallida: {audit}")
        return analysis, tables, audit

    analysis, tables, audit = _retry_stage("analyst", analyze_and_audit, trace, client, retries)
    dictionary = _retry_stage(
        "dictionary",
        lambda feedback: dictionary_agent(call, requirements, tables, analysis["attributes"], feedback),
        trace, client, retries,
    )

    def code_and_render(feedback):
        coder = validate_coder(coder_agent(call, tables, dictionary, feedback), analysis["attributes"])
        return coder, render_ddl(tables, dictionary, coder)

    try:
        coder, ddl = _retry_stage("coder", code_and_render, trace, client, retries)
        coder_status, coder_error = "ok", None
    except ModelError as exc:
        coder, ddl = None, render_ddl(tables, dictionary)
        coder_status, coder_error = "fallback", str(exc)
        trace.append({"agent": "coder", "status": "fallback", "reason": coder_error})
        if getattr(client, "progress", None):
            client.progress({"event": "fallback", "agent": "coder", "reason": coder_error})
    return {"analysis": analysis, "tables": tables, "dictionary": dictionary, "coder": coder, "coder_status": coder_status,
            "coder_error": coder_error, "audit": audit, "ddl": ddl}


def _design_single(client, requirements, trace):
    answer = single_agent(partial(_agent, client, trace), requirements)
    try:
        attrs = validate_single_response(answer)
        audit = audit_model(attrs, answer["functional_dependencies"], answer["tables"])
        dictionary = validate_dictionary({"columns": answer["dictionary"]}, attrs)
        ddl = render_ddl(answer["tables"], dictionary)
        return {"analysis": {k: answer.get(k) for k in ("attributes", "functional_dependencies", "assumptions")}, "tables": answer["tables"], "dictionary": dictionary, "audit": audit, "ddl": ddl}
    except (ModelError, KeyError, TypeError) as exc:
        _reject(trace, "single", str(exc))
        raise


def design(requirements, client=None, mode="multi", retries=2, progress=None):
    if not isinstance(requirements, str) or not requirements.strip():
        raise ValueError("Los requisitos no pueden estar vacíos")
    if mode not in {"multi", "single"}:
        raise ValueError("mode debe ser multi o single")
    client = client if client is not None else default_client()
    if progress is not None:
        client = copy(client)
        client.progress = progress
    trace = []
    start = time.perf_counter()
    result = {"requirements": requirements, "mode": mode, "model": client.model, "started_at": datetime.now(timezone.utc).isoformat(), "trace": trace,
              "ollama_options": {"think": False, "temperature": 0, "seed": 42, "timeout_seconds": getattr(client, "timeout", None)}}
    try:
        result["artifact"] = _design_multi(client, requirements, trace, retries) if mode == "multi" else _design_single(client, requirements, trace)
        result["status"] = "ok"
    except (LLMError, ModelError, KeyError, TypeError, ValueError) as exc:
        result["status"] = "error"
        result["error"] = str(exc)
    except KeyboardInterrupt:
        result["status"] = "cancelled"
        result["error"] = "Ejecución cancelada por el usuario"
    result["seconds"] = round(time.perf_counter() - start, 3)
    return result
