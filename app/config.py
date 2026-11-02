"""Configuración de la aplicación, leída desde variables de entorno o desde el archivo .env."""

import tempfile
from functools import lru_cache
from pathlib import Path
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

    # Por defecto, un archivo SQLite en data/ (ignorada por git). En el servidor, PostgreSQL.
    database_url: str = "sqlite:///./data/app.db"
    # Contraseña de los usuarios de demostración que crea scripts/sembrar_datos.py.
    seed_password: SecretStr | None = None

    # Transcripción de audios. fake: devuelve un texto fijo (tests y pruebas sin API key).
    stt_provider: Literal["fake", "openai"] = "fake"
    stt_model: str = "gpt-transcribe"
    # Carpeta donde se guarda cada audio solo mientras se transcribe. Por defecto, la carpeta
    # temporal del usuario: fuera del repositorio y de OneDrive.
    audio_dir: Path = Path(tempfile.gettempdir()) / "pds3-audios"

    # Extracción de los campos con IA. fake: no usa IA y deja los campos vacíos (tests).
    llm_provider: Literal["fake", "openai"] = "fake"
    llm_model: str = "gpt-6-luna"

    # La API key de OpenAI que entregó el curso: sirve para la transcripción y para el LLM.
    openai_api_key: SecretStr | None = None

    @model_validator(mode="after")
    def _exigir_credenciales(self) -> "Config":
        if self.telegram_mode != "off" and not self.telegram_bot_token:
            raise ValueError(f"TELEGRAM_MODE={self.telegram_mode} requiere TELEGRAM_BOT_TOKEN")
        if not self.openai_api_key:
            if self.stt_provider == "openai":
                raise ValueError("STT_PROVIDER=openai requiere OPENAI_API_KEY")
            if self.llm_provider == "openai":
                raise ValueError("LLM_PROVIDER=openai requiere OPENAI_API_KEY")
        return self


@lru_cache
def obtener_config() -> Config:
    """Lee la configuración una sola vez y la reutiliza."""
    return Config()
