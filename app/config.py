"""Configuración de la aplicación, leída desde variables de entorno o desde el archivo .env."""

import re
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Telegram solo acepta estos caracteres en el secreto del webhook.
SECRETO_DE_WEBHOOK = re.compile(r"[A-Za-z0-9_-]{1,256}")


class Config(BaseSettings):
    """Cada atributo se lee de la variable de entorno del mismo nombre en mayúsculas
    (log_level se lee de LOG_LEVEL). Las variables de entorno tienen prioridad sobre .env."""

    # extra="ignore": .env puede traer variables que esta versión del código todavía no usa.
    # populate_by_name: los tests pueden pasar los valores por el nombre del atributo.
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # SecretStr evita que el token se imprima por accidente: se muestra como '**********'.
    telegram_bot_token: SecretStr | None = None
    # off: no recibe mensajes (tests y CI). polling: desarrollo local con getUpdates.
    # webhook: en el servidor; Telegram envía cada mensaje a /webhooks/telegram.
    telegram_mode: Literal["off", "polling", "webhook"] = "off"
    # Secreto que Telegram envía en cada petición al webhook: prueba que la petición viene de él.
    telegram_webhook_secret: SecretStr | None = None
    # true: el bot borra del chat el mensaje del profesional una vez procesado.
    telegram_delete_incoming: bool = False

    # Kapso entrega los mensajes de WhatsApp por webhook HTTPS (formato kapso v2).
    whatsapp_enabled: bool = False
    kapso_api_key: SecretStr | None = None
    kapso_phone_number_id: str = ""
    kapso_webhook_secret: SecretStr | None = None
    # Número visible, internacional, solo dígitos (distinto del phone_number_id).
    whatsapp_phone_number: str = ""

    # Dirección de la plataforma web, para los enlaces que envía el bot. En Render se toma sola
    # de RENDER_EXTERNAL_URL, la dirección pública del servicio.
    public_base_url: str = Field(
        "http://localhost:8000",
        validation_alias=AliasChoices("PUBLIC_BASE_URL", "RENDER_EXTERNAL_URL"),
    )
    # Firma la cookie de sesión de la web. Si no se define, se genera una al azar al arrancar, y
    # las sesiones se cierran cada vez que se reinicia la aplicación.
    secret_key: SecretStr | None = None
    # Un borrador pendiente que no cambia en estos días aparece marcado "sin actividad" en la
    # web, para que alguien lo revise (regla 9 de la especificación). Nunca se borra solo.
    dias_sin_actividad_borrador: int = Field(30, ge=1)

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
            raise ValueError(
                f"TELEGRAM_MODE={self.telegram_mode} requiere TELEGRAM_BOT_TOKEN"
            )
        if self.telegram_mode == "webhook":
            secreto = self.telegram_webhook_secret
            if not secreto or not SECRETO_DE_WEBHOOK.fullmatch(
                secreto.get_secret_value()
            ):
                raise ValueError(
                    "TELEGRAM_MODE=webhook requiere TELEGRAM_WEBHOOK_SECRET, con 1 a 256 "
                    "letras, números, _ o -"
                )
            if not self.public_base_url.startswith("https://"):
                raise ValueError(
                    "TELEGRAM_MODE=webhook requiere una PUBLIC_BASE_URL con https"
                )
        if self.whatsapp_enabled:
            if (
                not self.kapso_api_key
                or not self.kapso_api_key.get_secret_value().strip()
            ):
                raise ValueError("WHATSAPP_ENABLED requiere KAPSO_API_KEY")
            if not re.fullmatch(r"[0-9]+", self.kapso_phone_number_id):
                raise ValueError(
                    "WHATSAPP_ENABLED requiere KAPSO_PHONE_NUMBER_ID numérico"
                )
            if (
                not self.kapso_webhook_secret
                or not self.kapso_webhook_secret.get_secret_value().strip()
            ):
                raise ValueError("WHATSAPP_ENABLED requiere KAPSO_WEBHOOK_SECRET")
            if not re.fullmatch(r"[1-9][0-9]{6,14}", self.whatsapp_phone_number):
                raise ValueError(
                    "WHATSAPP_PHONE_NUMBER debe llevar código de país, sin + ni espacios"
                )
            if not self.public_base_url.startswith("https://"):
                raise ValueError("WHATSAPP_ENABLED requiere PUBLIC_BASE_URL con https")
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
