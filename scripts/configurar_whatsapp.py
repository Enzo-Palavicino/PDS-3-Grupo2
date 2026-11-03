"""Registra el webhook Kapso v2 usando .env. Ejecutar después de publicar la URL HTTPS.

Uso: python -m scripts.configurar_whatsapp
No envía mensajes de WhatsApp. No modifica webhooks existentes.
"""

import sys

import httpx2

from app.config import Config, obtener_config
from app.logs import configurar_logs


def registrar(config: Config, http: httpx2.Client) -> str:
    if not config.whatsapp_enabled:
        raise ValueError(
            "Primero configura WHATSAPP_ENABLED=true y las variables de Kapso."
        )
    url = f"{config.public_base_url.rstrip('/')}/webhooks/whatsapp"
    endpoint = (
        "https://api.kapso.ai/platform/v1/whatsapp/phone_numbers/"
        f"{config.kapso_phone_number_id}/webhooks"
    )
    headers = {"X-API-Key": config.kapso_api_key.get_secret_value()}
    respuesta = http.get(endpoint, headers=headers)
    if respuesta.status_code != 200:
        raise ValueError(
            f"No se pudieron consultar los webhooks: HTTP {respuesta.status_code}."
        )
    cuerpo = respuesta.json()
    datos = cuerpo.get("data") if isinstance(cuerpo, dict) else None
    if not isinstance(datos, list):
        raise TypeError("Kapso devolvió una lista de webhooks inválida.")
    if any(
        isinstance(webhook, dict) and webhook.get("url") == url for webhook in datos
    ):
        return (
            "Ya existe un webhook para esta URL. No se creó otro. Revisa en Kapso que esté "
            "activo, sea tipo kapso v2, suscrito a whatsapp.message.received y use el mismo secreto."
        )
    respuesta = http.post(
        endpoint,
        headers=headers,
        json={
            "whatsapp_webhook": {
                "kind": "kapso",
                "url": url,
                "secret_key": config.kapso_webhook_secret.get_secret_value(),
                "events": ["whatsapp.message.received"],
                "active": True,
                "buffer_enabled": False,
            }
        },
    )
    if respuesta.status_code != 201:
        raise ValueError(f"No se pudo crear el webhook: HTTP {respuesta.status_code}.")
    return f"Webhook creado: {url}. Ahora vincula un profesional y envía un mensaje desde WhatsApp."


def main() -> int:
    configurar_logs("INFO")
    try:
        config = obtener_config()
        with httpx2.Client(timeout=30, follow_redirects=False) as http:
            mensaje = registrar(config, http)
    except httpx2.HTTPError:
        print("No se pudo conectar con Kapso. Revisa la conexión e intenta de nuevo.")
        return 1
    except (ValueError, TypeError):
        print(
            "No se pudo registrar el webhook. Revisa .env, la API key y el Phone Number ID."
        )
        return 1
    print(mensaje)
    return 0


if __name__ == "__main__":
    sys.exit(main())
