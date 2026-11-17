"""Interfaz de los proveedores de LLM.

Un proveedor pide al modelo un JSON estructurado o la lectura literal de una imagen. La
extracción y validación de campos la decide el núcleo (app/nucleo/extraccion.py), así que se
cambia un proveedor por otro con LLM_PROVIDER sin tocar el resto del código.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


class ErrorLLM(Exception):
    """El modelo no entregó una respuesta usable (por ejemplo, porque quedó cortada)."""


@dataclass(frozen=True)
class ResultadoLLM:
    texto: str  # JSON de la extracción, o texto literal de la imagen
    modelo: str


class ProveedorLLM(ABC):
    nombre: str  # se guarda con cada extracción, para saber de dónde salió

    @abstractmethod
    def generar_json(
        self, instrucciones: str, entrada: str, esquema: dict[str, Any]
    ) -> ResultadoLLM:
        """Pide al modelo un JSON que cumpla el esquema (JSON Schema)."""

    @abstractmethod
    def leer_imagen(self, contenido: bytes, mime: str) -> ResultadoLLM:
        """Lee una imagen JPG/PNG validada, sin interpretar ni completar datos.

        Devuelve el texto literal, con [ilegible] donde no puede leer, y el modelo usado.
        La imagen no está seudonimizada: en la demo solo se envían documentos ficticios.
        """
