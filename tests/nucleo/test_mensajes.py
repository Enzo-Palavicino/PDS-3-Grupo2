from sqlalchemy import func, select

from app.modelos import EstadoMensaje, MensajeEntrante, Profesional
from app.nucleo.mensajes import registrar_mensaje_entrante


def contar_mensajes(sesion) -> int:
    return sesion.scalar(select(func.count()).select_from(MensajeEntrante))


def test_registra_el_mensaje_como_recibido(sesion, profesional, crear_mensaje):
    fila = registrar_mensaje_entrante(sesion, crear_mensaje(), profesional.id)
    sesion.commit()

    assert fila.id is not None
    assert fila.estado == EstadoMensaje.RECIBIDO
    assert fila.intentos == 0
    assert fila.texto == "Mensaje de prueba"
    assert fila.profesional_id == profesional.id


def test_un_mensaje_duplicado_no_crea_otra_fila(sesion, profesional, crear_mensaje):
    assert registrar_mensaje_entrante(sesion, crear_mensaje(), profesional.id) is not None
    assert registrar_mensaje_entrante(sesion, crear_mensaje(), profesional.id) is None
    sesion.commit()

    assert contar_mensajes(sesion) == 1


def test_el_mismo_id_en_otro_canal_no_es_duplicado(sesion, profesional, crear_mensaje):
    registrar_mensaje_entrante(sesion, crear_mensaje(), profesional.id)
    registrar_mensaje_entrante(sesion, crear_mensaje(canal="whatsapp"), profesional.id)
    sesion.commit()

    assert contar_mensajes(sesion) == 2


def test_un_duplicado_no_deshace_el_resto_de_la_transaccion(sesion, profesional, crear_mensaje):
    registrar_mensaje_entrante(sesion, crear_mensaje(), profesional.id)
    sesion.commit()

    otro = Profesional(nombre="Otro profesional", especialidad="nutrición")
    sesion.add(otro)
    assert registrar_mensaje_entrante(sesion, crear_mensaje(), profesional.id) is None
    sesion.commit()
    sesion.expire_all()

    assert sesion.get(Profesional, otro.id) is not None
    assert contar_mensajes(sesion) == 1
