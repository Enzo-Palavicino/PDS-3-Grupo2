"""Carga los datos de demostración: residentes, profesionales y usuarios web.

Uso:  python -m scripts.sembrar_datos

Todos los datos son inventados. Se puede correr varias veces: lo que ya existe no se duplica,
y en lo que ya existe solo se completan los campos vacíos (por ejemplo, los que agregó una
migración), sin tocar lo que alguien editó.
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

# Fecha en que cada residente ingresó al Hogar.
INGRESOS = {
    "RES-01": date(2024, 3, 11),
    "RES-02": date(2026, 1, 20),
    "RES-03": date(2025, 6, 2),
    "RES-04": date(2023, 5, 15),
}

PROFESIONALES = [
    # nombre, especialidad, usuario web, registro profesional (inventado)
    ("Carolina Fuentes", "pediatría", "pediatra", "SIS-90001"),
    ("Felipe Araya", "nutrición", "nutricionista", "SIS-90002"),
    ("Javiera Muñoz", "kinesiología", "kinesiologo", "SIS-90003"),
]

USUARIOS_SIN_PROFESIONAL = [
    ("directora", Rol.DIRECTORA),
    ("encargada_salud", Rol.ENCARGADA_SALUD),
]


def sembrar(sesion: Session, password: str) -> None:
    for codigo, nombres, apellidos, apodo, nacimiento, nivel in RESIDENTES:
        ingreso = INGRESOS[codigo]
        residente = sesion.scalar(select(Residente).where(Residente.codigo == codigo))
        if residente is None:
            sesion.add(
                Residente(
                    codigo=codigo,
                    nombres=nombres,
                    apellidos=apellidos,
                    apodo=apodo,
                    fecha_nacimiento=nacimiento,
                    nivel=nivel,
                    fecha_ingreso=ingreso,
                )
            )
        elif residente.fecha_ingreso is None:
            residente.fecha_ingreso = ingreso

    for usuario, rol in USUARIOS_SIN_PROFESIONAL:
        if not _existe(sesion, UsuarioWeb.usuario, usuario):
            sesion.add(UsuarioWeb(usuario=usuario, rol=rol, hash_password=hashear_password(password)))

    for nombre, especialidad, usuario, registro in PROFESIONALES:
        existente = sesion.scalar(select(UsuarioWeb).where(UsuarioWeb.usuario == usuario))
        if existente is not None:
            profesional = sesion.get(Profesional, existente.profesional_id)
            if profesional is not None and profesional.registro is None:
                profesional.registro = registro
            continue
        profesional = Profesional(nombre=nombre, especialidad=especialidad, registro=registro)
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
    usuarios += [usuario for _, _, usuario, _ in PROFESIONALES]
    print("Datos de demostración cargados. Usuarios web:", ", ".join(usuarios))
    print("Todos usan la contraseña de SEED_PASSWORD.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
