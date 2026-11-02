"""Primer paso de cada mensaje recibido, común a todos los canales.

Tiene que ser rápido: no descarga audios ni llama a la IA. Decide qué hacer con el mensaje
(vincular la cuenta, rechazarlo o guardarlo para procesarlo después) y devuelve las respuestas
que hay que enviar. Quien la llama las envía: el polling, de inmediato; el webhook, después de
contestarle a Telegram, para no hacerlo esperar.
"""

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.canales.base import AdaptadorCanal, Ignorado, MensajeNormalizado
from app.modelos import TipoActor
from app.nucleo import textos
from app.nucleo.auditoria import Accion, registrar_evento
from app.nucleo.mensajes import registrar_mensaje_entrante
from app.nucleo.vinculacion import buscar_vinculo_activo, canjear_codigo

logger = logging.getLogger(__name__)

# Las plataformas no permiten que los bots descarguen archivos más grandes (Telegram: 20 MB).
TAMANO_MAXIMO_AUDIO_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True)
class Respuesta:
    destino: str
    texto: str
    responder_a: str | None = None  # id externo del mensaje al que responde


def ingerir(
    fabrica_de_sesiones: sessionmaker[Session], adaptador: AdaptadorCanal, evento: dict[str, Any]
) -> list[Respuesta]:
    """Traduce un evento del canal y lo procesa en su propia transacción."""
    mensaje = adaptador.parsear(evento)
    with fabrica_de_sesiones.begin() as sesion:
        return procesar_mensaje(sesion, mensaje)


def enviar_respuestas(adaptador: AdaptadorCanal, respuestas: list[Respuesta]) -> None:
    for respuesta in respuestas:
        adaptador.enviar_texto(respuesta.destino, respuesta.texto, respuesta.responder_a)


def procesar_mensaje(sesion: Session, mensaje: MensajeNormalizado | Ignorado) -> list[Respuesta]:
    if isinstance(mensaje, Ignorado):
        logger.info("Mensaje ignorado: %s", mensaje.motivo)
        return []

    comando, argumento = _separar_comando(mensaje)
    if comando == "/start" and argumento:
        return [_responder(mensaje, _canjear(sesion, mensaje, argumento), citar=False)]

    vinculo = buscar_vinculo_activo(sesion, mensaje.canal, mensaje.remitente_externo)
    if vinculo is None:
        if comando == "/start":
            return [_responder(mensaje, textos.START_SIN_CODIGO, citar=False)]
        registrar_evento(
            sesion,
            Accion.MENSAJE_RECHAZADO,
            actor_tipo=TipoActor.SISTEMA,
            detalle={
                "canal": mensaje.canal,
                "remitente_externo": mensaje.remitente_externo,
                "tipo": mensaje.tipo,
            },
        )
        logger.info("Mensaje %s rechazado: remitente no vinculado", mensaje.id_externo)
        return [_responder(mensaje, textos.NO_AUTORIZADO)]

    if comando:
        # /start sin código de una cuenta ya vinculada, /ayuda o cualquier otro comando.
        return [_responder(mensaje, textos.AYUDA, citar=False)]
    if mensaje.tipo == "no_soportado":
        return [_responder(mensaje, textos.TIPO_NO_SOPORTADO)]
    if mensaje.tipo == "audio" and (mensaje.audio_tamano_bytes or 0) > TAMANO_MAXIMO_AUDIO_BYTES:
        return [_responder(mensaje, textos.AUDIO_DEMASIADO_LARGO)]

    fila = registrar_mensaje_entrante(sesion, mensaje, vinculo.profesional_id)
    if fila is None:
        # Reintento de un mensaje que ya se recibió y se respondió.
        logger.info("Mensaje %s duplicado: se ignora", mensaje.id_externo)
        return []
    registrar_evento(
        sesion,
        Accion.MENSAJE_RECIBIDO,
        actor_tipo=TipoActor.PROFESIONAL,
        actor_id=vinculo.profesional_id,
        entidad="mensaje",
        entidad_id=fila.id,
        detalle={"canal": mensaje.canal, "tipo": mensaje.tipo},
    )
    logger.info("Mensaje %s guardado con id %s (%s)", mensaje.id_externo, fila.id, mensaje.tipo)
    return [_responder(mensaje, textos.RECIBIDO)]


def _separar_comando(mensaje: MensajeNormalizado) -> tuple[str | None, str]:
    """Separa el comando de su argumento: "/start abc" da ("/start", "abc").

    Si el mensaje no es un comando, devuelve (None, "").
    """
    if mensaje.tipo != "comando" or not mensaje.texto:
        return None, ""
    comando, _, argumento = mensaje.texto.partition(" ")
    # En algunos clientes de Telegram el comando llega como /start@nombre_del_bot.
    return comando.split("@")[0].lower(), argumento.strip()


def _canjear(sesion: Session, mensaje: MensajeNormalizado, codigo: str) -> str:
    vinculo = canjear_codigo(sesion, mensaje.canal, mensaje.remitente_externo, codigo)
    if vinculo is None:
        logger.info("Código de vinculación rechazado para el mensaje %s", mensaje.id_externo)
        return textos.CODIGO_INVALIDO
    logger.info("Cuenta vinculada: vínculo %s", vinculo.id)
    return textos.VINCULACION_EXITOSA


def _responder(mensaje: MensajeNormalizado, texto: str, citar: bool = True) -> Respuesta:
    # citar: la respuesta aparece como respuesta al mensaje original, para saber a cuál se refiere.
    return Respuesta(mensaje.destino_respuesta, texto, mensaje.id_externo if citar else None)
