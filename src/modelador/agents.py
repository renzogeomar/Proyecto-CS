"""Prompts, esquemas JSON y validación de respuestas de los agentes."""

import copy
import json
import re
import unicodedata

from .core import IDENT, ModelError, names, parse_fds
from .sql import ALLOWED_TYPES


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


def analyst(call, requirements, feedback=None):
    prompt = "Analiza estos requisitos de negocio y genera el modelo conceptual:\n\n" + requirements
    if feedback:
        prompt += "\n\nLa respuesta anterior fue rechazada: " + feedback + "\nCorrige exclusivamente tu salida. No copies los requisitos ni el mensaje de error."
    answer = call("analyst", """Extrae atributos atómicos, dependencias funcionales, entidades y supuestos del texto de negocio.
Devuelve un objeto JSON con EXACTAMENTE estas claves: attributes, functional_dependencies, entities, assumptions.
Cada dependencia tiene determinant y dependent como listas de atributos snake_case. Cada entidad tiene name y attributes.
No copies el texto de entrada. No inventes reglas ausentes; explica ambigüedades en assumptions.""", prompt, ANALYST_SCHEMA)
    return _validate_analysis(answer)


def name_tables(tables, entities):
    used = set()
    for table in tables:
        choices = [e for e in entities if isinstance(e, dict) and isinstance(e.get("name"), str) and IDENT.fullmatch(e["name"]) and set(table["columns"]) == set(e.get("attributes", []))]
        if choices and choices[0]["name"] not in used:
            table["name"] = choices[0]["name"]
        used.add(table["name"])
    return tables


def dictionary_agent(call, requirements, tables, attributes, feedback=None):
    prompt = "Atributos aprobados, una definición por nombre:\n" + ", ".join(attributes) + "\n\nRequisitos:\n" + requirements + "\n\nTablas aprobadas:\n" + json.dumps(tables, ensure_ascii=False)
    if feedback:
        prompt += "\n\nCorrige la respuesta anterior: " + feedback
    answer = call("dictionary", """Eres el agente de diccionario de datos. Devuelve un objeto JSON con la clave columns.
columns debe ser un objeto: cada clave es un nombre de atributo aprobado y cada valor contiene type, nullable y description.
Incluye exactamente una definición por atributo aprobado, incluso si aparece en varias tablas. No antepongas nombres de tabla ni crees atributos nuevos.
Tipos permitidos: TEXT, INTEGER, BIGINT, NUMERIC, BOOLEAN, DATE, TIMESTAMP, UUID. Describe el significado de negocio. Si un tipo no está claro, usa TEXT. No inventes longitudes ni valores por defecto. No copies la entrada.""", prompt, dictionary_schema(attributes))
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
        unexpected = sorted(set(details) - {"type", "nullable", "description"})
        if unexpected:
            raise ModelError(f"diccionario.{name}: campos desconocidos {unexpected}")
        converted.append({"name": name, **details})
    return validate_dictionary({"columns": converted}, attributes)


def coder_agent(call, tables, dictionary, feedback=None):
    prompt = "Tablas aprobadas:\n" + json.dumps(tables, ensure_ascii=False) + "\n\nDiccionario:\n" + json.dumps(dictionary, ensure_ascii=False)
    if feedback:
        prompt += "\n\nCorrige la respuesta anterior: " + feedback
    return call("coder", """Eres agente codificador PostgreSQL. Devuelve un objeto JSON con column_types y notes.
column_types debe tener exactamente una clave por cada atributo del diccionario: usa el nombre real de cada columna, nunca un nombre de ejemplo.
Elige exclusivamente TEXT, INTEGER, BIGINT, NUMERIC, BOOLEAN, DATE, TIMESTAMP o UUID. Conserva todas las tablas y claves suministradas. Tu propuesta será validada y convertida a DDL por un compilador determinista. No copies la entrada.""", prompt, coder_schema([item["name"] for item in dictionary]))


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


def single_agent(call, requirements):
    return call("single", """Diseña una base de datos PostgreSQL en 3FN a partir de requisitos. Devuelve SOLO JSON:
{"attributes":["a"],"functional_dependencies":[{"determinant":["a"],"dependent":["b"]}],"tables":[{"name":"tabla","columns":["a","b"],"primary_key":["a"]}],"dictionary":[{"name":"a","type":"TEXT","nullable":false,"description":"..."}],"assumptions":["..."]}.
Usa nombres snake_case y tipos TEXT, INTEGER, BIGINT, NUMERIC, BOOLEAN, DATE, TIMESTAMP o UUID. Incluye todos los atributos. No copies la entrada. No habrá reparación automática; esta es una línea base experimental de un solo agente.""", "Requisitos de negocio:\n\n" + requirements, SINGLE_SCHEMA)


def validate_single_response(answer):
    _required_object(answer, "agente único", SINGLE_SCHEMA["required"])
    attributes = names(_text_list(answer["attributes"], "attributes"))
    parse_fds(answer["functional_dependencies"], attributes)
    return attributes
