"""Agentes locales y orquestación trazable."""

from __future__ import annotations

from datetime import datetime, timezone
import copy
import json
import os
import re
import selectors
import subprocess
import sys
import time
import unicodedata

from .core import IDENT, ModelError, audit_model, names, parse_fds, synthesize_3nf


ALLOWED_TYPES = {"TEXT", "INTEGER", "BIGINT", "NUMERIC", "BOOLEAN", "DATE", "TIMESTAMP", "UUID"}


def _object(properties, required=None):
    return {"type": "object", "properties": properties, "required": required or list(properties), "additionalProperties": False}


_STR = {"type": "string"}
_STRINGS = {"type": "array", "items": _STR}
_FD = _object({"determinant": _STRINGS, "dependent": _STRINGS})
_ENTITY = _object({"name": _STR, "attributes": _STRINGS})
_COLUMN = _object({"name": _STR, "type": {"type": "string", "enum": sorted(ALLOWED_TYPES)}, "nullable": {"type": "boolean"}, "description": _STR})
_COLUMN_DETAILS = _object({"type": {"type": "string", "enum": sorted(ALLOWED_TYPES)}, "nullable": {"type": "boolean"}, "description": _STR})
ANALYST_SCHEMA = _object({"attributes": _STRINGS, "functional_dependencies": {"type": "array", "items": _FD}, "entities": {"type": "array", "items": _ENTITY}, "assumptions": _STRINGS})
_TABLE = _object({"name": _STR, "columns": _STRINGS, "primary_key": _STRINGS})
SINGLE_SCHEMA = _object({"attributes": _STRINGS, "functional_dependencies": {"type": "array", "items": _FD}, "tables": {"type": "array", "items": _TABLE}, "dictionary": {"type": "array", "items": _COLUMN}, "assumptions": _STRINGS})


def dictionary_schema(attributes):
    return _object({"columns": _object({name: _COLUMN_DETAILS for name in attributes})})


def coder_schema(attributes):
    types = {name: {"type": "string", "enum": sorted(ALLOWED_TYPES)} for name in attributes}
    return _object({"column_types": _object(types), "notes": _STRINGS})


class OllamaError(RuntimeError):
    pass


