"""Proveedores de transcripción de audio. Se elige uno con STT_PROVIDER."""

from app.config import Config
from app.proveedores.stt.base import ProveedorSTT
from app.proveedores.stt.fake import ProveedorSTTFake
from app.proveedores.stt.openai import ProveedorSTTOpenAI


def crear_proveedor_stt(config: Config) -> ProveedorSTT:
    if config.stt_provider == "openai":
        return ProveedorSTTOpenAI(config.openai_api_key.get_secret_value(), config.stt_model)
    return ProveedorSTTFake()
