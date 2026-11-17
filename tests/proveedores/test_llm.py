import json
from base64 import b64encode

import httpx2
import pytest
from openai import OpenAI

from app.config import Config
from app.logs import configurar_logs
from app.proveedores.llm import crear_proveedor_llm
from app.proveedores.llm.base import ErrorLLM
from app.proveedores.llm.fake import ProveedorLLMFake
from app.proveedores.llm.openai import INSTRUCCIONES_LECTURA, ProveedorLLMOpenAI

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


@pytest.mark.parametrize("mime", ["image/jpeg", "image/png"])
def test_envia_la_imagen_y_devuelve_texto_literal_con_el_modelo_usado(mime):
    peticiones = []
    texto = "Fecha: 12/06/2025\nObservaciones: [ilegible]\nControl en dos semanas."
    respuesta = respuesta_de_chat(texto)
    respuesta["model"] = "modelo-version-prueba"
    proveedor = ProveedorLLMOpenAI("clave", "gpt-6-luna", cliente_falso(respuesta, peticiones))

    resultado = proveedor.leer_imagen(b"imagen-ficticia", mime)

    assert resultado.texto == texto
    assert resultado.modelo == "modelo-version-prueba"
    cuerpo = json.loads(peticiones[0].read())
    assert cuerpo["model"] == "gpt-6-luna"
    assert cuerpo["messages"][0] == {"role": "system", "content": INSTRUCCIONES_LECTURA}
    assert "[ilegible]" in cuerpo["messages"][0]["content"]
    assert "No reconstruyas texto tachado" in cuerpo["messages"][0]["content"]
    assert cuerpo["reasoning_effort"] == "medium"
    assert cuerpo["messages"][1]["content"][1] == {
        "type": "image_url",
        "image_url": {
            "url": f"data:{mime};base64,{b64encode(b'imagen-ficticia').decode('ascii')}",
            "detail": "high",
        },
    }
    assert "response_format" not in cuerpo


@pytest.mark.parametrize(
    "respuesta,motivo",
    [
        (respuesta_de_chat("parcial", finish_reason="length"), "incompleta"),
        (respuesta_de_chat(None, refusal="rechazo"), "se negó"),
        (respuesta_de_chat(""), "vacía"),
        (respuesta_de_chat("   "), "vacía"),
        (respuesta_de_chat(None), "vacía"),
        (respuesta_de_chat("texto") | {"choices": []}, "no devolvió"),
    ],
)
def test_no_presenta_una_lectura_fallida_como_valida(respuesta, motivo):
    proveedor = ProveedorLLMOpenAI("clave", "gpt-6-luna", cliente_falso(respuesta, []))

    with pytest.raises(ErrorLLM, match=motivo):
        proveedor.leer_imagen(b"imagen-ficticia", "image/png")


@pytest.mark.parametrize("contenido,mime", [(b"", "image/png"), (b"pdf", "application/pdf")])
def test_no_envia_un_tipo_incompatible_a_la_api(contenido, mime):
    peticiones = []
    proveedor = ProveedorLLMOpenAI(
        "clave", "gpt-6-luna", cliente_falso(respuesta_de_chat("texto"), peticiones)
    )

    with pytest.raises(ErrorLLM, match="JPG o PNG"):
        proveedor.leer_imagen(contenido, mime)

    assert peticiones == []


def test_el_fake_separa_las_lecturas_de_las_respuestas_json():
    proveedor = ProveedorLLMFake(['{"a": 1}'], lecturas=["Primera", "Segunda [ilegible]"])

    assert proveedor.leer_imagen(b"uno", "image/png").texto == "Primera"
    assert proveedor.generar_json("instrucciones", "entrada", ESQUEMA).texto == '{"a": 1}'
    assert proveedor.leer_imagen(b"dos", "image/jpeg").texto == "Segunda [ilegible]"
    assert proveedor.imagenes == [(b"uno", "image/png"), (b"dos", "image/jpeg")]


def test_los_logs_del_sdk_no_publican_imagen_ni_texto_aun_en_debug(caplog):
    caplog.set_level("DEBUG")
    configurar_logs("DEBUG")
    contenido = b"DOCUMENTO_FICTICIO_RESERVADO"
    respuesta = respuesta_de_chat("LECTURA_FICTICIA_RESERVADA")
    proveedor = ProveedorLLMOpenAI("clave", "gpt-6-luna", cliente_falso(respuesta, []))

    proveedor.leer_imagen(contenido, "image/png")

    assert "LECTURA_FICTICIA_RESERVADA" not in caplog.text
    assert b64encode(contenido).decode("ascii") not in caplog.text
