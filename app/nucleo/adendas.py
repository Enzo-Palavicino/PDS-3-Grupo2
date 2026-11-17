"""Correcciones de atenciones firmadas (E3-06).

Una atención firmada no se modifica (Ley 20.584, art. 12): se corrige con una adenda, que es
otra atención que la corrige. La adenda empieza con una copia de los campos de la original, el
profesional cambia lo que estaba mal y la firma como cualquier atención. Al firmarla, la ficha
reemplaza lo que aportó la original (ver app/nucleo/incorporacion.py). La original no cambia y
sigue verificando su integridad.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modelos import Atencion, EstadoAtencion, OrigenAtencion, Rol, UsuarioWeb
from app.nucleo.atenciones import ErrorDeAtencion, crear_atencion


class CorreccionEnCurso(ErrorDeAtencion):
    """La atención ya tiene una adenda sin firmar: se continúa esa, no se crea otra."""

    def __init__(self, adenda: Atencion):
        super().__init__(f"Ya hay una corrección en curso: la atención #{adenda.id}.")
        self.adenda = adenda


def crear_adenda(
    sesion: Session, original: Atencion, usuario: UsuarioWeb, motivo: str
) -> Atencion:
    """Crea una adenda en borrador que corrige la atención original, con una copia de sus campos.
    No hace commit.

    Lanza ErrorDeAtencion si falta el motivo, si la original no está firmada o si quien corrige
    no es su profesional autor, y CorreccionEnCurso si ya hay una adenda sin firmar.
    """
    motivo = (motivo or "").strip()
    if not motivo:
        raise ErrorDeAtencion("Indica el motivo de la corrección.")
    if original.estado != EstadoAtencion.FIRMADA:
        raise ErrorDeAtencion("Solo se corrige una atención firmada; una en borrador se edita.")
    es_autor = (
        usuario.rol == Rol.PROFESIONAL
        and usuario.profesional_id is not None
        and usuario.profesional_id == original.profesional_id
    )
    if not es_autor:
        raise ErrorDeAtencion("Solo el profesional que hizo la atención puede corregirla.")
    en_curso = adenda_en_curso(sesion, original)
    if en_curso is not None:
        raise CorreccionEnCurso(en_curso)
    return crear_atencion(
        sesion,
        original.residente_id,
        usuario,
        original.campos,
        OrigenAtencion.WEB,
        fecha_atencion=original.fecha_atencion,
        corrige_a_id=original.id,
        motivo_correccion=motivo,
    )


def adenda_en_curso(sesion: Session, atencion: Atencion) -> Atencion | None:
    """La adenda sin firmar que corrige esta atención, si hay una."""
    return sesion.scalar(
        select(Atencion).where(
            Atencion.corrige_a_id == atencion.id,
            Atencion.estado == EstadoAtencion.BORRADOR,
        )
    )


def correcciones_de(sesion: Session, atencion: Atencion) -> list[Atencion]:
    """Las adendas firmadas que corrigen esta atención, de la primera a la última. En la ficha,
    la original se muestra como "Corregida por" cada una de ellas."""
    return list(
        sesion.scalars(
            select(Atencion)
            .where(
                Atencion.corrige_a_id == atencion.id,
                Atencion.estado == EstadoAtencion.FIRMADA,
            )
            .order_by(Atencion.firmada_en, Atencion.id)
        )
    )
