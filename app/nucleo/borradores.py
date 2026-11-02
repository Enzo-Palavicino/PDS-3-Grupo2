"""Borradores de atención: arman lo que extrajo la IA y aplican las reglas de negocio.

Un borrador nunca es una atención registrada: siempre lo revisa un profesional en la plataforma.
El profesional puede completarlo respondiéndole al mensaje del bot; si no responde a un borrador
pendiente suyo, cada mensaje crea uno nuevo.
"""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modelos import (
    BorradorAtencion,
    BorradorMensaje,
    EstadoBorrador,
    Extraccion,
    MensajeEntrante,
    Profesional,
    Residente,
    Transcripcion,
)
from app.nucleo import textos
from app.nucleo.extraccion import RegistroExtraido, extraer_registro
from app.proveedores.llm.base import ProveedorLLM

logger = logging.getLogger(__name__)

# Campos que muestran que un mensaje trae datos de una atención. El motivo no está: ante una
# pregunta, el LLM a veces la anota como motivo ("consulta por alergias").
CAMPOS_CLINICOS = (
    "diagnosticos",
    "evolucion_clinica",
    "observaciones",
    "indicaciones_farmacologicas",
    "otras_indicaciones",
    "examenes_solicitados",
    "proximo_control",
)


def armar_borrador(
    sesion: Session, mensaje: MensajeEntrante, llm: ProveedorLLM
) -> BorradorAtencion | None:
    """Extrae los campos del mensaje y los guarda en un borrador: el que el mensaje completa, si
    le responde al bot, o uno nuevo. Devuelve None si el mensaje era una consulta."""
    existente = borrador_al_que_responde(sesion, mensaje)
    textos_previos = textos_del_borrador(sesion, existente) if existente else []
    texto_nuevo = texto_del_mensaje(sesion, mensaje)
    profesional = sesion.get(Profesional, mensaje.profesional_id)
    residentes = list(sesion.scalars(select(Residente).order_by(Residente.codigo)))
    resultado = extraer_registro(
        "\n".join([*textos_previos, texto_nuevo]),
        residentes,
        profesional.especialidad,
        mensaje.recibido_en,
        llm,
    )

    if existente is None and es_consulta(texto_nuevo, resultado.registro):
        logger.info("El mensaje %s es una consulta: no se crea borrador", mensaje.id)
        return None

    borrador = existente or BorradorAtencion(
        profesional_id=mensaje.profesional_id, canal=mensaje.canal
    )
    sesion.add(borrador)
    sesion.flush()  # asigna borrador.id
    sesion.add(BorradorMensaje(borrador_id=borrador.id, mensaje_id=mensaje.id))
    sesion.add(
        Extraccion(
            borrador_id=borrador.id,
            entrada_seudonimizada=resultado.entrada,
            salida=resultado.salida,
            proveedor=resultado.proveedor,
            modelo=resultado.modelo,
        )
    )

    campos = resultado.registro.model_dump(exclude={"ambiguedades", "es_consulta"})
    # La especialidad no la extrae la IA: se conoce por el vínculo del profesional.
    campos["especialidad"] = {"valor": profesional.especialidad, "fragmento": None}
    borrador.residente_id = resultado.residente_id
    borrador.campos = campos
    borrador.faltantes = calcular_faltantes(resultado.registro)
    borrador.ambiguedades = [ambiguedad.model_dump() for ambiguedad in resultado.registro.ambiguedades]
    logger.info("Mensaje %s guardado en el borrador %s", mensaje.id, borrador.id)
    return borrador


def borrador_al_que_responde(sesion: Session, mensaje: MensajeEntrante) -> BorradorAtencion | None:
    """El borrador pendiente del mismo profesional cuyo último mensaje del bot es el que este
    mensaje responde. Si responde a un borrador descartado o de otro profesional, no hay ninguno."""
    if not mensaje.responde_a:
        return None
    return sesion.scalar(
        select(BorradorAtencion).where(
            BorradorAtencion.mensaje_bot_id_externo == mensaje.responde_a,
            BorradorAtencion.canal == mensaje.canal,
            BorradorAtencion.profesional_id == mensaje.profesional_id,
            BorradorAtencion.estado == EstadoBorrador.PENDIENTE,
        )
    )


def borrador_del_mensaje(sesion: Session, mensaje: MensajeEntrante) -> BorradorAtencion:
    return sesion.scalar(
        select(BorradorAtencion)
        .join(BorradorMensaje, BorradorMensaje.borrador_id == BorradorAtencion.id)
        .where(BorradorMensaje.mensaje_id == mensaje.id)
    )


