"""Registro de auditoría: quién hizo qué y cuándo.

Los eventos solo se insertan; la base de datos rechaza modificarlos o borrarlos. El detalle
lleva ids, tipos y canales, nunca el texto de los mensajes ni datos clínicos.
"""

from enum import StrEnum
from typing import Any

from sqlalchemy.orm import Session

from app.modelos import EventoAuditoria, TipoActor


class Accion(StrEnum):
    CODIGO_GENERADO = "codigo_generado"
    CODIGO_RECHAZADO = "codigo_rechazado"  # código inexistente, usado o vencido
    VINCULO_CREADO = "vinculo_creado"
    VINCULO_REVOCADO = "vinculo_revocado"
    MENSAJE_RECIBIDO = "mensaje_recibido"
    MENSAJE_RECHAZADO = "mensaje_rechazado"  # remitente no vinculado


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
