"""Configuración común a todos los tests."""

import os

# Los tests nunca se conectan a Telegram, aunque el .env local tenga TELEGRAM_MODE=polling:
# las variables de entorno tienen prioridad sobre .env.
os.environ["TELEGRAM_MODE"] = "off"
