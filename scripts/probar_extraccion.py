"""Prueba la seudonimización y la extracción con IA sobre un texto, sin pasar por el bot.

Uso:  python -m scripts.probar_extraccion "Hoy atendí a Emilia Soto en el Hogar..."
      python -m scripts.probar_extraccion --especialidad nutrición "Martina Rojas, ..."

Usa los residentes de la base de datos (corre antes scripts.sembrar_datos) y el proveedor de
LLM_PROVIDER. Sirve para afinar las instrucciones con los guiones de la demo. Muestra el texto
y los datos extraídos en la consola: úsalo solo con datos ficticios.
"""

import argparse
import json
import sys

from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.config import obtener_config
from app.db import ahora, crear_fabrica_de_sesiones, crear_motor
from app.modelos import Residente
from app.nucleo.extraccion import ErrorExtraccion, extraer_registro
from app.proveedores.llm import crear_proveedor_llm


def main(argumentos: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Prueba la extracción con IA sobre un texto.")
    parser.add_argument("texto", help="texto del registro, entre comillas")
    parser.add_argument("--especialidad", default="pediatría")
    opciones = parser.parse_args(argumentos)

    config = obtener_config()
    motor = crear_motor(config.database_url)
    try:
        with crear_fabrica_de_sesiones(motor)() as sesion:
            residentes = list(sesion.scalars(select(Residente).order_by(Residente.codigo)))
    except OperationalError:
        print("No se pudo leer la base de datos. ¿Creaste las tablas con: alembic upgrade head?")
        return 1
    finally:
        motor.dispose()
    if not residentes:
        print("No hay residentes en la base de datos. Corre: python -m scripts.sembrar_datos")
        return 1

    llm = crear_proveedor_llm(config)
    try:
        resultado = extraer_registro(opciones.texto, residentes, opciones.especialidad, ahora(), llm)
    except ErrorExtraccion as error:
        print(f"No se pudo extraer: {error}")
        return 1

    print(f"Proveedor: {resultado.proveedor} ({resultado.modelo})\n")
    print("Lo que recibió el LLM:")
    print(resultado.entrada)
    print("\nDatos extraídos y validados:")
    print(
        json.dumps(resultado.registro.model_dump(exclude_none=True), indent=2, ensure_ascii=False)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
