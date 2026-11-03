import hashlib
import hmac
import json
from copy import deepcopy

import httpx2
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select

from app import main
from app.canales.base import ErrorDeCanal, Ignorado
from app.canales.whatsapp.adaptador import AdaptadorWhatsApp
from app.canales.whatsapp.cliente import ClienteKapso
from app.config import Config
from app.modelos import (
    BorradorAtencion,
    EstadoMensaje,
    MensajeEntrante,
    Transcripcion,
    VinculoCanal,
)
from app.nucleo.vinculacion import generar_codigo

SECRETO = "secreto-de-prueba"
NUMERO_ID = "123456789"
REMITENTE = "56912345678"


def evento(texto="Atención de prueba", identificador="wamid.1"):
    return {
        "phone_number_id": NUMERO_ID,
        "message": {
            "id": identificador,
            "timestamp": "1793718000",
            "type": "text",
            "from": REMITENTE,
            "text": {"body": texto},
            "kapso": {
                "direction": "inbound",
                "status": "received",
                "origin": "cloud_api",
            },
        },
    }


class KapsoFalso:
    phone_number_id = NUMERO_ID

    def __init__(self):
        self.enviados = []
        self.cerrado = False

    def enviar_mensaje(self, destino, texto, responder_a=None):
        self.enviados.append((destino, texto, responder_a))
        return f"wamid.bot{len(self.enviados)}"

    def descargar_audio(self, referencia):
        return b"audio sintetico", "audio/ogg"

    def cerrar(self):
        self.cerrado = True


@pytest.fixture
def adaptador():
    return AdaptadorWhatsApp(KapsoFalso(), SECRETO)


def firma(cuerpo):
    return hmac.new(SECRETO.encode(), cuerpo, hashlib.sha256).hexdigest()


def enviar(cliente, datos, firma_incorrecta=False, tipo="whatsapp.message.received"):
    cuerpo = json.dumps(datos).encode()
    return cliente.post(
        "/webhooks/whatsapp",
        content=cuerpo,
        headers={
            "X-Webhook-Signature": "incorrecta" if firma_incorrecta else firma(cuerpo),
            "X-Webhook-Event": tipo,
        },
    )


def test_firma_depende_de_los_bytes_originales(adaptador):
    cuerpo = b'{"a": 1}'
    assert adaptador.verificar_peticion({"x-webhook-signature": firma(cuerpo)}, cuerpo)
    assert not adaptador.verificar_peticion(
        {"X-Webhook-Signature": firma(cuerpo)}, b'{"a":1}'
    )
    assert not adaptador.verificar_peticion({}, cuerpo)
    assert not adaptador.verificar_peticion({"X-Webhook-Signature": "ñ"}, cuerpo)


def test_texto_comando_y_respuesta(adaptador):
    datos = evento("/start codigo")
    datos["message"]["context"] = {"id": "wamid.anterior"}
    mensaje = adaptador.parsear(datos)
    assert mensaje.tipo == "comando"
    assert mensaje.responde_a_id_externo == "wamid.anterior"
    assert mensaje.canal == "whatsapp"
    assert mensaje.destino_respuesta == REMITENTE


def test_audio_normaliza_mime_y_no_usa_transcripcion_de_kapso(adaptador):
    datos = evento()
    datos["message"].update(
        type="audio", audio={"id": "media123", "mime_type": "audio/ogg; codecs=opus"}
    )
    datos["message"]["kapso"].update(
        media_data={"byte_size": 42}, transcript={"text": "ignorar"}
    )
    mensaje = adaptador.parsear(datos)
    assert mensaje.audio_ref == "media123"
    assert mensaje.audio_mime == "audio/ogg"
    assert mensaje.audio_tamano_bytes == 42
    assert mensaje.texto is None


@pytest.mark.parametrize(
    "cambio",
    [
        {"kapso": {"direction": "outbound"}},
        {"kapso": {"direction": "inbound", "passive": True}},
        {"kapso": {"direction": "inbound", "origin": "history_sync"}},
        {"timestamp": "invalido"},
        {"from": "grupo@g.us"},
        {"text": None},
        {"id": None},
    ],
)
def test_ignora_eventos_no_utilizables(adaptador, cambio):
    datos = evento()
    datos["message"].update(cambio)
    assert isinstance(adaptador.parsear(datos), Ignorado)


