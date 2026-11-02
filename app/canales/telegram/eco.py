"""Manejador temporal para probar la conexión con Telegram: responde un eco de lo que recibe.

Solo para desarrollo, porque le responde a cualquiera que le escriba. Se reemplaza por la
ingesta real, que exige que el remitente esté vinculado.
"""

import logging
from typing import Any

from app.canales.base import Ignorado
from app.canales.telegram.adaptador import AdaptadorTelegram
from app.canales.telegram.polling import Manejador

logger = logging.getLogger(__name__)


def crear_manejador_eco(adaptador: AdaptadorTelegram) -> Manejador:
    def manejar(update: dict[str, Any]) -> None:
        mensaje = adaptador.parsear(update)
        if isinstance(mensaje, Ignorado):
            logger.info("Update %s ignorado: %s", update["update_id"], mensaje.motivo)
            return
        if mensaje.tipo == "audio":
            eco = f"Eco (audio de {mensaje.audio_duracion_seg} s)"
        elif mensaje.tipo == "no_soportado":
            eco = "Eco (tipo no soportado)"
        else:
            eco = f"Eco ({mensaje.tipo}): {mensaje.texto}"
        adaptador.enviar_texto(mensaje.destino_respuesta, eco, responder_a=mensaje.id_externo)
        logger.info("Eco enviado para el mensaje %s (%s)", mensaje.id_externo, mensaje.tipo)

    return manejar
