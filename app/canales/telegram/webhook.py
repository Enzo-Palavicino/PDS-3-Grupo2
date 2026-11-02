"""Recepción de mensajes por webhook, en el servidor: Telegram envía cada update con un POST.

Solo se aceptan las peticiones que traen, en el encabezado X-Telegram-Bot-Api-Secret-Token, el
secreto configurado con setWebhook. Cualquier otra se rechaza con 401 sin leer su contenido.

La ruta responde apenas guarda el mensaje: las respuestas al chat se envían después de
contestarle a Telegram, y la transcripción y la IA las hace el worker en segundo plano. Si
Telegram reintenta un update, la ingesta lo reconoce y no lo guarda dos veces.
"""

import json
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from app.canales.base import AdaptadorCanal
from app.logs import trazas_habilitadas
from app.nucleo.ingesta import Respuesta, enviar_respuestas, ingerir
from app.nucleo.worker import Worker

logger = logging.getLogger(__name__)

RUTA = "/webhooks/telegram"

router = APIRouter()


@router.post(RUTA)
async def recibir_update(request: Request, tareas: BackgroundTasks) -> dict[str, bool]:
    adaptador = request.app.state.webhook_telegram
    if adaptador is None:
        raise HTTPException(404, "La aplicación no está recibiendo mensajes por webhook.")
    cuerpo = await request.body()
    if not adaptador.verificar_peticion(request.headers, cuerpo):
        logger.warning("Petición al webhook de Telegram rechazada: secreto ausente o incorrecto")
        raise HTTPException(401, "No autorizado.")
    try:
        update = json.loads(cuerpo)
    except ValueError:
        raise HTTPException(400, "El cuerpo de la petición no es JSON.") from None

    # Guardar el mensaje es rápido (una inserción) y se hace antes de responder, para no perderlo.
    respuestas = await run_in_threadpool(
        ingerir, request.app.state.fabrica_de_sesiones, adaptador, update
    )
    tareas.add_task(_despues_de_responder, adaptador, respuestas, request.app.state.worker)
    return {"ok": True}


def _despues_de_responder(
    adaptador: AdaptadorCanal, respuestas: list[Respuesta], worker: Worker
) -> None:
    try:
        enviar_respuestas(adaptador, respuestas)
    except Exception as error:
        logger.warning(
            "No se pudieron enviar las respuestas al chat (%s)",
            type(error).__name__,
            exc_info=trazas_habilitadas(),
        )
    worker.despertar()  # si se guardó un mensaje, se procesa en segundo plano
