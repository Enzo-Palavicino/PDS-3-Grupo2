"""Registro de auditoría: quién hizo qué y cuándo.

Los eventos solo se insertan; la base de datos rechaza modificarlos o borrarlos. El detalle
lleva ids, tipos y canales, nunca el texto de los mensajes ni datos clínicos.
"""

from enum import StrEnum
from typing import Any

from sqlalchemy.orm import Session

from app.modelos import EventoAuditoria, TipoActor


class Accion(StrEnum):
    CONTRASENA_CAMBIADA = "contrasena_cambiada"
    CODIGO_GENERADO = "codigo_generado"
    CODIGO_RECHAZADO = "codigo_rechazado"  # código inexistente, usado o vencido
    VINCULO_CREADO = "vinculo_creado"
    VINCULO_REVOCADO = "vinculo_revocado"
    MENSAJE_RECIBIDO = "mensaje_recibido"
    MENSAJE_RECHAZADO = "mensaje_rechazado"  # remitente no vinculado
    INICIO_SESION = "inicio_sesion"
    INICIO_SESION_FALLIDO = "inicio_sesion_fallido"
    BORRADOR_LEIDO = "borrador_leido"
    BORRADOR_DESCARTADO = "borrador_descartado"
    # Ficha clínica
    RESIDENTE_CREADO = "residente_creado"
    RESIDENTE_EDITADO = "residente_editado"
    RESIDENTE_EGRESADO = "residente_egresado"
    PROFESIONAL_CREADO = "profesional_creado"
    PROFESIONAL_DESACTIVADO = "profesional_desactivado"
    FICHA_LEIDA = "ficha_leida"
    ATENCION_CREADA = "atencion_creada"
    ATENCION_EDITADA = "atencion_editada"
    ATENCION_FIRMADA = "atencion_firmada"
    ADJUNTO_SUBIDO = "adjunto_subido"
    ADJUNTO_DESCARGADO = "adjunto_descargado"
    DOCUMENTO_SUBIDO = "documento_subido"
    DOCUMENTO_INCORPORADO = "documento_incorporado"
    DOCUMENTO_DESCARTADO = "documento_descartado"
    TRATAMIENTO_SUSPENDIDO = "tratamiento_suspendido"


def registrar_evento(
    sesion: Session,
    accion: Accion,
    actor_tipo: TipoActor,
    actor_id: str | int | None = None,
    entidad: str | None = None,
    entidad_id: str | int | None = None,
    detalle: dict[str, Any] | None = None,
) -> None:
    sesion.add(
        EventoAuditoria(
            accion=accion,
            actor_tipo=actor_tipo,
            actor_id=None if actor_id is None else str(actor_id),
            entidad=entidad,
            entidad_id=None if entidad_id is None else str(entidad_id),
            detalle=detalle,
        )
    )
