"""Rutas reservadas para la administración de residentes (E2-01)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.modelos import Rol, UsuarioWeb
from app.web.autenticacion import exigir_rol
from app.web.plantillas import pagina

router = APIRouter(prefix="/residentes")
Administracion = Annotated[
    UsuarioWeb, Depends(exigir_rol(Rol.DIRECTORA, Rol.ENCARGADA_SALUD))
]


@router.get("")
def listar(request: Request, usuario: Administracion):
    return pagina(
        request, "pendiente.html", usuario=usuario, titulo="Residentes", status_code=501
    )
