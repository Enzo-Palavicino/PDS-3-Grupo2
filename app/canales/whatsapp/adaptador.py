"""Traduce el payload de whatsapp.message.received de Kapso (v2)."""

import hashlib
import hmac
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from app.canales.base import AdaptadorCanal, Ignorado, MensajeNormalizado
from app.canales.whatsapp.cliente import ClienteKapso

ENCABEZADO_FIRMA = "X-Webhook-Signature"


class AdaptadorWhatsApp(AdaptadorCanal):
    canal = "whatsapp"

    def __init__(self, cliente: ClienteKapso, secreto_webhook: str):
        self.cliente = cliente
        self._secreto = secreto_webhook

    def verificar_peticion(self, headers: Mapping[str, str], body: bytes) -> bool:
        firma = next(
            (v for k, v in headers.items() if k.lower() == ENCABEZADO_FIRMA.lower()), ""
        )
        esperada = hmac.new(self._secreto.encode(), body, hashlib.sha256).hexdigest()
        return bool(self._secreto) and hmac.compare_digest(
            firma.encode(), esperada.encode()
        )

    def parsear(self, evento: dict[str, Any]) -> MensajeNormalizado | Ignorado:
        if evento.get("phone_number_id") != self.cliente.phone_number_id:
            return Ignorado("WhatsApp: número receptor diferente")
        mensaje = evento.get("message")
        if not isinstance(mensaje, dict):
            return Ignorado("WhatsApp: evento sin mensaje")
        kapso = mensaje.get("kapso") or {}
        if not isinstance(kapso, dict) or kapso.get("direction") != "inbound":
            return Ignorado("WhatsApp: evento no entrante")
        if kapso.get("passive") or kapso.get("origin") == "history_sync":
            return Ignorado("WhatsApp: mensaje pasivo o histórico")
        remitente = mensaje.get("from") or mensaje.get("from_user_id")
        identificador = mensaje.get("id")
        if not all(isinstance(x, str) and x for x in (remitente, identificador)):
            return Ignorado("WhatsApp: faltan identificadores")
        if not remitente.isdecimal() and not remitente.startswith("US."):
            return Ignorado("WhatsApp: remitente no individual")
        try:
            fecha = datetime.fromtimestamp(int(mensaje["timestamp"]), UTC)
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            return Ignorado("WhatsApp: fecha inválida")
        contexto = mensaje.get("context") or {}
        respuesta_a = contexto.get("id") if isinstance(contexto, dict) else None
        datos = {
            "canal": self.canal,
            "id_externo": identificador,
            "remitente_externo": remitente,
            "destino_respuesta": remitente,
            "recibido_en": fecha,
            "responde_a_id_externo": respuesta_a
            if isinstance(respuesta_a, str)
            else None,
        }
        if mensaje.get("type") == "text":
            texto = mensaje.get("text")
            texto = texto.get("body") if isinstance(texto, dict) else None
            if not isinstance(texto, str) or not texto.strip():
                return Ignorado("WhatsApp: texto vacío o inválido")
            texto = texto.strip()
            return MensajeNormalizado(
                **datos,
                tipo="comando" if texto.startswith("/") else "texto",
                texto=texto,
            )
        if mensaje.get("type") == "audio":
            audio = mensaje.get("audio") or {}
            if (
                not isinstance(audio, dict)
                or not isinstance(audio.get("id"), str)
                or not audio["id"]
            ):
                return Ignorado("WhatsApp: audio sin referencia")
            media = kapso.get("media_data") or {}
            media = media if isinstance(media, dict) else {}
            mime = audio.get("mime_type") or media.get("content_type")
            tamano = media.get("byte_size")
            return MensajeNormalizado(
                **datos,
                tipo="audio",
                audio_ref=audio["id"],
                audio_mime=mime.split(";", 1)[0].strip().lower()
                if isinstance(mime, str)
                else None,
                audio_tamano_bytes=tamano
                if isinstance(tamano, int) and tamano >= 0
                else None,
            )
        return MensajeNormalizado(**datos, tipo="no_soportado")

    def descargar_audio(self, referencia: str) -> tuple[bytes, str]:
        return self.cliente.descargar_audio(referencia)

    def enviar_texto(
        self, destino: str, texto: str, responder_a: str | None = None
    ) -> str:
        return self.cliente.enviar_mensaje(destino, texto, responder_a)

    def borrar_mensaje(self, destino: str, id_mensaje_externo: str) -> bool:
        # La API no permite borrar del chat el mensaje entrante del profesional.
        return False
