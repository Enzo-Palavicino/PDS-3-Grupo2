"""Procesamiento en segundo plano de cada mensaje que guardó la ingesta.

Cada paso revisa primero si su resultado ya existe, así que repetirlo no hace daño: si un intento
falla a la mitad, el reintento sigue desde donde quedó. Por ahora el único paso es transcribir
los audios; los textos no lo necesitan.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.canales.base import AdaptadorCanal
from app.logs import trazas_habilitadas
from app.modelos import EstadoMensaje, MensajeEntrante, Transcripcion
from app.proveedores.stt.base import ProveedorSTT

logger = logging.getLogger(__name__)

# Estados de los mensajes que todavía tienen pasos por hacer.
ESTADOS_PENDIENTES = (EstadoMensaje.RECIBIDO, EstadoMensaje.DESCARGADO)

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
    carpeta_audios: Path


def procesar(sesion: Session, mensaje: MensajeEntrante, contexto: Contexto) -> None:
    """Hace los pasos pendientes del mensaje. Si alguno falla, la excepción llega al worker, que
    registra el error y programa un reintento."""
    adaptador = contexto.adaptadores[mensaje.canal]
    _indicar_procesando(adaptador, mensaje)
    if mensaje.tipo == "audio":
        _transcribir(sesion, mensaje, adaptador, contexto)
    mensaje.estado = EstadoMensaje.TRANSCRITO


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
