"""Revisión humana de históricos. Todas las escrituras pertenecen a una sola transacción."""

from datetime import date
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import ahora
from app.modelos import (
    Adjunto,
    Atencion,
    DocumentoHistorico,
    EstadoAtencion,
    EstadoDocumento,
    OrigenAtencion,
    Residente,
    Rol,
    TipoActor,
    UsuarioWeb,
)
from app.nucleo.atenciones import ErrorDeAtencion, crear_atencion, incorporar_a_ficha
from app.nucleo.auditoria import Accion, registrar_evento
from app.nucleo.campos import CAMPOS_ATENCION
from app.nucleo.digitalizacion import posibles_duplicados
from app.nucleo.extraccion import FECHA, HORA, Campo, RegistroExtraido


class DocumentoNoRevisable(ErrorDeAtencion):
    """El estado cambió o el documento todavía no puede revisarse."""


class DocumentoDuplicado(ErrorDeAtencion):
    def __init__(self, ids: list[int]):
        self.ids = ids
        super().__init__("No se puede incorporar: hay posibles duplicados con la misma fecha y diagnóstico.")


def _documento_bloqueado(
    sesion: Session, documento_id: int, usuario: UsuarioWeb
) -> DocumentoHistorico:
    if not usuario.activo or usuario.rol != Rol.ENCARGADA_SALUD:
        raise PermissionError("Solo la encargada de salud puede revisar documentos históricos.")
    documento = sesion.scalar(select(DocumentoHistorico).where(
        DocumentoHistorico.id == documento_id
    ).with_for_update().execution_options(populate_existing=True))
    if documento is None:
        raise LookupError("Documento histórico no encontrado.")
    return documento


def _campos_validos(campos: dict[str, Any]) -> dict[str, Any]:
    if set(campos) - set(CAMPOS_ATENCION):
        raise ErrorDeAtencion("El formulario contiene campos no reconocidos.")
    try:
        registro = RegistroExtraido.model_validate(campos)
        especialidad = Campo.model_validate(campos["especialidad"]) if campos.get("especialidad") else None
    except ValidationError:
        raise ErrorDeAtencion("Revisa los campos: peso y talla deben ser números positivos y finitos.") from None
    fechas = [
        registro.fecha_atencion.valor if registro.fecha_atencion else None,
        registro.proximo_control.fecha if registro.proximo_control else None,
    ]
    for indicacion in registro.indicaciones_farmacologicas:
        if not indicacion.medicamento or not indicacion.medicamento.strip():
            raise ErrorDeAtencion("Cada indicación debe identificar el medicamento.")
        fechas.extend([indicacion.fecha_inicio, indicacion.fecha_termino])
        if (
            indicacion.fecha_inicio and indicacion.fecha_termino
            and indicacion.fecha_termino < indicacion.fecha_inicio
        ):
            raise ErrorDeAtencion("El término de un tratamiento no puede ser anterior a su inicio.")
    for valor in fechas:
        if valor:
            if not FECHA.fullmatch(valor):
                raise ErrorDeAtencion("Las fechas deben tener el formato AAAA-MM-DD.")
            try:
                date.fromisoformat(valor)
            except ValueError:
                raise ErrorDeAtencion("Hay una fecha que no existe. Corrígela o déjala vacía.") from None
    if (
        registro.hora_atencion and registro.hora_atencion.valor
        and not HORA.fullmatch(registro.hora_atencion.valor)
    ):
        raise ErrorDeAtencion("La hora debe tener el formato HH:MM.")
    resultado = registro.model_dump(exclude={"es_consulta", "ambiguedades"})
    resultado["especialidad"] = especialidad.model_dump() if especialidad else None
    return resultado


def verificar_documento(
    sesion: Session, documento_id: int, usuario: UsuarioWeb, campos: dict[str, Any],
    profesional_texto: str, verificado: bool,
) -> Atencion:
    documento = _documento_bloqueado(sesion, documento_id, usuario)
    if documento.estado != EstadoDocumento.POR_REVISAR or documento.atencion_id is not None:
        raise DocumentoNoRevisable("El documento no está por revisar o ya fue incorporado.")
    if not verificado:
        raise ErrorDeAtencion("Debes verificar los datos contra el original antes de incorporarlos.")
    profesional_texto = profesional_texto.strip()
    if not profesional_texto:
        raise ErrorDeAtencion("Indica el profesional del documento o que no consta en el original.")
    campos = _campos_validos(campos)
    fecha_texto = (campos.get("fecha_atencion") or {}).get("valor")
    fecha = date.fromisoformat(fecha_texto) if fecha_texto else None
    # Serializa también revisiones simultáneas de documentos distintos del mismo residente.
    sesion.execute(select(Residente.id).where(
        Residente.id == documento.residente_id
    ).with_for_update())
    duplicados = posibles_duplicados(
        sesion, documento.residente_id, fecha,
        [d["valor"] for d in campos["diagnosticos"] if d.get("valor")],
    )
    if duplicados:
        raise DocumentoDuplicado(duplicados)
    atencion = crear_atencion(
        sesion, documento.residente_id, usuario, campos, OrigenAtencion.HISTORICO,
        fecha_atencion=fecha, documento_id=documento.id,
    )
    momento = ahora()
    atencion.profesional_texto = profesional_texto
    # El historial usa FIRMADA para registros confirmados; no se inventa una firma médica.
    atencion.estado = EstadoAtencion.FIRMADA
    atencion.verificada_por = usuario.id
    atencion.verificada_en = momento
    incorporar_a_ficha(sesion, atencion)
    documento.estado = EstadoDocumento.INCORPORADO
    documento.fecha_original = fecha
    documento.posibles_duplicados = duplicados
    documento.revisado_por = usuario.id
    documento.revisado_en = momento
    adjunto = sesion.get(Adjunto, documento.adjunto_id)
    adjunto.atencion_id = atencion.id
    adjunto.fecha_emision = fecha
    registrar_evento(
        sesion, Accion.DOCUMENTO_INCORPORADO, TipoActor.USUARIO, usuario.id,
        entidad="documento_historico", entidad_id=documento.id,
        detalle={"atencion_id": atencion.id},
    )
    sesion.flush()
    return atencion


def descartar_documento(
    sesion: Session, documento_id: int, usuario: UsuarioWeb, motivo: str
) -> None:
    documento = _documento_bloqueado(sesion, documento_id, usuario)
    if documento.estado not in (EstadoDocumento.POR_REVISAR, EstadoDocumento.ERROR):
        raise DocumentoNoRevisable("Solo se pueden descartar documentos por revisar o en error.")
    if not motivo.strip():
        raise ErrorDeAtencion("Indica el motivo del descarte.")
    documento.estado = EstadoDocumento.DESCARTADO
    documento.motivo_descarte = motivo.strip()
    documento.revisado_por = usuario.id
    documento.revisado_en = ahora()
    registrar_evento(
        sesion, Accion.DOCUMENTO_DESCARTADO, TipoActor.USUARIO, usuario.id,
        entidad="documento_historico", entidad_id=documento.id,
    )
