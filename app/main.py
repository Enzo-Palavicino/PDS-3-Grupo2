"""Punto de entrada de la aplicación. uvicorn la levanta con: uvicorn app.main:app --reload"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.canales.telegram.adaptador import AdaptadorTelegram
from app.canales.telegram.cliente import ClienteBotTelegram
from app.canales.telegram.eco import crear_manejador_eco
from app.canales.telegram.polling import PollingTelegram
from app.config import Config, obtener_config
from app.logs import configurar_logs


def crear_app(config: Config | None = None) -> FastAPI:
    """Crea la aplicación. Los tests pueden pasarle su propia configuración."""
    config = config or obtener_config()
    configurar_logs(config.log_level)

    @asynccontextmanager
    async def ciclo_de_vida(_app: FastAPI) -> AsyncGenerator[None, None]:
        """Arranca la recepción de mensajes al iniciar la aplicación y la detiene al cerrarla."""
        polling = None
        if config.telegram_mode == "polling":
            cliente = ClienteBotTelegram(config.telegram_bot_token.get_secret_value())
            # Por ahora el bot solo responde un eco, para probar la conexión.
            polling = PollingTelegram(cliente, crear_manejador_eco(AdaptadorTelegram(cliente)))
            polling.iniciar()
        yield
        if polling:
            polling.detener()

    app = FastAPI(title="Plataforma de salud del Hogar Misión de María", lifespan=ciclo_de_vida)

    @app.get("/health")
    def estado_servicio() -> dict[str, str]:
        """Estado del servicio. Es público, así que no expone ningún dato."""
        return {"estado": "ok"}

    return app


app = crear_app()
