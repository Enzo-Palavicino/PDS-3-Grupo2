"""Rutas reservadas para consultar las fichas clínicas (E1-02)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from app.modelos import Rol, UsuarioWeb
from app.nucleo.permisos import puede_ver_ficha
from app.web.autenticacion import SesionBD, exigir_rol
from app.web.plantillas import pagina

router = APIRouter()
PersonalClinico = Annotated[
    UsuarioWeb, Depends(exigir_rol(Rol.ENCARGADA_SALUD, Rol.PROFESIONAL))
]


@router.get("/fichas")
def listar(request: Request, usuario: PersonalClinico):
    return pagina(
        request, "pendiente.html", usuario=usuario, titulo="Fichas", status_code=501
    )


# El convertidor int evita que esta ruta capture /residentes/nuevo, que pertenece a E2-01.
@router.get("/residentes/{residente_id:int}")
def ver(residente_id: int, request: Request, sesion: SesionBD, usuario: PersonalClinico):
    if not puede_ver_ficha(sesion, usuario, residente_id):
        raise HTTPException(403, "No tienes acceso a esta ficha.")
    return pagina(
        request, "pendiente.html", usuario=usuario, titulo="Ficha", status_code=501
    )
