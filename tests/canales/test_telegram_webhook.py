import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import main
from app.canales.telegram.adaptador import ENCABEZADO_SECRETO
from app.config import Config
from app.modelos import MensajeEntrante, VinculoCanal
from app.nucleo import textos

SECRETO = "secreto-de-prueba"


class TelegramFalso:
    """Reemplaza al cliente de la Bot API: guarda lo que la aplicación le pide."""

    def __init__(self):
        self.webhooks = []  # (url, secreto, tipos)
        self.enviados = []  # textos enviados al chat

    def configurar_webhook(self, url, secreto, tipos):
        self.webhooks.append((url, secreto, tipos))

    def obtener_bot(self):
        return {"username": "bot_de_prueba_bot"}

    def enviar_mensaje(self, chat_id, texto, responder_a=None):
        self.enviados.append(texto)
        return {"message_id": 900 + len(self.enviados), "chat": {"id": int(chat_id)}}

    def enviar_accion(self, chat_id, accion="typing"):
        pass

    def borrar_mensaje(self, chat_id, message_id):
        pass


@pytest.fixture
def telegram(monkeypatch) -> TelegramFalso:
    falso = TelegramFalso()
    monkeypatch.setattr(main, "ClienteBotTelegram", lambda token: falso)
    return falso


@pytest.fixture
def cliente(telegram, url_bd, sesion, profesional):
    # La cuenta 55667788 (la de los updates de ejemplo) queda vinculada.
    sesion.add(VinculoCanal(profesional_id=profesional.id, canal="telegram", id_externo="55667788"))
    sesion.commit()
    config = Config(
        _env_file=None,
        database_url=url_bd,
        secret_key="clave-de-sesion-de-prueba",
        telegram_mode="webhook",
        telegram_bot_token="123456789:TOKEN-FALSO",
        telegram_webhook_secret=SECRETO,
        public_base_url="https://pds3.example",
    )
    with TestClient(main.crear_app(config)) as cliente:
        yield cliente


def contar_mensajes(sesion) -> int:
    sesion.commit()  # cierra la transacción anterior, para ver lo que escribió la aplicación
    cantidad = sesion.scalar(select(func.count()).select_from(MensajeEntrante))
    sesion.commit()  # y la de esta lectura, para no bloquear al worker, que escribe en paralelo
    return cantidad


def test_al_arrancar_configura_el_webhook_con_su_secreto(cliente, telegram):
    assert telegram.webhooks == [("https://pds3.example/webhooks/telegram", SECRETO, ["message"])]


def test_sin_el_secreto_responde_401_y_no_guarda_nada(cliente, cargar_update, sesion):
    respuesta = cliente.post("/webhooks/telegram", json=cargar_update("texto"))

    assert respuesta.status_code == 401
    assert contar_mensajes(sesion) == 0


def test_con_un_secreto_distinto_responde_401(cliente, cargar_update, sesion):
    respuesta = cliente.post(
        "/webhooks/telegram", json=cargar_update("texto"), headers={ENCABEZADO_SECRETO: "otro"}
    )

    assert respuesta.status_code == 401
    assert contar_mensajes(sesion) == 0


def test_con_el_secreto_guarda_el_mensaje_y_responde_en_el_chat(
    cliente, cargar_update, sesion, telegram
):
    respuesta = cliente.post(
        "/webhooks/telegram", json=cargar_update("texto"), headers={ENCABEZADO_SECRETO: SECRETO}
    )

    assert respuesta.status_code == 200
    assert respuesta.json() == {"ok": True}
    assert contar_mensajes(sesion) == 1
    assert textos.RECIBIDO in telegram.enviados


def test_un_reintento_de_telegram_no_duplica_el_mensaje(cliente, cargar_update, sesion, telegram):
    for _ in range(2):
        cliente.post(
            "/webhooks/telegram",
            json=cargar_update("texto"),
            headers={ENCABEZADO_SECRETO: SECRETO},
        )

    assert contar_mensajes(sesion) == 1
    assert telegram.enviados.count(textos.RECIBIDO) == 1


def test_un_cuerpo_que_no_es_json_se_rechaza(cliente):
    respuesta = cliente.post(
        "/webhooks/telegram", content=b"no es json", headers={ENCABEZADO_SECRETO: SECRETO}
    )

    assert respuesta.status_code == 400


def test_sin_modo_webhook_la_ruta_no_recibe_mensajes(url_bd):
    config = Config(_env_file=None, database_url=url_bd, secret_key="clave-de-sesion-de-prueba")
    with TestClient(main.crear_app(config)) as cliente:
        respuesta = cliente.post("/webhooks/telegram", json={}, headers={ENCABEZADO_SECRETO: "x"})

    assert respuesta.status_code == 404
