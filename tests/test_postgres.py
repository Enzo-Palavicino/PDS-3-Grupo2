"""Pruebas contra un PostgreSQL real, como el del servidor.

Solo corren si está definida TEST_POSTGRES_URL (en el CI, un PostgreSQL en un contenedor).
Revisan lo que cambia respecto de SQLite: las migraciones, el trigger de auditoría, los SAVEPOINT
y el índice único parcial de los vínculos.
"""

import os

import pytest
from alembic import command
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.db import crear_fabrica_de_sesiones, crear_motor
from app.modelos import (
    EventoAuditoria,
    MensajeEntrante,
    Profesional,
    TipoActor,
    VinculoCanal,
)
from app.nucleo.mensajes import registrar_mensaje_entrante

URL = os.environ.get("TEST_POSTGRES_URL")

pytestmark = pytest.mark.skipif(not URL, reason="sin TEST_POSTGRES_URL")


@pytest.fixture
def fabrica_postgres(configurar_alembic):
    configuracion = configurar_alembic(URL)
    command.downgrade(configuracion, "base")  # parte de una base de datos vacía
    command.upgrade(configuracion, "head")
    motor = crear_motor(URL)
    yield crear_fabrica_de_sesiones(motor)
    motor.dispose()
    command.downgrade(configuracion, "base")


@pytest.fixture
def profesional_postgres(fabrica_postgres) -> int:
    with fabrica_postgres.begin() as sesion:
        profesional = Profesional(nombre="Profesional de prueba", especialidad="pediatría")
        sesion.add(profesional)
        sesion.flush()
        return profesional.id


def test_los_modelos_coinciden_con_las_migraciones(fabrica_postgres, configurar_alembic):
    command.check(configurar_alembic(URL))


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE eventos_auditoria SET accion = 'modificada'",
        "DELETE FROM eventos_auditoria",
        "TRUNCATE eventos_auditoria",
    ],
)
def test_la_auditoria_es_solo_de_insercion(fabrica_postgres, sql):
    with fabrica_postgres.begin() as sesion:
        sesion.add(EventoAuditoria(actor_tipo=TipoActor.SISTEMA, accion="prueba"))

    with fabrica_postgres() as sesion, pytest.raises(DBAPIError, match="solo de inserción"):
        sesion.execute(text(sql))

    with fabrica_postgres() as sesion:
        assert sesion.scalar(select(func.count()).select_from(EventoAuditoria)) == 1


def test_un_mensaje_duplicado_no_crea_otra_fila(
    fabrica_postgres, profesional_postgres, crear_mensaje
):
    with fabrica_postgres.begin() as sesion:
        assert registrar_mensaje_entrante(sesion, crear_mensaje(), profesional_postgres)
        assert registrar_mensaje_entrante(sesion, crear_mensaje(), profesional_postgres) is None

    with fabrica_postgres() as sesion:
        assert sesion.scalar(select(func.count()).select_from(MensajeEntrante)) == 1


def test_una_cuenta_no_puede_tener_dos_vinculos_activos(fabrica_postgres, profesional_postgres):
    def vincular(activo: bool) -> None:
        with fabrica_postgres.begin() as sesion:
            sesion.add(
                VinculoCanal(
                    profesional_id=profesional_postgres,
                    canal="telegram",
                    id_externo="55667788",
                    activo=activo,
                )
            )

    vincular(activo=False)  # un vínculo revocado no impide uno nuevo
    vincular(activo=True)
    with pytest.raises(IntegrityError):
        vincular(activo=True)
