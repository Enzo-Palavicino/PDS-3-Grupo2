"""Plantillas HTML (Jinja2) y funciones para mostrar los datos en ellas.

Jinja2 escapa todo el texto que se muestra, así que el contenido de un mensaje nunca se
interpreta como HTML.
"""

import re
import secrets
from datetime import datetime
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.nucleo.extraccion import ZONA_HORARIA

plantillas = Jinja2Templates(directory=Path(__file__).parent / "plantillas")

MARCA_DE_RESIDENTE = re.compile(r"\[(RES-\d+(?:\|RES-\d+)*)\]")


def token_csrf(request: Request) -> str:
    """Token que va escondido en cada formulario. Otro sitio no lo conoce, así que no puede
    enviar formularios en nombre del usuario (protección CSRF)."""
    if "csrf" not in request.session:
        request.session["csrf"] = secrets.token_urlsafe(32)
    return request.session["csrf"]


def pagina(request: Request, plantilla: str, status_code: int = 200, **datos):
    """Renderiza una página. Todas reciben el token CSRF para sus formularios."""
    contexto = {"csrf": token_csrf(request), **datos}
    return plantillas.TemplateResponse(request, plantilla, contexto, status_code=status_code)


def hora_chile(momento: datetime | None) -> str:
    return momento.astimezone(ZONA_HORARIA).strftime("%d-%m-%Y %H:%M") if momento else "—"


def con_nombres(texto: str | None, nombres: dict[str, str]) -> str:
    """Los fragmentos guardados vienen seudonimizados ("[RES-02]"). En la web, que exige
    iniciar sesión, se muestran con el nombre: "Emilia Soto (RES-02)"."""
    if not texto:
        return "—"

    def con_nombre(marca: re.Match) -> str:
        codigos = marca.group(1).split("|")
        posibles = " o ".join(nombres.get(codigo, codigo) for codigo in codigos)
        return f"{posibles} ({'|'.join(codigos)})"

    return MARCA_DE_RESIDENTE.sub(con_nombre, texto)


plantillas.env.filters["hora_chile"] = hora_chile
plantillas.env.filters["con_nombres"] = con_nombres
