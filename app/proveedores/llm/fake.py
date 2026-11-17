from typing import Any

from app.proveedores.llm.base import ProveedorLLM, ResultadoLLM


class ProveedorLLMFake(ProveedorLLM):
    """No usa IA: devuelve respuestas fijas.

    Por defecto devuelve un JSON vacío ({}), que deja todos los campos sin completar. Los tests
    le pasan las respuestas que necesitan, en orden. La lectura de imágenes también es
    simulada: nunca sirve como evidencia de que el modelo real acepta imágenes.
    """

    nombre = "fake"

    def __init__(
        self, respuestas: list[str] | None = None, *, lecturas: list[str] | None = None
    ):
        self._respuestas = list(respuestas or [])
        self._lecturas = list(lecturas or [])
        self.entradas: list[str] = []  # lo que recibió, para revisarlo en los tests
        self.imagenes: list[tuple[bytes, str]] = []

    def generar_json(
        self, instrucciones: str, entrada: str, esquema: dict[str, Any]
    ) -> ResultadoLLM:
        self.entradas.append(entrada)
        texto = self._respuestas.pop(0) if self._respuestas else "{}"
        return ResultadoLLM(texto=texto, modelo="fake")

    def leer_imagen(self, contenido: bytes, mime: str) -> ResultadoLLM:
        self.imagenes.append((contenido, mime))
        texto = self._lecturas.pop(0) if self._lecturas else "Lectura de prueba (proveedor fake)."
        return ResultadoLLM(texto=texto, modelo="fake")
