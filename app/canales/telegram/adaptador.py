"""Adaptador de Telegram: traduce los updates de la Bot API a MensajeNormalizado y le ofrece al
núcleo las operaciones del canal (responder, borrar mensajes y descargar audios)."""

import hmac
import mimetypes
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from app.canales.base import AdaptadorCanal, Ignorado, MensajeNormalizado
from app.canales.telegram.cliente import ClienteBotTelegram, ErrorTelegram

# En modo webhook, Telegram envía en este encabezado el secreto configurado con setWebhook.
ENCABEZADO_SECRETO = "X-Telegram-Bot-Api-Secret-Token"


class AdaptadorTelegram(AdaptadorCanal):
    canal = "telegram"

    def __init__(self, cliente: ClienteBotTelegram, secreto_webhook: str | None = None):
        self._cliente = cliente
        self._secreto_webhook = secreto_webhook

    def verificar_peticion(self, headers: Mapping[str, str], body: bytes) -> bool:
        if not self._secreto_webhook:
            return False
        recibido = next(
            (valor for nombre, valor in headers.items() if nombre.lower() == ENCABEZADO_SECRETO.lower()),
            None,
        )
        # compare_digest tarda lo mismo acierte o no, así que el tiempo de respuesta no revela
        # cuántos caracteres del secreto coinciden.
        return recibido is not None and hmac.compare_digest(
            recibido.encode(), self._secreto_webhook.encode()
        )

    def parsear(self, evento: dict[str, Any]) -> MensajeNormalizado | Ignorado:
        mensaje = evento.get("message")
        if mensaje is None:
            # edited_message, callback_query y otros tipos de update.
            return Ignorado("tipo de update no soportado")
        chat = mensaje["chat"]
        if chat["type"] != "private":
            return Ignorado("chat no privado")
        remitente = mensaje.get("from", {})
        if remitente.get("is_bot"):
            return Ignorado("mensaje de un bot")

        chat_id = str(chat["id"])
        original = mensaje.get("reply_to_message")
        datos = {
            "canal": self.canal,
            "id_externo": f"{chat_id}:{mensaje['message_id']}",
            # En un chat privado, chat.id y from.id son el mismo usuario.
            "remitente_externo": str(remitente.get("id", chat_id)),
            "destino_respuesta": chat_id,
            "recibido_en": datetime.fromtimestamp(mensaje["date"], tz=UTC),
            "responde_a_id_externo": f"{chat_id}:{original['message_id']}" if original else None,
        }

        if "text" in mensaje:
            texto = mensaje["text"]
            tipo = "comando" if texto.startswith("/") else "texto"
            return MensajeNormalizado(tipo=tipo, texto=texto, **datos)

        # voice es una nota de voz grabada en el chat; audio, un archivo de audio adjunto.
        audio = mensaje.get("voice") or mensaje.get("audio")
        if audio:
            return MensajeNormalizado(
                tipo="audio",
                audio_ref=audio["file_id"],
                audio_mime=audio.get("mime_type"),
                audio_tamano_bytes=audio.get("file_size"),
                audio_duracion_seg=audio.get("duration"),
                **datos,
            )

        # Stickers, fotos, documentos, ubicaciones, etc.
        return MensajeNormalizado(tipo="no_soportado", **datos)

    def descargar_audio(self, referencia: str) -> tuple[bytes, str]:
        ruta = self._cliente.obtener_archivo(referencia)["file_path"]
        return self._cliente.descargar_archivo(ruta), _tipo_mime(ruta)

    def enviar_texto(self, destino: str, texto: str, responder_a: str | None = None) -> str:
        enviado = self._cliente.enviar_mensaje(
            destino, texto, responder_a=_id_mensaje(responder_a) if responder_a else None
        )
        return f"{enviado['chat']['id']}:{enviado['message_id']}"

    def borrar_mensaje(self, destino: str, id_mensaje_externo: str) -> bool:
        try:
            self._cliente.borrar_mensaje(destino, _id_mensaje(id_mensaje_externo))
        except ErrorTelegram as error:
            if error.codigo == 400:  # el mensaje ya no existe o tiene más de 48 horas
                return False
            raise
        return True


def _id_mensaje(id_externo: str) -> int:
    """Extrae el message_id de un id externo con la forma "chat.id:message_id"."""
    return int(id_externo.rsplit(":", 1)[1])


def _tipo_mime(ruta: str) -> str:
    # Las notas de voz llegan como .oga: audio OGG con códec Opus.
    if ruta.lower().endswith((".oga", ".ogg", ".opus")):
        return "audio/ogg"
    return mimetypes.guess_type(ruta)[0] or "application/octet-stream"
