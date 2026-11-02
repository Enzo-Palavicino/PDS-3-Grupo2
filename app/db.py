"""Conexión a la base de datos.

En desarrollo se usa SQLite (un archivo en data/) y en el servidor, PostgreSQL. Con SQLAlchemy el
mismo código sirve para las dos: solo cambia DATABASE_URL.
"""

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import (
    Connection,
    DateTime,
    Engine,
    MetaData,
    create_engine,
    event,
    inspect,
)
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator

# Nombres fijos para índices y restricciones. Alembic los necesita para poder modificarlos en
# migraciones futuras, sobre todo en SQLite.
CONVENCION_DE_NOMBRES = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Clase base de los modelos: cada subclase es una tabla."""

    metadata = MetaData(naming_convention=CONVENCION_DE_NOMBRES)


class FechaHoraUTC(TypeDecorator):
    """Fecha y hora que se guarda en UTC y se lee con zona horaria.

    SQLite no guarda zonas horarias: sin esto, las fechas volverían sin zona y no se podrían
    comparar con ahora().
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, valor: datetime | None, dialect) -> datetime | None:
        if valor is None:
            return None
        if valor.tzinfo is None:
            raise ValueError("La fecha debe tener zona horaria: usa ahora() o datetime.now(UTC)")
        return valor.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, valor: datetime | None, dialect) -> datetime | None:
        return None if valor is None else valor.replace(tzinfo=UTC)


def ahora() -> datetime:
    """Fecha y hora actual, en UTC."""
    return datetime.now(UTC)


def normalizar_url(url: str) -> str:
    """Render entrega la URL de PostgreSQL como postgres:// o postgresql://. SQLAlchemy necesita
    que indique también el driver: postgresql+psycopg://."""
    for prefijo in ("postgres://", "postgresql://"):
        if url.startswith(prefijo):
            return "postgresql+psycopg://" + url.removeprefix(prefijo)
    return url


def crear_motor(url: str) -> Engine:
    """Crea el motor de conexión a la base de datos de la URL."""
    url = normalizar_url(url)
    url_bd = make_url(url)
    if url_bd.get_backend_name() != "sqlite":
        # pool_pre_ping: revisa que la conexión siga viva antes de usarla.
        return create_engine(url, pool_pre_ping=True)

    if url_bd.database and url_bd.database != ":memory:":
        # SQLite crea el archivo de la base de datos, pero no la carpeta que lo contiene.
        Path(url_bd.database).parent.mkdir(parents=True, exist_ok=True)
    motor = create_engine(url)
    event.listen(motor, "connect", _configurar_conexion_sqlite)
    event.listen(motor, "begin", _iniciar_transaccion_sqlite)
    return motor


def _configurar_conexion_sqlite(conexion_dbapi, _registro) -> None:
    # El driver sqlite3 decide por su cuenta cuándo empezar una transacción, y con eso fallan
    # los SAVEPOINT. Así SQLAlchemy toma el control (ver _iniciar_transaccion_sqlite).
    conexion_dbapi.isolation_level = None
    cursor = conexion_dbapi.cursor()
    # SQLite solo revisa las claves foráneas si se activa en cada conexión.
    cursor.execute("PRAGMA foreign_keys = ON")
    # WAL permite leer mientras otro hilo escribe: el polling, el worker y la web usan la base
    # de datos al mismo tiempo.
    cursor.execute("PRAGMA journal_mode = WAL")
    # Si la base de datos está ocupada, espera hasta 5 s antes de fallar.
    cursor.execute("PRAGMA busy_timeout = 5000")
    cursor.close()


def _iniciar_transaccion_sqlite(conexion: Connection) -> None:
    # IMMEDIATE: la transacción toma el permiso de escritura al empezar. Si otra está escribiendo,
    # espera (busy_timeout) en vez de fallar a la mitad con "database is locked". Por eso las
    # transacciones tienen que ser cortas: ver cerrar_transaccion().
    conexion.exec_driver_sql("BEGIN IMMEDIATE")


def crear_fabrica_de_sesiones(motor: Engine) -> sessionmaker[Session]:
    # expire_on_commit=False: los objetos siguen legibles después del commit, sin volver a la BD.
    return sessionmaker(bind=motor, expire_on_commit=False)


def cerrar_transaccion(sesion: Session) -> None:
    """Cierra la transacción antes de llamar a un servicio externo (Telegram, OpenAI), que puede
    tardar varios segundos. Así la base de datos no queda tomada mientras tanto, y la recepción
    de mensajes y la web pueden seguir escribiendo. Los objetos ya leídos siguen disponibles."""
    sesion.commit()


def esquema_creado(motor: Engine) -> bool:
    """Indica si ya se corrieron las migraciones (alembic upgrade head)."""
    return inspect(motor).has_table("alembic_version")
