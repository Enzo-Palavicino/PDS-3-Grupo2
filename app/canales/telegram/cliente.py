"""Cliente mínimo de la Bot API de Telegram (https://core.telegram.org/bots/api).

Implementa solo los métodos que usa la aplicación. Cada método se llama con un POST a
https://api.telegram.org/bot<TOKEN>/<método>, y Telegram responde un JSON con la forma
{"ok": true, "result": ...} o {"ok": false, "error_code": ..., "description": ...}.

Las URL llevan el token del bot, así que este módulo nunca las incluye en errores ni en logs.
"""

from typing import Any

import httpx2

URL_API = "https://api.telegram.org"

# getUpdates mantiene la petición abierta hasta 30 s esperando mensajes nuevos (long polling),
# así que el tiempo máximo de lectura tiene que ser mayor que eso.
ESPERA_GET_UPDATES_SEG = 30
TIMEOUT = httpx2.Timeout(10.0, read=ESPERA_GET_UPDATES_SEG + 10)


class ErrorTelegram(Exception):
    """Error al llamar a la Bot API. Su mensaje nunca incluye la URL, porque lleva el token."""

    def __init__(
        self, descripcion: str, codigo: int | None = None, reintentar_en: int | None = None
    ):
        super().__init__(descripcion)
        # error_code de Telegram, o None si fue un error de red.
        self.codigo = codigo
        # Segundos que Telegram pide esperar cuando se supera su límite de mensajes (error 429).
        self.reintentar_en = reintentar_en


class ClienteBotTelegram:
    def __init__(self, token: str, http: httpx2.Client | None = None):
        self._token = token
        # Los tests pasan un cliente con un transporte falso, para no salir a internet.
        self._http = http or httpx2.Client(timeout=TIMEOUT)

    def obtener_bot(self) -> dict[str, Any]:
        """getMe: datos del bot, como su nombre de usuario."""
        return self._llamar("getMe")

    def obtener_actualizaciones(
        self, offset: int | None, tipos: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """getUpdates: updates desde offset. Si no hay ninguno, espera hasta 30 s."""
        return self._llamar(
            "getUpdates", offset=offset, timeout=ESPERA_GET_UPDATES_SEG, allowed_updates=tipos
        )

    def enviar_mensaje(
        self, chat_id: str, texto: str, responder_a: int | None = None
    ) -> dict[str, Any]:
        """sendMessage. Con responder_a, el mensaje aparece como respuesta a ese otro."""
        respuesta_a = None
        if responder_a is not None:
            # allow_sending_without_reply: se envía igual si el mensaje original ya fue borrado.
            respuesta_a = {"message_id": responder_a, "allow_sending_without_reply": True}
        return self._llamar(
            "sendMessage", chat_id=chat_id, text=texto, reply_parameters=respuesta_a
        )

    def enviar_accion(self, chat_id: str, accion: str = "typing") -> None:
        """sendChatAction: muestra "escribiendo…" en el chat durante unos 5 segundos."""
        self._llamar("sendChatAction", chat_id=chat_id, action=accion)

    def borrar_mensaje(self, chat_id: str, message_id: int) -> None:
        """deleteMessage. En chats privados se pueden borrar mensajes de menos de 48 horas."""
        self._llamar("deleteMessage", chat_id=chat_id, message_id=message_id)

    def obtener_archivo(self, file_id: str) -> dict[str, Any]:
        """getFile: entrega el file_path para descargar el archivo (máximo 20 MB)."""
        return self._llamar("getFile", file_id=file_id)

    def descargar_archivo(self, file_path: str) -> bytes:
        try:
            respuesta = self._http.get(f"{URL_API}/file/bot{self._token}/{file_path}")
        except httpx2.HTTPError as error:
            # "from None" descarta el error original, que puede incluir la URL con el token.
            raise ErrorTelegram(
                f"error de red al descargar un archivo ({type(error).__name__})"
            ) from None
        if respuesta.status_code != 200:
            raise ErrorTelegram(
                f"no se pudo descargar el archivo (HTTP {respuesta.status_code})",
                codigo=respuesta.status_code,
            )
        return respuesta.content

    def _llamar(self, metodo: str, **parametros: Any) -> Any:
        datos = {nombre: valor for nombre, valor in parametros.items() if valor is not None}
        try:
            respuesta = self._http.post(f"{URL_API}/bot{self._token}/{metodo}", json=datos)
            cuerpo = respuesta.json()
        except httpx2.HTTPError as error:
            raise ErrorTelegram(f"{metodo}: error de red ({type(error).__name__})") from None
        except ValueError:
            raise ErrorTelegram(
                f"{metodo}: respuesta inválida (HTTP {respuesta.status_code})",
                codigo=respuesta.status_code,
            ) from None
        if not cuerpo.get("ok"):
            raise ErrorTelegram(
                f"{metodo}: {cuerpo.get('description', 'error desconocido')}",
                codigo=cuerpo.get("error_code"),
                reintentar_en=cuerpo.get("parameters", {}).get("retry_after"),
            )
        return cuerpo["result"]
