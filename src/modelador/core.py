"""Dependencias funcionales, síntesis 3FN y auditoría formal.

La prueba de 3FN es relativa a las dependencias declaradas. Ningún algoritmo
puede demostrar que las dependencias inferidas de lenguaje natural son ciertas.
"""

from __future__ import annotations

from itertools import combinations
import re


IDENT = re.compile(r"^[a-z][a-z0-9_]*$")
MAX_TABLE_ATTRIBUTES = 14


class ModelError(ValueError):
    pass


def names(items):
    result = list(items)
    if not result or len(result) != len(set(result)) or any(not isinstance(x, str) or not IDENT.fullmatch(x) for x in result):
        raise ModelError("Los atributos deben ser identificadores snake_case únicos y no vacíos")
    return result


def parse_fds(raw, universe):
    universe = set(universe)
    result = []
    for item in raw:
        left = frozenset(names(item["determinant"]))
        right = names(item["dependent"])
        if not left <= universe or not set(right) <= universe:
            raise ModelError(f"Dependencia fuera del universo: {item}")
        for attribute in right:
            if attribute not in left:
                result.append((left, attribute))
    return sorted(set(result), key=lambda x: (tuple(sorted(x[0])), x[1]))


def closure(seed, fds):
    found = set(seed)
    while True:
        previous = len(found)
        for left, right in fds:
            if left <= found:
                found.add(right)
        if len(found) == previous:
            return frozenset(found)


def canonical_cover(fds):
    cover = list(dict.fromkeys(fds))
    changed = True
    while changed:
        changed = False
        for index, (left, right) in enumerate(cover):
            for attr in sorted(left):
                if len(left) > 1 and right in closure(left - {attr}, cover):
                    cover[index] = (left - {attr}, right)
                    changed = True
                    break
            if changed:
                break
    for fd in list(cover):
        trial = cover.copy()
        trial.remove(fd)
        if fd[1] in closure(fd[0], trial):
            cover.remove(fd)
    return sorted(set(cover), key=lambda x: (tuple(sorted(x[0])), x[1]))


def candidate_keys(attributes, fds):
    attributes = frozenset(attributes)
    if len(attributes) > MAX_TABLE_ATTRIBUTES:
        raise ModelError(f"La tabla supera el límite de auditoría exacta de {MAX_TABLE_ATTRIBUTES} atributos")
    mandatory = attributes - {right for _, right in fds}
    optional = sorted(attributes - mandatory)
    keys = []
    for count in range(len(optional) + 1):
        for extra in combinations(optional, count):
            trial = mandatory | set(extra)
            if not any(key <= trial for key in keys) and attributes <= closure(trial, fds):
                keys.append(frozenset(trial))
    return keys


def projected_fds(attributes, fds):
    """Proyección exacta, incluso para dependencias derivadas indirectamente."""
    attributes = frozenset(attributes)
    if len(attributes) > MAX_TABLE_ATTRIBUTES:
        raise ModelError(f"La tabla supera el límite de auditoría exacta de {MAX_TABLE_ATTRIBUTES} atributos")
    output = []
    ordered = sorted(attributes)
    for count in range(len(ordered) + 1):
        for subset in combinations(ordered, count):
            left = frozenset(subset)
            for right in (closure(left, fds) & attributes) - left:
                output.append((left, right))
    return output


