"""Generación determinista de DDL PostgreSQL."""

from .core import ModelError

ALLOWED_TYPES = {"TEXT", "INTEGER", "BIGINT", "NUMERIC", "BOOLEAN", "DATE", "TIMESTAMP", "UUID"}


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
