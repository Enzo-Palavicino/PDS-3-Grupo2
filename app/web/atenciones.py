"""Rutas reservadas para el registro y la firma de atenciones (E3)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.modelos import Rol, UsuarioWeb
from app.web.autenticacion import exigir_rol
from app.web.plantillas import pagina

router = APIRouter(prefix="/atenciones")
PersonalClinico = Annotated[
    UsuarioWeb, Depends(exigir_rol(Rol.ENCARGADA_SALUD, Rol.PROFESIONAL))
]


@router.get("")
def listar(request: Request, usuario: PersonalClinico):
    return pagina(
        request, "pendiente.html", usuario=usuario, titulo="Atenciones", status_code=501
    )
