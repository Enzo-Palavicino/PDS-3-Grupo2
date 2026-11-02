import json
from datetime import UTC, datetime

import httpx2
import pytest

from app.canales.base import Ignorado, MensajeNormalizado
from app.canales.telegram.adaptador import AdaptadorTelegram

RECIBIDO_EN = datetime(2026, 11, 2, 15, 40, tzinfo=UTC)
SECRETO = "secreto-de-prueba"


def sin_red(peticion):
    raise AssertionError("este test no debería llamar a la Bot API")


@pytest.fixture
def adaptador(cliente_falso):
    cliente, _ = cliente_falso(sin_red)
    return AdaptadorTelegram(cliente, secreto_webhook=SECRETO)


# parsear


def test_texto(adaptador, cargar_update):
    assert adaptador.parsear(cargar_update("texto")) == MensajeNormalizado(
        canal="telegram",
        id_externo="55667788:412",
        remitente_externo="55667788",
        destino_respuesta="55667788",
        tipo="texto",
        recibido_en=RECIBIDO_EN,
        texto="Hola, esto es un mensaje de prueba",
    )


def test_nota_de_voz(adaptador, cargar_update):
    mensaje = adaptador.parsear(cargar_update("voz"))

    assert mensaje.tipo == "audio"
    assert mensaje.id_externo == "55667788:413"
    assert mensaje.audio_ref == "AwACAgEAAxkBAAIBnWVoz-voz-de-prueba"
    assert mensaje.audio_mime == "audio/ogg"
    assert mensaje.audio_tamano_bytes == 28417
    assert mensaje.audio_duracion_seg == 7
    assert mensaje.texto is None


def test_archivo_de_audio(adaptador, cargar_update):
    mensaje = adaptador.parsear(cargar_update("audio"))

    assert mensaje.tipo == "audio"
    assert mensaje.audio_ref == "CQACAgEAAxkBAAIBnmVoz-audio-de-prueba"
    assert mensaje.audio_mime == "audio/mpeg"


def test_sticker_no_soportado(adaptador, cargar_update):
    mensaje = adaptador.parsear(cargar_update("sticker"))

    assert mensaje.tipo == "no_soportado"
    assert mensaje.texto is None
    assert mensaje.audio_ref is None


def test_chat_de_grupo_se_ignora(adaptador, cargar_update):
    assert adaptador.parsear(cargar_update("grupo")) == Ignorado("chat no privado")


def test_start_con_codigo_es_comando(adaptador, cargar_update):
    mensaje = adaptador.parsear(cargar_update("start_codigo"))

    assert mensaje.tipo == "comando"
    assert mensaje.texto == "/start Ab3dE_f-9XyZ"


def test_respuesta_a_un_mensaje_del_bot(adaptador, cargar_update):
    mensaje = adaptador.parsear(cargar_update("respuesta"))

    assert mensaje.tipo == "texto"
    assert mensaje.id_externo == "55667788:421"
    assert mensaje.responde_a_id_externo == "55667788:420"


def test_mensaje_editado_se_ignora(adaptador, cargar_update):
    assert adaptador.parsear(cargar_update("editado")) == Ignorado("tipo de update no soportado")


def test_mensaje_de_otro_bot_se_ignora(adaptador, cargar_update):
    update = cargar_update("texto")
    update["message"]["from"]["is_bot"] = True

    assert adaptador.parsear(update) == Ignorado("mensaje de un bot")


# verificar_peticion


def test_acepta_el_secreto_correcto(adaptador):
    assert adaptador.verificar_peticion({"X-Telegram-Bot-Api-Secret-Token": SECRETO}, b"{}")
    # Los nombres de los encabezados HTTP no distinguen mayúsculas de minúsculas.
    assert adaptador.verificar_peticion({"x-telegram-bot-api-secret-token": SECRETO}, b"{}")


def test_rechaza_un_secreto_ausente_o_distinto(adaptador):
    assert not adaptador.verificar_peticion({}, b"{}")
    assert not adaptador.verificar_peticion({"X-Telegram-Bot-Api-Secret-Token": "otro"}, b"{}")


def test_sin_secreto_configurado_rechaza_todo(cliente_falso):
    cliente, _ = cliente_falso(sin_red)
    adaptador = AdaptadorTelegram(cliente, secreto_webhook=None)

    assert not adaptador.verificar_peticion({"X-Telegram-Bot-Api-Secret-Token": ""}, b"{}")


# Operaciones del canal


def test_enviar_texto_como_respuesta_al_mensaje_original(cliente_falso, token_bot):
    cliente, peticiones = cliente_falso(
        lambda peticion: httpx2.Response(
            200, json={"ok": True, "result": {"message_id": 430, "chat": {"id": 55667788}}}
        )
    )

    id_enviado = AdaptadorTelegram(cliente).enviar_texto(
        "55667788", "Recibido.", responder_a="55667788:412"
    )

    assert id_enviado == "55667788:430"
    assert peticiones[0].url.path == f"/bot{token_bot}/sendMessage"
    assert json.loads(peticiones[0].content) == {
        "chat_id": "55667788",
        "text": "Recibido.",
        "reply_parameters": {"message_id": 412, "allow_sending_without_reply": True},
    }


def test_enviar_texto_sin_responder_a_otro_mensaje(cliente_falso):
    cliente, peticiones = cliente_falso(
        lambda peticion: httpx2.Response(
            200, json={"ok": True, "result": {"message_id": 431, "chat": {"id": 55667788}}}
        )
    )

    AdaptadorTelegram(cliente).enviar_texto("55667788", "Hola.")

    assert json.loads(peticiones[0].content) == {"chat_id": "55667788", "text": "Hola."}


def test_borrar_mensaje(cliente_falso):
    cliente, peticiones = cliente_falso(
        lambda peticion: httpx2.Response(200, json={"ok": True, "result": True})
    )

    assert AdaptadorTelegram(cliente).borrar_mensaje("55667788", "55667788:412") is True
    assert json.loads(peticiones[0].content) == {"chat_id": "55667788", "message_id": 412}


def test_borrar_un_mensaje_que_ya_no_se_puede_borrar(cliente_falso):
    cliente, _ = cliente_falso(
        lambda peticion: httpx2.Response(
            400,
            json={
                "ok": False,
                "error_code": 400,
                "description": "Bad Request: message to delete not found",
            },
        )
    )

    assert AdaptadorTelegram(cliente).borrar_mensaje("55667788", "55667788:412") is False


def test_descargar_una_nota_de_voz(cliente_falso, token_bot):
    def responder(peticion):
        if peticion.url.path == f"/bot{token_bot}/getFile":
            return httpx2.Response(
                200, json={"ok": True, "result": {"file_id": "AwAC", "file_path": "voice/file_7.oga"}}
            )
        if peticion.url.path == f"/file/bot{token_bot}/voice/file_7.oga":
            return httpx2.Response(200, content=b"contenido-ogg")
        return httpx2.Response(404)

    cliente, peticiones = cliente_falso(responder)

    contenido, mime = AdaptadorTelegram(cliente).descargar_audio("AwAC")

    assert contenido == b"contenido-ogg"
    assert mime == "audio/ogg"
    assert json.loads(peticiones[0].content) == {"file_id": "AwAC"}
