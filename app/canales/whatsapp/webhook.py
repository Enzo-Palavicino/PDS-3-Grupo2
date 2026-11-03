"""Recepción autenticada de Kapso v2; guarda antes de confirmar la entrega."""

import json

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from app.nucleo.ingesta import enviar_respuestas, procesar_mensaje

RUTA = "/webhooks/whatsapp"
MAXIMO_CUERPO = 1024 * 1024
router = APIRouter()


@router.post(RUTA)
async def recibir_evento(request: Request, tareas: BackgroundTasks) -> dict[str, bool]:
    adaptador = request.app.state.webhook_whatsapp
    if adaptador is None:
        raise HTTPException(404, "WhatsApp no está habilitado.")
    cuerpo = bytearray()
    async for bloque in request.stream():
        cuerpo.extend(bloque)
        if len(cuerpo) > MAXIMO_CUERPO:
            raise HTTPException(413, "El evento es demasiado grande.")
    if not adaptador.verificar_peticion(request.headers, bytes(cuerpo)):
        raise HTTPException(401, "Firma de Kapso ausente o incorrecta.")
    try:
        evento = json.loads(cuerpo)
    except ValueError:
        raise HTTPException(400, "El cuerpo no es JSON.") from None
    if not isinstance(evento, dict):
        raise HTTPException(400, "El evento debe ser un objeto.")
    if request.headers.get("X-Webhook-Event") != "whatsapp.message.received":
        return {"ok": True}
    eventos = evento.get("data") if evento.get("batch") is True else [evento]
    if not isinstance(eventos, list) or not all(isinstance(e, dict) for e in eventos):
        raise HTTPException(400, "El lote de eventos no es válido.")
    respuestas = await run_in_threadpool(
        _guardar, request.app.state.fabrica_de_sesiones, adaptador, eventos
    )
    # Despierta incluso si el proceso se interrumpe durante las respuestas inmediatas.
    request.app.state.worker.despertar()
    tareas.add_task(enviar_respuestas, adaptador, respuestas)
    return {"ok": True}


def _guardar(fabrica, adaptador, eventos):
    respuestas = []
    # Una transacción para todo el lote; una entrega parcial no se confirma.
    with fabrica.begin() as sesion:
        for evento in eventos:
            respuestas.extend(procesar_mensaje(sesion, adaptador.parsear(evento)))
    return respuestas
