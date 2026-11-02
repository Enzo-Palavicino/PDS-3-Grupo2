"""Tipos comunes a todos los canales de mensajería (Telegram ahora, WhatsApp después).

El núcleo de la aplicación trabaja solo con estos tipos, nunca con el formato propio de cada
canal. Cada canal hereda AdaptadorCanal y traduce sus eventos a MensajeNormalizado.
"""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

TipoMensaje = Literal["texto", "audio", "comando", "no_soportado"]


@dataclass(frozen=True)
class MensajeNormalizado:
    """Mensaje recibido por cualquier canal, en un formato común."""

    canal: str
    id_externo: str  # identifica el mensaje en el canal; en Telegram, "chat.id:message_id"
    remitente_externo: str  # quién lo envió; en Telegram, from.id
    destino_respuesta: str  # dónde responder; en Telegram, chat.id
    tipo: TipoMensaje
    recibido_en: datetime
    texto: str | None = None
    audio_ref: str | None = None  # referencia para descargar el audio; en Telegram, file_id
    audio_mime: str | None = None
    audio_tamano_bytes: int | None = None
    audio_duracion_seg: int | None = None
    responde_a_id_externo: str | None = None  # si es respuesta a otro mensaje, el id de ese


@dataclass(frozen=True)
class Ignorado:
    """Evento que no se procesa (por ejemplo, un mensaje de un chat de grupo)."""

    motivo: str


class AdaptadorCanal(ABC):
    """Interfaz que implementa cada canal. Es lo único que el núcleo conoce de un canal."""

    canal: str  # "telegram", "whatsapp"

    @abstractmethod
    def verificar_peticion(self, headers: Mapping[str, str], body: bytes) -> bool:
        """Comprueba que una petición recibida en el webhook venga realmente del canal."""

    @abstractmethod
    def parsear(self, evento: dict[str, Any]) -> MensajeNormalizado | Ignorado:
        """Traduce un evento del canal a MensajeNormalizado, o indica por qué se ignora."""

    @abstractmethod
    def descargar_audio(self, referencia: str) -> tuple[bytes, str]:
        """Descarga un audio y devuelve su contenido y su tipo MIME."""

    @abstractmethod
    def enviar_texto(self, destino: str, texto: str, responder_a: str | None = None) -> str:
        """Envía un texto, opcionalmente como respuesta a otro mensaje, y devuelve su id externo."""

    @abstractmethod
    def borrar_mensaje(self, destino: str, id_mensaje_externo: str) -> bool:
        """Borra un mensaje del chat. Devuelve False si el canal ya no permite borrarlo."""
