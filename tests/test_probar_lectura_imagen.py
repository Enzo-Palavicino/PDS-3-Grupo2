import httpx2
import pytest
from openai import APIConnectionError, APIStatusError

from app.config import Config
from app.proveedores.llm.base import ErrorLLM
from app.proveedores.llm.fake import ProveedorLLMFake
from scripts import probar_lectura_imagen as script

JPG = b"\xff\xd8\xff" + b"imagen-ficticia" + b"\xff\xd9"


@pytest.fixture
def imagen(tmp_path):
    ruta = tmp_path / "documento.jpg"
    ruta.write_bytes(JPG)
    return ruta


@pytest.fixture
def proveedor(monkeypatch):
    config = Config(_env_file=None, llm_provider="openai", openai_api_key="clave-de-prueba")
    monkeypatch.setattr(script, "obtener_config", lambda: config)
    llm = ProveedorLLMFake(lecturas=["Fecha: 12/06/2025\nObservaciones: [ilegible]"])
    monkeypatch.setattr(script, "crear_proveedor_llm", lambda config: llm)
    return llm


def test_muestra_la_lectura_y_el_tiempo(imagen, proveedor, monkeypatch, capsys):
    tiempos = iter([10.0, 12.5])
    monkeypatch.setattr(script, "perf_counter", lambda: next(tiempos))

    assert script.main(["--datos-ficticios", str(imagen)]) == 0

    salida = capsys.readouterr()
    assert "Tiempo de respuesta: 2.50 s" in salida.out
    assert "Modelo solicitado: gpt-6-luna" in salida.out
    assert "Modelo usado: fake" in salida.out
    assert "Fecha: 12/06/2025\nObservaciones: [ilegible]" in salida.out
    assert salida.err == ""
    assert proveedor.imagenes == [(JPG, "image/jpeg")]


def test_exige_confirmar_que_son_datos_ficticios(imagen, proveedor):
    with pytest.raises(SystemExit) as error:
        script.main([str(imagen)])

    assert error.value.code == 2
    assert proveedor.imagenes == []


@pytest.mark.parametrize(
    "contenido",
    [b"", b"no es una imagen", b"%PDF-1.7\nprueba\n%%EOF", b"x" * (10 * 1024 * 1024 + 1)],
)
def test_rechaza_archivos_invalidos_antes_de_llamar_a_la_api(
    imagen, proveedor, contenido, capsys
):
    imagen.write_bytes(contenido)

    assert script.main(["--datos-ficticios", str(imagen)]) == 1
    assert proveedor.imagenes == []
    assert "Imagen no válida" in capsys.readouterr().err


def test_informa_si_el_archivo_no_existe(tmp_path, capsys):
    assert script.main(["--datos-ficticios", str(tmp_path / "no-existe.jpg")]) == 1
    assert "No se pudo abrir" in capsys.readouterr().err


def test_no_confunde_el_proveedor_fake_con_una_prueba_real(imagen, monkeypatch, capsys):
    monkeypatch.setattr(script, "obtener_config", lambda: Config(_env_file=None))

    assert script.main(["--datos-ficticios", str(imagen)]) == 1
    assert "LLM_PROVIDER=openai" in capsys.readouterr().err


@pytest.mark.parametrize("tipo", ["red", "http", "lectura"])
def test_informa_errores_sin_exponer_datos_de_la_respuesta(
    imagen, proveedor, monkeypatch, capsys, tipo
):
    peticion = httpx2.Request("POST", "https://api.openai.com/v1/chat/completions")
    errores = {
        "red": APIConnectionError(request=peticion),
        "http": APIStatusError(
            "contenido-que-no-debe-publicarse",
            response=httpx2.Response(400, request=peticion),
            body={"texto": "contenido-que-no-debe-publicarse"},
        ),
        "lectura": ErrorLLM("lectura vacía"),
    }

    def fallar(contenido, mime):
        raise errores[tipo]

    monkeypatch.setattr(proveedor, "leer_imagen", fallar)

    assert script.main(["--datos-ficticios", str(imagen)]) == 1
    salida = capsys.readouterr()
    assert salida.err
    assert "contenido-que-no-debe-publicarse" not in salida.err
    assert "Texto literal" not in salida.out
