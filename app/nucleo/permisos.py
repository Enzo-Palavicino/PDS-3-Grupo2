"""Permisos clínicos por rol y asignación vigente.

Se conservan las firmas compartidas. Edición y firma obtienen la sesión de los objetos
ORM; objetos desconectados no autorizan a un profesional (fallo seguro).
"""

from sqlalchemy import select
from sqlalchemy.orm import Session, object_session

from app.modelos import (
    Asignacion,
    Atencion,
    EstadoAtencion,
    Profesional,
    Residente,
    Rol,
    UsuarioWeb,
)


class SinAsignacion(PermissionError):
    """No se permite registrar para el residente indicado."""


def residentes_asignados(profesional_id: int | None):
    """Subconsulta para filtrar listados sin cargar fichas no autorizadas."""
    return (
        select(Asignacion.residente_id)
        .join(Profesional)
        .where(Asignacion.profesional_id == profesional_id, Profesional.activo)
    )


def profesional_asignado(
    sesion: Session, profesional_id: int | None, residente_id: int
) -> bool:
    return (
        profesional_id is not None
        and sesion.scalar(
            residentes_asignados(profesional_id).where(
                Asignacion.residente_id == residente_id
            )
        )
        is not None
    )


def puede_ver_ficha(sesion: Session, usuario: UsuarioWeb, residente_id: int) -> bool:
    if usuario.activo is False or sesion.get(Residente, residente_id) is None:
        return False
    if usuario.rol == Rol.ENCARGADA_SALUD:
        return True
    return usuario.rol == Rol.PROFESIONAL and profesional_asignado(
        sesion, usuario.profesional_id, residente_id
    )


def puede_registrar_atencion(
    sesion: Session, usuario: UsuarioWeb, residente_id: int
) -> bool:
    return puede_ver_ficha(sesion, usuario, residente_id)


def _acceso(usuario: UsuarioWeb, atencion: Atencion) -> bool:
    sesion = object_session(usuario) or object_session(atencion)
    return sesion is not None and puede_ver_ficha(
        sesion, usuario, atencion.residente_id
    )


def puede_editar_atencion(usuario: UsuarioWeb, atencion: Atencion) -> bool:
    return (
        atencion.estado != EstadoAtencion.FIRMADA
        and _acceso(usuario, atencion)
        and (usuario.rol == Rol.ENCARGADA_SALUD or _es_autor(usuario, atencion))
    )


def puede_firmar(usuario: UsuarioWeb, atencion: Atencion) -> bool:
    return (
        atencion.estado != EstadoAtencion.FIRMADA
        and _es_autor(usuario, atencion)
        and _acceso(usuario, atencion)
    )


def _es_autor(usuario: UsuarioWeb, atencion: Atencion) -> bool:
    return (
        usuario.rol == Rol.PROFESIONAL
        and usuario.profesional_id is not None
        and usuario.profesional_id == atencion.profesional_id
    )
