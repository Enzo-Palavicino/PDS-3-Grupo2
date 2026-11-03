"""Inicio de sesión, permisos por rol y protección CSRF de la plataforma web.

La sesión vive en una cookie firmada con SECRET_KEY: el navegador la guarda, pero no la puede
modificar. Solo lleva el id del usuario y el token CSRF.
"""

import hmac
from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modelos import Rol, TipoActor, UsuarioWeb
from app.nucleo.auditoria import Accion, registrar_evento
from app.seguridad import verificar_password
from app.web.plantillas import pagina

router = APIRouter()

# Página de inicio de cada rol. Cada rol tiene una sola sección: después de iniciar sesión, solo
# se vuelve a páginas dentro de ella.
PAGINA_INICIAL = {
    Rol.DIRECTORA: "/vinculos",
    Rol.ENCARGADA_SALUD: "/borradores",
    Rol.PROFESIONAL: "/borradores",
}


class SesionRequerida(Exception):
    """La página exige iniciar sesión. Se responde con una redirección a /login, que después
    vuelve a la página pedida."""

    def __init__(self, siguiente: str):
        self.siguiente = siguiente


def obtener_sesion_bd(request: Request) -> Iterator[Session]:
    with request.app.state.fabrica_de_sesiones() as sesion:
        yield sesion


SesionBD = Annotated[Session, Depends(obtener_sesion_bd)]


def verificar_csrf(request: Request, csrf: Annotated[str, Form()] = "") -> None:
    esperado = request.session.get("csrf", "")
    if not esperado or not hmac.compare_digest(csrf, esperado):
        raise HTTPException(403, "El formulario venció. Vuelve a cargar la página e inténtalo otra vez.")


def usuario_actual(request: Request, sesion: SesionBD) -> UsuarioWeb:
    usuario_id = request.session.get("usuario_id")
    usuario = sesion.get(UsuarioWeb, usuario_id) if usuario_id else None
    if usuario is None or not usuario.activo:
        raise SesionRequerida(request.url.path)
    return usuario


def exigir_rol(*roles: Rol):
    """Dependencia para una página que solo pueden ver ciertos roles."""

    def con_rol(usuario: Annotated[UsuarioWeb, Depends(usuario_actual)]) -> UsuarioWeb:
        if usuario.rol not in roles:
            raise HTTPException(403, "Tu rol no tiene acceso a esta página.")
        return usuario

    return con_rol


@router.get("/")
def inicio():
    return RedirectResponse("/login", status_code=303)


@router.get("/login")
def formulario_de_inicio(request: Request, sesion: SesionBD, siguiente: str = ""):
    usuario_id = request.session.get("usuario_id")
    usuario = sesion.get(UsuarioWeb, usuario_id) if usuario_id else None
    if usuario is not None and usuario.activo:
        return RedirectResponse(_destino(siguiente, usuario), status_code=303)
    return pagina(request, "login.html", siguiente=siguiente)


@router.post("/login", dependencies=[Depends(verificar_csrf)])
def iniciar_sesion(
    request: Request,
    sesion: SesionBD,
    usuario: Annotated[str, Form()],
    password: Annotated[str, Form()],
    siguiente: Annotated[str, Form()] = "",
):
    encontrado = sesion.scalar(
        select(UsuarioWeb).where(UsuarioWeb.usuario == usuario, UsuarioWeb.activo)
    )
    if encontrado is None or not verificar_password(password, encontrado.hash_password):
        registrar_evento(
            sesion,
            Accion.INICIO_SESION_FALLIDO,
            actor_tipo=TipoActor.SISTEMA,
            detalle={"usuario": usuario},
        )
        sesion.commit()
        return pagina(
            request,
            "login.html",
            status_code=401,
            siguiente=siguiente,
            error="Usuario o contraseña incorrectos.",
        )

    # Al iniciar sesión se parte con una sesión nueva: nadie puede reutilizar una cookie anterior.
    request.session.clear()
    request.session["usuario_id"] = encontrado.id
    registrar_evento(
        sesion, Accion.INICIO_SESION, actor_tipo=TipoActor.USUARIO, actor_id=encontrado.id
    )
    sesion.commit()
    return RedirectResponse(_destino(siguiente, encontrado), status_code=303)


@router.post("/logout", dependencies=[Depends(verificar_csrf)])
def cerrar_sesion(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


def _destino(siguiente: str, usuario: UsuarioWeb) -> str:
    """A dónde ir después de iniciar sesión: a la página pedida si es de la sección del rol (las
    demás le responderían 403, como un enlace de borrador abierto por la directora) y, si no, a
    su página de inicio."""
    inicio = PAGINA_INICIAL[usuario.rol]
    # Como inicio empieza con "/" y una letra, esto también impide redirigir a otro sitio.
    if siguiente == inicio or siguiente.startswith((f"{inicio}/", f"{inicio}?")):
        return siguiente
    return inicio
