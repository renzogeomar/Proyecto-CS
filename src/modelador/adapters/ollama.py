"""Cliente de Ollama con streaming, plazo y progreso."""

import json
import os
import selectors
import subprocess
import sys
import time

from .base import LLMError


class OllamaError(LLMError):
    pass


class Ollama:
    def __init__(self, model=None, url=None, timeout=240, progress=None, worker_command=None):
        self.model = model or os.getenv("OLLAMA_MODEL", "qwen3:4b")
        self.url = (url or os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")).rstrip("/")
        self.timeout = timeout
        self.progress = progress
        self.worker_command = worker_command or [sys.executable, "-m", "modelador.adapters.ollama_worker"]

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
        usage["input_tokens"] = usage.get("prompt_eval_count") or 0
        usage["output_tokens"] = usage.get("eval_count") or 0
        return answer, usage
