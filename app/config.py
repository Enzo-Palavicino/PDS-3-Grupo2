"""Configuración de la aplicación, leída desde variables de entorno o desde el archivo .env."""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """Cada atributo se lee de la variable de entorno del mismo nombre en mayúsculas
    (log_level se lee de LOG_LEVEL). Las variables de entorno tienen prioridad sobre .env."""

    # extra="ignore": .env puede traer variables que esta versión del código todavía no usa.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # SecretStr evita que el token se imprima por accidente: se muestra como '**********'.
    telegram_bot_token: SecretStr | None = None
    # off: no recibe mensajes (tests y CI). polling: desarrollo local con getUpdates.
    telegram_mode: Literal["off", "polling"] = "off"

    @model_validator(mode="after")
    def _exigir_token_de_telegram(self) -> "Config":
        if self.telegram_mode != "off" and not self.telegram_bot_token:
            raise ValueError(f"TELEGRAM_MODE={self.telegram_mode} requiere TELEGRAM_BOT_TOKEN")
        return self


@lru_cache
def obtener_config() -> Config:
    """Lee la configuración una sola vez y la reutiliza."""
    return Config()
