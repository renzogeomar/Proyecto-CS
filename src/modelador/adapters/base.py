"""Contrato independiente del proveedor para los modelos de lenguaje."""

from typing import Callable, Protocol


class LLMError(RuntimeError):
    """Error de consulta a un proveedor de modelos de lenguaje."""


class LLMClient(Protocol):
    model: str
    progress: Callable[[dict], None] | None

    def ask(self, system: str, user: str, schema: dict | None = None) -> tuple[dict, dict]:
        """Devuelve JSON y uso con input_tokens y output_tokens."""

