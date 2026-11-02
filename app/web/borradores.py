"""Borradores: la encargada de salud ve todos; cada profesional, solo los suyos.

Cada vez que alguien abre un borrador queda un evento de auditoría de lectura. Los pendientes
que no cambian hace más de DIAS_SIN_ACTIVIDAD_BORRADOR días aparecen marcados "sin actividad".
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
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
    Rol,
    TipoActor,
    Transcripcion,
    UsuarioWeb,
)
from app.nucleo.auditoria import Accion, registrar_evento
from app.nucleo.borradores import sin_actividad
from app.web.autenticacion import SesionBD, exigir_rol, verificar_csrf
from app.web.plantillas import pagina

router = APIRouter()

LectorDeBorradores = Annotated[
    UsuarioWeb, Depends(exigir_rol(Rol.ENCARGADA_SALUD, Rol.PROFESIONAL))
]

# Campos del Registro de Atención, en el orden en que se muestran.
ETIQUETAS = {
    "residente": "Residente",
    "fecha_atencion": "Fecha de atención",
    "hora_atencion": "Hora",
    "lugar": "Lugar",
    "especialidad": "Especialidad",
    "motivo": "Motivo",
    "diagnosticos": "Diagnósticos",
    "evolucion_clinica": "Evolución clínica",
    "observaciones": "Observaciones",
    "indicaciones_farmacologicas": "Indicaciones farmacológicas",
    "otras_indicaciones": "Otras indicaciones",
    "examenes_solicitados": "Exámenes solicitados",
    "proximo_control": "Próximo control",
    "acompanante": "Acompañante",
}


@router.get("/borradores")
def lista_de_borradores(request: Request, sesion: SesionBD, usuario: LectorDeBorradores):
    consulta = (
        select(BorradorAtencion, Profesional, Residente)
        .join(Profesional, Profesional.id == BorradorAtencion.profesional_id)
        .outerjoin(Residente, Residente.id == BorradorAtencion.residente_id)
        .order_by(BorradorAtencion.id.desc())
    )
    if usuario.rol == Rol.PROFESIONAL:
        consulta = consulta.where(BorradorAtencion.profesional_id == usuario.profesional_id)
    filas = sesion.execute(consulta).all()
    dias = _dias_sin_actividad(request)
    return pagina(
        request,
        "borradores.html",
        usuario=usuario,
        filas=filas,
        ids_sin_actividad={borrador.id for borrador, _, _ in filas if sin_actividad(borrador, dias)},
        dias_sin_actividad=dias,
    )


@router.get("/borradores/{borrador_id}")
def detalle_de_borrador(
    borrador_id: int, request: Request, sesion: SesionBD, usuario: LectorDeBorradores
):
    borrador = _borrador_visible(sesion, borrador_id, usuario)
    mensajes = sesion.execute(
        select(MensajeEntrante, Transcripcion)
        .join(BorradorMensaje, BorradorMensaje.mensaje_id == MensajeEntrante.id)
        .outerjoin(Transcripcion, Transcripcion.mensaje_id == MensajeEntrante.id)
        .where(BorradorMensaje.borrador_id == borrador.id)
        .order_by(MensajeEntrante.recibido_en, MensajeEntrante.id)
    ).all()
    extracciones = sesion.scalars(
        select(Extraccion).where(Extraccion.borrador_id == borrador.id).order_by(Extraccion.id)
    ).all()
    nombres = {r.codigo: f"{r.nombres} {r.apellidos}" for r in sesion.scalars(select(Residente))}

    # Cada lectura queda registrada: quién abrió qué borrador y cuándo (D41, art. 9).
    registrar_evento(
        sesion,
        Accion.BORRADOR_LEIDO,
        actor_tipo=TipoActor.USUARIO,
        actor_id=usuario.id,
        entidad="borrador",
        entidad_id=borrador.id,
    )
    sesion.commit()
    dias = _dias_sin_actividad(request)
    return pagina(
        request,
        "borrador.html",
        usuario=usuario,
        borrador=borrador,
        marcado_sin_actividad=sin_actividad(borrador, dias),
        dias_sin_actividad=dias,
        profesional=sesion.get(Profesional, borrador.profesional_id),
        residente=sesion.get(Residente, borrador.residente_id) if borrador.residente_id else None,
        campos=filas_de_campos(borrador.campos),
        mensajes=mensajes,
        extracciones=extracciones,
        nombres=nombres,
        puede_descartar=_puede_descartar(usuario, borrador),
    )


@router.post("/borradores/{borrador_id}/descartar", dependencies=[Depends(verificar_csrf)])
def descartar_borrador(borrador_id: int, sesion: SesionBD, usuario: LectorDeBorradores):
    borrador = _borrador_visible(sesion, borrador_id, usuario)
    if not _puede_descartar(usuario, borrador):
        raise HTTPException(403, "No puedes descartar este borrador.")
    borrador.estado = EstadoBorrador.DESCARTADO
    registrar_evento(
        sesion,
        Accion.BORRADOR_DESCARTADO,
        actor_tipo=TipoActor.USUARIO,
        actor_id=usuario.id,
        entidad="borrador",
        entidad_id=borrador.id,
    )
    sesion.commit()
    return RedirectResponse(f"/borradores/{borrador.id}", status_code=303)


def _dias_sin_actividad(request: Request) -> int:
    return request.app.state.config.dias_sin_actividad_borrador


def _borrador_visible(sesion: Session, borrador_id: int, usuario: UsuarioWeb) -> BorradorAtencion:
    borrador = sesion.get(BorradorAtencion, borrador_id)
    if borrador is None:
        raise HTTPException(404, "Ese borrador no existe.")
    if usuario.rol == Rol.PROFESIONAL and borrador.profesional_id != usuario.profesional_id:
        raise HTTPException(403, "Este borrador es de otro profesional.")
    return borrador


def _puede_descartar(usuario: UsuarioWeb, borrador: BorradorAtencion) -> bool:
    """Lo puede descartar su profesional o la encargada de salud, mientras esté pendiente."""
    es_suyo = borrador.profesional_id == usuario.profesional_id
    return borrador.estado == EstadoBorrador.PENDIENTE and (
        usuario.rol == Rol.ENCARGADA_SALUD or es_suyo
    )


def filas_de_campos(campos: dict[str, Any]) -> list[dict[str, Any]]:
    """Una fila por dato (etiqueta, valor y fragmento de origen). Los campos vacíos también
    aparecen, para ver de un vistazo lo que falta."""
    filas = []
    for clave, etiqueta in ETIQUETAS.items():
        dato = campos.get(clave)
        datos = [d for d in (dato if isinstance(dato, list) else [dato]) if d]
        if not datos:
            filas.append({"etiqueta": etiqueta, "valor": None, "fragmento": None})
        for d in datos:
            filas.append(
                {"etiqueta": etiqueta, "valor": _valor_legible(clave, d), "fragmento": d.get("fragmento")}
            )
    return filas


def _valor_legible(clave: str, dato: dict[str, Any]) -> str | None:
    if clave == "residente":
        return f"[{dato.get('valor')}]"  # la plantilla cambia la marca por el nombre
    if clave == "indicaciones_farmacologicas":
        partes = [dato.get("medicamento") or "medicamento sin nombre"]
        detalles = (
            ("dosis", "dosis"),
            ("frecuencia_horario", "frecuencia"),
            ("via", "vía"),
            ("duracion", "duración"),
            ("fecha_inicio", "desde"),
            ("fecha_termino", "hasta"),
        )
        partes += [f"{etiqueta}: {dato[nombre]}" for nombre, etiqueta in detalles if dato.get(nombre)]
        return "; ".join(partes)
    if clave == "proximo_control":
        return " · ".join(parte for parte in (dato.get("fecha"), dato.get("descripcion")) if parte)
    if clave == "acompanante":
        nombre, cargo = dato.get("nombre"), dato.get("cargo")
        return f"{nombre} ({cargo})" if nombre and cargo else nombre or cargo
    return dato.get("valor")
