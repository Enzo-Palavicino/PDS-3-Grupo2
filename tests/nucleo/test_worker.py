import logging
import time
from datetime import timedelta

from app.db import ahora
from app.modelos import EstadoMensaje, MensajeEntrante
from app.nucleo import textos
from app.nucleo.worker import MAXIMO_INTENTOS, Worker


def leer(fabrica_de_sesiones, mensaje_id: int) -> MensajeEntrante:
    """Lee el mensaje con una sesión nueva, para ver lo último que guardó el worker."""
    with fabrica_de_sesiones() as sesion:
        return sesion.get(MensajeEntrante, mensaje_id)


def cumplir_la_espera(fabrica_de_sesiones, mensaje_id: int) -> None:
    """Simula que ya pasó el tiempo de espera antes del próximo reintento."""
    with fabrica_de_sesiones.begin() as sesion:
        mensaje = sesion.get(MensajeEntrante, mensaje_id)
        if mensaje.proximo_intento_en is not None:
            mensaje.proximo_intento_en = ahora() - timedelta(seconds=1)


def test_procesa_los_mensajes_pendientes(fabrica_de_sesiones, contexto, guardar_mensaje, audio):
    texto = guardar_mensaje(id_externo="55667788:1")
    nota_de_voz = guardar_mensaje(id_externo="55667788:2", **audio)

    assert Worker(fabrica_de_sesiones, contexto).procesar_pendientes() == 2

    assert leer(fabrica_de_sesiones, texto.id).estado == EstadoMensaje.TRANSCRITO
    assert leer(fabrica_de_sesiones, nota_de_voz.id).estado == EstadoMensaje.TRANSCRITO


def test_un_mensaje_que_falla_se_reintenta_despues_de_esperar(
    fabrica_de_sesiones, contexto, guardar_mensaje, audio, stt_que_falla, canal_falso
):
    contexto.stt = stt_que_falla(fallos=1)
    mensaje = guardar_mensaje(**audio)
    worker = Worker(fabrica_de_sesiones, contexto)

    worker.procesar_pendientes()

    fallido = leer(fabrica_de_sesiones, mensaje.id)
    assert fallido.estado == EstadoMensaje.ERROR
    assert fallido.intentos == 1
    assert fallido.ultimo_error == "RuntimeError"
    assert fallido.proximo_intento_en > ahora() + timedelta(seconds=5)
    # Mientras no pase la espera, no se vuelve a intentar.
    assert worker.procesar_pendientes() == 0

    cumplir_la_espera(fabrica_de_sesiones, mensaje.id)
    worker.procesar_pendientes()

    assert leer(fabrica_de_sesiones, mensaje.id).estado == EstadoMensaje.TRANSCRITO
    assert canal_falso.enviados == []
    assert list(contexto.carpeta_audios.iterdir()) == []


def test_despues_de_3_fallos_queda_en_error_y_se_avisa_una_sola_vez(
    fabrica_de_sesiones, contexto, guardar_mensaje, audio, stt_que_falla, canal_falso
):
    contexto.stt = stt_que_falla(fallos=10)
    mensaje = guardar_mensaje(**audio)
    worker = Worker(fabrica_de_sesiones, contexto)

    for _ in range(MAXIMO_INTENTOS):
        worker.procesar_pendientes()
        cumplir_la_espera(fabrica_de_sesiones, mensaje.id)

    assert worker.procesar_pendientes() == 0  # ya no se reintenta
    final = leer(fabrica_de_sesiones, mensaje.id)
    assert final.estado == EstadoMensaje.ERROR
    assert final.intentos == MAXIMO_INTENTOS
    assert final.proximo_intento_en is None
    assert canal_falso.enviados == [("55667788", textos.ERROR, "55667788:412")]


def test_el_log_de_un_fallo_no_incluye_su_contenido(
    fabrica_de_sesiones, contexto, guardar_mensaje, audio, stt_que_falla, caplog
):
    caplog.set_level(logging.INFO)
    contexto.stt = stt_que_falla(fallos=1)
    guardar_mensaje(**audio)

    Worker(fabrica_de_sesiones, contexto).procesar_pendientes()

    assert "RuntimeError" in caplog.text
    assert "dato clínico de prueba" not in caplog.text


def test_al_arrancar_borra_audios_de_intentos_interrumpidos(fabrica_de_sesiones, contexto):
    contexto.carpeta_audios.mkdir(parents=True)
    (contexto.carpeta_audios / "7.ogg").write_bytes(b"audio")
    worker = Worker(fabrica_de_sesiones, contexto)
    worker.detener()  # ejecutar() hace la limpieza y termina enseguida

    worker.ejecutar()

    assert list(contexto.carpeta_audios.iterdir()) == []


def test_al_despertarlo_procesa_un_mensaje_nuevo_sin_esperar_la_revision(
    fabrica_de_sesiones, contexto, guardar_mensaje
):
    # Con un intervalo de 60 s, si el mensaje se procesa en menos es porque despertar() funcionó.
    worker = Worker(fabrica_de_sesiones, contexto, intervalo_seg=60)
    worker.iniciar()
    try:
        time.sleep(0.2)  # deja que el worker revise la cola vacía y se ponga a esperar
        mensaje = guardar_mensaje()
        worker.despertar()

        limite = time.monotonic() + 5
        while leer(fabrica_de_sesiones, mensaje.id).estado != EstadoMensaje.TRANSCRITO:
            assert time.monotonic() < limite, "el worker no procesó el mensaje"
            time.sleep(0.05)
    finally:
        worker.detener()
