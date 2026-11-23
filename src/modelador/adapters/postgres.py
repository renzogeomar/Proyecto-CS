"""Validación de DDL en una transacción revertida de PostgreSQL."""

import subprocess
from uuid import uuid4


def validate_postgres(ddl, dsn=None):
    """Ejecuta DDL en una transacción revertida; requiere PostgreSQL accesible."""
    schema = "modelador_test_" + uuid4().hex[:12]
    script = f"BEGIN;\nCREATE SCHEMA {schema};\nSET LOCAL search_path TO {schema};\n" + ddl + "\nROLLBACK;\n"
    command = ["psql", "-X", "-v", "ON_ERROR_STOP=1", "-q", "-t"]
    if dsn:
        command.extend(["-d", dsn])
    try:
        run = subprocess.run(command, input=script, text=True, capture_output=True, timeout=30)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return {"status": "unavailable", "detail": str(exc)}
    if run.returncode:
        detail = run.stderr.strip()[:2000]
        unavailable = any(mark in detail.lower() for mark in ("connection", "conexión", "no such file", "could not connect", "no responde"))
        return {"status": "unavailable" if unavailable else "failed", "detail": detail}
    return {"status": "passed", "detail": "DDL ejecutado y revertido en PostgreSQL"}
