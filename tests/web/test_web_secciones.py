"""Permisos y navegación de las secciones compartidas de la entrega 2."""

import re

import pytest


def test_las_secciones_nuevas_exigen_iniciar_sesion(cliente):
    for ruta in (
        "/residentes",
        "/profesionales",
        "/fichas",
        "/residentes/2",
        "/atenciones",
        "/adjuntos",
        "/digitalizacion",
    ):
        respuesta = cliente.get(ruta, follow_redirects=False)
        assert respuesta.status_code == 303
        assert respuesta.headers["location"] == f"/login?siguiente={ruta}"


@pytest.mark.parametrize(
    "cuenta,rutas",
    [
        (
            "directora",
            ["/fichas", "/residentes/2", "/atenciones", "/adjuntos", "/digitalizacion"],
        ),
        ("pediatra", ["/residentes", "/profesionales", "/digitalizacion"]),
        ("encargada_salud", ["/profesionales"]),
    ],
)
def test_el_servidor_rechaza_las_secciones_de_otro_rol(cliente, entrar, cuenta, rutas):
    entrar(cuenta)
    for ruta in rutas:
        assert cliente.get(ruta).status_code == 403


@pytest.mark.parametrize("cuenta", ["encargada_salud", "pediatra"])
def test_las_secciones_pendientes_se_pueden_abrir_sin_ejecutar_servicios(
    cliente, entrar, cuenta
):
    entrar(cuenta)
    rutas = ["/atenciones"]
    for ruta in rutas:
        respuesta = cliente.get(ruta)
        assert respuesta.status_code == 501
        assert "Disponible próximamente" in respuesta.text


@pytest.mark.parametrize(
    "cuenta,presentes,ausentes",
    [
        (
            "directora",
            ["/residentes", "/profesionales"],
            ["/fichas", "/atenciones", "/adjuntos", "/digitalizacion"],
        ),
        (
            "encargada_salud",
            ["/residentes", "/fichas", "/atenciones", "/adjuntos", "/digitalizacion"],
            ["/profesionales"],
        ),
        (
            "pediatra",
            ["/fichas", "/atenciones", "/adjuntos"],
            ["/residentes", "/profesionales", "/digitalizacion"],
        ),
    ],
)
def test_el_menu_muestra_una_sola_vez_los_accesos_del_rol(
    cliente, entrar, cuenta, presentes, ausentes
):
    respuesta = cliente.get(entrar(cuenta).headers["location"])
    menu = re.search(r"<nav\b[^>]*>(.*?)</nav>", respuesta.text, re.DOTALL).group(1)
    enlaces = re.findall(r'href="([^"]+)"', menu)
    for ruta in presentes:
        assert enlaces.count(ruta) == 1
    for ruta in ausentes:
        assert ruta not in enlaces
