from fastapi.testclient import TestClient

from app.config import Config
from app.main import crear_app


def test_health_responde_ok():
    cliente = TestClient(crear_app())

    respuesta = cliente.get("/health")

    assert respuesta.status_code == 200
    assert respuesta.json() == {"estado": "ok"}


def test_al_arrancar_avisa_si_faltan_las_migraciones(tmp_path, caplog):
    config = Config(_env_file=None, database_url=f"sqlite:///{(tmp_path / 'vacia.db').as_posix()}")

    # Usar el TestClient con "with" ejecuta el inicio y el cierre de la aplicación.
    with TestClient(crear_app(config)) as cliente:
        assert cliente.get("/health").status_code == 200

    assert "corre primero alembic upgrade head" in caplog.text


def test_con_la_base_de_datos_migrada_arranca_sin_avisos(url_bd, caplog):
    with TestClient(crear_app(Config(_env_file=None, database_url=url_bd))):
        pass

    assert "alembic upgrade head" not in caplog.text
