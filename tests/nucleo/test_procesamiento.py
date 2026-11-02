import pytest
from sqlalchemy import func, select

from app.modelos import EstadoMensaje, Transcripcion
from app.nucleo.procesamiento import procesar


def contar_transcripciones(sesion) -> int:
    return sesion.scalar(select(func.count()).select_from(Transcripcion))


def test_una_nota_de_voz_se_transcribe_y_el_audio_se_borra(
    sesion, contexto, guardar_mensaje, audio
):
    mensaje = guardar_mensaje(**audio)

    procesar(sesion, mensaje, contexto)
    sesion.commit()

    transcripcion = sesion.scalar(select(Transcripcion))
    assert transcripcion.mensaje_id == mensaje.id
    assert transcripcion.texto == "Transcripción de prueba"
    assert (transcripcion.proveedor, transcripcion.modelo) == ("fake", "fake")
    assert transcripcion.duracion_seg == 7
    assert mensaje.estado == EstadoMensaje.TRANSCRITO
    assert list(contexto.carpeta_audios.iterdir()) == []


def test_el_archivo_temporal_se_llama_como_el_id_del_mensaje(
    sesion, contexto, guardar_mensaje, audio, stt_que_falla
):
    contexto.stt = stt_que_falla(fallos=0)
    mensaje = guardar_mensaje(**audio)

    procesar(sesion, mensaje, contexto)

    assert [ruta.name for ruta in contexto.stt.rutas] == [f"{mensaje.id}.ogg"]
    assert not contexto.stt.rutas[0].exists()


def test_un_texto_no_necesita_transcripcion(sesion, contexto, guardar_mensaje):
    mensaje = guardar_mensaje()

    procesar(sesion, mensaje, contexto)
    sesion.commit()

    assert mensaje.estado == EstadoMensaje.TRANSCRITO
    assert contar_transcripciones(sesion) == 0


def test_repetir_el_procesamiento_no_vuelve_a_transcribir(
    sesion, contexto, guardar_mensaje, audio, canal_falso
):
    mensaje = guardar_mensaje(**audio)

    procesar(sesion, mensaje, contexto)
    sesion.commit()
    procesar(sesion, mensaje, contexto)
    sesion.commit()

    assert canal_falso.descargas == 1
    assert contar_transcripciones(sesion) == 1


def test_si_la_transcripcion_falla_el_audio_se_borra_igual(
    sesion, contexto, guardar_mensaje, audio, stt_que_falla
):
    contexto.stt = stt_que_falla(fallos=1)
    mensaje = guardar_mensaje(**audio)

    with pytest.raises(RuntimeError):
        procesar(sesion, mensaje, contexto)

    assert list(contexto.carpeta_audios.iterdir()) == []


def test_muestra_escribiendo_en_el_chat_mientras_procesa(
    sesion, contexto, guardar_mensaje, canal_falso
):
    procesar(sesion, guardar_mensaje(), contexto)

    assert canal_falso.procesando == ["55667788"]
