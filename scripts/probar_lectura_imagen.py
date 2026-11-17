"""Prueba real de lectura literal de una imagen ficticia, sin base de datos ni worker.

Uso: python -m scripts.probar_lectura_imagen --datos-ficticios ruta/al/documento.jpg
Muestra la lectura y su tiempo en consola; no guarda imágenes ni textos en logs.
"""

import argparse
import sys
from pathlib import Path
from time import perf_counter

from openai import APIConnectionError, APIStatusError
from pydantic import ValidationError

from app.config import obtener_config
from app.nucleo.adjuntos import TAMANO_MAXIMO_BYTES, ArchivoNoPermitido, detectar_mime
from app.proveedores.llm import crear_proveedor_llm
from app.proveedores.llm.base import ErrorLLM


def main(argumentos: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Lee un manuscrito ficticio con el modelo del curso.")
    parser.add_argument("imagen", type=Path, help="imagen JPG o PNG de hasta 10 MB")
    parser.add_argument(
        "--datos-ficticios", action="store_true", required=True,
        help="confirma que la imagen no contiene datos personales o clínicos reales",
    )
    opciones = parser.parse_args(argumentos)

    try:
        with opciones.imagen.open("rb") as archivo:
            contenido = archivo.read(TAMANO_MAXIMO_BYTES + 1)
        mime = detectar_mime(contenido)
        if mime not in ("image/jpeg", "image/png"):
            raise ArchivoNoPermitido("Esta prueba requiere JPG o PNG, no PDF.")
    except OSError:
        print("No se pudo abrir la imagen. Revisa la ruta y sus permisos.", file=sys.stderr)
        return 1
    except ArchivoNoPermitido as error:
        print(f"Imagen no válida: {error}", file=sys.stderr)
        return 1

    try:
        config = obtener_config()
    except ValidationError:
        print("Configuración inválida. Revisa las variables de .env.", file=sys.stderr)
        return 1
    if config.llm_provider != "openai" or not config.openai_api_key:
        print(
            "La prueba real requiere LLM_PROVIDER=openai y OPENAI_API_KEY en .env.",
            file=sys.stderr,
        )
        return 1
    llm = crear_proveedor_llm(config)
    inicio = perf_counter()
    try:
        resultado = llm.leer_imagen(contenido, mime)
    except APIStatusError as error:
        print(
            f"La API rechazó la lectura (HTTP {error.status_code}). "
            "Verifica los permisos del modelo, el saldo y el formato de imagen. "
            "No se ha confirmado soporte de imágenes.",
            file=sys.stderr,
        )
        return 1
    except APIConnectionError:
        print("No se pudo conectar con la API. Revisa la conexión e intenta de nuevo.", file=sys.stderr)
        return 1
    except ErrorLLM as error:
        print(f"No se obtuvo una lectura válida: {error}", file=sys.stderr)
        return 1

    print(f"Proveedor: {llm.nombre}")
    print(f"Modelo solicitado: {config.llm_model}")
    print(f"Modelo usado: {resultado.modelo}")
    print(f"Tiempo de respuesta: {perf_counter() - inicio:.2f} s")
    print("\nTexto literal:\n")
    print(resultado.texto)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
