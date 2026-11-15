from datetime import date, datetime

from alembic import command
from sqlalchemy import text

from app.db import crear_motor


def test_los_modelos_coinciden_con_las_migraciones(url_bd, configurar_alembic):
    # Falla si alguien cambió un modelo sin crear su migración (alembic revision --autogenerate).
    command.check(configurar_alembic(url_bd))


def test_las_migraciones_se_pueden_revertir(url_bd, configurar_alembic):
    configuracion = configurar_alembic(url_bd)

    command.downgrade(configuracion, "base")
    command.upgrade(configuracion, "head")


def test_la_0004_deja_activos_los_residentes_que_ya_existian(tmp_path, configurar_alembic):
    # Como en el servidor: ya hay residentes y profesionales cuando se aplica la 0004.
    url = f"sqlite:///{(tmp_path / 'servidor.db').as_posix()}"
    configuracion = configurar_alembic(url)
    command.upgrade(configuracion, "0003")
    motor = crear_motor(url)
    insertar_datos_previos_a_la_0004(motor)

    command.upgrade(configuracion, "head")
    with motor.connect() as conexion:
        assert conexion.execute(text("SELECT codigo, estado FROM residentes")).one() == (
            "RES-01",
            "activo",
        )
        assert conexion.execute(text("SELECT nombre, registro FROM profesionales")).one() == (
            "Profesional de prueba",
            None,
        )

    # Revertirla tampoco pierde datos, aunque SQLite tenga que recrear las tablas.
    command.downgrade(configuracion, "0003")
    with motor.connect() as conexion:
        assert conexion.execute(text("SELECT codigo FROM residentes")).scalar_one() == "RES-01"
    motor.dispose()


def insertar_datos_previos_a_la_0004(motor) -> None:
    """Un residente y un profesional con las columnas que tenían antes de la 0004."""
    with motor.begin() as conexion:
        conexion.execute(
            text(
                "INSERT INTO residentes (codigo, nombres, apellidos, fecha_nacimiento, nivel)"
                " VALUES ('RES-01', 'Tomás', 'Rivas', :nacimiento, 'heterogeneo')"
            ),
            {"nacimiento": date(2023, 7, 14)},
        )
        conexion.execute(
            text(
                "INSERT INTO profesionales (nombre, especialidad, activo, creado_en)"
                " VALUES ('Profesional de prueba', 'pediatría', :activo, :creado)"
            ),
            {"activo": True, "creado": datetime(2026, 11, 2, 15, 0)},
        )
