"""Interfaz de los proveedores de LLM.

Un proveedor solo sabe pedirle al modelo un JSON que cumpla un esquema. Qué se le pide, con qué
instrucciones, y cómo se valida la respuesta lo decide el núcleo (app/nucleo/extraccion.py), así
que se cambia un proveedor por otro con LLM_PROVIDER sin tocar el resto del código.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


class ErrorLLM(Exception):
    """El modelo no entregó una respuesta usable (por ejemplo, porque quedó cortada)."""


@dataclass(frozen=True)
class ResultadoLLM:
    texto: str  # el JSON que devolvió el modelo, como texto
    modelo: str


class ProveedorLLM(ABC):
    nombre: str  # se guarda con cada extracción, para saber de dónde salió

    @abstractmethod
    def generar_json(
        self, instrucciones: str, entrada: str, esquema: dict[str, Any]
    ) -> ResultadoLLM:
        """Pide al modelo un JSON que cumpla el esquema (JSON Schema)."""
