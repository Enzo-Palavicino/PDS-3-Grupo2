"""Límite de tamaño de las peticiones y configuración del despliegue (E5-01)."""

import re
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.web.limites import LimiteDeSubida
from tests.web.test_web_adjuntos import PDF, TAMANO_MAXIMO_BYTES, subir

RAIZ = Path(__file__).resolve().parents[2]


@pytest.fixture
def eco() -> TestClient:
    """Aplicación mínima que devuelve cuántos bytes recibió, con un límite de 100 bytes."""
    app = FastAPI()
    app.add_middleware(LimiteDeSubida, maximo_bytes=100)

    @app.post("/eco")
    async def eco_(request: Request):
        return {"bytes": len(await request.body())}

    return TestClient(app)


def test_una_peticion_dentro_del_limite_pasa(eco):
    respuesta = eco.post("/eco", content=b"x" * 100)

    assert respuesta.json() == {"bytes": 100}


def test_una_peticion_que_declara_mas_del_maximo_se_rechaza(eco):
    respuesta = eco.post("/eco", content=b"x" * 101)

    assert respuesta.status_code == 413
    assert "50 MB" in respuesta.text


def test_una_peticion_por_partes_se_corta_al_superar_el_maximo(eco):
    # Sin Content-Length: el cuerpo llega por partes y se cuenta a medida que llega.
    partes = (b"x" * 40 for _ in range(3))

    respuesta = eco.post("/eco", content=partes)

    assert respuesta.status_code == 413


def test_el_servidor_acepta_un_adjunto_de_10_mb(cliente, entrar, csrf):
    grande = PDF[:-6] + b" " * (TAMANO_MAXIMO_BYTES - len(PDF)) + PDF[-6:]
    entrar("encargada_salud")

    respuesta = subir(cliente, csrf, contenido=grande, nombre="examen.pdf")

    assert respuesta.status_code == 200
    assert "Documento adjuntado exitosamente" in respuesta.text


def test_render_yaml_deja_whatsapp_encendido_y_sus_secretos_en_el_panel():
    # Un "Manual sync" del Blueprint aplica estos valores: con "false", apagaría WhatsApp.
    blueprint = (RAIZ / "render.yaml").read_text(encoding="utf-8")

    assert re.search(r'key: WHATSAPP_ENABLED\s+value: "true"', blueprint)
    for variable in (
        "KAPSO_API_KEY",
        "KAPSO_PHONE_NUMBER_ID",
        "KAPSO_WEBHOOK_SECRET",
        "WHATSAPP_PHONE_NUMBER",
    ):
        assert re.search(rf"key: {variable}\s+sync: false", blueprint), variable
