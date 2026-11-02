"""Punto de entrada de la aplicación. uvicorn la levanta con: uvicorn app.main:app --reload"""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from app.canales.telegram.adaptador import AdaptadorTelegram
from app.canales.telegram.cliente import ClienteBotTelegram
from app.canales.telegram.polling import PollingTelegram
from app.config import Config, obtener_config
from app.db import crear_fabrica_de_sesiones, crear_motor, esquema_creado
from app.logs import configurar_logs
from app.nucleo.ingesta import enviar_respuestas, ingerir

logger = logging.getLogger(__name__)


def crear_app(config: Config | None = None) -> FastAPI:
    """Crea la aplicación. Los tests pueden pasarle su propia configuración."""
    config = config or obtener_config()
    configurar_logs(config.log_level)

    @asynccontextmanager
    async def ciclo_de_vida(_app: FastAPI) -> AsyncGenerator[None, None]:
        """Arranca la recepción de mensajes al iniciar la aplicación y la detiene al cerrarla."""
        motor = crear_motor(config.database_url)
        if not esquema_creado(motor):
            logger.error("La base de datos no tiene tablas: corre primero alembic upgrade head")
        fabrica_de_sesiones = crear_fabrica_de_sesiones(motor)

        polling = None
        if config.telegram_mode == "polling":
            cliente = ClienteBotTelegram(config.telegram_bot_token.get_secret_value())
            adaptador = AdaptadorTelegram(cliente)

            def manejar_update(update: dict[str, Any]) -> None:
                enviar_respuestas(adaptador, ingerir(fabrica_de_sesiones, adaptador, update))

            polling = PollingTelegram(cliente, manejar_update)
            polling.iniciar()
        yield
        if polling:
            polling.detener()
        motor.dispose()

    app = FastAPI(title="Plataforma de salud del Hogar Misión de María", lifespan=ciclo_de_vida)

    @app.get("/health")
    def estado_servicio() -> dict[str, str]:
        """Estado del servicio. Es público, así que no expone ningún dato."""
        return {"estado": "ok"}

    return app


app = crear_app()
