"""Interfaz de los proveedores de transcripción de audio (speech-to-text).

Todos los proveedores cumplen la misma interfaz, así que se cambia uno por otro con STT_PROVIDER
sin tocar el resto del código.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ResultadoTranscripcion:
    texto: str
    modelo: str
    # Fragmentos con sus tiempos ([{"inicio": 0.0, "fin": 2.5, "texto": "..."}]), si el
    # proveedor los entrega.
    segmentos: list[dict[str, Any]] | None = None
    duracion_seg: float | None = None


class ProveedorSTT(ABC):
    nombre: str  # se guarda con cada transcripción, para saber de dónde salió

    @abstractmethod
    def transcribir(
        self, ruta_audio: Path, mime: str, idioma: str = "es"
    ) -> ResultadoTranscripcion:
        """Transcribe el archivo de audio. idioma es un código ISO 639-1, como "es"."""