def test_no_acepta_otro_numero_receptor(adaptador):
    datos = evento()
    datos["phone_number_id"] = "otro"
    assert isinstance(adaptador.parsear(datos), Ignorado)


def test_identidad_sin_telefono(adaptador):
    datos = evento()
    del datos["message"]["from"]
    datos["message"]["from_user_id"] = "US.1234567"
    assert adaptador.parsear(datos).destino_respuesta == "US.1234567"


@pytest.mark.parametrize(
    "destino,campo", [(REMITENTE, "to"), ("US.1234567", "recipient")]
)
def test_envio_api_con_contexto(destino, campo):
    def responder(request):
        assert (
            str(request.url)
            == f"https://api.kapso.ai/meta/whatsapp/v24.0/{NUMERO_ID}/messages"
        )
        assert request.headers["X-API-Key"] == "clave-falsa"
        datos = json.loads(request.content)
        assert datos[campo] == destino
        assert datos["context"] == {"message_id": "wamid.original"}
        assert datos["text"]["body"] == "Recibido"
        return httpx2.Response(200, json={"messages": [{"id": "wamid.respuesta"}]})

    with httpx2.Client(transport=httpx2.MockTransport(responder)) as http:
        cliente = ClienteKapso("clave-falsa", NUMERO_ID, http)
        assert (
            cliente.enviar_mensaje(destino, "Recibido", "wamid.original")
            == "wamid.respuesta"
        )


def test_descarga_audio_autenticada_y_acotada():
    peticiones = []

    def responder(request):
        peticiones.append(request)
        if request.url.path.endswith("/media123"):
            assert request.url.params["phone_number_id"] == NUMERO_ID
            return httpx2.Response(
                200,
                json={
                    "download_url": "https://api.kapso.ai/meta/whatsapp/media_download?token=falso",
                    "mime_type": "audio/ogg; codecs=opus",
                    "file_size": "5",
                },
            )
        assert "x-api-key" not in request.headers
        return httpx2.Response(200, content=b"audio")

    with httpx2.Client(transport=httpx2.MockTransport(responder)) as http:
        assert ClienteKapso("clave-falsa", NUMERO_ID, http).descargar_audio(
            "media123"
        ) == (b"audio", "audio/ogg")
    assert len(peticiones) == 2


@pytest.mark.parametrize(
    "url",
    [
        "http://api.kapso.ai/media",
        "https://evil.example/audio",
        "https://api.kapso.ai@evil.example/audio",
    ],
)
def test_no_descarga_desde_urls_ajenas(url):
    def responder(request):
        return httpx2.Response(200, json={"download_url": url})

    with (
        httpx2.Client(transport=httpx2.MockTransport(responder)) as http,
        pytest.raises(ErrorDeCanal, match="no permitida"),
    ):
        ClienteKapso("clave-falsa", NUMERO_ID, http).descargar_audio("media123")


def test_error_no_expone_respuesta_y_respeta_retry_after():
    def responder(request):
        return httpx2.Response(
            429, headers={"Retry-After": "45"}, json={"error": "dato privado"}
        )

    with (
        httpx2.Client(transport=httpx2.MockTransport(responder)) as http,
        pytest.raises(ErrorDeCanal) as error,
    ):
        ClienteKapso("clave-falsa", NUMERO_ID, http).enviar_mensaje(
            REMITENTE, "registro"
        )
    assert str(error.value) == "Kapso: HTTP 429"
    assert error.value.reintentar_en == 45


@pytest.fixture
def aplicacion(monkeypatch, url_bd, tmp_path):
    kapso = KapsoFalso()
    monkeypatch.setattr(main, "ClienteKapso", lambda *args: kapso)
    # Procesamiento determinista: se ejecuta el worker real manualmente al afirmar resultados.
    monkeypatch.setattr(main.Worker, "iniciar", lambda self: None)
    config = Config(
        _env_file=None,
        database_url=url_bd,
        secret_key="sesion-de-prueba",
        whatsapp_enabled=True,
        kapso_api_key="clave-falsa",
        kapso_phone_number_id=NUMERO_ID,
        kapso_webhook_secret=SECRETO,
        whatsapp_phone_number="56987654321",
        public_base_url="https://pds.example",
        audio_dir=tmp_path / "audios",
    )
    with TestClient(main.crear_app(config)) as cliente:
        yield cliente, kapso
    assert kapso.cerrado


