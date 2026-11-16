"""Digitalización de documentos históricos (E4-03).

El worker procesa los documentos pendientes como procesa los mensajes: por estado, guardando el
avance después de cada paso, con reintentos.

    subido ─(leer la imagen)─► leido ─(seudonimizar y extraer)─► por_revisar

Contrato del esqueleto (E1-01): las firmas no cambian sin avisar a quien las usa.
"""

from sqlalchemy.orm import Session


def procesar_documento(sesion: Session, documento_id: int) -> None:
    """Hace los pasos que le faltan al documento. Si alguno falla, la excepción llega al worker,
    que registra el error y programa un reintento."""
    raise NotImplementedError
