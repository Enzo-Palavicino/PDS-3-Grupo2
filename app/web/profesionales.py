"""Pantalla de administración, reservada a la directora."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.modelos import Profesional, Rol, UsuarioWeb, VinculoCanal
from app.nucleo.profesionales import crear_profesional, desactivar_profesional
from app.web.autenticacion import SesionBD, exigir_rol, verificar_csrf
from app.web.plantillas import pagina

router = APIRouter(prefix="/profesionales")
Directora = Annotated[UsuarioWeb, Depends(exigir_rol(Rol.DIRECTORA))]


def _pagina(
    request,
    sesion,
    usuario,
    *,
    error=None,
    valores=None,
    status_code=200,
    buscar="",
    especialidad="",
    estado="",
    exito=None,
):
    profesionales = list(
        sesion.scalars(select(Profesional).order_by(Profesional.nombre))
    )
    especialidades = sorted({p.especialidad for p in profesionales}, key=str.casefold)
    total = len(profesionales)
    profesionales = [
        p
        for p in profesionales
        if (not buscar or buscar.casefold() in p.nombre.casefold())
        and (not especialidad or p.especialidad == especialidad)
        and (not estado or p.activo == (estado == "activo"))
    ]
    vinculos = {}
    for vinculo in sesion.scalars(select(VinculoCanal).where(VinculoCanal.activo)):
        vinculos.setdefault(vinculo.profesional_id, set()).add(vinculo.canal)
    return pagina(
        request,
        "profesionales.html",
        usuario=usuario,
        profesionales=profesionales,
        vinculos=vinculos,
        error=error,
        exito=exito,
        buscar=buscar,
        especialidad=especialidad,
        estado=estado,
        opciones_especialidad=[("", "Todas las especialidades")]
        + [(e, e) for e in especialidades],
        total=total,
        valores=valores or {},
        status_code=status_code,
    )


@router.get("")
def listar(
    request: Request,
    sesion: SesionBD,
    usuario: Directora,
    buscar: str = "",
    especialidad: str = "",
    estado: Literal["", "activo", "desactivado"] = "",
):
    exito = request.session.pop("profesional_creado", False)
    return _pagina(
        request,
        sesion,
        usuario,
        buscar=buscar.strip(),
        especialidad=especialidad,
        estado=estado,
        exito=exito,
    )


@router.post("", dependencies=[Depends(verificar_csrf)])
def crear(
    request: Request,
    sesion: SesionBD,
    usuario: Directora,
    nombre: Annotated[str, Form()] = "",
    especialidad: Annotated[str, Form()] = "",
    registro: Annotated[str, Form()] = "",
    cuenta: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
):
    valores = {
        "nombre": nombre,
        "especialidad": especialidad,
        "registro": registro,
        "cuenta": cuenta,
    }
    try:
        crear_profesional(sesion, **valores, password=password, actor_id=usuario.id)
        sesion.commit()
    except (ValueError, IntegrityError) as exc:
        sesion.rollback()
        error = (
            str(exc)
            if isinstance(exc, ValueError)
            else "Ese usuario ya existe. Elige otro."
        )
        return _pagina(
            request, sesion, usuario, error=error, valores=valores, status_code=400
        )
    request.session["profesional_creado"] = True
    return RedirectResponse("/profesionales", status_code=303)


@router.post("/{profesional_id}/desactivar", dependencies=[Depends(verificar_csrf)])
def desactivar(profesional_id: int, sesion: SesionBD, usuario: Directora):
    profesional = sesion.get(Profesional, profesional_id)
    if profesional is None:
        raise HTTPException(404, "Profesional no encontrado.")
    desactivar_profesional(sesion, profesional, usuario.id)
    sesion.commit()
    return RedirectResponse("/profesionales", status_code=303)
