"""Genera un enlace de vinculación de Telegram para un profesional, desde la consola.

Uso:  python -m scripts.generar_codigo <usuario web del profesional>
      python -m scripts.generar_codigo pediatra

Sirve mientras no exista la vista web de vínculos, donde la directora generará los enlaces.
El enlace es de un solo uso y vence en 10 minutos.
"""

import sys

from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.canales.telegram.cliente import ClienteBotTelegram, ErrorTelegram
from app.config import Config, obtener_config
from app.db import crear_fabrica_de_sesiones, crear_motor
from app.modelos import UsuarioWeb
from app.nucleo.vinculacion import generar_codigo


def main(argumentos: list[str]) -> int:
    if len(argumentos) != 1:
        print("Uso: python -m scripts.generar_codigo <usuario web del profesional>")
        return 1
    nombre_usuario = argumentos[0]
    config = obtener_config()
    motor = crear_motor(config.database_url)
    try:
        with crear_fabrica_de_sesiones(motor).begin() as sesion:
            usuario = sesion.scalar(select(UsuarioWeb).where(UsuarioWeb.usuario == nombre_usuario))
            if usuario is None or usuario.profesional_id is None:
                print(f"No hay un profesional con el usuario web '{nombre_usuario}'.")
                return 1
            codigo = generar_codigo(sesion, usuario.profesional_id).codigo
    except OperationalError:
        print("No se pudo generar el código. ¿Creaste las tablas con: alembic upgrade head?")
        return 1
    finally:
        motor.dispose()

    print("Código de vinculación (un solo uso, vence en 10 minutos):", codigo)
    usuario_bot = _usuario_del_bot(config)
    if usuario_bot:
        print(f"Abre este enlace en Telegram: https://t.me/{usuario_bot}?start={codigo}")
    else:
        print(f"Envíale al bot este mensaje: /start {codigo}")
    return 0


def _usuario_del_bot(config: Config) -> str | None:
    """Nombre de usuario del bot, para armar el enlace. None si no se puede consultar."""
    if not config.telegram_bot_token:
        return None
    try:
        bot = ClienteBotTelegram(config.telegram_bot_token.get_secret_value()).obtener_bot()
    except ErrorTelegram:
        return None
    return bot.get("username")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
