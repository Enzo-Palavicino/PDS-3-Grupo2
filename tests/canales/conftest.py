"""Utilidades para los tests de Telegram. Ningún test sale a internet."""

import json
from pathlib import Path

import httpx2
import pytest

from app.canales.telegram.cliente import ClienteBotTelegram

CARPETA_UPDATES = Path(__file__).parent / "updates"


@pytest.fixture
def token_bot() -> str:
    return "123456789:TOKEN-FALSO-DE-PRUEBA"


@pytest.fixture
def cargar_update():
    """Carga un update de ejemplo de tests/canales/updates/."""

    def cargar(nombre: str) -> dict:
        return json.loads((CARPETA_UPDATES / f"{nombre}.json").read_text(encoding="utf-8"))

    return cargar


@pytest.fixture
def cliente_falso(token_bot):
    """Crea un ClienteBotTelegram que, en vez de llamar a Telegram, le pasa cada petición a la
    función `responder` del test. Devuelve el cliente y la lista de peticiones que recibió."""

    def crear(responder):
        peticiones = []

        def transporte(peticion: httpx2.Request) -> httpx2.Response:
            peticiones.append(peticion)
            return responder(peticion)

        http = httpx2.Client(transport=httpx2.MockTransport(transporte))
        return ClienteBotTelegram(token_bot, http=http), peticiones

    return crear
