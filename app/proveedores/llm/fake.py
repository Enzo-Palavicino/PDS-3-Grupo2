from typing import Any

from app.proveedores.llm.base import ProveedorLLM, ResultadoLLM


class ProveedorLLMFake(ProveedorLLM):
    """No usa IA: devuelve respuestas fijas.

    Por defecto devuelve un JSON vacío ({}), que deja todos los campos sin completar. Los tests
    le pasan las respuestas que necesitan, en orden.
    """

    nombre = "fake"

    def __init__(self, respuestas: list[str] | None = None):
        self._respuestas = list(respuestas or [])
        self.entradas: list[str] = []  # lo que recibió, para revisarlo en los tests

    def generar_json(
        self, instrucciones: str, entrada: str, esquema: dict[str, Any]
    ) -> ResultadoLLM:
        self.entradas.append(entrada)
        texto = self._respuestas.pop(0) if self._respuestas else "{}"
        return ResultadoLLM(texto=texto, modelo="fake")
