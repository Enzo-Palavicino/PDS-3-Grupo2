"""Digitalización de documentos históricos (E4-03).

El worker procesa los documentos pendientes como procesa los mensajes: por estado, guardando el
avance después de cada paso, con reintentos.

    subido ─(leer la imagen)─► leido ─(seudonimizar y extraer)─► por_revisar

El proveedor se inyecta desde el contexto del worker, igual que para los mensajes.
"""

import logging
from datetime import date, datetime, time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import cerrar_transaccion
from app.modelos import (
    Adjunto,
    Atencion,
    DocumentoHistorico,
    EstadoAtencion,
    EstadoDocumento,
    Residente,
)
from app.nucleo.adjuntos import detectar_mime
from app.nucleo.extraccion import ZONA_HORARIA, Ambiguedad, Campo, extraer_registro
from app.nucleo.pdf import imagen_del_pdf
from app.nucleo.seudonimizacion import normalizar
from app.proveedores.llm.base import ErrorLLM, ProveedorLLM

logger = logging.getLogger(__name__)
ESTADOS_PENDIENTES = (EstadoDocumento.SUBIDO, EstadoDocumento.LEIDO)


def procesar_documento(sesion: Session, documento_id: int, llm: ProveedorLLM) -> None:
    """Guarda el texto antes de extraer. Las excepciones llegan al worker para su reintento."""
    documento = sesion.get(DocumentoHistorico, documento_id)
    if documento is None:
        raise LookupError("Documento histórico no encontrado.")
    if documento.estado not in ESTADOS_PENDIENTES:
        return
    if documento.estado == EstadoDocumento.SUBIDO:
        adjunto = sesion.get(Adjunto, documento.adjunto_id)
        if adjunto is None or adjunto.residente_id != documento.residente_id:
            raise ValueError("El original no corresponde al documento.")
        contenido = adjunto.contenido
        mime = detectar_mime(contenido)
        cerrar_transaccion(sesion)
        if mime == "application/pdf":
            contenido, mime = imagen_del_pdf(contenido), "image/png"
        lectura = llm.leer_imagen(contenido, mime)
        if not lectura.texto.strip():
            raise ErrorLLM("el proveedor devolvió una lectura vacía")
        documento.texto_leido = lectura.texto
        documento.modelo_lectura = lectura.modelo
        documento.estado = EstadoDocumento.LEIDO
        sesion.commit()
        logger.info("Documento %s leído", documento_id)

    if not documento.texto_leido:
        raise ValueError("El documento leído no tiene transcripción.")
    residentes = list(sesion.scalars(select(Residente).order_by(Residente.codigo)))
    residente = next((r for r in residentes if r.id == documento.residente_id), None)
    if residente is None:
        raise LookupError("Residente del documento no encontrado.")
    referencia = (
        datetime.combine(documento.fecha_original, time(12), tzinfo=ZONA_HORARIA)
        if documento.fecha_original else None
    )
    cerrar_transaccion(sesion)
    resultado = extraer_registro(
        documento.texto_leido, residentes, "no informada; documento histórico", referencia, llm
    )
    registro = resultado.registro
    ambiguedades = [a for a in registro.ambiguedades if a.campo != "residente"]
    if resultado.residente_id is not None and resultado.residente_id != documento.residente_id:
        ambiguedades.append(Ambiguedad(
            campo="residente", motivo="El texto nombra a otro residente; verifica el original."
        ))
    elif resultado.residente_id is None:
        ambiguedades.append(Ambiguedad(
            campo="residente", motivo="No se pudo comprobar el residente en el texto del original."
        ))
    registro.residente = Campo(valor=residente.codigo)
    if documento.fecha_original:
        original = documento.fecha_original.isoformat()
        if registro.fecha_atencion and registro.fecha_atencion.valor != original:
            ambiguedades.append(Ambiguedad(
                campo="fecha_atencion",
                motivo="La fecha leída difiere de la fecha original indicada al subir.",
            ))
        registro.fecha_atencion = Campo(valor=original)
    if "[ilegible]" in documento.texto_leido.casefold():
        ambiguedades.append(Ambiguedad(
            campo="documento", motivo="Hay texto [ilegible]; compáralo con el original."
        ))
    fecha = (
        date.fromisoformat(registro.fecha_atencion.valor)
        if registro.fecha_atencion and registro.fecha_atencion.valor else None
    )
    documento.posibles_duplicados = posibles_duplicados(
        sesion, documento.residente_id, fecha,
        [dato.valor for dato in registro.diagnosticos if dato.valor],
    )
    documento.campos = registro.model_dump(exclude={"es_consulta", "ambiguedades"})
    documento.ambiguedades = [a.model_dump() for a in ambiguedades]
    documento.entrada_seudonimizada = resultado.entrada
    documento.salida = resultado.salida
    documento.estado = EstadoDocumento.POR_REVISAR
    documento.proximo_intento_en = None
    documento.ultimo_error = None
    sesion.commit()
    logger.info("Documento %s por revisar", documento_id)


def posibles_duplicados(
    sesion: Session, residente_id: int, fecha: date | None, diagnosticos: list[str]
) -> list[int]:
    """Coincidencia de fecha y al menos un diagnóstico; nunca basta una fecha o un vacío."""
    claves = {" ".join(normalizar(d).split()) for d in diagnosticos if d.strip()}
    if fecha is None or not claves:
        return []
    atenciones = sesion.scalars(select(Atencion).where(
        Atencion.residente_id == residente_id,
        Atencion.fecha_atencion == fecha,
        Atencion.estado == EstadoAtencion.FIRMADA,
    ).order_by(Atencion.id))
    return [
        atencion.id for atencion in atenciones
        if any(
            isinstance(dato, dict) and isinstance(dato.get("valor"), str)
            and " ".join(normalizar(dato["valor"]).split()) in claves
            for dato in (atencion.campos or {}).get("diagnosticos", [])
        )
    ]
