"""Tratamientos (E1-04): suspender un tratamiento vigente desde la ficha."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse

from app.modelos import Tratamiento, UsuarioWeb
from app.nucleo.permisos import puede_suspender_tratamiento, puede_ver_ficha
from app.nucleo.tratamientos import (
    ErrorDeTratamiento,
    TratamientoNoVigente,
    suspender_tratamiento,
)
from app.web.autenticacion import SesionBD, usuario_actual, verificar_csrf

router = APIRouter()

UsuarioActual = Annotated[UsuarioWeb, Depends(usuario_actual)]


@router.post("/tratamientos/{tratamiento_id:int}/suspender", dependencies=[Depends(verificar_csrf)])
def suspender(
    tratamiento_id: int,
    sesion: SesionBD,
    usuario: UsuarioActual,
    motivo: Annotated[str, Form()] = "",
):
    tratamiento = sesion.get(Tratamiento, tratamiento_id)
    if tratamiento is None:
        raise HTTPException(404, "El tratamiento no existe.")
    if not puede_suspender_tratamiento(usuario) or not puede_ver_ficha(
        sesion, usuario, tratamiento.residente_id
    ):
        raise HTTPException(403, "Solo un profesional puede suspender tratamientos.")
    try:
        suspender_tratamiento(sesion, tratamiento, usuario, motivo)
    except TratamientoNoVigente as error:
        raise HTTPException(409, str(error)) from None
    except ErrorDeTratamiento as error:
        raise HTTPException(400, str(error)) from None
    sesion.commit()
    return RedirectResponse(f"/residentes/{tratamiento.residente_id}", status_code=303)
