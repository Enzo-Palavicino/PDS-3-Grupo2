"""Rutas reservadas para la digitalización de documentos históricos (E4)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.modelos import Rol, UsuarioWeb
from app.web.autenticacion import exigir_rol
from app.web.plantillas import pagina

router = APIRouter(prefix="/digitalizacion")
EncargadaSalud = Annotated[UsuarioWeb, Depends(exigir_rol(Rol.ENCARGADA_SALUD))]


@router.get("")
def listar(request: Request, usuario: EncargadaSalud):
    return pagina(
        request,
        "pendiente.html",
        usuario=usuario,
        titulo="Digitalización",
        status_code=501,
    )
