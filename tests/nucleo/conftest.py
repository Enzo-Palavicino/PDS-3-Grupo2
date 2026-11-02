"""Utilidades para los tests del núcleo: un canal y un proveedor de transcripción falsos."""

import pytest

from app.canales.base import AdaptadorCanal
from app.modelos import MensajeEntrante
from app.nucleo.mensajes import registrar_mensaje_entrante
from app.nucleo.procesamiento import Contexto
from app.proveedores.stt.base import ProveedorSTT, ResultadoTranscripcion
from app.proveedores.stt.fake import ProveedorSTTFake


class CanalFalso(AdaptadorCanal):
    """Canal de mensajería que, en vez de llamar a una API, guarda lo que se le pide."""

    canal = "telegram"

    def __init__(self):
        self.mensaje = None  # lo que devuelve parsear()
        self.audio = (b"audio-de-prueba", "audio/ogg")  # lo que devuelve descargar_audio()
        self.descargas = 0
        self.enviados = []  # (destino, texto, responder_a)
        self.procesando = []  # destinos donde se mostró "escribiendo…"

    def parsear(self, evento):
        return self.mensaje

    def verificar_peticion(self, headers, body):
        return True

    def descargar_audio(self, referencia):
        self.descargas += 1
        return self.audio

    def enviar_texto(self, destino, texto, responder_a=None):
        self.enviados.append((destino, texto, responder_a))
        return f"{destino}:{900 + len(self.enviados)}"

    def borrar_mensaje(self, destino, id_mensaje_externo):
        return True

    def indicar_procesando(self, destino):
        self.procesando.append(destino)


class STTQueFalla(ProveedorSTT):
    """Falla las primeras `fallos` veces y después transcribe. Guarda las rutas que recibió."""

    nombre = "fake"

    def __init__(self, fallos: int):
        self.fallos_pendientes = fallos
        self.rutas = []

    def transcribir(self, ruta_audio, mime, idioma="es"):
        assert ruta_audio.exists(), "el audio debe existir mientras se transcribe"
        self.rutas.append(ruta_audio)
        if self.fallos_pendientes > 0:
            self.fallos_pendientes -= 1
            raise RuntimeError("dato clínico de prueba")
        return ResultadoTranscripcion(texto="Transcripción de prueba", modelo="fake")


@pytest.fixture
def canal_falso() -> CanalFalso:
    return CanalFalso()


@pytest.fixture
def stt_que_falla():
    return STTQueFalla


@pytest.fixture
def contexto(canal_falso, tmp_path) -> Contexto:
    return Contexto(
        adaptadores={"telegram": canal_falso},
        stt=ProveedorSTTFake(),
        carpeta_audios=tmp_path / "audios",
    )


@pytest.fixture
def guardar_mensaje(sesion, profesional, crear_mensaje):
    """Guarda un mensaje como lo haría la ingesta y lo devuelve."""

    def guardar(**cambios) -> MensajeEntrante:
        fila = registrar_mensaje_entrante(sesion, crear_mensaje(**cambios), profesional.id)
        sesion.commit()
        return fila

    return guardar


@pytest.fixture
def audio():
    """Campos de un mensaje de audio, para pasarle a crear_mensaje o a guardar_mensaje."""
    return {
        "tipo": "audio",
        "texto": None,
        "audio_ref": "AwAC",
        "audio_mime": "audio/ogg",
        "audio_tamano_bytes": 28417,
        "audio_duracion_seg": 7,
    }
