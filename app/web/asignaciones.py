"""Gestión de asignaciones sin acceso al historial clínico."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.modelos import Asignacion, Profesional, Residente, Rol, TipoActor, UsuarioWeb
from app.nucleo.auditoria import Accion, registrar_evento
from app.web.autenticacion import SesionBD, exigir_rol, verificar_csrf
from app.web.plantillas import pagina

router = APIRouter(prefix="/residentes")
Administracion = Annotated[
    UsuarioWeb, Depends(exigir_rol(Rol.DIRECTORA, Rol.ENCARGADA_SALUD))
]


def _residente(sesion, residente_id):
    residente = sesion.scalar(
        select(Residente).where(Residente.id == residente_id).with_for_update()
    )
    if residente is None:
        raise HTTPException(404, "Residente no encontrado.")
    return residente


@router.get("/{residente_id}/asignaciones")
def listar(
    residente_id: int, request: Request, sesion: SesionBD, usuario: Administracion
):
    residente = _residente(sesion, residente_id)
    asignados = sesion.execute(
        select(Asignacion, Profesional)
        .join(Profesional)
        .where(Asignacion.residente_id == residente_id)
        .order_by(Profesional.nombre)
    ).all()
    disponibles = list(
        sesion.scalars(
            select(Profesional)
            .where(
                Profesional.activo, Profesional.id.not_in([p.id for _, p in asignados])
            )
            .order_by(Profesional.nombre)
        )
    )
    return pagina(
        request,
        "asignaciones.html",
        usuario=usuario,
        residente=residente,
        asignados=asignados,
        disponibles=disponibles,
        exito=request.session.pop("asignacion_exito", None),
    )


@router.post("/{residente_id}/asignaciones", dependencies=[Depends(verificar_csrf)])
def cambiar(
    residente_id: int,
    request: Request,
    sesion: SesionBD,
    usuario: Administracion,
    profesional_id: Annotated[int, Form()],
    accion: Annotated[str, Form()],
):
    _residente(sesion, residente_id)  # serializa altas/bajas del mismo residente
    profesional = sesion.get(Profesional, profesional_id)
    if profesional is None:
        raise HTTPException(404, "Profesional no encontrado.")
    asignacion = sesion.scalar(
        select(Asignacion).where(
            Asignacion.residente_id == residente_id,
            Asignacion.profesional_id == profesional_id,
        )
    )
    if accion == "asignar":
        if not profesional.activo:
            raise HTTPException(400, "No se puede asignar un profesional desactivado.")
        if asignacion is None:
            sesion.add(
                Asignacion(
                    residente_id=residente_id,
                    profesional_id=profesional_id,
                    asignado_por=usuario.id,
                )
            )
    elif accion == "quitar":
        if asignacion is not None:
            sesion.delete(asignacion)
    else:
        raise HTTPException(400, "Acción no válida.")
    if (accion == "asignar" and asignacion is None) or (
        accion == "quitar" and asignacion is not None
    ):
        registrar_evento(
            sesion,
            Accion.ASIGNACION_CREADA
            if accion == "asignar"
            else Accion.ASIGNACION_RETIRADA,
            TipoActor.USUARIO,
            actor_id=usuario.id,
            entidad="residente",
            entidad_id=residente_id,
            detalle={"profesional_id": profesional_id},
        )
    sesion.commit()
    request.session["asignacion_exito"] = (
        "Profesional asignado."
        if accion == "asignar"
        else "Asignación retirada. Se conserva el historial."
    )
    return RedirectResponse(f"/residentes/{residente_id}/asignaciones", status_code=303)
