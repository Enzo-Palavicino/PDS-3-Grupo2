"""Transcripción con la API de OpenAI.

Un audio no se puede seudonimizar antes de transcribirlo, así que este proveedor recibe datos
identificables. En producción debe usarse una cuenta configurada sin retención de datos, o un
modelo local como Whisper. En desarrollo y en la demo, solo datos ficticios.
"""

from pathlib import Path

from openai import OpenAI

from app.proveedores.stt.base import ProveedorSTT, ResultadoTranscripcion


class ProveedorSTTOpenAI(ProveedorSTT):
    nombre = "openai"

    def __init__(self, api_key: str, modelo: str, cliente: OpenAI | None = None):
        self._modelo = modelo
        # Los reintentos los maneja el worker: aquí solo se reintenta una vez un error de red.
        self._cliente = cliente or OpenAI(api_key=api_key, timeout=120, max_retries=1)

    def transcribir(
        self, ruta_audio: Path, mime: str, idioma: str = "es"
    ) -> ResultadoTranscripcion:
        respuesta = self._cliente.audio.transcriptions.create(
            model=self._modelo,
            # Nombre con extensión y tipo de contenido: así la API reconoce el formato del audio.
            file=(ruta_audio.name, ruta_audio.read_bytes(), mime),
            language=idioma,
        )
        return ResultadoTranscripcion(texto=respuesta.text, modelo=self._modelo)
