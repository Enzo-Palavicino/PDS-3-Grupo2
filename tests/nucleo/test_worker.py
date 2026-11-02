import logging
import time
from datetime import timedelta

from app.db import ahora
from app.modelos import EstadoMensaje, EventoAuditoria, MensajeEntrante, TipoActor
from app.nucleo import textos
from app.nucleo.worker import MAXIMO_INTENTOS, Worker
from app.proveedores.llm.base import ProveedorLLM, ResultadoLLM


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

    assert leer(fabrica_de_sesiones, texto.id).estado == EstadoMensaje.LISTO
    assert leer(fabrica_de_sesiones, nota_de_voz.id).estado == EstadoMensaje.LISTO


def test_un_mensaje_que_falla_se_reintenta_despues_de_esperar(
    fabrica_de_sesiones, contexto, guardar_mensaje, audio, stt_que_falla, canal_falso
):
    contexto.stt = stt_que_falla(fallos=1)
    mensaje = guardar_mensaje(**audio)
    worker = Worker(fabrica_de_sesiones, contexto)

    worker.procesar_pendientes()

    fallido = leer(fabrica_de_sesiones, mensaje.id)
    # Conserva su estado mientras le queden reintentos: el reintento sigue desde ese paso.
    assert fallido.estado == EstadoMensaje.RECIBIDO
    assert fallido.intentos == 1
    assert fallido.ultimo_error == "RuntimeError"
    assert fallido.proximo_intento_en > ahora() + timedelta(seconds=5)
    # Mientras no pase la espera, no se vuelve a intentar.
    assert worker.procesar_pendientes() == 0

    cumplir_la_espera(fabrica_de_sesiones, mensaje.id)
    worker.procesar_pendientes()

    assert leer(fabrica_de_sesiones, mensaje.id).estado == EstadoMensaje.LISTO
    assert textos.ERROR not in [texto for _, texto, _ in canal_falso.enviados]
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


def test_si_falla_el_envio_de_la_respuesta_el_reintento_no_vuelve_a_llamar_a_la_ia(
    fabrica_de_sesiones, contexto, guardar_mensaje, canal_falso
):
    canal_falso.envios_que_fallan = 1
    mensaje = guardar_mensaje()
    worker = Worker(fabrica_de_sesiones, contexto)

    worker.procesar_pendientes()
    assert leer(fabrica_de_sesiones, mensaje.id).estado == EstadoMensaje.EXTRAIDO

    cumplir_la_espera(fabrica_de_sesiones, mensaje.id)
    worker.procesar_pendientes()

    assert leer(fabrica_de_sesiones, mensaje.id).estado == EstadoMensaje.LISTO
    assert len(contexto.llm.entradas) == 1  # la IA se llamó una sola vez
    assert len(canal_falso.enviados) == 1


class LLMQueEsperaMientrasOtrosEscriben(ProveedorLLM):
    """Mientras la IA "piensa", otra parte de la aplicación escribe en la base de datos (por
    ejemplo, la web guarda un evento de auditoría)."""

    nombre = "fake"

    def __init__(self, fabrica_de_sesiones):
        self._fabrica = fabrica_de_sesiones

    def generar_json(self, instrucciones, entrada, esquema):
        with self._fabrica.begin() as otra_sesion:
            otra_sesion.add(EventoAuditoria(actor_tipo=TipoActor.SISTEMA, accion="prueba"))
        return ResultadoLLM(texto="{}", modelo="fake")


def test_mientras_la_ia_responde_los_demas_pueden_escribir(
    fabrica_de_sesiones, contexto, guardar_mensaje
):
    # Si el worker dejara su transacción abierta durante la llamada a la IA, en SQLite la otra
    # escritura quedaría bloqueada y el intento fallaría con "database is locked".
    contexto.llm = LLMQueEsperaMientrasOtrosEscriben(fabrica_de_sesiones)
    mensaje = guardar_mensaje()

    Worker(fabrica_de_sesiones, contexto).procesar_pendientes()

    procesado = leer(fabrica_de_sesiones, mensaje.id)
    assert procesado.estado == EstadoMensaje.LISTO
    assert procesado.intentos == 0


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
        while leer(fabrica_de_sesiones, mensaje.id).estado != EstadoMensaje.LISTO:
            assert time.monotonic() < limite, "el worker no procesó el mensaje"
            time.sleep(0.05)
    finally:
        worker.detener()
