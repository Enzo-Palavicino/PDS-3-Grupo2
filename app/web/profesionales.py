"""Rutas reservadas para la administración de profesionales (E2-02)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.modelos import Rol, UsuarioWeb
from app.web.autenticacion import exigir_rol
from app.web.plantillas import pagina

router = APIRouter(prefix="/profesionales")
Directora = Annotated[UsuarioWeb, Depends(exigir_rol(Rol.DIRECTORA))]


@router.get("")
def listar(request: Request, usuario: Directora):
    return pagina(
        request,
        "pendiente.html",
        usuario=usuario,
        titulo="Profesionales",
        status_code=501,
    )
