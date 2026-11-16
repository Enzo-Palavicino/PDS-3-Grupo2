"""Rutas reservadas para los archivos de la ficha (E3-04)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.modelos import Rol, UsuarioWeb
from app.web.autenticacion import exigir_rol
from app.web.plantillas import pagina

router = APIRouter(prefix="/adjuntos")
PersonalClinico = Annotated[
    UsuarioWeb, Depends(exigir_rol(Rol.ENCARGADA_SALUD, Rol.PROFESIONAL))
]


@router.get("")
def listar(request: Request, usuario: PersonalClinico):
    return pagina(
        request, "pendiente.html", usuario=usuario, titulo="Adjuntos", status_code=501
    )
