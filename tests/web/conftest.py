"""Utilidades para los tests de la plataforma web."""

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Config
from app.main import crear_app
from app.modelos import BorradorAtencion, EventoAuditoria, UsuarioWeb
from scripts.sembrar_datos import sembrar

PASSWORD = "clave-de-prueba"


@pytest.fixture
def datos_demo(sesion):
    """Residentes, profesionales y usuarios de la demo; todos con la contraseña PASSWORD."""
    sembrar(sesion, PASSWORD)
    sesion.commit()


@pytest.fixture
def cliente(url_bd, datos_demo):
    config = Config(_env_file=None, database_url=url_bd, secret_key="clave-de-sesion-de-prueba")
    # Con "with", el TestClient ejecuta el inicio de la aplicación (la conexión a la base de datos).
    with TestClient(crear_app(config)) as cliente:
        yield cliente


def csrf_de(html: str) -> str:
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


@pytest.fixture
def entrar(cliente):
    """Inicia sesión con un usuario de la demo; devuelve la respuesta del POST a /login."""

    def entrar_como(usuario: str, password: str = PASSWORD, siguiente: str = ""):
        csrf = csrf_de(cliente.get("/login").text)
        datos = {"usuario": usuario, "password": password, "csrf": csrf, "siguiente": siguiente}
        return cliente.post("/login", data=datos, follow_redirects=False)

    return entrar_como


@pytest.fixture
def csrf(cliente):
    """Token CSRF de la sesión actual, sacado de una página que tenga formularios."""

    def de_la_pagina(ruta: str = "/borradores") -> str:
        return csrf_de(cliente.get(ruta).text)

    return de_la_pagina


@pytest.fixture
def id_profesional(sesion, datos_demo):
    """Id del profesional de un usuario web de la demo (por ejemplo, "pediatra")."""

    def buscar(usuario: str) -> int:
        profesional_id = sesion.scalar(
            select(UsuarioWeb.profesional_id).where(UsuarioWeb.usuario == usuario)
        )
        # Cierra la transacción de lectura: en SQLite tomaría el permiso de escritura y la
        # aplicación no podría escribir mientras tanto.
        sesion.commit()
        return profesional_id

    return buscar


@pytest.fixture
def crear_borrador(sesion, id_profesional):
    """Crea un borrador de Emilia Soto (RES-02) del profesional del usuario indicado."""

    def crear(usuario: str = "pediatra") -> BorradorAtencion:
        borrador = BorradorAtencion(
            profesional_id=id_profesional(usuario),
            residente_id=2,
            canal="telegram",
            campos={
                "residente": {"valor": "RES-02", "fragmento": "atendí a [RES-02]"},
                "diagnosticos": [
                    {"valor": "bronquiolitis leve", "fragmento": "cuadro de bronquiolitis leve"}
                ],
            },
            faltantes=[
                {"campo": "acompanante", "descripcion": "acompañante (nombre y cargo)", "obligatorio": False}
            ],
        )
        sesion.add(borrador)
        sesion.commit()
        return borrador

    return crear


@pytest.fixture
def acciones(sesion):
    """Acciones registradas en la auditoría, en orden."""

    def leer() -> list[str]:
        sesion.commit()  # cierra la transacción anterior, para ver lo que escribió la aplicación
        resultado = list(sesion.scalars(select(EventoAuditoria.accion).order_by(EventoAuditoria.id)))
        sesion.commit()  # y la de esta lectura, para no bloquear a la aplicación
        return resultado

    return leer
