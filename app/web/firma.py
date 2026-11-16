"""Firma de atenciones (E3-03): el timbre del profesional y la pantalla de firma."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response

from app.modelos import Profesional, Rol, UsuarioWeb
from app.nucleo.timbres import (
    TAMANO_MAXIMO_BYTES,
    TimbreNoValido,
    guardar_timbre,
    timbre_de,
)
from app.web.autenticacion import SesionBD, exigir_rol, usuario_actual, verificar_csrf
from app.web.plantillas import pagina

router = APIRouter()

UsuarioProfesional = Annotated[UsuarioWeb, Depends(exigir_rol(Rol.PROFESIONAL))]
UsuarioActual = Annotated[UsuarioWeb, Depends(usuario_actual)]


@router.get("/cuenta/timbre")
def ver_mi_timbre(request: Request, sesion: SesionBD, usuario: UsuarioProfesional):
    profesional = sesion.get(Profesional, usuario.profesional_id)
    return pagina(request, "timbre.html", usuario=usuario, profesional=profesional)


@router.post("/cuenta/timbre", dependencies=[Depends(verificar_csrf)])
def subir_mi_timbre(
    request: Request,
    sesion: SesionBD,
    usuario: UsuarioProfesional,
    archivo: Annotated[UploadFile, File()],
):
    profesional = sesion.get(Profesional, usuario.profesional_id)
    # Se lee un byte más que el máximo: alcanza para saber si lo supera sin cargar todo.
    contenido = archivo.file.read(TAMANO_MAXIMO_BYTES + 1)
    try:
        guardar_timbre(sesion, profesional, contenido, usuario)
    except TimbreNoValido as error:
        return pagina(
            request,
            "timbre.html",
            status_code=400,
            usuario=usuario,
            profesional=profesional,
            error=str(error),
        )
    sesion.commit()
    return RedirectResponse("/cuenta/timbre?guardado=1", status_code=303)


@router.get("/profesionales/{profesional_id:int}/timbre")
def imagen_del_timbre(profesional_id: int, sesion: SesionBD, usuario: UsuarioActual):
    """La imagen del timbre, para mostrarla junto a la firma. Exige sesión iniciada."""
    profesional = sesion.get(Profesional, profesional_id)
    if profesional is None:
        raise HTTPException(404, "El profesional no existe.")
    contenido, mime = timbre_de(profesional)
    return Response(
        contenido,
        media_type=mime,
        headers={
            # Solo para quien inició sesión: no se guarda en cachés compartidas.
            "Cache-Control": "private, no-store",
            # El navegador no adivina otro tipo de contenido que el declarado.
            "X-Content-Type-Options": "nosniff",
        },
    )
