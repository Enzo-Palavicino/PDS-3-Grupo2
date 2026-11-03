"""Proveedores de LLM. Se elige uno con LLM_PROVIDER."""

from app.config import Config
from app.proveedores.llm.base import ProveedorLLM
from app.proveedores.llm.fake import ProveedorLLMFake
from app.proveedores.llm.openai import ProveedorLLMOpenAI


def crear_proveedor_llm(config: Config) -> ProveedorLLM:
    if config.llm_provider == "openai":
        return ProveedorLLMOpenAI(config.openai_api_key.get_secret_value(), config.llm_model)
    return ProveedorLLMFake()
