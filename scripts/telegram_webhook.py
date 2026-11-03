"""Configura, borra o muestra el webhook de Telegram.

Uso:  python -m scripts.telegram_webhook set      # Telegram enviará los mensajes al servidor
      python -m scripts.telegram_webhook delete   # el bot vuelve a quedar para polling
      python -m scripts.telegram_webhook info     # URL configurada, pendientes y último error

En el servidor no hace falta "set": en modo webhook, la aplicación lo configura al arrancar.
Mientras un bot tiene un webhook activo, el polling de ese mismo bot no funciona (Telegram
responde 409); para volver a usarlo en local, corre "delete".
"""

import sys

from app.canales.telegram.cliente import ClienteBotTelegram, ErrorTelegram
from app.canales.telegram.webhook import RUTA
from app.config import obtener_config

USO = "Uso: python -m scripts.telegram_webhook set|delete|info"


def main(argumentos: list[str]) -> int:
    if argumentos not in (["set"], ["delete"], ["info"]):
        print(USO)
        return 1
    config = obtener_config()
    if not config.telegram_bot_token:
        print("Falta TELEGRAM_BOT_TOKEN en .env.")
        return 1
    cliente = ClienteBotTelegram(config.telegram_bot_token.get_secret_value())
    try:
        if argumentos == ["set"]:
            return _configurar(cliente, config)
        if argumentos == ["delete"]:
            cliente.borrar_webhook()
            print("Webhook borrado: el bot vuelve a quedar disponible para polling.")
            return 0
        _mostrar(cliente.info_webhook())
    except ErrorTelegram as error:
        print(f"Telegram respondió con un error: {error}")
        return 1
    return 0


def _configurar(cliente: ClienteBotTelegram, config) -> int:
    if not config.telegram_webhook_secret or not config.public_base_url.startswith("https://"):
        print("Faltan TELEGRAM_WEBHOOK_SECRET o una PUBLIC_BASE_URL con https (la del servidor).")
        return 1
    url = f"{config.public_base_url.rstrip('/')}{RUTA}"
    cliente.configurar_webhook(url, config.telegram_webhook_secret.get_secret_value(), ["message"])
    print(f"Webhook configurado en {url}")
    return 0


def _mostrar(info: dict) -> None:
    print("URL:", info.get("url") or "(sin webhook: el bot está en modo polling)")
    print("Updates pendientes:", info.get("pending_update_count", 0))
    if info.get("last_error_message"):
        print("Último error:", info["last_error_message"])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
