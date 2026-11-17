"""Incorporación de una atención a la ficha del residente (E1-03).

Cuando una atención se firma (o se verifica un documento histórico), sus datos pasan a la ficha
sin que nadie los copie a mano:

- cada indicación farmacológica, a un tratamiento activo;
- el próximo control, a un control pendiente;
- las alergias, vacunas y hospitalizaciones, a antecedentes;
- el peso y la talla, a una medición.

Los diagnósticos no se copian: quedan en el historial, que son las atenciones firmadas.

Si la atención es una adenda, antes se retira lo que aportó la atención que corrige: sus
tratamientos vigentes quedan suspendidos y sus controles pendientes, anulados. Así la ficha no
muestra a la vez el dato corregido y el original.

Se usa a través de app.nucleo.atenciones.incorporar_a_ficha, que es el contrato del esqueleto.
"""

from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import ahora
from app.modelos import (
    Antecedente,
    Atencion,
    Control,
    EstadoControl,
    EstadoTratamiento,
    Medicion,
    OrigenAtencion,
    TipoAntecedente,
    Tratamiento,
    UsuarioWeb,
)
from app.nucleo.extraccion import ZONA_HORARIA
from app.nucleo.tratamientos import estado_vigente, suspender_tratamiento

ANTECEDENTES = {
    "alergias": TipoAntecedente.ALERGIA,
    "vacunas": TipoAntecedente.VACUNA,
    "hospitalizaciones": TipoAntecedente.HOSPITALIZACION,
}


def incorporar(sesion: Session, atencion: Atencion, momento: datetime | None = None) -> None:
    """Pasa los datos de la atención a la ficha y la marca como incorporada. Si ya estaba
    incorporada, no hace nada: firmar o reintentar no duplica nada. No hace commit.

    momento es "ahora"; las pruebas lo fijan para no depender del día en que corren.
    """
    if atencion.incorporada_en is not None:
        return
    momento = momento or ahora()
    hoy = momento.astimezone(ZONA_HORARIA).date()
    if atencion.corrige_a_id is not None:
        _retirar_lo_corregido(sesion, atencion, momento)
    campos = atencion.campos or {}
    autor = atencion.firmada_por or atencion.verificada_por or atencion.creado_por

    for indicacion in campos.get("indicaciones_farmacologicas") or []:
        if tratamiento := _tratamiento(atencion, indicacion, hoy):
            sesion.add(tratamiento)
    if control := _control(atencion, campos.get("proximo_control")):
        sesion.add(control)
    for nombre, tipo in ANTECEDENTES.items():
        for dato in campos.get(nombre) or []:
            descripcion = _texto(dato.get("valor")) if isinstance(dato, dict) else None
            if descripcion:
                sesion.add(
                    Antecedente(
                        residente_id=atencion.residente_id,
                        atencion_id=atencion.id,
                        tipo=tipo,
                        descripcion=descripcion,
                        fecha=atencion.fecha_atencion,  # cuándo quedó registrado
                        registrado_por=autor,
                    )
                )
    if medicion := _medicion(atencion, campos.get("mediciones")):
        sesion.add(medicion)
    atencion.incorporada_en = momento


def _retirar_lo_corregido(sesion: Session, adenda: Atencion, momento: datetime) -> None:
    """Suspende los tratamientos vigentes y anula los controles pendientes de la atención que la
    adenda corrige. La suspensión queda a nombre de quien firmó la adenda."""
    firmante = sesion.get(UsuarioWeb, adenda.firmada_por)
    motivo = f"Corregido por la atención #{adenda.id}"
    hoy = momento.astimezone(ZONA_HORARIA).date()
    tratamientos = sesion.scalars(
        select(Tratamiento).where(Tratamiento.atencion_id == adenda.corrige_a_id)
    )
    for tratamiento in tratamientos:
        if estado_vigente(tratamiento, hoy) == EstadoTratamiento.ACTIVO:
            suspender_tratamiento(sesion, tratamiento, firmante, motivo, momento)
    controles = sesion.scalars(
        select(Control).where(
            Control.atencion_id == adenda.corrige_a_id,
            Control.estado == EstadoControl.PENDIENTE,
        )
    )
    for control in controles:
        control.estado = EstadoControl.ANULADO


def _tratamiento(atencion: Atencion, indicacion: Any, hoy: date) -> Tratamiento | None:
    if not isinstance(indicacion, dict) or not _texto(indicacion.get("medicamento")):
        return None
    termino = _fecha(indicacion.get("fecha_termino"))
    # Una atención histórica no es una indicación vigente: sus tratamientos quedan terminados,
    # salvo que el documento diga que terminan en el futuro. Si siguen, se vuelven a indicar.
    historica = atencion.origen == OrigenAtencion.HISTORICO
    vigente = not historica or (termino is not None and termino >= hoy)
    return Tratamiento(
        residente_id=atencion.residente_id,
        atencion_id=atencion.id,
        medicamento=_texto(indicacion.get("medicamento")),
        dosis=_texto(indicacion.get("dosis")),
        frecuencia_horario=_texto(indicacion.get("frecuencia_horario")),
        via=_texto(indicacion.get("via")),
        duracion=_texto(indicacion.get("duracion")),
        indicado_en=atencion.fecha_atencion,
        fecha_inicio=_fecha(indicacion.get("fecha_inicio")),
        fecha_termino=termino,
        estado=EstadoTratamiento.ACTIVO if vigente else EstadoTratamiento.TERMINADO,
    )


def _control(atencion: Atencion, dato: Any) -> Control | None:
    if not isinstance(dato, dict):
        return None
    fecha, descripcion = _fecha(dato.get("fecha")), _texto(dato.get("descripcion"))
    if fecha is None and descripcion is None:
        return None
    return Control(
        residente_id=atencion.residente_id,
        atencion_id=atencion.id,
        fecha=fecha,
        descripcion=descripcion,
        estado=EstadoControl.PENDIENTE,
    )


def _medicion(atencion: Atencion, dato: Any) -> Medicion | None:
    if not isinstance(dato, dict):
        return None
    peso, talla = _numero(dato.get("peso_kg")), _numero(dato.get("talla_cm"))
    if peso is None and talla is None:
        return None
    return Medicion(
        residente_id=atencion.residente_id,
        atencion_id=atencion.id,
        fecha=atencion.fecha_atencion,
        peso_kg=peso,
        talla_cm=talla,
    )


def _texto(valor: Any) -> str | None:
    return valor.strip() or None if isinstance(valor, str) else None


def _fecha(valor: Any) -> date | None:
    """Una fecha AAAA-MM-DD, o None si falta o no es válida: un dato mal escrito no impide
    incorporar el resto de la atención."""
    if not isinstance(valor, str):
        return None
    try:
        return date.fromisoformat(valor.strip())
    except ValueError:
        return None


def _numero(valor: Any) -> float | None:
    """Un número positivo; acepta coma decimal ("12,4"). None si falta o no es válido."""
    if isinstance(valor, bool):
        return None
    if isinstance(valor, str):
        valor = valor.strip().replace(",", ".")
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None
    return numero if numero > 0 else None
