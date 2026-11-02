"""Configuración de la aplicación, leída desde variables de entorno o desde el archivo .env."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """Cada atributo se lee de la variable de entorno del mismo nombre en mayúsculas
    (log_level se lee de LOG_LEVEL). Las variables de entorno tienen prioridad sobre .env."""

    # extra="ignore": .env puede traer variables que esta versión del código todavía no usa.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


@lru_cache
def obtener_config() -> Config:
    """Lee la configuración una sola vez y la reutiliza."""
    return Config()
