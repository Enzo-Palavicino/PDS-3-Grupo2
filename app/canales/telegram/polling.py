"""Recepción de mensajes en modo polling, para desarrollo local.

Un hilo le pide a Telegram los updates nuevos con getUpdates. Es long polling: si no hay
mensajes, Telegram mantiene la petición abierta hasta 30 s antes de responder. Cada update se le
entrega a un manejador, y el offset (último update_id + 1) le indica a Telegram cuáles ya se
recibieron, para que no los vuelva a enviar.
"""

import logging
import threading
from collections.abc import Callable
from typing import Any

from app.canales.telegram.cliente import ClienteBotTelegram, ErrorTelegram
from app.logs import trazas_habilitadas

logger = logging.getLogger(__name__)

Manejador = Callable[[dict[str, Any]], None]


class PollingTelegram:
    def __init__(
        self,
        cliente: ClienteBotTelegram,
        manejador: Manejador,
        espera_inicial_seg: float = 2,
        espera_maxima_seg: float = 60,
    ):
        self._cliente = cliente
        self._manejador = manejador
        self._espera_inicial_seg = espera_inicial_seg
        self._espera_maxima_seg = espera_maxima_seg
        self._offset: int | None = None
        self._detenido = threading.Event()

    @property
    def offset(self) -> int | None:
        return self._offset

    def iniciar(self) -> None:
        """Arranca el polling en un hilo aparte, para no bloquear la aplicación."""
        # daemon: el hilo no impide que el proceso termine aunque esté esperando en getUpdates.
        threading.Thread(target=self.ejecutar, name="polling-telegram", daemon=True).start()

    def detener(self) -> None:
        self._detenido.set()

    def ejecutar(self) -> None:
        """Pide updates hasta que se llame a detener()."""
        self._saludar()
        espera = self._espera_inicial_seg
        while not self._detenido.is_set():
            try:
                updates = self._cliente.obtener_actualizaciones(self._offset, tipos=["message"])
            except ErrorTelegram as error:
                _registrar_error(error)
                # Si Telegram indica cuánto esperar (error 429), se respeta ese tiempo.
                self._detenido.wait(error.reintentar_en or espera)
                espera = min(espera * 2, self._espera_maxima_seg)
                continue
            espera = self._espera_inicial_seg
            self.procesar_lote(updates)

    def procesar_lote(self, updates: list[dict[str, Any]]) -> None:
        """Entrega cada update al manejador, en orden, y avanza el offset."""
        for update in updates:
            self._offset = update["update_id"] + 1
            try:
                self._manejador(update)
            except Exception as error:
                # Solo el id y el tipo de error: el update puede traer datos clínicos.
                logger.error(
                    "No se pudo manejar el update %s (%s)",
                    update["update_id"],
                    type(error).__name__,
                    exc_info=trazas_habilitadas(),
                )

    def _saludar(self) -> None:
        try:
            bot = self._cliente.obtener_bot()
        except ErrorTelegram as error:
            _registrar_error(error)
            return
        logger.info("Polling de Telegram iniciado para @%s", bot.get("username"))


def _registrar_error(error: ErrorTelegram) -> None:
    if error.codigo == 401:
        logger.error("Telegram rechazó el token del bot: revisa TELEGRAM_BOT_TOKEN")
    elif error.codigo == 409:
        logger.error(
            "Telegram rechazó getUpdates porque hay un webhook activo u otra instancia usando "
            "este bot. Para desarrollar, usa un bot propio."
        )
    else:
        logger.warning("Error al comunicarse con Telegram: %s", error)
