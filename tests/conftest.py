"""Configuración común a todos los tests."""

import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config as ConfigAlembic

from app.canales.base import MensajeNormalizado
from app.db import crear_fabrica_de_sesiones, crear_motor
from app.modelos import Profesional

# Los tests nunca se conectan a Telegram, aunque el .env local tenga TELEGRAM_MODE=polling:
# las variables de entorno tienen prioridad sobre .env.
os.environ["TELEGRAM_MODE"] = "off"

RAIZ = Path(__file__).resolve().parent.parent


def configuracion_alembic(url: str) -> ConfigAlembic:
    """Configuración de Alembic sin alembic.ini, para que no modifique los logs de los tests."""
    configuracion = ConfigAlembic()
    configuracion.set_main_option("script_location", str(RAIZ / "migrations"))
    configuracion.set_main_option("sqlalchemy.url", url)
    return configuracion


def _url_sqlite(ruta: Path) -> str:
    return f"sqlite:///{ruta.as_posix()}"


# Base de datos


@pytest.fixture(scope="session")
def bd_migrada(tmp_path_factory) -> Path:
    """Base de datos SQLite con todas las migraciones aplicadas. Se crea una sola vez."""
    ruta = tmp_path_factory.mktemp("bd") / "plantilla.db"
    command.upgrade(configuracion_alembic(_url_sqlite(ruta)), "head")
    return ruta


@pytest.fixture
def url_bd(bd_migrada, tmp_path) -> str:
    """URL de una copia nueva de la base de datos migrada: cada test parte de cero."""
    ruta = tmp_path / "test.db"
    shutil.copy(bd_migrada, ruta)
    return _url_sqlite(ruta)


@pytest.fixture
def fabrica_de_sesiones(url_bd):
    motor = crear_motor(url_bd)
    yield crear_fabrica_de_sesiones(motor)
    motor.dispose()


@pytest.fixture
def sesion(fabrica_de_sesiones):
    with fabrica_de_sesiones() as sesion:
        yield sesion


@pytest.fixture
def configurar_alembic():
    return configuracion_alembic


# Datos de prueba


@pytest.fixture
def profesional(sesion) -> Profesional:
    profesional = Profesional(nombre="Profesional de prueba", especialidad="pediatría")
    sesion.add(profesional)
    sesion.commit()
    return profesional


@pytest.fixture
def crear_mensaje():
    """Crea un MensajeNormalizado de Telegram; cada test cambia solo los campos que le importan."""

    def crear(**cambios) -> MensajeNormalizado:
        datos = {
            "canal": "telegram",
            "id_externo": "55667788:412",
            "remitente_externo": "55667788",
            "destino_respuesta": "55667788",
            "tipo": "texto",
            "recibido_en": datetime(2026, 11, 2, 15, 40, tzinfo=UTC),
            "texto": "Mensaje de prueba",
        }
        return MensajeNormalizado(**(datos | cambios))

    return crear
