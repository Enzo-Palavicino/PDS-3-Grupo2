"""Firma de atenciones (E3-03): el timbre del profesional y la pantalla de firma."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from app.modelos import (
    Atencion,
    EstadoAtencion,
    Profesional,
    Residente,
    Rol,
    UsuarioWeb,
)
from app.nucleo.atenciones import AtencionFirmada, ErrorDeAtencion, firmar_atencion
from app.nucleo.permisos import puede_firmar
from app.nucleo.timbres import (
    TAMANO_MAXIMO_BYTES,
    TimbreNoValido,
    guardar_timbre,
    timbre_de,
)
from app.web.autenticacion import SesionBD, exigir_rol, usuario_actual, verificar_csrf
from app.web.borradores import filas_de_campos
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


@router.get("/atenciones/{atencion_id:int}/firmar")
def pantalla_de_firma(
    request: Request, atencion_id: int, sesion: SesionBD, usuario: UsuarioProfesional
):
    atencion = _atencion_por_firmar(sesion, atencion_id, usuario)
    return _pagina_de_firma(request, sesion, atencion, usuario)


@router.post("/atenciones/{atencion_id:int}/firmar", dependencies=[Depends(verificar_csrf)])
def firmar(
    request: Request,
    atencion_id: int,
    sesion: SesionBD,
    usuario: UsuarioProfesional,
    password: Annotated[str, Form()] = "",
):
    atencion = _atencion_por_firmar(sesion, atencion_id, usuario)
    try:
        firmar_atencion(sesion, atencion, usuario, password)
    except AtencionFirmada:
        raise
    except ErrorDeAtencion as error:
        # Contraseña incorrecta o datos incompletos: no se firmó nada.
        return _pagina_de_firma(request, sesion, atencion, usuario, str(error), status_code=400)
    sesion.commit()
    return RedirectResponse(f"/residentes/{atencion.residente_id}", status_code=303)


def _atencion_por_firmar(sesion: Session, atencion_id: int, usuario: UsuarioWeb) -> Atencion:
    atencion = sesion.get(Atencion, atencion_id)
    if atencion is None:
        raise HTTPException(404, "La atención no existe.")
    if atencion.estado == EstadoAtencion.FIRMADA:
        raise AtencionFirmada("La atención ya está firmada.")
    if not puede_firmar(usuario, atencion):
        raise HTTPException(403, "Solo el profesional que hizo la atención puede firmarla.")
    return atencion


def _pagina_de_firma(
    request: Request,
    sesion: Session,
    atencion: Atencion,
    usuario: UsuarioWeb,
    error: str | None = None,
    status_code: int = 200,
):
    residente = sesion.get(Residente, atencion.residente_id)
    return pagina(
        request,
        "firmar.html",
        status_code=status_code,
        usuario=usuario,
        atencion=atencion,
        residente=residente,
        campos=filas_de_campos(atencion.campos),
        nombres={residente.codigo: f"{residente.nombres} {residente.apellidos}"},
        error=error,
    )
