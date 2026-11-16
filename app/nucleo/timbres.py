"""Timbre del profesional: la imagen que acompaña su firma en cada atención (E3-03).

El profesional puede subir una foto de su timbre (PNG o JPG, hasta 1 MB). Si no la sube, se
genera uno en SVG con su nombre, especialidad y registro.
"""

from xml.sax.saxutils import escape

from sqlalchemy.orm import Session

from app.modelos import Profesional, TipoActor, UsuarioWeb
from app.nucleo.auditoria import Accion, registrar_evento

TAMANO_MAXIMO_BYTES = 1024 * 1024
# Primeros bytes de cada formato aceptado: el tipo se decide por el contenido, no por la
# extensión ni por lo que declare el navegador.
FIRMAS_DE_FORMATO = {
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
}
MIME_SVG = "image/svg+xml"


class TimbreNoValido(Exception):
    """El archivo no es PNG ni JPG, está vacío o pesa más de 1 MB. El mensaje se puede mostrar."""


def tipo_de_imagen(contenido: bytes) -> str | None:
    """El tipo MIME según los primeros bytes del archivo, o None si no es PNG ni JPG."""
    return next(
        (mime for firma, mime in FIRMAS_DE_FORMATO.items() if contenido.startswith(firma)), None
    )


def guardar_timbre(
    sesion: Session, profesional: Profesional, contenido: bytes, usuario: UsuarioWeb
) -> None:
    """Guarda la imagen del timbre del profesional y lo audita (timbre_subido). No hace commit.
    Lanza TimbreNoValido si el archivo no corresponde."""
    if not contenido:
        raise TimbreNoValido("El archivo está vacío.")
    if len(contenido) > TAMANO_MAXIMO_BYTES:
        raise TimbreNoValido("El timbre no puede pesar más de 1 MB.")
    mime = tipo_de_imagen(contenido)
    if mime is None:
        raise TimbreNoValido("El timbre debe ser una imagen PNG o JPG.")
    profesional.timbre_imagen = contenido
    profesional.timbre_mime = mime
    registrar_evento(
        sesion,
        Accion.TIMBRE_SUBIDO,
        actor_tipo=TipoActor.USUARIO,
        actor_id=usuario.id,
        entidad="profesional",
        entidad_id=profesional.id,
        detalle={"mime": mime, "tamano_bytes": len(contenido)},
    )


def timbre_de(profesional: Profesional) -> tuple[bytes, str]:
    """La imagen del timbre y su tipo MIME: la que subió el profesional o, si no hay, una
    generada con sus datos."""
    if profesional.timbre_imagen:
        return profesional.timbre_imagen, profesional.timbre_mime
    return timbre_generado(profesional).encode(), MIME_SVG


def timbre_generado(profesional: Profesional) -> str:
    """Timbre en SVG con el nombre, la especialidad y el registro del profesional. Los textos van
    escapados: un nombre con "<" o "&" no puede alterar el SVG."""
    nombre = _escapar(profesional.nombre)
    especialidad = _escapar(profesional.especialidad.capitalize())
    registro = _escapar(f"Registro {profesional.registro}") if profesional.registro else ""
    color = "#1f4e79"
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="260" height="104" '
        f'viewBox="0 0 260 104" role="img" aria-label="Timbre de {nombre}">'
        f'<rect x="3" y="3" width="254" height="98" rx="12" fill="none" stroke="{color}" '
        'stroke-width="3"/>'
        f'<g font-family="Arial, sans-serif" text-anchor="middle" fill="{color}">'
        f'<text x="130" y="40" font-size="17" font-weight="700">{nombre}</text>'
        f'<text x="130" y="64" font-size="14">{especialidad}</text>'
        f'<text x="130" y="86" font-size="12">{registro}</text>'
        "</g></svg>"
    )


def _escapar(texto: str) -> str:
    """Escapa &, <, > y las comillas: el resultado sirve dentro del texto y de un atributo."""
    return escape(texto, {'"': "&quot;"})
