"""Quién puede hacer qué sobre la ficha clínica.

A la ficha accede quien participa en la atención (Ley 20.584, art. 13): la encargada de salud
ve todas las fichas y la directora solo los datos administrativos, nunca el historial clínico.

Esta es la versión por rol. Cuando existan las asignaciones (E2-03), un profesional verá solo
las fichas de los residentes que tiene asignados, sin cambiar las firmas de estas funciones.

La web las usa para responder 403; los botones que oculta son solo una ayuda visual.
"""

from sqlalchemy.orm import Session

from app.modelos import Atencion, EstadoAtencion, Rol, UsuarioWeb


def puede_ver_ficha(sesion: Session, usuario: UsuarioWeb, residente_id: int) -> bool:
    """Ver el historial clínico de un residente. sesion queda para revisar las asignaciones."""
    return usuario.rol in (Rol.ENCARGADA_SALUD, Rol.PROFESIONAL)


def puede_editar_atencion(usuario: UsuarioWeb, atencion: Atencion) -> bool:
    """Editar una atención en borrador: su profesional autor o la encargada de salud."""
    if atencion.estado == EstadoAtencion.FIRMADA:
        return False
    return usuario.rol == Rol.ENCARGADA_SALUD or _es_autor(usuario, atencion)


def puede_firmar(usuario: UsuarioWeb, atencion: Atencion) -> bool:
    """Firmar una atención en borrador: solo su profesional autor."""
    return atencion.estado != EstadoAtencion.FIRMADA and _es_autor(usuario, atencion)


def _es_autor(usuario: UsuarioWeb, atencion: Atencion) -> bool:
    return (
        usuario.rol == Rol.PROFESIONAL
        and usuario.profesional_id is not None
        and usuario.profesional_id == atencion.profesional_id
    )