def test_webhook_rechaza_firma_incorrecta_y_json_invalido(aplicacion, sesion):
    cliente, _ = aplicacion
    assert enviar(cliente, evento(), firma_incorrecta=True).status_code == 401
    cuerpo = b"no json"
    assert (
        cliente.post(
            "/webhooks/whatsapp",
            content=cuerpo,
            headers={"X-Webhook-Signature": firma(cuerpo)},
        ).status_code
        == 400
    )
    assert enviar(cliente, []).status_code == 400
    assert sesion.scalar(select(func.count()).select_from(MensajeEntrante)) == 0


def test_vincular_texto_audio_y_duplicados_crean_borradores(
    aplicacion, sesion, profesional
):
    cliente, kapso = aplicacion
    codigo = generar_codigo(sesion, profesional.id).codigo
    sesion.commit()
    assert enviar(cliente, evento(f"/start {codigo}", "wamid.link")).status_code == 200
    texto = evento()
    audio = evento(identificador="wamid.audio")
    audio["message"].update(type="audio", audio={"id": "media123"})
    for _ in range(2):
        assert (
            enviar(cliente, {"batch": True, "data": [texto, audio]}).status_code == 200
        )
    assert cliente.app.state.worker.procesar_pendientes() == 2
    sesion.expire_all()
    mensajes = list(sesion.scalars(select(MensajeEntrante)))
    assert len(mensajes) == 2
    assert all(
        m.estado == EstadoMensaje.LISTO and m.canal == "whatsapp" for m in mensajes
    )
    assert sesion.scalar(select(func.count()).select_from(Transcripcion)) == 1
    assert sesion.scalar(select(func.count()).select_from(BorradorAtencion)) == 2
    assert sesion.scalar(select(VinculoCanal)).canal == "whatsapp"
    assert not list(cliente.app.state.config.audio_dir.iterdir())
    assert len(kapso.enviados) == 5  # vinculación, dos recibidos, dos borradores


def test_no_autorizado_y_estados_no_crean_registros(aplicacion, sesion):
    cliente, kapso = aplicacion
    assert enviar(cliente, evento()).status_code == 200
    assert len(kapso.enviados) == 1
    assert (
        enviar(cliente, evento(), tipo="whatsapp.message.delivered").status_code == 200
    )
    assert sesion.scalar(select(func.count()).select_from(MensajeEntrante)) == 0
    assert len(kapso.enviados) == 1


def test_whatsapp_apagado_no_recibe(url_bd):
    with TestClient(
        main.crear_app(Config(_env_file=None, database_url=url_bd))
    ) as cliente:
        assert enviar(cliente, evento()).status_code == 404


def test_lote_invalido_se_rechaza(aplicacion):
    cliente, _ = aplicacion
    assert enviar(cliente, {"batch": True, "data": [None]}).status_code == 400


def test_respuesta_completa_el_mismo_borrador(aplicacion, sesion, profesional):
    cliente, _ = aplicacion
    sesion.add(
        VinculoCanal(
            profesional_id=profesional.id, canal="whatsapp", id_externo=REMITENTE
        )
    )
    sesion.commit()
    enviar(cliente, evento())
    cliente.app.state.worker.procesar_pendientes()
    borrador = sesion.scalar(select(BorradorAtencion))
    respuesta_id = borrador.mensaje_bot_id_externo
    sesion.commit()
    respuesta = deepcopy(evento("Más antecedentes de prueba", "wamid.2"))
    respuesta["message"]["context"] = {"id": respuesta_id}
    enviar(cliente, respuesta)
    cliente.app.state.worker.procesar_pendientes()
    assert sesion.scalar(select(func.count()).select_from(BorradorAtencion)) == 1


