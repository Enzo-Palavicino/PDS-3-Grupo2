"""Vínculos: la directora autoriza las cuentas de mensajería de los profesionales.

Genera un enlace de vinculación de un solo uso (con su código QR) y puede revocar un vínculo,
que se desactiva de inmediato.
"""

from typing import Annotated, Any, Literal
from urllib.parse import quote

import qrcode
import qrcode.image.svg
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.canales.telegram.cliente import ErrorTelegram
from app.modelos import (
    CodigoVinculacion,
    Profesional,
    Rol,
    TipoActor,
    UsuarioWeb,
    VinculoCanal,
)
from app.nucleo.vinculacion import generar_codigo, revocar_vinculo
from app.web.autenticacion import SesionBD, exigir_rol, verificar_csrf
from app.web.plantillas import pagina

router = APIRouter()

Directora = Annotated[UsuarioWeb, Depends(exigir_rol(Rol.DIRECTORA))]


@router.get("/vinculos")
def ver_vinculos(request: Request, sesion: SesionBD, usuario: Directora):
    return _pagina_de_vinculos(request, sesion, usuario)


@router.post("/vinculos/codigo", dependencies=[Depends(verificar_csrf)])
def generar_enlace(
    request: Request,
    sesion: SesionBD,
    usuario: Directora,
    profesional_id: Annotated[int, Form()],
    canal: Annotated[Literal["telegram", "whatsapp"], Form()] = "telegram",
):
    profesional = sesion.get(Profesional, profesional_id)
    if profesional is None or not profesional.activo:
        raise HTTPException(404, "Ese profesional no existe.")
    if canal == "whatsapp" and not request.app.state.config.whatsapp_enabled:
        raise HTTPException(400, "WhatsApp no está habilitado.")
    codigo = generar_codigo(sesion, profesional.id, creado_por=usuario.id)
    sesion.commit()
    enlace = _datos_del_enlace(request, profesional, codigo, canal)
    return _pagina_de_vinculos(request, sesion, usuario, enlace=enlace)


@router.post("/vinculos/{vinculo_id}/revocar", dependencies=[Depends(verificar_csrf)])
def revocar(vinculo_id: int, sesion: SesionBD, usuario: Directora):
    vinculo = sesion.get(VinculoCanal, vinculo_id)
    if vinculo is None or not vinculo.activo:
        raise HTTPException(404, "Ese vínculo no existe o ya fue revocado.")
    revocar_vinculo(sesion, vinculo, actor_tipo=TipoActor.USUARIO, actor_id=usuario.id)
    sesion.commit()
    return RedirectResponse("/vinculos", status_code=303)


def _pagina_de_vinculos(
    request: Request,
    sesion: Session,
    usuario: UsuarioWeb,
    enlace: dict[str, Any] | None = None,
):
    profesionales = sesion.scalars(
        select(Profesional).where(Profesional.activo).order_by(Profesional.nombre)
    ).all()
    vinculos: dict[int, list[VinculoCanal]] = {}
    for vinculo in sesion.scalars(select(VinculoCanal).where(VinculoCanal.activo)):
        vinculos.setdefault(vinculo.profesional_id, []).append(vinculo)
    return pagina(
        request,
        "vinculos.html",
        usuario=usuario,
        profesionales=profesionales,
        vinculos=vinculos,
        enlace=enlace,
        whatsapp_habilitado=request.app.state.config.whatsapp_enabled,
    )


def _datos_del_enlace(
    request: Request,
    profesional: Profesional,
    codigo: CodigoVinculacion,
    canal: str = "telegram",
) -> dict[str, Any]:
    if canal == "whatsapp":
        numero = request.app.state.config.whatsapp_phone_number
        url = f"https://wa.me/{numero}?text={quote('/start ' + codigo.codigo, safe='')}"
    else:
        usuario_bot = _usuario_del_bot(request)
        url = (
            f"https://t.me/{usuario_bot}?start={codigo.codigo}" if usuario_bot else None
        )
    return {
        "profesional": profesional,
        "canal": canal,
        "codigo": codigo.codigo,
        "url": url,
        "qr": _qr_en_svg(url) if url else None,
        "expira_en": codigo.expira_en,
    }


def _usuario_del_bot(request: Request) -> str | None:
    """Nombre de usuario del bot de Telegram, para armar el enlace. Se consulta una sola vez
    (getMe). Si no hay token o Telegram no responde, la página muestra el comando /start."""
    estado = request.app.state
    if estado.usuario_bot is None and estado.cliente_telegram is not None:
        try:
            estado.usuario_bot = estado.cliente_telegram.obtener_bot().get("username")
        except ErrorTelegram:
            return None
    return estado.usuario_bot


def _qr_en_svg(url: str) -> str:
    """El enlace como código QR, en SVG para incrustarlo directo en la página."""
    imagen = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage)
    return imagen.to_string(encoding="unicode")
