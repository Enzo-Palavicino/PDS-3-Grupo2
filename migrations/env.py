"""Entorno de Alembic: conecta las migraciones con los modelos y con la base de datos."""

from logging.config import fileConfig

from alembic import context

from app import modelos  # noqa: F401  (al importarlo, las tablas quedan en Base.metadata)
from app.config import obtener_config
from app.db import Base, FechaHoraUTC, crear_motor

config = context.config

# El comando alembic configura sus logs con alembic.ini. Los tests llaman a Alembic sin ese
# archivo, para no alterar los logs de la aplicación.
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def _url() -> str:
    # Los tests indican la URL directamente; si no, se usa DATABASE_URL.
    return config.get_main_option("sqlalchemy.url") or obtener_config().database_url


def _renderizar_tipo(tipo: str, objeto, contexto):
    """En las migraciones generadas, FechaHoraUTC se escribe como sa.DateTime(): en la base de
    datos es una columna de fecha común, y la conversión a UTC la hace el modelo."""
    if tipo == "type" and isinstance(objeto, FechaHoraUTC):
        return "sa.DateTime()"
    return False


def _opciones() -> dict:
    return {
        "target_metadata": Base.metadata,
        "render_item": _renderizar_tipo,
        # SQLite casi no permite modificar tablas: en ese caso Alembic las recrea ("batch").
        "render_as_batch": True,
    }


if context.is_offline_mode():
    # alembic upgrade head --sql: escribe el SQL en vez de ejecutarlo.
    context.configure(url=_url(), literal_binds=True, **_opciones())
    with context.begin_transaction():
        context.run_migrations()
else:
    motor = crear_motor(_url())
    with motor.connect() as conexion:
        context.configure(connection=conexion, **_opciones())
        with context.begin_transaction():
            context.run_migrations()
    motor.dispose()
