import hashlib
import re
import unicodedata
from datetime import date

from sqlalchemy.orm import Session

from app.modelos import (
    Adjunto,
    Atencion,
    EstadoAtencion,
    Rol,
    TipoActor,
    TipoAdjunto,
    UsuarioWeb,
)
from app.nucleo.auditoria import Accion, registrar_evento
from app.nucleo.permisos import puede_ver_ficha

TIPOS_PERMITIDOS = {"application/pdf", "image/jpeg", "image/png"}
TAMANO_MAXIMO_BYTES = 10 * 1024 * 1024
EXTENSIONES = {"application/pdf": ".pdf", "image/jpeg": ".jpg", "image/png": ".png"}


class ArchivoNoPermitido(Exception):
    """Archivo vacío, demasiado grande o formato no admitido según sus bytes."""


def detectar_mime(contenido: bytes) -> str:
    """Reconoce firmas binarias y marcadores de cierre, no extensión ni MIME del cliente.

    Es identificación de formato, no un análisis antivirus ni validación de cada objeto PDF.
    """
    if not contenido:
        raise ArchivoNoPermitido("El archivo está vacío.")
    if len(contenido) > TAMANO_MAXIMO_BYTES:
        raise ArchivoNoPermitido("El archivo supera el máximo de 10 MB.")
    if (
        contenido.startswith(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")
        and len(contenido) >= 45
        and contenido.endswith(b"\x00\x00\x00\x00IEND\xaeB`\x82")
    ):
        return "image/png"
    if (
        len(contenido) >= 12
        and contenido.startswith(b"\xff\xd8\xff")
        and contenido.endswith(b"\xff\xd9")
    ):
        return "image/jpeg"
    if re.match(
        rb"%PDF-(?:1\.[0-7]|2\.0)[\r\n]", contenido
    ) and contenido.rstrip().endswith(b"%%EOF"):
        return "application/pdf"
    raise ArchivoNoPermitido(
        "El contenido debe ser PDF, JPG o PNG."
    )


def nombre_seguro(nombre: str, mime: str) -> str:
    nombre = unicodedata.normalize("NFC", nombre.replace("\\", "/").rsplit("/", 1)[-1])
    nombre = "".join(c for c in nombre if not unicodedata.category(c).startswith("C"))
    base = nombre.rsplit(".", 1)[0].strip(" .")[:150] or "documento"
    return base + EXTENSIONES[mime]


def exigir_acceso(sesion: Session, usuario: UsuarioWeb, residente_id: int) -> None:
    if not puede_ver_ficha(sesion, usuario, residente_id):
        raise PermissionError("No tienes permiso sobre la ficha de este residente.")


def validar_destino(
    sesion: Session, usuario: UsuarioWeb, residente_id: int, atencion_id: int | None
):
    exigir_acceso(sesion, usuario, residente_id)
    if atencion_id is None:
        return
    atencion = sesion.get(Atencion, atencion_id)
    if atencion is None or atencion.residente_id != residente_id:
        raise ValueError("La atención no pertenece al residente seleccionado.")
    if atencion.estado not in (EstadoAtencion.BORRADOR, EstadoAtencion.FIRMADA):
        raise ValueError("La atención no admite adjuntos.")
    if (
        usuario.rol != Rol.ENCARGADA_SALUD
        and atencion.profesional_id != usuario.profesional_id
    ):
        raise PermissionError(
            "Solo el autor o la encargada pueden agregar documentos a esta atención."
        )


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
    """Agrega a la ficha o atención (incluso firmada), sin alterar su contenido ni firma.

    Valida permisos, destino, formato y tamaño. Audita sin incluir contenido clínico.
    Lanza PermissionError, ValueError o ArchivoNoPermitido. No hace commit.
    """
    validar_destino(sesion, usuario, residente_id, atencion_id)
    try:
        tipo = TipoAdjunto(tipo)
    except ValueError:
        raise ValueError("Selecciona un tipo de documento válido.") from None
    if emisor is not None and len(emisor.strip()) > 200:
        raise ValueError("El emisor admite hasta 200 caracteres.")
    mime = detectar_mime(contenido)
    adjunto = Adjunto(
        residente_id=residente_id,
        atencion_id=atencion_id,
        nombre_archivo=nombre_seguro(nombre, mime),
        tipo=tipo,
        emisor=emisor.strip() or None if emisor is not None else None,
        fecha_emision=fecha_emision,
        mime=mime,
        tamano_bytes=len(contenido),
        sha256=hashlib.sha256(contenido).hexdigest(),
        contenido=contenido,
        subido_por=usuario.id,
    )
    sesion.add(adjunto)
    sesion.flush()
    registrar_evento(
        sesion,
        Accion.ADJUNTO_SUBIDO,
        TipoActor.USUARIO,
        actor_id=usuario.id,
        entidad="adjunto",
        entidad_id=adjunto.id,
        detalle={
            "residente_id": residente_id,
            "atencion_id": atencion_id,
            "mime": mime,
            "tamano_bytes": len(contenido),
        },
    )
    return adjunto


def leer_adjunto(sesion: Session, adjunto_id: int, usuario: UsuarioWeb) -> Adjunto:
    """Autoriza antes de cargar los bytes y audita la descarga. No hace commit."""
    adjunto = sesion.get(Adjunto, adjunto_id)
    if adjunto is None:
        raise LookupError("Adjunto no encontrado.")
    exigir_acceso(sesion, usuario, adjunto.residente_id)
    # La columna deferred solo se carga después de verificar el permiso.
    if hashlib.sha256(adjunto.contenido).hexdigest() != adjunto.sha256:
        raise ValueError("No se pudo verificar la integridad del archivo.")
    registrar_evento(
        sesion,
        Accion.ADJUNTO_DESCARGADO,
        TipoActor.USUARIO,
        actor_id=usuario.id,
        entidad="adjunto",
        entidad_id=adjunto.id,
    )
    return adjunto
