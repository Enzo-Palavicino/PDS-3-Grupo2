"""Registro de los mensajes recibidos por cualquier canal."""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.canales.base import MensajeNormalizado
from app.modelos import MensajeEntrante


def registrar_mensaje_entrante(
    sesion: Session, mensaje: MensajeNormalizado, profesional_id: int
) -> MensajeEntrante | None:
    """Guarda el mensaje y devuelve la fila creada.

    Si ya existía uno con el mismo canal e id externo (por ejemplo, porque Telegram reintentó
    el webhook), no guarda nada y devuelve None.
    """
    fila = MensajeEntrante(
        canal=mensaje.canal,
        id_externo=mensaje.id_externo,
        remitente_externo=mensaje.remitente_externo,
        destino_respuesta=mensaje.destino_respuesta,
        profesional_id=profesional_id,
        tipo=mensaje.tipo,
        texto=mensaje.texto,
        audio_ref=mensaje.audio_ref,
        audio_mime=mensaje.audio_mime,
        audio_tamano_bytes=mensaje.audio_tamano_bytes,
        audio_duracion_seg=mensaje.audio_duracion_seg,
        responde_a=mensaje.responde_a_id_externo,
        recibido_en=mensaje.recibido_en,
    )
    try:
        # SAVEPOINT: si la inserción choca con la clave única, solo se deshace esta parte y el
        # resto de la transacción sigue intacto.
        with sesion.begin_nested():
            sesion.add(fila)
    except IntegrityError:
        return None
    return fila
