import httpx2
from openai import OpenAI

from app.config import Config
from app.proveedores.stt import crear_proveedor_stt
from app.proveedores.stt.fake import ProveedorSTTFake
from app.proveedores.stt.openai import ProveedorSTTOpenAI


def test_por_defecto_se_usa_el_proveedor_fake():
    assert isinstance(crear_proveedor_stt(Config(_env_file=None)), ProveedorSTTFake)


def test_con_stt_provider_openai_se_usa_openai():
    config = Config(_env_file=None, stt_provider="openai", openai_api_key="clave-de-prueba")

    assert isinstance(crear_proveedor_stt(config), ProveedorSTTOpenAI)


def test_openai_recibe_el_audio_con_su_modelo_idioma_y_formato(tmp_path):
    peticiones = []

    def responder(peticion: httpx2.Request) -> httpx2.Response:
        peticiones.append(peticion)
        return httpx2.Response(200, json={"text": "Texto transcrito"})

    # Un cliente de OpenAI que, en vez de salir a internet, le pasa la petición a responder().
    cliente = OpenAI(
        api_key="clave-de-prueba",
        http_client=httpx2.Client(transport=httpx2.MockTransport(responder)),
    )
    ruta = tmp_path / "7.ogg"
    ruta.write_bytes(b"contenido-ogg")

    resultado = ProveedorSTTOpenAI("clave-de-prueba", "gpt-transcribe", cliente=cliente).transcribir(
        ruta, "audio/ogg"
    )

    assert resultado.texto == "Texto transcrito"
    assert resultado.modelo == "gpt-transcribe"
    peticion = peticiones[0]
    assert peticion.url.path == "/v1/audio/transcriptions"
    cuerpo = peticion.read()  # formulario multipart con el archivo y los parámetros
    assert b'name="model"\r\n\r\ngpt-transcribe\r\n' in cuerpo
    assert b'name="language"\r\n\r\nes\r\n' in cuerpo
    assert b'filename="7.ogg"' in cuerpo
    assert b"Content-Type: audio/ogg" in cuerpo
    assert b"contenido-ogg" in cuerpo
