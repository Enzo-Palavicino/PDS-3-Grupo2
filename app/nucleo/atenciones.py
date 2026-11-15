"""Atenciones: todo lo que las crea, las edita, las firma y las pasa a la ficha.

Una atención en borrador se puede editar. Firmada, ya no cambia: se corrige con una adenda. Las
funciones validan los datos y la inmutabilidad, pero no los permisos del usuario: eso lo revisa
la web con app/nucleo/permisos.py antes de llamarlas.

Contrato del esqueleto (E1-01): las firmas no cambian sin avisar a quien las usa.
"""

from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.modelos import Atencion, OrigenAtencion, UsuarioWeb


class ErrorDeAtencion(Exception):
    """Error de una operación sobre una atención. Su mensaje se puede mostrar en la web."""


class AtencionFirmada(ErrorDeAtencion):
    """Se intentó modificar una atención firmada. En la web corresponde a un 409."""


class DatosIncompletos(ErrorDeAtencion):
    """Faltan datos obligatorios: el residente, la fecha y el motivo o el diagnóstico."""

    def __init__(self, faltantes: list[str]):
        super().__init__("Faltan datos obligatorios: " + ", ".join(faltantes))
        self.faltantes = faltantes


class PasswordIncorrecta(ErrorDeAtencion):
    """La contraseña que se reingresó para firmar no es la del usuario."""


def crear_atencion(
    sesion: Session,
    residente_id: int,
    autor: UsuarioWeb,
    campos: dict[str, Any],
    origen: OrigenAtencion,
    fecha_atencion: date | None = None,
    borrador_id: int | None = None,
    documento_id: int | None = None,
) -> Atencion:
    """Crea una atención en borrador y la audita (atencion_creada).

    - autor: el usuario web que la registra. Si es un profesional, queda como profesional de la
      atención.
    - campos: con el formato de app/nucleo/campos.py.
    - borrador_id: el borrador de la IA del que viene, si llegó por mensajería.
    - documento_id: el documento histórico del que viene; el documento queda apuntando a la
      atención.

    Lanza DatosIncompletos si faltan el residente, la fecha o el motivo o diagnóstico (en una
    atención histórica la fecha puede faltar).
    """
    raise NotImplementedError


def actualizar_atencion(
    sesion: Session,
    atencion: Atencion,
    campos: dict[str, Any],
    usuario: UsuarioWeb,
    fecha_atencion: date | None = None,
) -> Atencion:
    """Reemplaza los campos de una atención en borrador, anota cuáles se cambiaron a mano y lo
    audita (atencion_editada).

    Lanza AtencionFirmada si ya está firmada y DatosIncompletos si faltan datos obligatorios.
    """
    raise NotImplementedError


def firmar_atencion(
    sesion: Session, atencion: Atencion, usuario: UsuarioWeb, password: str
) -> Atencion:
    """Firma la atención con la contraseña del profesional autor, todo en una transacción:

    - guarda quién firmó, cuándo y el hash SHA-256 de lo firmado;
    - pasa el borrador de IA de origen, si hay, al estado confirmado;
    - llama a incorporar_a_ficha;
    - audita atencion_firmada.

    Lanza PasswordIncorrecta, AtencionFirmada o DatosIncompletos. Si algo falla, no queda nada
    firmado.
    """
    raise NotImplementedError


def verificar_integridad(atencion: Atencion) -> bool:
    """Recalcula el hash de una atención firmada y lo compara con el guardado al firmar. False si
    el contenido cambió después de la firma o si la atención no está firmada."""
    raise NotImplementedError


def incorporar_a_ficha(sesion: Session, atencion: Atencion) -> None:
    """Pasa los datos de una atención a la ficha del residente: tratamientos, próximo control,
    antecedentes (alergias, vacunas, hospitalizaciones) y mediciones (peso y talla).

    La llaman firmar_atencion y la incorporación de un documento histórico (E4-04). Si la
    atención ya se incorporó, no hace nada.
    """
    raise NotImplementedError
