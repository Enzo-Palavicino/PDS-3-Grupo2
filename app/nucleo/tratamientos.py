"""Tratamientos del residente (E1-04): cuáles están vigentes y cómo se suspenden.

Un tratamiento nunca se borra. Deja de estar vigente cuando pasa su fecha de término (se calcula
al leerlo, sin tareas programadas) o cuando un profesional lo suspende indicando el motivo. Los
tratamientos se crean al firmar una atención (app/nucleo/incorporacion.py).
"""

from datetime import date, datetime
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import ahora
from app.modelos import EstadoTratamiento, TipoActor, Tratamiento, UsuarioWeb
from app.nucleo.auditoria import Accion, registrar_evento
from app.nucleo.extraccion import ZONA_HORARIA


class ErrorDeTratamiento(Exception):
    """Error al operar sobre un tratamiento. Su mensaje se puede mostrar en la web."""


class TratamientoNoVigente(ErrorDeTratamiento):
    """El tratamiento ya terminó o ya se suspendió. En la web corresponde a un 409."""


class TratamientosDelResidente(NamedTuple):
    vigentes: list[Tratamiento]
    historial: list[Tratamiento]  # terminados y suspendidos


def hoy_en_chile(momento: datetime | None = None) -> date:
    return (momento or ahora()).astimezone(ZONA_HORARIA).date()


def estado_vigente(tratamiento: Tratamiento, hoy: date) -> str:
    """El estado del tratamiento hoy: uno activo cuya fecha de término ya pasó está terminado,
    aunque nadie lo haya cambiado."""
    termino = tratamiento.fecha_termino
    if tratamiento.estado == EstadoTratamiento.ACTIVO and termino is not None and termino < hoy:
        return EstadoTratamiento.TERMINADO
    return tratamiento.estado


def tratamientos_del_residente(
    sesion: Session, residente_id: int, hoy: date | None = None
) -> TratamientosDelResidente:
    """Los tratamientos del residente: primero los vigentes y aparte el historial, cada grupo
    del indicado más recientemente al más antiguo."""
    hoy = hoy or hoy_en_chile()
    tratamientos = sorted(
        sesion.scalars(select(Tratamiento).where(Tratamiento.residente_id == residente_id)),
        key=lambda t: (t.indicado_en or date.min, t.id),
        reverse=True,
    )
    vigentes = [t for t in tratamientos if estado_vigente(t, hoy) == EstadoTratamiento.ACTIVO]
    historial = [t for t in tratamientos if t not in vigentes]
    return TratamientosDelResidente(vigentes, historial)


def suspender_tratamiento(
    sesion: Session,
    tratamiento: Tratamiento,
    usuario: UsuarioWeb,
    motivo: str,
    momento: datetime | None = None,
) -> Tratamiento:
    """Suspende un tratamiento vigente, con el motivo, y lo audita (tratamiento_suspendido). No
    lo borra ni hace commit. Los permisos los revisa la web (permisos.puede_suspender_tratamiento).

    Lanza ErrorDeTratamiento si falta el motivo y TratamientoNoVigente si ya no está vigente.
    """
    motivo = (motivo or "").strip()
    if not motivo:
        raise ErrorDeTratamiento("Indica el motivo de la suspensión.")
    momento = momento or ahora()
    if estado_vigente(tratamiento, hoy_en_chile(momento)) != EstadoTratamiento.ACTIVO:
        raise TratamientoNoVigente("El tratamiento ya no está vigente.")
    tratamiento.estado = EstadoTratamiento.SUSPENDIDO
    tratamiento.suspendido_por = usuario.id
    tratamiento.suspendido_en = momento
    tratamiento.motivo_suspension = motivo
    registrar_evento(
        sesion,
        Accion.TRATAMIENTO_SUSPENDIDO,
        actor_tipo=TipoActor.USUARIO,
        actor_id=usuario.id,
        entidad="tratamiento",
        entidad_id=tratamiento.id,
        # Solo ids: el motivo es texto clínico.
        detalle={"residente_id": tratamiento.residente_id},
    )
    return tratamiento
