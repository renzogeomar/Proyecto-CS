"""Integraciones externas del modelador."""
def default_client():
    """Mantiene Ollama como proveedor predeterminado para el uso local."""
    from .ollama import Ollama

    return Ollama()
