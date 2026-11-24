"""Evaluación reproducible frente a casos con respuestas esperadas."""

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .adapters.postgres import validate_postgres as validate_postgres
from .core import ModelError, audit_model
from .pipeline import design


def score(result, expected):
    if result["status"] != "ok":
        return {"success": False, "schema_success": False, "ddl_generated": False, "agents_completed": False, "full_agent_success": False, "error": result.get("error")}
    artifact = result["artifact"]
    inferred = artifact["analysis"]["functional_dependencies"]
    gold = expected["functional_dependencies"]
    def to_set(data):
        return {(tuple(sorted(x["determinant"])), dependent) for x in data for dependent in x["dependent"]}
    got, want = to_set(inferred), to_set(gold)
    precision = len(got & want) / len(got) if got else 0
    recall = len(got & want) / len(want) if want else 1
    try:
        gold_audit = audit_model(expected["attributes"], gold, artifact["tables"]) if set(artifact["analysis"]["attributes"]) == set(expected["attributes"]) else None
    except (ModelError, KeyError, TypeError):
        gold_audit = None
    local = artifact["audit"]
    passed = bool(gold_audit and gold_audit["valid_3nf"] and not gold_audit["missing_attributes"] and not gold_audit["unpreserved_dependencies"] and gold_audit["contains_candidate_key"] is not False)
    agents_completed = result["mode"] == "single" or artifact.get("coder_status") == "ok"
    return {"success": passed, "schema_success": passed, "ddl_generated": bool(artifact["ddl"]), "agents_completed": agents_completed,
            "full_agent_success": passed and agents_completed, "fd_precision": round(precision, 3), "fd_recall": round(recall, 3),
            "inferred_3nf": local["valid_3nf"], "gold_3nf": gold_audit["valid_3nf"] if gold_audit else False, "gold_audit": gold_audit}


def run_benchmark(cases, output_dir, client=None, postgres_dsn=None, progress=None):
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("run_%Y%m%dT%H%M%S_%fZ") + "_" + uuid4().hex[:8]
    run_dir = output_root / run_id
    run_dir.mkdir()
    rows = []
    cancelled = False
    for case in cases:
        for mode in ("multi", "single"):
            if progress:
                progress({"event": "case", "case_id": case["id"], "mode": mode})
            result = design(case["requirements"], client=client, mode=mode, progress=progress)
            metrics = score(result, case["expected"])
            postgres = validate_postgres(result["artifact"]["ddl"], postgres_dsn) if result["status"] == "ok" else {"status": "not_run"}
            record = {"case_id": case["id"], "mode": mode, "model": result["model"], "status": result["status"],
                      "coder_status": result.get("artifact", {}).get("coder_status", "not_applicable"),
                      "think": result["ollama_options"]["think"], "temperature": result["ollama_options"]["temperature"],
                      "seed": result["ollama_options"]["seed"], "timeout_seconds": result["ollama_options"]["timeout_seconds"],
                      "seconds": result["seconds"], **metrics, "postgres": postgres}
            rows.append(record)
            (run_dir / f"{case['id']}_{mode}.json").write_text(json.dumps({"run": result, "metrics": metrics, "postgres": postgres}, ensure_ascii=False, indent=2), encoding="utf-8")
            if result["status"] == "cancelled":
                cancelled = True
                break
        if cancelled:
            break
    with (run_dir / "summary.csv").open("w", newline="", encoding="utf-8") as handle:
        fields = ["case_id", "mode", "model", "think", "temperature", "seed", "timeout_seconds", "status", "coder_status", "seconds", "success", "schema_success", "ddl_generated", "agents_completed", "full_agent_success", "fd_precision", "fd_recall", "inferred_3nf", "gold_3nf", "postgres_status", "error"]
        writer = csv.DictWriter(handle, fields)
        writer.writeheader()
        for row in rows:
            flat = {**row, "postgres_status": row["postgres"]["status"]}
            writer.writerow({field: flat.get(field, "") for field in fields})
    return rows, run_dir


def load_cases(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        raise ValueError("El archivo de casos debe contener una lista no vacía")
    for case in data:
        if not all(k in case for k in ("id", "requirements", "expected")):
            raise ValueError("Cada caso requiere id, requirements y expected")
    return data
