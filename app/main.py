"""Punto de entrada de la aplicación. uvicorn la levanta con: uvicorn app.main:app --reload"""

from fastapi import FastAPI

from app.config import Config, obtener_config
from app.logs import configurar_logs


def crear_app(config: Config | None = None) -> FastAPI:
    """Crea la aplicación. Los tests pueden pasarle su propia configuración."""
    config = config or obtener_config()
    configurar_logs(config.log_level)

    app = FastAPI(title="Plataforma de salud del Hogar Misión de María")

    @app.get("/health")
    def estado_servicio() -> dict[str, str]:
        """Estado del servicio. Es público, así que no expone ningún dato."""
        return {"estado": "ok"}

    return app


app = crear_app()
