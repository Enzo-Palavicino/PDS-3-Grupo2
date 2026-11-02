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
from app.nucleo.procesamiento import Contexto
from app.nucleo.worker import Worker
from app.proveedores.llm import crear_proveedor_llm
from app.proveedores.stt import crear_proveedor_stt

logger = logging.getLogger(__name__)


def crear_app(config: Config | None = None) -> FastAPI:
    """Crea la aplicación. Los tests pueden pasarle su propia configuración."""
    config = config or obtener_config()
    configurar_logs(config.log_level)

    @asynccontextmanager
    async def ciclo_de_vida(_app: FastAPI) -> AsyncGenerator[None, None]:
        """Arranca la recepción y el procesamiento de mensajes al iniciar la aplicación, y los
        detiene al cerrarla."""
        motor = crear_motor(config.database_url)
        if not esquema_creado(motor):
            logger.error("La base de datos no tiene tablas: corre primero alembic upgrade head")
        fabrica_de_sesiones = crear_fabrica_de_sesiones(motor)

        polling = worker = None
        if config.telegram_mode == "polling":
            cliente = ClienteBotTelegram(config.telegram_bot_token.get_secret_value())
            adaptador = AdaptadorTelegram(cliente)
            contexto = Contexto(
                adaptadores={"telegram": adaptador},
                stt=crear_proveedor_stt(config),
                llm=crear_proveedor_llm(config),
                carpeta_audios=config.audio_dir,
                url_publica=config.public_base_url,
                borrar_mensajes_importados=config.telegram_delete_incoming,
            )
            worker = Worker(fabrica_de_sesiones, contexto)

            def manejar_update(update: dict[str, Any]) -> None:
                enviar_respuestas(adaptador, ingerir(fabrica_de_sesiones, adaptador, update))
                worker.despertar()  # si se guardó un mensaje, se procesa en segundo plano

            polling = PollingTelegram(cliente, manejar_update)
            worker.iniciar()
            polling.iniciar()
        yield
        if polling:
            polling.detener()
        if worker:
            worker.detener()
        motor.dispose()

    app = FastAPI(title="Plataforma de salud del Hogar Misión de María", lifespan=ciclo_de_vida)

    @app.get("/health")
    def estado_servicio() -> dict[str, str]:
        """Estado del servicio. Es público, así que no expone ningún dato."""
        return {"estado": "ok"}

    return app


app = crear_app()