def textos_del_borrador(sesion: Session, borrador: BorradorAtencion) -> list[str]:
    """Textos (o transcripciones) de los mensajes que ya alimentan el borrador, en orden."""
    filas = sesion.execute(
        select(MensajeEntrante, Transcripcion.texto)
        .join(BorradorMensaje, BorradorMensaje.mensaje_id == MensajeEntrante.id)
        .outerjoin(Transcripcion, Transcripcion.mensaje_id == MensajeEntrante.id)
        .where(BorradorMensaje.borrador_id == borrador.id)
        .order_by(MensajeEntrante.recibido_en, MensajeEntrante.id)
    )
    return [transcripcion or mensaje.texto or "" for mensaje, transcripcion in filas]


def texto_del_mensaje(sesion: Session, mensaje: MensajeEntrante) -> str:
    if mensaje.tipo == "audio":
        return (
            sesion.scalar(select(Transcripcion.texto).where(Transcripcion.mensaje_id == mensaje.id))
            or ""
        )
    return mensaje.texto or ""


def es_consulta(texto: str, registro: RegistroExtraido) -> bool:
    """Una pregunta ("¿qué alergias tiene...?") no es un registro, así que no crea borrador.

    Es pregunta si el LLM la marcó como consulta o si el texto tiene "?". Además no debe traer
    datos de una atención: así, un registro real con una pregunta en medio sí crea su borrador.
    """
    pregunta = registro.es_consulta or "?" in texto
    return pregunta and not any(getattr(registro, campo) for campo in CAMPOS_CLINICOS)


def calcular_faltantes(registro: RegistroExtraido) -> list[dict[str, Any]]:
    """Lo que le falta al registro (sección 10 de la especificación).

    Los obligatorios son el mínimo de un borrador completo. Los esperados se informan, pero no
    bloquean el borrador.
    """
    faltantes = []

    def falta(campo: str, descripcion: str, obligatorio: bool) -> None:
        faltantes.append({"campo": campo, "descripcion": descripcion, "obligatorio": obligatorio})

    if registro.residente is None:
        falta("residente", "residente", obligatorio=True)
    if registro.fecha_atencion is None:
        falta("fecha_atencion", "fecha de atención", obligatorio=True)
    if registro.motivo is None and not registro.diagnosticos:
        falta("diagnostico_o_motivo", "diagnóstico o motivo", obligatorio=True)
    if registro.proximo_control is None:
        falta("proximo_control", "próximo control", obligatorio=False)
    acompanante = registro.acompanante
    sin_nombre = acompanante is None or acompanante.nombre is None
    sin_cargo = acompanante is None or acompanante.cargo is None
    if sin_nombre and sin_cargo:
        falta("acompanante", "acompañante (nombre y cargo)", obligatorio=False)
    elif sin_nombre:
        falta("acompanante", "nombre del acompañante", obligatorio=False)
    elif sin_cargo:
        falta("acompanante", "cargo del acompañante", obligatorio=False)
    return faltantes


def texto_de_respuesta(
    borrador: BorradorAtencion, residente: Residente | None, ya_se_pidio: bool, url_publica: str
) -> str:
    """Respuesta del bot sobre el borrador (sección 11). No lleva datos clínicos: el residente
    va solo con sus iniciales, y el detalle se ve en la plataforma.

    ya_se_pidio: el bot ya pidió una vez lo que faltaba, así que ahora solo lo informa.
    """
    url = f"{url_publica.rstrip('/')}/borradores/{borrador.id}"
    if residente is None:
        plantilla = (
            textos.BORRADOR_ACTUALIZADO_SIN_RESIDENTE
            if ya_se_pidio
            else textos.RESIDENTE_NO_IDENTIFICADO
        )
        return plantilla.format(id=borrador.id, url=url)

    faltantes = ", ".join(falta["descripcion"] for falta in borrador.faltantes)
    if ya_se_pidio:
        plantilla = (
            textos.BORRADOR_ACTUALIZADO_CON_FALTANTES if faltantes else textos.BORRADOR_ACTUALIZADO
        )
    else:
        plantilla = textos.BORRADOR_CON_FALTANTES if faltantes else textos.BORRADOR_COMPLETO
    return plantilla.format(
        id=borrador.id, iniciales=iniciales(residente), faltantes=faltantes, url=url
    )


def iniciales(residente: Residente) -> str:
    """Iniciales del residente: "Emilia Soto" da "E. S."."""
    return f"{residente.nombres[0]}. {residente.apellidos[0]}."
