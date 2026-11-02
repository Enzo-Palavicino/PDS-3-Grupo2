import logging

from app.canales.telegram.cliente import ErrorTelegram
from app.canales.telegram.polling import PollingTelegram


class TelegramFalso:
    """Reemplaza al cliente de la Bot API: entrega las respuestas en orden y, cuando se acaban,
    detiene el polling. Guarda el offset que recibió en cada llamada a getUpdates."""

    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.offsets = []
        self.polling = None

    def obtener_bot(self):
        return {"username": "bot_de_prueba_bot"}

    def obtener_actualizaciones(self, offset, tipos=None):
        self.offsets.append(offset)
        if not self.respuestas:
            self.polling.detener()
            return []
        respuesta = self.respuestas.pop(0)
        if isinstance(respuesta, Exception):
            raise respuesta
        return respuesta


def crear_polling(respuestas, manejador):
    telegram = TelegramFalso(respuestas)
    # Sin esperas entre reintentos, para que los tests terminen al instante.
    polling = PollingTelegram(telegram, manejador, espera_inicial_seg=0, espera_maxima_seg=0)
    telegram.polling = polling
    return polling, telegram


def test_entrega_los_updates_en_orden_y_avanza_el_offset():
    recibidos = []
    polling, telegram = crear_polling(
        [[{"update_id": 10}, {"update_id": 11}], [{"update_id": 12}]],
        lambda update: recibidos.append(update["update_id"]),
    )

    polling.ejecutar()

    assert recibidos == [10, 11, 12]
    # Cada getUpdates le confirma a Telegram lo recibido: offset = último update_id + 1.
    assert telegram.offsets == [None, 12, 13]


def test_un_error_en_el_manejador_no_detiene_el_lote_ni_se_registra_su_contenido(caplog):
    caplog.set_level(logging.INFO)
    recibidos = []

    def manejador(update):
        if update["update_id"] == 10:
            raise ValueError("dato clínico de prueba")
        recibidos.append(update["update_id"])

    polling, _ = crear_polling([[{"update_id": 10}, {"update_id": 11}]], manejador)

    polling.ejecutar()

    assert recibidos == [11]
    assert polling.offset == 12
    assert "No se pudo manejar el update 10 (ValueError)" in caplog.text
    assert "dato clínico de prueba" not in caplog.text


def test_reintenta_cuando_telegram_rechaza_get_updates(caplog):
    recibidos = []
    conflicto = ErrorTelegram(
        "getUpdates: Conflict: can't use getUpdates method while webhook is active", codigo=409
    )
    polling, _ = crear_polling(
        [conflicto, [{"update_id": 10}]], lambda update: recibidos.append(update["update_id"])
    )

    polling.ejecutar()

    assert recibidos == [10]
    assert "hay un webhook activo" in caplog.text
