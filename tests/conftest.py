"""Configuración común a todos los tests."""

import os
import shutil
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config as ConfigAlembic

from app.db import crear_fabrica_de_sesiones, crear_motor

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
def sesion(url_bd):
    motor = crear_motor(url_bd)
    with crear_fabrica_de_sesiones(motor)() as sesion:
        yield sesion
    motor.dispose()


@pytest.fixture
def configurar_alembic():
    return configuracion_alembic
