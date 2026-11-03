"""Cliente de Kapso. Los errores nunca incluyen claves, URLs ni contenido del mensaje."""

from urllib.parse import quote, urlsplit

import httpx2

from app.canales.base import ErrorDeCanal

URL_API = "https://api.kapso.ai/meta/whatsapp/v24.0"
MAXIMO_AUDIO = 20 * 1024 * 1024


class ClienteKapso:
    def __init__(
        self, api_key: str, phone_number_id: str, http: httpx2.Client | None = None
    ):
        self._api_key = api_key
        self.phone_number_id = phone_number_id
        self._http = http or httpx2.Client(timeout=30, follow_redirects=False)

    def cerrar(self) -> None:
        self._http.close()

    def enviar_mensaje(
        self, destino: str, texto: str, responder_a: str | None = None
    ) -> str:
        datos = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "type": "text",
            "text": {"body": texto, "preview_url": False},
        }
        # BSUID: WhatsApp puede ocultar el teléfono del remitente.
        datos["to" if destino.isdecimal() else "recipient"] = destino
        if responder_a:
            datos["context"] = {"message_id": responder_a}
        respuesta = self._json(
            "POST", f"{quote(self.phone_number_id, safe='')}/messages", json=datos
        )
        try:
            identificador = respuesta["messages"][0]["id"]
            if not isinstance(identificador, str) or not identificador:
                raise ValueError
            return identificador
        except (KeyError, IndexError, TypeError, ValueError):
            raise ErrorDeCanal("Kapso: respuesta de envío inválida") from None

    def descargar_audio(self, referencia: str) -> tuple[bytes, str]:
        datos = self._json(
            "GET",
            quote(referencia, safe=""),
            params={"phone_number_id": self.phone_number_id},
        )
        try:
            tamano = int(datos.get("file_size", 0))
        except (TypeError, ValueError):
            raise ErrorDeCanal("Kapso: tamaño de audio inválido") from None
        if tamano > MAXIMO_AUDIO:
            raise ErrorDeCanal("Kapso: el audio supera 20 MB")
        url = datos.get("download_url")
        if not isinstance(url, str):
            raise ErrorDeCanal("Kapso: falta la URL de descarga del audio")
        partes = urlsplit(url)
        if (
            partes.scheme != "https"
            or partes.netloc != "api.kapso.ai"
            or partes.path != "/meta/whatsapp/media_download"
        ):
            raise ErrorDeCanal("Kapso: URL de descarga no permitida")
        try:
            # El token de download_url autentica la descarga; no se envía la API key.
            with self._http.stream("GET", url, follow_redirects=False) as respuesta:
                self._comprobar(respuesta)
                contenido = bytearray()
                for bloque in respuesta.iter_bytes():
                    if len(contenido) + len(bloque) > MAXIMO_AUDIO:
                        raise ErrorDeCanal("Kapso: el audio supera 20 MB")
                    contenido.extend(bloque)
                mime = datos.get("mime_type") or respuesta.headers.get(
                    "content-type", "audio/ogg"
                )
                return bytes(contenido), mime.split(";", 1)[0].strip().lower()
        except httpx2.HTTPError:
            raise ErrorDeCanal("Kapso: error de red al descargar el audio") from None

    def _json(self, metodo: str, ruta: str, **parametros) -> dict:
        try:
            respuesta = self._http.request(
                metodo,
                f"{URL_API}/{ruta}",
                headers={"X-API-Key": self._api_key},
                follow_redirects=False,
                **parametros,
            )
            self._comprobar(respuesta)
            datos = respuesta.json()
        except httpx2.HTTPError:
            raise ErrorDeCanal("Kapso: error de red") from None
        except ValueError:
            raise ErrorDeCanal("Kapso: respuesta JSON inválida") from None
        if not isinstance(datos, dict):
            raise ErrorDeCanal("Kapso: respuesta JSON inválida")
        return datos

    @staticmethod
    def _comprobar(respuesta: httpx2.Response) -> None:
        if not 200 <= respuesta.status_code < 300:
            espera = respuesta.headers.get("retry-after", "")
            raise ErrorDeCanal(
                f"Kapso: HTTP {respuesta.status_code}",
                reintentar_en=int(espera) if espera.isdecimal() else None,
            )
