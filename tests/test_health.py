from fastapi.testclient import TestClient

from app.main import crear_app


def test_health_responde_ok():
    cliente = TestClient(crear_app())

    respuesta = cliente.get("/health")

    assert respuesta.status_code == 200
    assert respuesta.json() == {"estado": "ok"}
