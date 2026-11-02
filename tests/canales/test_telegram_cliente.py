import json

import httpx2
import pytest

from app.canales.telegram.cliente import ErrorTelegram


def test_llama_al_metodo_de_la_bot_api(cliente_falso, token_bot):
    cliente, peticiones = cliente_falso(
        lambda peticion: httpx2.Response(
            200, json={"ok": True, "result": {"username": "bot_de_prueba_bot"}}
        )
    )

    assert cliente.obtener_bot() == {"username": "bot_de_prueba_bot"}
    assert peticiones[0].method == "POST"
    assert str(peticiones[0].url) == f"https://api.telegram.org/bot{token_bot}/getMe"


def test_no_envia_parametros_vacios(cliente_falso):
    cliente, peticiones = cliente_falso(
        lambda peticion: httpx2.Response(200, json={"ok": True, "result": []})
    )

    assert cliente.obtener_actualizaciones(offset=None, tipos=["message"]) == []
    assert json.loads(peticiones[0].content) == {"timeout": 30, "allowed_updates": ["message"]}


def test_error_de_telegram_trae_la_descripcion_pero_no_el_token(cliente_falso, token_bot):
    cliente, _ = cliente_falso(
        lambda peticion: httpx2.Response(
            400, json={"ok": False, "error_code": 400, "description": "Bad Request: chat not found"}
        )
    )

    with pytest.raises(ErrorTelegram) as error:
        cliente.enviar_mensaje("1", "hola")

    assert str(error.value) == "sendMessage: Bad Request: chat not found"
    assert error.value.codigo == 400
    assert token_bot not in str(error.value)


def test_limite_de_mensajes_indica_cuanto_esperar(cliente_falso):
    cliente, _ = cliente_falso(
        lambda peticion: httpx2.Response(
            429,
            json={
                "ok": False,
                "error_code": 429,
                "description": "Too Many Requests: retry after 5",
                "parameters": {"retry_after": 5},
            },
        )
    )

    with pytest.raises(ErrorTelegram) as error:
        cliente.enviar_mensaje("1", "hola")

    assert error.value.codigo == 429
    assert error.value.reintentar_en == 5


def test_error_de_red_no_expone_el_token(cliente_falso, token_bot):
    def sin_conexion(peticion):
        raise httpx2.ConnectError(f"no se pudo conectar a {peticion.url}", request=peticion)

    cliente, _ = cliente_falso(sin_conexion)

    with pytest.raises(ErrorTelegram) as error:
        cliente.obtener_bot()

    assert str(error.value) == "getMe: error de red (ConnectError)"
    assert error.value.codigo is None
    # El error original, cuyo mensaje sí incluye la URL con el token, no queda encadenado.
    assert error.value.__cause__ is None
    assert error.value.__suppress_context__


def test_respuesta_que_no_es_json(cliente_falso):
    cliente, _ = cliente_falso(lambda peticion: httpx2.Response(502, text="Bad Gateway"))

    with pytest.raises(ErrorTelegram) as error:
        cliente.obtener_bot()

    assert error.value.codigo == 502


def test_descarga_fallida_no_expone_el_token(cliente_falso, token_bot):
    cliente, _ = cliente_falso(lambda peticion: httpx2.Response(404))

    with pytest.raises(ErrorTelegram) as error:
        cliente.descargar_archivo("voice/file_7.oga")

    assert error.value.codigo == 404
    assert token_bot not in str(error.value)