def test_whatsapp_y_telegram_comparten_el_worker(
    aplicacion, monkeypatch, cargar_update, sesion, profesional
):
    from tests.canales.test_telegram_webhook import TelegramFalso

    cliente_wa, _ = aplicacion
    telegram = TelegramFalso()
    monkeypatch.setattr(main, "ClienteBotTelegram", lambda *args: telegram)
    config = cliente_wa.app.state.config.model_copy(
        update={
            "telegram_mode": "webhook",
            "telegram_bot_token": SecretStr("token-falso"),
            "telegram_webhook_secret": SecretStr(SECRETO),
        }
    )
    sesion.add_all(
        [
            VinculoCanal(
                profesional_id=profesional.id, canal="telegram", id_externo="55667788"
            ),
            VinculoCanal(
                profesional_id=profesional.id, canal="whatsapp", id_externo=REMITENTE
            ),
        ]
    )
    sesion.commit()
    with TestClient(main.crear_app(config)) as cliente:
        assert enviar(cliente, evento()).status_code == 200
        assert (
            cliente.post(
                "/webhooks/telegram",
                json=cargar_update("texto"),
                headers={
                    "X-Telegram-Bot-Api-Secret-Token": SECRETO,
                },
            ).status_code
            == 200
        )
        assert cliente.app.state.worker.procesar_pendientes() == 2
    assert set(sesion.scalars(select(MensajeEntrante.canal))) == {
        "telegram",
        "whatsapp",
    }
    assert set(sesion.scalars(select(MensajeEntrante.estado))) == {EstadoMensaje.LISTO}


@pytest.mark.parametrize(
    "campo,valor",
    [
        ("kapso_api_key", None),
        ("kapso_webhook_secret", ""),
        ("kapso_phone_number_id", ""),
        ("whatsapp_phone_number", "+56912345678"),
        ("public_base_url", "http://localhost:8000"),
    ],
)
def test_configuracion_incompleta_no_arranca(campo, valor):
    datos = {
        "whatsapp_enabled": True,
        "kapso_api_key": "clave-falsa",
        "kapso_webhook_secret": SECRETO,
        "kapso_phone_number_id": NUMERO_ID,
        "whatsapp_phone_number": REMITENTE,
        "public_base_url": "https://pds.example",
    }
    datos[campo] = valor
    with pytest.raises(ValueError):
        Config(_env_file=None, **datos)


def test_descarga_rechaza_tamano_real_aunque_metadata_sea_menor(monkeypatch):
    from app.canales.whatsapp import cliente as modulo

    monkeypatch.setattr(modulo, "MAXIMO_AUDIO", 4)

    def responder(request):
        if request.url.path.endswith("/media123"):
            return httpx2.Response(
                200,
                json={
                    "download_url": "https://api.kapso.ai/meta/whatsapp/media_download?token=falso",
                    "file_size": "1",
                },
            )
        return httpx2.Response(200, content=b"12345")

    with (
        httpx2.Client(transport=httpx2.MockTransport(responder)) as http,
        pytest.raises(ErrorDeCanal, match="supera"),
    ):
        ClienteKapso("clave-falsa", NUMERO_ID, http).descargar_audio("media123")


@pytest.mark.parametrize("existente", [True, False])
def test_registro_webhook_no_duplica_y_usa_configuracion_v2(aplicacion, existente):
    from scripts.configurar_whatsapp import registrar

    cliente, _ = aplicacion
    config = cliente.app.state.config
    peticiones = []

    def responder(request):
        peticiones.append(request)
        if request.method == "GET":
            return httpx2.Response(
                200,
                json={
                    "data": [{"url": "https://pds.example/webhooks/whatsapp"}]
                    if existente
                    else []
                },
            )
        datos = json.loads(request.content)["whatsapp_webhook"]
        assert datos["kind"] == "kapso"
        assert datos["events"] == ["whatsapp.message.received"]
        assert datos["secret_key"] == SECRETO
        assert datos["active"] is True
        assert datos["buffer_enabled"] is False
        return httpx2.Response(201, json={"data": {"id": "webhook1"}})

    with httpx2.Client(transport=httpx2.MockTransport(responder)) as http:
        resultado = registrar(config, http)
    assert SECRETO not in resultado
    assert len(peticiones) == (1 if existente else 2)