class Ollama:
    def __init__(self, model=None, url=None, timeout=240, progress=None, worker_command=None):
        self.model = model or os.getenv("OLLAMA_MODEL", "qwen3:4b")
        self.url = (url or os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")).rstrip("/")
        self.timeout = timeout
        self.progress = progress
        self.worker_command = worker_command or [sys.executable, "-m", "modelador.ollama_worker"]

    def ask(self, system, user, schema=None):
        payload = {
            "model": self.model, "stream": True, "format": schema or "json", "think": False,
            "options": {"temperature": 0, "seed": 42},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        started = time.monotonic()
        process = subprocess.Popen(self.worker_command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        content = []
        pending = bytearray()
        chars = 0
        last_progress = started
        done = False
        usage = {}
        try:
            process.stdin.write((json.dumps({"url": self.url, "timeout": self.timeout, "payload": payload}, ensure_ascii=False) + "\n").encode("utf-8"))
            process.stdin.close()
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while not done:
                    elapsed = time.monotonic() - started
                    if elapsed >= self.timeout:
                        raise OllamaError(f"Ollama superó el límite de {self.timeout} s por consulta")
                    ready = selector.select(timeout=min(1.0, self.timeout - elapsed))
                    if not ready:
                        if process.poll() is not None:
                            raise OllamaError("El proceso de lectura de Ollama terminó sin respuesta completa")
                    else:
                        block = os.read(process.stdout.fileno(), 65536)
                        if not block:
                            raise OllamaError("Ollama cerró la conexión sin respuesta completa")
                        pending.extend(block)
                        while b"\n" in pending:
                            line, _, rest = pending.partition(b"\n")
                            pending = bytearray(rest)
                            event = json.loads(line)
                            if event["event"] == "error":
                                raise OllamaError(f"Error de Ollama: {event['detail']}")
                            if event["event"] == "chunk":
                                content.append(event["content"])
                                chars += len(event["content"])
                            if event["event"] == "done":
                                done = True
                                usage = event["usage"]
                    if self.progress and time.monotonic() - last_progress >= 5:
                        self.progress({"event": "waiting", "elapsed": round(time.monotonic() - started, 1), "characters": chars})
                        last_progress = time.monotonic()
            process.wait(timeout=1)
        except (OllamaError, KeyboardInterrupt) as exc:
            exc.partial = "".join(content)
            exc.usage = usage
            raise
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            raise OllamaError(f"No se pudo completar la consulta a Ollama: {exc}") from exc
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            process.stdout.close()
        try:
            answer = json.loads("".join(content))
        except ValueError as exc:
            raise OllamaError("Ollama no devolvió JSON válido") from exc
        return answer, usage


def _agent(client, role, system, payload, trace, schema=None):
    start = time.perf_counter()
    entry = {"agent": role, "status": "running"}
    trace.append(entry)
    if isinstance(client, Ollama) and client.progress:
        client.progress({"event": "started", "agent": role})
    try:
        prompt = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        answer, usage = client.ask(system, prompt, schema=schema) if isinstance(client, Ollama) else client.ask(system, prompt)
    except BaseException as exc:
        entry.update({"status": "cancelled" if isinstance(exc, KeyboardInterrupt) else "error", "seconds": round(time.perf_counter() - start, 3), "error": str(exc)})
        if getattr(exc, "partial", ""):
            entry["partial_response"] = exc.partial
        if getattr(exc, "usage", None):
            entry["usage"] = exc.usage
        raise
    entry.update({"status": "ok", "seconds": round(time.perf_counter() - start, 3), "usage": usage, "output": answer})
    if isinstance(client, Ollama) and client.progress:
        client.progress({"event": "completed", "agent": role, "seconds": entry["seconds"]})
    return answer


def _required_object(answer, label, fields):
    if not isinstance(answer, dict):
        raise ModelError(f"{label}: se esperaba un objeto JSON")
    missing = sorted(set(fields) - set(answer))
    if missing:
        actual = ", ".join(sorted(answer)) or "ninguno"
        raise ModelError(f"{label}: faltan campos {', '.join(missing)}; campos recibidos: {actual}")
    return answer


def _text_list(value, label):
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ModelError(f"{label}: se esperaba una lista de textos")
    return value


def _validate_analysis(answer):
    _required_object(answer, "analista", ANALYST_SCHEMA["required"])
    attributes = names(_text_list(answer["attributes"], "attributes"))
    fds = answer["functional_dependencies"]
    if not isinstance(fds, list) or not fds:
        raise ModelError("analista: functional_dependencies debe ser una lista no vacía")
    for fd in fds:
        _required_object(fd, "dependencia funcional", ("determinant", "dependent"))
        _text_list(fd["determinant"], "determinant")
        _text_list(fd["dependent"], "dependent")
    parse_fds(fds, attributes)
    entities = answer["entities"]
    if not isinstance(entities, list):
        raise ModelError("analista: entities debe ser una lista")
    normalized = copy.deepcopy(answer)
    changes = []
    for entity in normalized["entities"]:
        _required_object(entity, "entidad", ("name", "attributes"))
        if not isinstance(entity["name"], str):
            raise ModelError("entidad: name debe ser texto")
        original = entity["name"]
        ascii_name = unicodedata.normalize("NFKD", original).encode("ascii", "ignore").decode("ascii").lower()
        entity["name"] = re.sub(r"[^a-z0-9]+", "_", ascii_name).strip("_")
        if not IDENT.fullmatch(entity["name"]):
            raise ModelError("entidad: name no puede convertirse a snake_case")
        if entity["name"] != original:
            changes.append({"from": original, "to": entity["name"]})
        _text_list(entity["attributes"], "entity.attributes")
    _text_list(answer["assumptions"], "assumptions")
    normalized["entity_name_changes"] = changes
    return normalized


def analyst(client, requirements, trace, feedback=None):
    prompt = "Analiza estos requisitos de negocio y genera el modelo conceptual:\n\n" + requirements
    if feedback:
        prompt += "\n\nLa respuesta anterior fue rechazada: " + feedback + "\nCorrige exclusivamente tu salida. No copies los requisitos ni el mensaje de error."
    answer = _agent(client, "analyst", """Extrae atributos atómicos, dependencias funcionales, entidades y supuestos del texto de negocio.
Devuelve un objeto JSON con EXACTAMENTE estas claves: attributes, functional_dependencies, entities, assumptions.
Cada dependencia tiene determinant y dependent como listas de atributos snake_case. Cada entidad tiene name y attributes.
No copies el texto de entrada. No inventes reglas ausentes; explica ambigüedades en assumptions.""", prompt, trace, ANALYST_SCHEMA)
    return _validate_analysis(answer)


def name_tables(tables, entities):
    used = set()
    for table in tables:
        choices = [e for e in entities if isinstance(e, dict) and isinstance(e.get("name"), str) and IDENT.fullmatch(e["name"]) and set(table["columns"]) == set(e.get("attributes", []))]
        if choices and choices[0]["name"] not in used:
            table["name"] = choices[0]["name"]
        used.add(table["name"])
    return tables


def dictionary_agent(client, requirements, tables, attributes, trace, feedback=None):
    prompt = "Atributos aprobados, una definición por nombre:\n" + ", ".join(attributes) + "\n\nRequisitos:\n" + requirements + "\n\nTablas aprobadas:\n" + json.dumps(tables, ensure_ascii=False)
    if feedback:
        prompt += "\n\nCorrige la respuesta anterior: " + feedback
    answer = _agent(client, "dictionary", """Eres el agente de diccionario de datos. Devuelve un objeto JSON con la clave columns.
columns debe ser un objeto: cada clave es un nombre de atributo aprobado y cada valor contiene type, nullable y description.
Incluye exactamente una definición por atributo aprobado, incluso si aparece en varias tablas. No antepongas nombres de tabla ni crees atributos nuevos.
Tipos permitidos: TEXT, INTEGER, BIGINT, NUMERIC, BOOLEAN, DATE, TIMESTAMP, UUID. Describe el significado de negocio. Si un tipo no está claro, usa TEXT. No inventes longitudes ni valores por defecto. No copies la entrada.""", prompt, trace, dictionary_schema(attributes))
    return validate_dictionary_response(answer, attributes)


def validate_dictionary_response(answer, attributes):
    _required_object(answer, "diccionario", ("columns",))
    columns = answer["columns"]
    if isinstance(columns, list):
        observed = [item.get("name") for item in columns if isinstance(item, dict)]
        missing = sorted(set(attributes) - set(name for name in observed if isinstance(name, str)))
        unknown = sorted(set(name for name in observed if isinstance(name, str)) - set(attributes))
        raise ModelError(f"diccionario: columns debe ser un objeto; faltan atributos {missing}; desconocidos {unknown}")
    if not isinstance(columns, dict):
        raise ModelError("diccionario: columns debe ser un objeto con los atributos como claves")
    missing = sorted(set(attributes) - set(columns))
    unknown = sorted(set(columns) - set(attributes))
    if missing or unknown:
        raise ModelError(f"diccionario: faltan atributos {missing}; desconocidos {unknown}")
    converted = []
    for name in attributes:
        details = _required_object(columns[name], f"diccionario.{name}", ("type", "nullable", "description"))
        converted.append({"name": name, **details})
    return validate_dictionary({"columns": converted}, attributes)


def coder_agent(client, tables, dictionary, trace, feedback=None):
    prompt = "Tablas aprobadas:\n" + json.dumps(tables, ensure_ascii=False) + "\n\nDiccionario:\n" + json.dumps(dictionary, ensure_ascii=False)
    if feedback:
        prompt += "\n\nCorrige la respuesta anterior: " + feedback
    return _agent(client, "coder", """Eres agente codificador PostgreSQL. Devuelve un objeto JSON con column_types y notes.
column_types debe tener exactamente una clave por cada atributo del diccionario: usa el nombre real de cada columna, nunca un nombre de ejemplo.
Elige exclusivamente TEXT, INTEGER, BIGINT, NUMERIC, BOOLEAN, DATE, TIMESTAMP o UUID. Conserva todas las tablas y claves suministradas. Tu propuesta será validada y convertida a DDL por un compilador determinista. No copies la entrada.""", prompt, trace, coder_schema([item["name"] for item in dictionary]))


def validate_dictionary(answer, attributes):
    _required_object(answer, "diccionario", ("columns",))
    columns = answer["columns"]
    if not isinstance(columns, list):
        raise ModelError("diccionario: columns debe ser una lista")
    for column in columns:
        _required_object(column, "columna", ("name", "type", "nullable", "description"))
        if not isinstance(column["name"], str) or not IDENT.fullmatch(column["name"]):
            raise ModelError("diccionario: cada name debe ser snake_case")
    if len(columns) != len(attributes) or {c.get("name") for c in columns} != set(attributes):
        raise ModelError("El diccionario no cubre exactamente los atributos del modelo")
    for column in columns:
        if column.get("type") not in ALLOWED_TYPES or not isinstance(column.get("description"), str):
            raise ModelError(f"Entrada inválida en diccionario: {column}")
        if not isinstance(column.get("nullable"), bool):
            raise ModelError("nullable debe ser booleano")
    return columns


def validate_coder(answer, attributes):
    _required_object(answer, "codificador", ("column_types", "notes"))
    if not isinstance(answer["column_types"], dict):
        raise ModelError("codificador: column_types debe ser un objeto")
    missing = set(attributes) - set(answer["column_types"])
    extra = set(answer["column_types"]) - set(attributes)
    if missing or extra:
        raise ModelError(f"codificador: faltan columnas {sorted(missing)}; columnas desconocidas {sorted(extra)}")
    if any(value not in ALLOWED_TYPES for value in answer["column_types"].values()):
        raise ModelError("codificador: uno o más tipos no están permitidos")
    _text_list(answer["notes"], "notes")
    return answer


def render_ddl(tables, dictionary, coder=None):
    catalog = {c["name"]: c for c in dictionary}
    proposals = (coder or {}).get("column_types", {})
    for name, value in proposals.items():
        if name not in catalog or value not in ALLOWED_TYPES:
            raise ModelError(f"Tipo propuesto no permitido: {name}={value}")
    lines = []
    references = []
    for table in tables:
        definitions = []
        for name in table["columns"]:
            column = catalog[name]
            sql_type = proposals.get(name, column["type"])
            required = name in table["primary_key"] or not column["nullable"]
            definitions.append(f"    {name} {sql_type}{' NOT NULL' if required else ''}")
        definitions.append("    PRIMARY KEY (" + ", ".join(table["primary_key"]) + ")")
        # Una referencia se deriva únicamente cuando la clave completa aparece en otra tabla.
        for target in tables:
            if target is table or not set(target["primary_key"]) <= set(table["columns"]):
                continue
            if set(target["primary_key"]) == set(table["primary_key"]):
                continue
            cols = ", ".join(target["primary_key"])
            references.append(f"ALTER TABLE {table['name']} ADD FOREIGN KEY ({cols}) REFERENCES {target['name']} ({cols});")
        lines.append(f"CREATE TABLE {table['name']} (\n" + ",\n".join(definitions) + "\n);")
    return "\n\n".join(lines + references) + "\n"


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
            if isinstance(client, Ollama) and client.progress:
                client.progress({"event": "rejected", "agent": role, "reason": reason})
            feedback = reason
    raise ModelError(f"{role}: no se obtuvo una respuesta válida tras {retries + 1} intentos; último error: {feedback}")


def _design_multi(client, requirements, trace, retries):
    def analyze_and_audit(feedback):
        analysis = analyst(client, requirements, trace, feedback)
        attrs = analysis["attributes"]
        fds = parse_fds(analysis["functional_dependencies"], attrs)
        tables = name_tables(synthesize_3nf(attrs, fds), analysis["entities"])
        audit = audit_model(attrs, analysis["functional_dependencies"], tables)
        if not audit["valid_3nf"] or audit["missing_attributes"] or audit["unpreserved_dependencies"] or audit["contains_candidate_key"] is False:
            raise ModelError(f"Auditoría de 3FN fallida: {audit}")
        return analysis, tables, audit

    analysis, tables, audit = _retry_stage("analyst", analyze_and_audit, trace, client, retries)
    dictionary = _retry_stage("dictionary", lambda feedback: dictionary_agent(client, requirements, tables, analysis["attributes"], trace, feedback), trace, client, retries)

    def code_and_render(feedback):
        coder = validate_coder(coder_agent(client, tables, dictionary, trace, feedback), analysis["attributes"])
        return coder, render_ddl(tables, dictionary, coder)

    try:
        coder, ddl = _retry_stage("coder", code_and_render, trace, client, retries)
        coder_status, coder_error = "ok", None
    except ModelError as exc:
        coder, ddl = None, render_ddl(tables, dictionary)
        coder_status, coder_error = "fallback", str(exc)
        trace.append({"agent": "coder", "status": "fallback", "reason": coder_error})
        if isinstance(client, Ollama) and client.progress:
            client.progress({"event": "fallback", "agent": "coder", "reason": coder_error})
    return {"analysis": analysis, "tables": tables, "dictionary": dictionary, "coder": coder, "coder_status": coder_status,
            "coder_error": coder_error, "audit": audit, "ddl": ddl}


def _design_single(client, requirements, trace):
    answer = _agent(client, "single", """Diseña una base de datos PostgreSQL en 3FN a partir de requisitos. Devuelve SOLO JSON:
{"attributes":["a"],"functional_dependencies":[{"determinant":["a"],"dependent":["b"]}],"tables":[{"name":"tabla","columns":["a","b"],"primary_key":["a"]}],"dictionary":[{"name":"a","type":"TEXT","nullable":false,"description":"..."}],"assumptions":["..."]}.
Usa nombres snake_case y tipos TEXT, INTEGER, BIGINT, NUMERIC, BOOLEAN, DATE, TIMESTAMP o UUID. Incluye todos los atributos. No copies la entrada. No habrá reparación automática; esta es una línea base experimental de un solo agente.""", "Requisitos de negocio:\n\n" + requirements, trace, SINGLE_SCHEMA)
    try:
        _required_object(answer, "agente único", SINGLE_SCHEMA["required"])
        attrs = names(_text_list(answer["attributes"], "attributes"))
        parse_fds(answer["functional_dependencies"], attrs)
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
    client = client or Ollama()
    if isinstance(client, Ollama) and progress:
        client = Ollama(client.model, client.url, client.timeout, progress, client.worker_command)
    trace = []
    start = time.perf_counter()
    result = {"requirements": requirements, "mode": mode, "model": client.model, "started_at": datetime.now(timezone.utc).isoformat(), "trace": trace,
              "ollama_options": {"think": False, "temperature": 0, "seed": 42, "timeout_seconds": getattr(client, "timeout", None)}}
    try:
        result["artifact"] = _design_multi(client, requirements, trace, retries) if mode == "multi" else _design_single(client, requirements, trace)
        result["status"] = "ok"
    except (OllamaError, ModelError, KeyError, TypeError, ValueError) as exc:
        result["status"] = "error"
        result["error"] = str(exc)
    except KeyboardInterrupt:
        result["status"] = "cancelled"
        result["error"] = "Ejecución cancelada por el usuario"
    result["seconds"] = round(time.perf_counter() - start, 3)
    return result
