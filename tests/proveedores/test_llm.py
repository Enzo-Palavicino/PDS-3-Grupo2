import json

import httpx2
import pytest
from openai import OpenAI

from app.config import Config
from app.proveedores.llm import crear_proveedor_llm
from app.proveedores.llm.base import ErrorLLM
from app.proveedores.llm.fake import ProveedorLLMFake
from app.proveedores.llm.openai import ProveedorLLMOpenAI

ESQUEMA = {
    "type": "object",
    "properties": {"a": {"type": "integer"}},
    "required": ["a"],
    "additionalProperties": False,
}


def cliente_falso(respuesta: dict, peticiones: list) -> OpenAI:
    """Cliente de OpenAI que, en vez de salir a internet, devuelve `respuesta`."""

    def responder(peticion: httpx2.Request) -> httpx2.Response:
        peticiones.append(peticion)
        return httpx2.Response(200, json=respuesta)

    return OpenAI(
        api_key="clave-de-prueba",
        http_client=httpx2.Client(transport=httpx2.MockTransport(responder)),
    )


def respuesta_de_chat(contenido, finish_reason="stop", refusal=None) -> dict:
    return {
        "id": "chatcmpl-prueba",
        "object": "chat.completion",
        "created": 0,
        "model": "gpt-6-luna",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": contenido, "refusal": refusal},
                "finish_reason": finish_reason,
            }
        ],
    }


def generar(respuesta: dict, peticiones: list | None = None):
    cliente = cliente_falso(respuesta, [] if peticiones is None else peticiones)
    return ProveedorLLMOpenAI("clave", "gpt-6-luna", cliente=cliente).generar_json(
        "Instrucciones", "Entrada", ESQUEMA
    )


def test_por_defecto_se_usa_el_llm_fake():
    assert isinstance(crear_proveedor_llm(Config(_env_file=None)), ProveedorLLMFake)


def test_con_llm_provider_openai_se_usa_gpt_6_luna():
    config = Config(_env_file=None, llm_provider="openai", openai_api_key="clave-de-prueba")

    proveedor = crear_proveedor_llm(config)

    assert isinstance(proveedor, ProveedorLLMOpenAI)
    assert proveedor.modelo == "gpt-6-luna"


def test_pide_un_json_estricto_con_el_esquema():
    peticiones = []

    resultado = generar(respuesta_de_chat('{"a": 1}'), peticiones)

    assert resultado.texto == '{"a": 1}'
    assert str(peticiones[0].url) == "https://api.openai.com/v1/chat/completions"
    cuerpo = json.loads(peticiones[0].read())
    assert cuerpo["model"] == "gpt-6-luna"
    assert cuerpo["messages"] == [
        {"role": "system", "content": "Instrucciones"},
        {"role": "user", "content": "Entrada"},
    ]
    assert cuerpo["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "respuesta", "strict": True, "schema": ESQUEMA},
    }
    assert cuerpo["reasoning_effort"] == "low"


def test_una_respuesta_cortada_es_un_error():
    with pytest.raises(ErrorLLM, match="length"):
        generar(respuesta_de_chat('{"a":', finish_reason="length"))


def test_si_el_modelo_se_niega_a_responder_es_un_error():
    with pytest.raises(ErrorLLM, match="se negó"):
        generar(respuesta_de_chat(None, refusal="No puedo ayudar con eso."))
