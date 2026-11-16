from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db import ahora
from app.modelos import (
    CodigoVinculacion,
    Profesional,
    Rol,
    TipoActor,
    UsuarioWeb,
    VinculoCanal,
)
from app.nucleo.auditoria import Accion, registrar_evento
from app.nucleo.vinculacion import revocar_vinculo
from app.seguridad import hashear_password


def validar_password(password: str) -> None:
    if not 10 <= len(password) <= 128 or not password.strip():
        raise ValueError(
            "La contraseña debe tener entre 10 y 128 caracteres y no ser solo espacios."
        )


def crear_profesional(
    sesion: Session,
    *,
    nombre: str,
    especialidad: str,
    registro: str,
    cuenta: str,
    password: str,
    actor_id: int,
) -> Profesional:
    nombre, especialidad, registro, cuenta = (
        valor.strip() for valor in (nombre, especialidad, registro, cuenta)
    )
    for valor, maximo, etiqueta in (
        (nombre, 120, "nombre"),
        (especialidad, 60, "especialidad"),
        (cuenta, 60, "usuario"),
    ):
        if not valor or len(valor) > maximo:
            raise ValueError(
                f"El {etiqueta} es obligatorio y admite hasta {maximo} caracteres."
            )
    if any(c.isspace() for c in cuenta):
        raise ValueError("El usuario no puede contener espacios.")
    if len(registro) > 120:
        raise ValueError("El registro profesional admite hasta 120 caracteres.")
    validar_password(password)
    if (
        sesion.scalar(select(UsuarioWeb.id).where(UsuarioWeb.usuario == cuenta))
        is not None
    ):
        raise ValueError("Ese usuario ya existe. Elige otro nombre de usuario.")
    profesional = Profesional(
        nombre=nombre, especialidad=especialidad, registro=registro or None
    )
    sesion.add(profesional)
    sesion.flush()
    sesion.add(
        UsuarioWeb(
            usuario=cuenta,
            rol=Rol.PROFESIONAL,
            profesional_id=profesional.id,
            hash_password=hashear_password(password),
        )
    )
    sesion.flush()
    registrar_evento(
        sesion,
        Accion.PROFESIONAL_CREADO,
        TipoActor.USUARIO,
        actor_id=actor_id,
        entidad="profesional",
        entidad_id=profesional.id,
    )
    return profesional


def desactivar_profesional(
    sesion: Session, profesional: Profesional, actor_id: int
) -> None:
    """Conserva la identidad y la autoría; revoca todos los accesos en la misma transacción."""
    if not profesional.activo:
        return
    profesional.activo = False
    sesion.execute(
        update(UsuarioWeb)
        .where(
            UsuarioWeb.profesional_id == profesional.id,
        )
        .values(activo=False)
    )
    sesion.execute(
        update(CodigoVinculacion)
        .where(
            CodigoVinculacion.profesional_id == profesional.id,
            CodigoVinculacion.usado_en.is_(None),
        )
        .values(expira_en=ahora())
    )
    for vinculo in sesion.scalars(
        select(VinculoCanal).where(
            VinculoCanal.profesional_id == profesional.id,
            VinculoCanal.activo,
        )
    ):
        revocar_vinculo(sesion, vinculo, TipoActor.USUARIO, actor_id)
    registrar_evento(
        sesion,
        Accion.PROFESIONAL_DESACTIVADO,
        TipoActor.USUARIO,
        actor_id=actor_id,
        entidad="profesional",
        entidad_id=profesional.id,
    )
