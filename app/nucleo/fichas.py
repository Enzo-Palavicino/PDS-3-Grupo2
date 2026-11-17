"""Ficha del residente: todo lo que la lee (E1-02).

Contrato del esqueleto (E1-01): las firmas no cambian sin avisar a quien las usa.

La ficha muestra solo información confirmada. Lo que la IA extrajo y nadie firmó todavía vive en
los borradores, que la web muestra aparte. Los antecedentes, tratamientos, controles y mediciones
se crean al firmar una atención (app/nucleo/incorporacion.py), o directamente sin atención (por
ejemplo, al ingreso); igual se filtran por la atención, para que un dato de una atención sin
firmar nunca aparezca como confirmado.
"""

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.modelos import (
    Antecedente,
    Atencion,
    Control,
    EstadoAtencion,
    EstadoControl,
    Medicion,
    Residente,
    TipoAntecedente,
    Tratamiento,
)
from app.nucleo.tratamientos import tratamientos_del_residente


@dataclass
class ResumenFicha:
    """Lo más importante de la ficha, que se muestra primero."""

    residente: Residente
    alergias: list[Antecedente] = field(default_factory=list)
    diagnosticos: list[Antecedente] = field(default_factory=list)
    tratamientos_activos: list[Tratamiento] = field(default_factory=list)
    ultima_medicion: Medicion | None = None
    proximos_controles: list[Control] = field(default_factory=list)
    hospitalizaciones: list[Antecedente] = field(default_factory=list)
    vacunas: list[Antecedente] = field(default_factory=list)


def resumen_de_ficha(
    sesion: Session, residente_id: int, hoy: date | None = None
) -> ResumenFicha:
    """Resumen de la ficha de un residente. Solo información confirmada: nunca borradores.

    hoy decide qué tratamientos siguen vigentes; las pruebas lo fijan para no depender del día.
    Lanza LookupError si el residente no existe.
    """
    residente = sesion.get(Residente, residente_id)
    if residente is None:
        raise LookupError("Residente no encontrado.")
    antecedentes = _antecedentes(sesion, residente_id)
    return ResumenFicha(
        residente=residente,
        alergias=antecedentes.get(TipoAntecedente.ALERGIA, []),
        diagnosticos=antecedentes.get(TipoAntecedente.DIAGNOSTICO_CRONICO, []),
        tratamientos_activos=_confirmados(
            sesion, tratamientos_del_residente(sesion, residente_id, hoy).vigentes
        ),
        ultima_medicion=_ultima_medicion(sesion, residente_id),
        proximos_controles=_proximos_controles(sesion, residente_id),
        hospitalizaciones=antecedentes.get(TipoAntecedente.HOSPITALIZACION, []),
        vacunas=antecedentes.get(TipoAntecedente.VACUNA, []),
    )


def historial(sesion: Session, residente_id: int) -> list[Atencion]:
    """Atenciones firmadas del residente, de la más reciente a la más antigua.

    Se ordenan por la fecha de la atención; las del mismo día, por la hora de firma. Una atención
    histórica sin fecha conocida va al final.
    """
    return list(
        sesion.scalars(
            select(Atencion)
            .where(
                Atencion.residente_id == residente_id,
                Atencion.estado == EstadoAtencion.FIRMADA,
            )
            .order_by(
                Atencion.fecha_atencion.desc().nulls_last(),
                Atencion.firmada_en.desc().nulls_last(),
                Atencion.id.desc(),
            )
        )
    )


def _de_atencion_firmada(columna):
    """Condición: el dato no viene de una atención, o viene de una atención firmada."""
    firmadas = select(Atencion.id).where(Atencion.estado == EstadoAtencion.FIRMADA)
    return or_(columna.is_(None), columna.in_(firmadas))


def _antecedentes(sesion: Session, residente_id: int) -> dict[str, list[Antecedente]]:
    """Antecedentes confirmados del residente por tipo, del más reciente al más antiguo."""
    por_tipo: dict[str, list[Antecedente]] = {}
    filas = sesion.scalars(
        select(Antecedente)
        .where(
            Antecedente.residente_id == residente_id,
            _de_atencion_firmada(Antecedente.atencion_id),
        )
        .order_by(Antecedente.fecha.desc().nulls_last(), Antecedente.id.desc())
    )
    for antecedente in filas:
        por_tipo.setdefault(antecedente.tipo, []).append(antecedente)
    return por_tipo


def _confirmados(sesion: Session, tratamientos: list[Tratamiento]) -> list[Tratamiento]:
    """Los tratamientos que vienen de una atención firmada, en el mismo orden."""
    ids = {t.atencion_id for t in tratamientos}
    if not ids:
        return []
    firmadas = set(
        sesion.scalars(
            select(Atencion.id).where(
                Atencion.id.in_(ids), Atencion.estado == EstadoAtencion.FIRMADA
            )
        )
    )
    return [t for t in tratamientos if t.atencion_id in firmadas]


def _ultima_medicion(sesion: Session, residente_id: int) -> Medicion | None:
    """La medición más reciente. Si dos son del mismo día, la última registrada."""
    return sesion.scalars(
        select(Medicion)
        .where(
            Medicion.residente_id == residente_id,
            _de_atencion_firmada(Medicion.atencion_id),
        )
        .order_by(Medicion.fecha.desc().nulls_last(), Medicion.id.desc())
        .limit(1)
    ).first()


def _proximos_controles(sesion: Session, residente_id: int) -> list[Control]:
    """Controles pendientes, del más próximo al más lejano; los sin fecha, al final. Incluye los
    atrasados, que siguen pendientes. Los realizados y los anulados no aparecen."""
    return list(
        sesion.scalars(
            select(Control)
            .where(
                Control.residente_id == residente_id,
                Control.estado == EstadoControl.PENDIENTE,
                _de_atencion_firmada(Control.atencion_id),
            )
            .order_by(Control.fecha.asc().nulls_last(), Control.id.asc())
        )
    )
