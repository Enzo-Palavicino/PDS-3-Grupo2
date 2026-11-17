"""Límite de tamaño de las peticiones (E5-01).

Cada servicio controla el tamaño de sus archivos (10 MB un adjunto o un documento, 1 MB un
timbre). Este límite es una barrera general: una petición enorme se rechaza con 413 antes de
leerla entera, para que no llene la memoria ni el disco del servidor gratuito. Es mayor que el de
un archivo porque la digitalización sube varias fotos en una sola petición.
"""

from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAXIMO_POR_PETICION_BYTES = 50 * 1024 * 1024  # hasta cinco fotos de 10 MB
MENSAJE = "El envío supera el máximo de 50 MB. Sube los archivos en partes."


class LimiteDeSubida:
    """Middleware ASGI: rechaza con 413 una petición cuyo cuerpo supera el máximo.

    Si la petición declara su largo (Content-Length), se rechaza sin leer nada. Si no lo declara
    (envío por partes), se cuentan los bytes a medida que llegan y se corta al superar el máximo.
    """

    def __init__(self, app: ASGIApp, maximo_bytes: int = MAXIMO_POR_PETICION_BYTES):
        self.app = app
        self.maximo_bytes = maximo_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declarado = dict(scope["headers"]).get(b"content-length", b"")
        if declarado.isdigit() and int(declarado) > self.maximo_bytes:
            await _responder_413(send)
            return

        recibidos = 0

        async def recibir() -> Message:
            nonlocal recibidos
            mensaje = await receive()
            if mensaje["type"] == "http.request":
                recibidos += len(mensaje.get("body", b""))
                if recibidos > self.maximo_bytes:
                    # La aplicación lo muestra como su página de error 413.
                    raise HTTPException(413, MENSAJE)
            return mensaje

        await self.app(scope, recibir, send)


async def _responder_413(send: Send) -> None:
    cuerpo = MENSAJE.encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"text/plain; charset=utf-8"),
                (b"content-length", str(len(cuerpo)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": cuerpo})
