from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.canales.base import MensajeNormalizado
from app.modelos import EstadoMensaje, MensajeEntrante, Profesional
from app.nucleo.mensajes import registrar_mensaje_entrante


def mensaje_de_prueba(**cambios) -> MensajeNormalizado:
    datos = {
        "canal": "telegram",
        "id_externo": "55667788:412",
        "remitente_externo": "55667788",
        "destino_respuesta": "55667788",
        "tipo": "texto",
        "recibido_en": datetime(2026, 11, 2, 15, 40, tzinfo=UTC),
        "texto": "Mensaje de prueba",
    }
    return MensajeNormalizado(**(datos | cambios))


@pytest.fixture
def profesional(sesion) -> Profesional:
    profesional = Profesional(nombre="Profesional de prueba", especialidad="pediatría")
    sesion.add(profesional)
    sesion.commit()
    return profesional


def contar_mensajes(sesion) -> int:
    return sesion.scalar(select(func.count()).select_from(MensajeEntrante))


def test_registra_el_mensaje_como_recibido(sesion, profesional):
    fila = registrar_mensaje_entrante(sesion, mensaje_de_prueba(), profesional.id)
    sesion.commit()

    assert fila.id is not None
    assert fila.estado == EstadoMensaje.RECIBIDO
    assert fila.intentos == 0
    assert fila.texto == "Mensaje de prueba"
    assert fila.profesional_id == profesional.id


def test_un_mensaje_duplicado_no_crea_otra_fila(sesion, profesional):
    assert registrar_mensaje_entrante(sesion, mensaje_de_prueba(), profesional.id) is not None
    assert registrar_mensaje_entrante(sesion, mensaje_de_prueba(), profesional.id) is None
    sesion.commit()

    assert contar_mensajes(sesion) == 1


def test_el_mismo_id_en_otro_canal_no_es_duplicado(sesion, profesional):
    registrar_mensaje_entrante(sesion, mensaje_de_prueba(), profesional.id)
    registrar_mensaje_entrante(sesion, mensaje_de_prueba(canal="whatsapp"), profesional.id)
    sesion.commit()

    assert contar_mensajes(sesion) == 2


def test_un_duplicado_no_deshace_el_resto_de_la_transaccion(sesion, profesional):
    registrar_mensaje_entrante(sesion, mensaje_de_prueba(), profesional.id)
    sesion.commit()

    otro = Profesional(nombre="Otro profesional", especialidad="nutrición")
    sesion.add(otro)
    assert registrar_mensaje_entrante(sesion, mensaje_de_prueba(), profesional.id) is None
    sesion.commit()
    sesion.expire_all()

    assert sesion.get(Profesional, otro.id) is not None
    assert contar_mensajes(sesion) == 1
