"""Proceso aislado para leer el stream de Ollama; el padre aplica el plazo real."""

import json
import sys
from urllib import error, request


def emit(data):
    print(json.dumps(data, ensure_ascii=False), flush=True)


def main():
    config = json.loads(sys.stdin.readline())
    payload = config["payload"]
    req = request.Request(
        config["url"] + "/api/chat",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with request.urlopen(req, timeout=config["timeout"]) as response:
            for line in response:
                if not line.strip():
                    continue
                item = json.loads(line)
                if item.get("error"):
                    emit({"event": "error", "detail": item["error"]})
                    return 1
                content = item.get("message", {}).get("content", "")
                if content:
                    emit({"event": "chunk", "content": content})
                if item.get("done"):
                    usage_keys = ("total_duration", "load_duration", "prompt_eval_count", "prompt_eval_duration", "eval_count", "eval_duration")
                    emit({"event": "done", "usage": {key: item.get(key) for key in usage_keys}})
                    return 0
        emit({"event": "error", "detail": "Ollama cerró el stream antes de completar la respuesta"})
    except (error.URLError, TimeoutError, OSError, ValueError) as exc:
        emit({"event": "error", "detail": str(exc)})
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
