"""Ingreso de documentos históricos (E4-02); procesamiento en digitalizacion.py (E4-03).

No hace commit ni llama a IA. Los documentos subidos son la cola durable del worker.
"""

from datetime import date

from sqlalchemy.orm import Session

from app.modelos import (
    DocumentoHistorico,
    EstadoDocumento,
    Residente,
    Rol,
    TipoActor,
    TipoAdjunto,
    UsuarioWeb,
)
from app.nucleo.adjuntos import ArchivoNoPermitido, detectar_mime, guardar_adjunto
from app.nucleo.auditoria import Accion, registrar_evento

MAXIMO_ARCHIVOS = 10
MAXIMO_LOTE_BYTES = 50 * 1024 * 1024


def subir_documento(
    sesion: Session,
    residente_id: int,
    contenido: bytes,
    nombre: str,
    tipo_documento: str,
    usuario: UsuarioWeb,
    fecha_original: date | None = None,
) -> DocumentoHistorico:
    """Guarda adjunto + documento + auditoría en la transacción del llamador."""
    if not usuario.activo or usuario.rol != Rol.ENCARGADA_SALUD:
        raise PermissionError(
            "Solo la encargada de salud puede subir documentos históricos."
        )
    if sesion.get(Residente, residente_id) is None:
        raise ValueError("Residente no encontrado.")
    tipo_documento = tipo_documento.strip()
    if not tipo_documento or len(tipo_documento) > 120:
        raise ValueError("Indica el tipo de documento (hasta 120 caracteres).")
    if detectar_mime(contenido) not in ("image/jpeg", "image/png", "application/pdf"):
        raise ArchivoNoPermitido("La digitalización admite archivos PDF, JPG o PNG.")
    adjunto = guardar_adjunto(
        sesion,
        residente_id,
        contenido,
        nombre,
        TipoAdjunto.DOCUMENTO_HISTORICO,
        usuario,
        fecha_emision=fecha_original,
    )
    documento = DocumentoHistorico(
        residente_id=residente_id,
        adjunto_id=adjunto.id,
        tipo_documento=tipo_documento,
        fecha_original=fecha_original,
        subido_por=usuario.id,
        estado=EstadoDocumento.SUBIDO,
        intentos=0,
        proximo_intento_en=None,
    )
    sesion.add(documento)
    sesion.flush()
    registrar_evento(
        sesion,
        Accion.DOCUMENTO_SUBIDO,
        TipoActor.USUARIO,
        actor_id=usuario.id,
        entidad="documento_historico",
        entidad_id=documento.id,
        detalle={"residente_id": residente_id, "adjunto_id": adjunto.id},
    )
    return documento