def audit_3nf(table, fds):
    attributes = frozenset(names(table["columns"]))
    if len(table["primary_key"]) != len(set(table["primary_key"])) or not set(table["primary_key"]) <= attributes:
        raise ModelError(f"Clave primaria inválida en {table['name']}")
    projected = projected_fds(attributes, fds)
    keys = candidate_keys(attributes, projected)
    prime = set().union(*keys) if keys else set()
    violations = []
    for left, right in projected:
        if right not in left and not attributes <= closure(left, projected) and right not in prime:
            violations.append({"determinant": sorted(left), "dependent": right})
    # Solo se muestran las violaciones mínimas para evitar listas exponenciales.
    minimal = []
    for item in sorted(violations, key=lambda x: (len(x["determinant"]), x["determinant"], x["dependent"])):
        if not any(old["dependent"] == item["dependent"] and set(old["determinant"]) <= set(item["determinant"]) for old in minimal):
            minimal.append(item)
    return {
        "table": table["name"], "valid": not minimal,
        "candidate_keys": [sorted(key) for key in keys], "violations": minimal,
        "primary_key_is_candidate": frozenset(table["primary_key"]) in keys,
    }


def synthesize_3nf(attributes, fds):
    """Síntesis clásica: cobertura mínima, una relación por determinante y clave."""
    attributes = names(attributes)
    if len(attributes) > 30:
        raise ModelError("Máximo 30 atributos por caso; divida el dominio en módulos")
    cover = canonical_cover(fds)
    groups = {}
    for left, right in cover:
        groups.setdefault(left, set(left)).add(right)
    relations = [(key, frozenset(value)) for key, value in groups.items()]
    relations = [(key, value) for key, value in relations if not any(value < other for _, other in relations)]
    all_keys = candidate_keys(attributes, fds) if len(attributes) <= MAX_TABLE_ATTRIBUTES else None
    if all_keys is None:
        # Para universos grandes, buscar una clave mediante reducción codiciosa.
        key = set(attributes)
        for attr in sorted(attributes):
            if set(attributes) <= closure(key - {attr}, fds):
                key.remove(attr)
        all_keys = [frozenset(key)]
    key = min(all_keys, key=lambda x: (len(x), sorted(x)))
    if not any(key <= value for _, value in relations):
        relations.append((key, key))
    if not relations:
        relations = [(key, frozenset(attributes))]
    tables = []
    used = set()
    for index, (determinant, columns) in enumerate(relations, 1):
        base = sorted(determinant)[0] if determinant else "relation"
        name = f"{base}_data"
        if name in used:
            name = f"{name}_{index}"
        used.add(name)
        local = projected_fds(columns, fds)
        local_keys = candidate_keys(columns, local)
        primary_key = min(local_keys, key=lambda x: (len(x), sorted(x)))
        tables.append({"name": name, "columns": sorted(columns), "primary_key": sorted(primary_key)})
    return tables


def audit_model(attributes, raw_fds, tables):
    attributes = names(attributes)
    fds = parse_fds(raw_fds, attributes)
    table_names = names([table["name"] for table in tables])
    if not table_names:
        raise ModelError("El esquema no tiene tablas")
    for table in tables:
        if not set(table["columns"]) <= set(attributes):
            raise ModelError(f"La tabla {table['name']} contiene atributos desconocidos")
    checks = [audit_3nf(table, fds) for table in tables]
    covered = set().union(*(set(t["columns"]) for t in tables))
    missing = sorted(set(attributes) - covered)
    # Comprobar preservación de cada FD mediante las dependencias proyectadas.
    union = []
    for table in tables:
        union.extend(projected_fds(table["columns"], fds))
    unpreserved = [{"determinant": sorted(left), "dependent": right} for left, right in fds if right not in closure(left, union)]
    # La síntesis con una relación que contiene una clave conserva unión sin pérdida.
    if len(attributes) <= MAX_TABLE_ATTRIBUTES:
        keys = candidate_keys(attributes, fds)
        key_relation = any(any(key <= set(t["columns"]) for key in keys) for t in tables)
    else:
        key_relation = None
    return {
        "valid_3nf": all(t["valid"] and t["primary_key_is_candidate"] for t in checks),
        "tables": checks, "missing_attributes": missing,
        "unpreserved_dependencies": unpreserved,
        "contains_candidate_key": key_relation,
        "note": "La 3FN se verifica respecto de las dependencias declaradas, no de toda la semántica del negocio.",
    }
