"""Archivos adjuntos de la ficha (E3-04).

Los archivos se guardan en la base de datos y solo se entregan con sesión iniciada y permiso
sobre la ficha, nunca desde una URL pública.

Contrato del esqueleto (E1-01): las firmas no cambian sin avisar a quien las usa.
"""

from datetime import date

from sqlalchemy.orm import Session

from app.modelos import Adjunto, TipoAdjunto, UsuarioWeb

TIPOS_PERMITIDOS = {"application/pdf", "image/jpeg", "image/png"}
TAMANO_MAXIMO_BYTES = 10 * 1024 * 1024


class ArchivoNoPermitido(Exception):
    """El archivo no es PDF, JPG ni PNG (según su contenido real) o pesa más de 10 MB."""


def guardar_adjunto(
    sesion: Session,
    residente_id: int,
    contenido: bytes,
    nombre: str,
    tipo: TipoAdjunto,
    usuario: UsuarioWeb,
    atencion_id: int | None = None,
    emisor: str | None = None,
    fecha_emision: date | None = None,
) -> Adjunto:
    """Guarda un archivo en la ficha del residente, o en una de sus atenciones en borrador, con
    su sha256, y lo audita (adjunto_subido).

    Lanza ArchivoNoPermitido si el tipo real o el tamaño no corresponden.
    """
    raise NotImplementedError


def leer_adjunto(sesion: Session, adjunto_id: int, usuario: UsuarioWeb) -> Adjunto:
    """Devuelve el adjunto, con su contenido, si el usuario tiene permiso sobre la ficha, y audita
    la descarga (adjunto_descargado). Lanza PermissionError si no tiene permiso."""
    raise NotImplementedError
