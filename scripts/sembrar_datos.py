"""Carga los datos de demostración: residentes, profesionales y usuarios web.

Uso:  python -m scripts.sembrar_datos

Todos los datos son inventados. Se puede correr varias veces: lo que ya existe no se duplica.
La contraseña de los usuarios sale de SEED_PASSWORD (en .env), nunca del código.
"""

import sys
from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.config import obtener_config
from app.db import crear_fabrica_de_sesiones, crear_motor
from app.modelos import Nivel, Profesional, Residente, Rol, UsuarioWeb
from app.seguridad import hashear_password

# Edades al 2 de noviembre de 2026. Los dos "Tomás" sirven para probar nombres ambiguos.
RESIDENTES = [
    # código, nombres, apellidos, apodo, fecha de nacimiento, nivel
    ("RES-01", "Tomás", "Rivas", "Tomi", date(2023, 7, 14), Nivel.HETEROGENEO),  # 3 años
    ("RES-02", "Emilia", "Soto", "Emi", date(2025, 12, 28), Nivel.SALA_CUNA_MENOR),  # 10 meses
    ("RES-03", "Martina", "Rojas", "Marti", date(2025, 2, 20), Nivel.SALA_CUNA_MAYOR),  # 20 meses
    ("RES-04", "Tomás", "Díaz", None, date(2022, 9, 3), Nivel.HETEROGENEO),  # 4 años
]

PROFESIONALES = [
    # nombre, especialidad, usuario web
    ("Carolina Fuentes", "pediatría", "pediatra"),
    ("Felipe Araya", "nutrición", "nutricionista"),
    ("Javiera Muñoz", "kinesiología", "kinesiologo"),
]

USUARIOS_SIN_PROFESIONAL = [
    ("directora", Rol.DIRECTORA),
    ("encargada_salud", Rol.ENCARGADA_SALUD),
]


def sembrar(sesion: Session, password: str) -> None:
    for codigo, nombres, apellidos, apodo, nacimiento, nivel in RESIDENTES:
        if not _existe(sesion, Residente.codigo, codigo):
            sesion.add(
                Residente(
                    codigo=codigo,
                    nombres=nombres,
                    apellidos=apellidos,
                    apodo=apodo,
                    fecha_nacimiento=nacimiento,
                    nivel=nivel,
                )
            )

    for usuario, rol in USUARIOS_SIN_PROFESIONAL:
        if not _existe(sesion, UsuarioWeb.usuario, usuario):
            sesion.add(UsuarioWeb(usuario=usuario, rol=rol, hash_password=hashear_password(password)))

    for nombre, especialidad, usuario in PROFESIONALES:
        if _existe(sesion, UsuarioWeb.usuario, usuario):
            continue
        profesional = Profesional(nombre=nombre, especialidad=especialidad)
        sesion.add(profesional)
        sesion.flush()  # asigna profesional.id, que necesita el usuario
        sesion.add(
            UsuarioWeb(
                usuario=usuario,
                rol=Rol.PROFESIONAL,
                profesional_id=profesional.id,
                hash_password=hashear_password(password),
            )
        )


def _existe(sesion: Session, columna, valor) -> bool:
    return sesion.scalar(select(columna).where(columna == valor)) is not None


def main() -> int:
    config = obtener_config()
    if not config.seed_password:
        print("Falta SEED_PASSWORD en .env: es la contraseña de los usuarios de demostración.")
        return 1
    motor = crear_motor(config.database_url)
    try:
        with crear_fabrica_de_sesiones(motor).begin() as sesion:
            sembrar(sesion, config.seed_password.get_secret_value())
    except OperationalError:
        print("No se pudo cargar los datos. ¿Creaste las tablas con: alembic upgrade head?")
        return 1
    finally:
        motor.dispose()
    usuarios = [usuario for usuario, _ in USUARIOS_SIN_PROFESIONAL]
    usuarios += [usuario for _, _, usuario in PROFESIONALES]
    print("Datos de demostración cargados. Usuarios web:", ", ".join(usuarios))
    print("Todos usan la contraseña de SEED_PASSWORD.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
