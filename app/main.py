"""Punto de entrada de la aplicación. uvicorn la levanta con: uvicorn app.main:app --reload"""

import logging
import secrets
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from http import HTTPStatus
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

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
from app.web import autenticacion, borradores, vinculos
from app.web.autenticacion import SesionRequerida
from app.web.plantillas import pagina

logger = logging.getLogger(__name__)

TITULOS_DE_ERROR = {403: "Sin acceso", 404: "No encontrado"}


def crear_app(config: Config | None = None) -> FastAPI:
    """Crea la aplicación. Los tests pueden pasarle su propia configuración."""
    config = config or obtener_config()
    configurar_logs(config.log_level)

    @asynccontextmanager
    async def ciclo_de_vida(aplicacion: FastAPI) -> AsyncGenerator[None, None]:
        """Al iniciar: conecta la base de datos y arranca la recepción y el procesamiento de
        mensajes. Al cerrar: los detiene."""
        motor = crear_motor(config.database_url)
        if not esquema_creado(motor):
            logger.error("La base de datos no tiene tablas: corre primero alembic upgrade head")
        fabrica_de_sesiones = crear_fabrica_de_sesiones(motor)
        cliente = None
        if config.telegram_bot_token:
            cliente = ClienteBotTelegram(config.telegram_bot_token.get_secret_value())
        # Lo que usan las páginas web.
        aplicacion.state.fabrica_de_sesiones = fabrica_de_sesiones
        aplicacion.state.cliente_telegram = cliente
        aplicacion.state.usuario_bot = None

        polling = worker = None
        if config.telegram_mode == "polling":
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
    app.add_middleware(
        SessionMiddleware,
        secret_key=_clave_de_sesion(config),
        max_age=8 * 60 * 60,  # la sesión dura 8 horas
        same_site="lax",
        # Con HTTPS (en el servidor), la cookie solo viaja cifrada.
        https_only=config.public_base_url.startswith("https://"),
    )
    app.include_router(autenticacion.router)
    app.include_router(vinculos.router)
    app.include_router(borradores.router)

    @app.exception_handler(SesionRequerida)
    async def ir_al_inicio_de_sesion(request: Request, error: SesionRequerida):
        return RedirectResponse(f"/login?siguiente={quote(error.siguiente)}", status_code=303)

    @app.exception_handler(StarletteHTTPException)
    async def pagina_de_error(request: Request, error: StarletteHTTPException):
        mensaje = error.detail
        if mensaje == HTTPStatus(error.status_code).phrase:  # texto genérico, en inglés
            mensaje = "La página no existe." if error.status_code == 404 else "Ocurrió un error."
        return pagina(
            request,
            "error.html",
            status_code=error.status_code,
            codigo=error.status_code,
            titulo=TITULOS_DE_ERROR.get(error.status_code, "Error"),
            mensaje=mensaje,
        )

    @app.get("/health")
    def estado_servicio() -> dict[str, str]:
        """Estado del servicio. Es público, así que no expone ningún dato."""
        return {"estado": "ok"}

    return app


def _clave_de_sesion(config: Config) -> str:
    if config.secret_key:
        return config.secret_key.get_secret_value()
    logger.warning(
        "SECRET_KEY no está definida: se usa una clave temporal y las sesiones de la web se "
        "cierran cada vez que se reinicia la aplicación"
    )
    return secrets.token_urlsafe(32)


app = crear_app()
