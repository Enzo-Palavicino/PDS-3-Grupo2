from threading import Event

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Config
from app.main import crear_app
from app.modelos import DocumentoHistorico, EstadoDocumento
from app.nucleo.worker import Worker
from scripts.sembrar_datos import sembrar
from tests.web.conftest import csrf_de
from tests.web.test_web_adjuntos import PNG


def test_subir_despierta_el_worker_real_sin_telegram_ni_whatsapp(
    sesion, url_bd, fabrica_de_sesiones, monkeypatch, tmp_path
):
    sembrar(sesion, "clave-de-prueba")
    sesion.commit()
    terminado = Event()
    procesar = Worker._procesar_documento

    def con_aviso(self, documento_id):
        procesar(self, documento_id)
        terminado.set()

    monkeypatch.setattr(Worker, "_procesar_documento", con_aviso)
    audio = tmp_path / "audio-de-otra-instancia"
    audio.write_bytes(b"no tocar")
    config = Config(
        _env_file=None, database_url=url_bd, secret_key="clave-de-prueba", audio_dir=tmp_path,
    )
    with TestClient(crear_app(config)) as cliente:
        assert cliente.app.state.worker_documentos is cliente.app.state.worker
        token = csrf_de(cliente.get("/login").text)
        cliente.post("/login", data={
            "csrf": token, "usuario": "encargada_salud", "password": "clave-de-prueba",
        })
        token = csrf_de(cliente.get("/digitalizacion?residente_id=2").text)
        respuesta = cliente.post("/digitalizacion", data={
            "csrf": token, "residente_id": 2, "confirmar_identidad": "true",
            "tipo_documento": "Registro",
        }, files={"archivos": ("ficticia.png", PNG, "image/png")})
        assert respuesta.status_code == 200
        assert terminado.wait(5), "La subida no despertó al worker"
        with fabrica_de_sesiones() as otra:
            assert otra.scalar(select(DocumentoHistorico)).estado == EstadoDocumento.POR_REVISAR
        hilo = cliente.app.state.worker._hilo
    assert not hilo.is_alive()
    assert audio.read_bytes() == b"no tocar"
