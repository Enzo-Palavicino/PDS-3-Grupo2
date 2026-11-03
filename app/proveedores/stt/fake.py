from pathlib import Path

from app.proveedores.stt.base import ProveedorSTT, ResultadoTranscripcion


class ProveedorSTTFake(ProveedorSTT):
    """Devuelve siempre el mismo texto. Sirve para los tests y para probar el flujo sin API key."""

    nombre = "fake"

    def __init__(self, texto: str = "Transcripción de prueba"):
        self._texto = texto

    def transcribir(
        self, ruta_audio: Path, mime: str, idioma: str = "es"
    ) -> ResultadoTranscripcion:
        return ResultadoTranscripcion(texto=self._texto, modelo="fake")
