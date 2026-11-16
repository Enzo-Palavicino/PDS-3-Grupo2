"""Ficha del residente: todo lo que la lee (E1-02).

Contrato del esqueleto (E1-01): las firmas no cambian sin avisar a quien las usa.
"""

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.modelos import Antecedente, Atencion, Control, Medicion, Residente, Tratamiento


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


def resumen_de_ficha(sesion: Session, residente_id: int) -> ResumenFicha:
    """Resumen de la ficha de un residente. Solo información confirmada: nunca borradores."""
    raise NotImplementedError


def historial(sesion: Session, residente_id: int) -> list[Atencion]:
    """Atenciones firmadas del residente, de la más reciente a la más antigua."""
    raise NotImplementedError
