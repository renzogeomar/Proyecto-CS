"""CLI: python -m modelador ..."""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from .adapters.ollama import Ollama
from .adapters.postgres import validate_postgres
from .evaluation import load_cases, run_benchmark
from .pipeline import design


def main(argv=None):
    parser = argparse.ArgumentParser(prog="modelador", description="Modelado autónomo y evaluación 3FN")
    parser.add_argument("--model", default=None, help="Modelo Ollama, por ejemplo qwen3:4b")
    parser.add_argument("--ollama-url", default=None)
    subs = parser.add_subparsers(dest="command", required=True)
    one = subs.add_parser("design", help="Diseñar desde un archivo de requisitos")
    one.add_argument("input")
    one.add_argument("--mode", choices=["multi", "single"], default="multi")
    one.add_argument("--output", default="runs")
    one.add_argument("--postgres-dsn", default=None)
    one.add_argument("--timeout", type=float, default=240, help="Segundos máximos por consulta a Ollama")
    batch = subs.add_parser("benchmark", help="Evaluar casos JSON")
    batch.add_argument("cases")
    batch.add_argument("--output", default="runs/benchmark")
    batch.add_argument("--postgres-dsn", default=None)
    batch.add_argument("--timeout", type=float, default=240, help="Segundos máximos por consulta a Ollama")
    web = subs.add_parser("serve", help="Abrir interfaz local")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8765)
    web.add_argument("--output", default="runs/web")
    web.add_argument("--timeout", type=float, default=240, help="Segundos máximos por consulta a Ollama")
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout debe ser mayor que cero")
    client = Ollama(args.model, args.ollama_url, args.timeout)

    def progress(event):
        kind = event["event"]
        if kind == "started":
            print(f"[{event['agent']}] iniciando consulta a Ollama...", file=sys.stderr, flush=True)
        elif kind == "waiting":
            print(f"  esperando {event['elapsed']:.0f} s; {event['characters']} caracteres recibidos", file=sys.stderr, flush=True)
        elif kind == "completed":
            print(f"[{event['agent']}] completado en {event['seconds']:.1f} s", file=sys.stderr, flush=True)
        elif kind == "rejected":
            print(f"[{event['agent']}] respuesta rechazada: {event['reason']}", file=sys.stderr, flush=True)
        elif kind == "fallback":
            print(f"[{event['agent']}] DDL generado desde el diccionario; el agente no produjo una salida válida", file=sys.stderr, flush=True)
        elif kind == "case":
            print(f"Caso {event['case_id']} · {event['mode']}", file=sys.stderr, flush=True)

    if args.command == "design":
        requirements = Path(args.input).read_text(encoding="utf-8")
        result = design(requirements, client, args.mode, progress=progress)
        if result["status"] == "ok":
            result["postgres"] = validate_postgres(result["artifact"]["ddl"], args.postgres_dsn)
            if result["artifact"].get("coder_status") == "fallback":
                print("Advertencia: se usó recuperación del codificador; revise coder_error en el JSON.", file=sys.stderr, flush=True)
        output = Path(args.output)
        output.mkdir(parents=True, exist_ok=True)
        target = output / f"design_{args.mode}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"status": result["status"], "path": str(target), "seconds": result["seconds"], "error": result.get("error"),
                          "coder_status": result.get("artifact", {}).get("coder_status"), "postgres": result.get("postgres")}, ensure_ascii=False))
        return 0 if result["status"] == "ok" else (130 if result["status"] == "cancelled" else 1)
    if args.command == "benchmark":
        rows, run_dir = run_benchmark(load_cases(args.cases), args.output, client, args.postgres_dsn, progress)
        print(json.dumps({"cases": len({row['case_id'] for row in rows}), "runs": len(rows), "summary": str(run_dir / "summary.csv")}, ensure_ascii=False))
        return 130 if any(row.get("error") == "Ejecución cancelada por el usuario" for row in rows) else 0
    from .web import serve
    serve(args.host, args.port, args.output, client)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
