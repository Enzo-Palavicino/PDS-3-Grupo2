"""Procesamiento en segundo plano de cada mensaje que guardó la ingesta.

Los pasos dependen del estado del mensaje, y cada uno guarda su avance en la base de datos
antes del siguiente. Así, si un paso falla, el reintento sigue desde ese paso: por ejemplo, si
falló el envío de la respuesta, no se vuelve a llamar a la IA.

    recibido ─(audio: descargar y transcribir)─► transcrito ─(IA y borrador)─► extraido
             ─(responder en el chat)─► listo
"""

import logging
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.canales.base import AdaptadorCanal
from app.logs import trazas_habilitadas
from app.modelos import EstadoMensaje, MensajeEntrante, Residente, Transcripcion
from app.nucleo import textos
from app.nucleo.borradores import (
    armar_borrador,
    borrador_del_mensaje,
    texto_de_respuesta,
)
from app.proveedores.llm.base import ProveedorLLM
from app.proveedores.stt.base import ProveedorSTT

logger = logging.getLogger(__name__)

# Estados de los mensajes que todavía tienen pasos por hacer.
ESTADOS_PENDIENTES = (
    EstadoMensaje.RECIBIDO,
    EstadoMensaje.DESCARGADO,
    EstadoMensaje.TRANSCRITO,
    EstadoMensaje.EXTRAIDO,
)

# Extensión del archivo temporal según el tipo de audio: la API de transcripción la usa para
# reconocer el formato.
EXTENSIONES_AUDIO = {
    "audio/ogg": ".ogg",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/webm": ".webm",
}


@dataclass
class Contexto:
    """Lo que el procesamiento necesita del resto de la aplicación."""

    adaptadores: dict[str, AdaptadorCanal]  # un adaptador por canal: "telegram", "whatsapp"
    stt: ProveedorSTT
    llm: ProveedorLLM
    carpeta_audios: Path
    url_publica: str = "http://localhost:8000"  # base de los enlaces que envía el bot
    borrar_mensajes_importados: bool = False


def procesar(sesion: Session, mensaje: MensajeEntrante, contexto: Contexto) -> None:
    """Hace los pasos que le faltan al mensaje. Si alguno falla, la excepción llega al worker,
    que registra el error y programa un reintento."""
    if mensaje.estado not in ESTADOS_PENDIENTES:
        return
    adaptador = contexto.adaptadores[mensaje.canal]
    _indicar_procesando(adaptador, mensaje)

    if mensaje.estado in (EstadoMensaje.RECIBIDO, EstadoMensaje.DESCARGADO):
        if mensaje.tipo == "audio":
            _transcribir(sesion, mensaje, adaptador, contexto)
        mensaje.estado = EstadoMensaje.TRANSCRITO
        sesion.commit()

    if mensaje.estado == EstadoMensaje.TRANSCRITO:
        if armar_borrador(sesion, mensaje, contexto.llm) is None:
            # Era una consulta: el bot no responde preguntas sobre los residentes.
            adaptador.enviar_texto(mensaje.destino_respuesta, textos.SOLO_REGISTROS, mensaje.id_externo)
            mensaje.estado = EstadoMensaje.LISTO
        else:
            mensaje.estado = EstadoMensaje.EXTRAIDO
        sesion.commit()

    if mensaje.estado == EstadoMensaje.EXTRAIDO:
        _responder(sesion, mensaje, adaptador, contexto)
        mensaje.estado = EstadoMensaje.LISTO
        sesion.commit()


def _indicar_procesando(adaptador: AdaptadorCanal, mensaje: MensajeEntrante) -> None:
    try:
        adaptador.indicar_procesando(mensaje.destino_respuesta)
    except Exception as error:
        # Es solo un aviso visual en el chat: si falla, el procesamiento sigue igual.
        logger.warning(
            "No se pudo mostrar 'escribiendo…' para el mensaje %s (%s)",
            mensaje.id,
            type(error).__name__,
            exc_info=trazas_habilitadas(),
        )


def _transcribir(
    sesion: Session, mensaje: MensajeEntrante, adaptador: AdaptadorCanal, contexto: Contexto
) -> None:
    ya_transcrito = sesion.scalar(
        select(Transcripcion.id).where(Transcripcion.mensaje_id == mensaje.id)
    )
    if ya_transcrito is not None:
        return

    contenido, mime_descargado = adaptador.descargar_audio(mensaje.audio_ref)
    mime = mensaje.audio_mime or mime_descargado
    # mode=0o700: en Linux, solo el usuario de la aplicación puede entrar a la carpeta.
    contexto.carpeta_audios.mkdir(mode=0o700, parents=True, exist_ok=True)
    ruta = contexto.carpeta_audios / f"{mensaje.id}{EXTENSIONES_AUDIO.get(mime, '')}"
    try:
        ruta.write_bytes(contenido)
        resultado = contexto.stt.transcribir(ruta, mime, idioma="es")
    finally:
        # El audio nunca se conserva: se borra al terminar el intento, salga bien o mal.
        ruta.unlink(missing_ok=True)

    sesion.add(
        Transcripcion(
            mensaje_id=mensaje.id,
            texto=resultado.texto,
            segmentos=resultado.segmentos,
            proveedor=contexto.stt.nombre,
            modelo=resultado.modelo,
            duracion_seg=resultado.duracion_seg or mensaje.audio_duracion_seg,
        )
    )
    logger.info("Mensaje %s transcrito con %s", mensaje.id, resultado.modelo)


def _responder(
    sesion: Session, mensaje: MensajeEntrante, adaptador: AdaptadorCanal, contexto: Contexto
) -> None:
    borrador = borrador_del_mensaje(sesion, mensaje)
    residente = sesion.get(Residente, borrador.residente_id) if borrador.residente_id else None
    # Si el borrador ya tiene un mensaje del bot, lo que falta ya se pidió una vez.
    ya_se_pidio = borrador.mensaje_bot_id_externo is not None
    texto = texto_de_respuesta(borrador, residente, ya_se_pidio, contexto.url_publica)
    # Se guarda el id del mensaje del bot: si el profesional le responde, completa este borrador.
    borrador.mensaje_bot_id_externo = adaptador.enviar_texto(
        mensaje.destino_respuesta, texto, mensaje.id_externo
    )
    logger.info("Respuesta enviada para el borrador %s", borrador.id)
    if contexto.borrar_mensajes_importados:
        _borrar_del_chat(adaptador, mensaje)


def _borrar_del_chat(adaptador: AdaptadorCanal, mensaje: MensajeEntrante) -> None:
    try:
        if not adaptador.borrar_mensaje(mensaje.destino_respuesta, mensaje.id_externo):
            logger.info("El mensaje %s ya no se podía borrar del chat", mensaje.id)
    except Exception as error:
        # El registro ya quedó guardado y respondido: un borrado fallido no se reintenta.
        logger.warning(
            "No se pudo borrar del chat el mensaje %s (%s)",
            mensaje.id,
            type(error).__name__,
            exc_info=trazas_habilitadas(),
        )
