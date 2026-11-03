import json
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.db import ahora
from app.modelos import (
    BorradorAtencion,
    BorradorMensaje,
    EstadoBorrador,
    EstadoMensaje,
    Extraccion,
    Profesional,
)
from app.nucleo import textos
from app.nucleo.borradores import calcular_faltantes, sin_actividad
from app.nucleo.extraccion import RegistroExtraido
from app.nucleo.mensajes import registrar_mensaje_entrante
from app.nucleo.procesamiento import procesar
from app.proveedores.llm.fake import ProveedorLLMFake

URL = "http://localhost:8000/borradores"

GUION_COMPLETO = (
    "Hoy atendí a Emilia Soto en el Hogar. Control pediátrico, cuadro de bronquiolitis leve. "
    "Indico salbutamol dos puff cada seis horas por cinco días y aseo nasal. Control en dos "
    "semanas. La acompañó la educadora María Pérez."
)
# Lo que respondería el LLM ante el guion completo (los campos que no están quedan vacíos).
RESPUESTA_COMPLETA = {
    "fecha_atencion": {"valor": "2026-11-02", "fragmento": "Hoy"},
    "motivo": {"valor": "Control pediátrico", "fragmento": "Control pediátrico"},
    "diagnosticos": [{"valor": "bronquiolitis leve", "fragmento": "cuadro de bronquiolitis leve"}],
    "proximo_control": {
        "fecha": "2026-11-16",
        "descripcion": "Control en dos semanas",
        "fragmento": "Control en dos semanas",
    },
    "acompanante": {
        "nombre": "María Pérez",
        "cargo": "educadora",
        "fragmento": "la educadora María Pérez",
    },
}


def contar(sesion, modelo) -> int:
    return sesion.scalar(select(func.count()).select_from(modelo))


def unico_borrador(sesion) -> BorradorAtencion:
    return sesion.scalar(select(BorradorAtencion))


@pytest.fixture(autouse=True)
def _con_residentes(residentes_guardados):
    """Todos los tests de este archivo usan los 4 residentes de la demo."""


# Los guiones de la demo


def test_un_registro_completo_crea_el_borrador_y_se_confirma(
    sesion, contexto, guardar_mensaje, canal_falso
):
    contexto.llm = ProveedorLLMFake([json.dumps(RESPUESTA_COMPLETA)])
    mensaje = guardar_mensaje(texto=GUION_COMPLETO)

    procesar(sesion, mensaje, contexto)

    borrador = unico_borrador(sesion)
    assert borrador.residente_id == 2
    assert borrador.faltantes == []
    assert borrador.ambiguedades == []
    assert borrador.campos["diagnosticos"][0]["valor"] == "bronquiolitis leve"
    # La especialidad sale del vínculo del profesional, no de la IA.
    assert borrador.campos["especialidad"]["valor"] == "pediatría"
    assert borrador.estado == EstadoBorrador.PENDIENTE
    confirmacion = (
        f"Borrador #{borrador.id} creado (residente E. S.). Revísalo en la plataforma: "
        f"{URL}/{borrador.id}"
    )
    assert canal_falso.enviados == [("55667788", confirmacion, "55667788:412")]
    assert borrador.mensaje_bot_id_externo == "55667788:901"
    assert mensaje.estado == EstadoMensaje.LISTO
    assert contar(sesion, Extraccion) == 1


def test_un_registro_incompleto_pide_lo_que_falta(sesion, contexto, guardar_mensaje, canal_falso):
    contexto.llm = ProveedorLLMFake(
        [json.dumps({"motivo": {"valor": "evaluación nutricional", "fragmento": "evaluación nutricional"}})]
    )
    mensaje = guardar_mensaje(texto="Martina Rojas, evaluación nutricional, peso adecuado.")

    procesar(sesion, mensaje, contexto)

    borrador = unico_borrador(sesion)
    assert borrador.residente_id == 3
    assert [falta["descripcion"] for falta in borrador.faltantes] == [
        "fecha de atención",
        "próximo control",
        "acompañante (nombre y cargo)",
    ]
    assert canal_falso.enviados[0][1] == (
        f"Borrador #{borrador.id} creado (residente M. R.). Falta: fecha de atención, próximo "
        "control, acompañante (nombre y cargo). Responde a este mensaje con los datos o "
        f"complétalos en la plataforma: {URL}/{borrador.id}"
    )


def test_responder_al_bot_completa_el_mismo_borrador(
    sesion, contexto, guardar_mensaje, canal_falso
):
    primero = guardar_mensaje(id_externo="55667788:412", texto="Atendí a Tomás por una otitis.")
    procesar(sesion, primero, contexto)
    borrador = unico_borrador(sesion)
    assert borrador.residente_id is None
    assert canal_falso.enviados[0][1] == textos.RESIDENTE_NO_IDENTIFICADO.format(
        id=borrador.id, url=f"{URL}/{borrador.id}"
    )

    respuesta = guardar_mensaje(
        id_externo="55667788:413",
        texto="Tomás Rivas",
        responde_a_id_externo=borrador.mensaje_bot_id_externo,
    )
    procesar(sesion, respuesta, contexto)

    assert contar(sesion, BorradorAtencion) == 1
    assert borrador.residente_id == 1
    assert contar(sesion, BorradorMensaje) == 2
    assert contar(sesion, Extraccion) == 2
    # La IA recibió los dos mensajes juntos y en orden.
    assert "por una otitis.\n[RES-01]" in contexto.llm.entradas[1]
    # Lo que falta ya se pidió una vez: ahora el bot solo lo informa.
    assert canal_falso.enviados[1][1].startswith(
        f"Borrador #{borrador.id} actualizado (residente T. R.). Aún falta:"
    )
    assert "Responde a este mensaje" not in canal_falso.enviados[1][1]


# Cuándo se crea un borrador nuevo


def test_responder_a_un_borrador_descartado_crea_uno_nuevo(sesion, contexto, guardar_mensaje):
    procesar(sesion, guardar_mensaje(id_externo="55667788:412", texto="Atendí a Tomás."), contexto)
    borrador = unico_borrador(sesion)
    borrador.estado = EstadoBorrador.DESCARTADO
    sesion.commit()

    respuesta = guardar_mensaje(
        id_externo="55667788:413",
        texto="Tomás Rivas",
        responde_a_id_externo=borrador.mensaje_bot_id_externo,
    )
    procesar(sesion, respuesta, contexto)

    assert contar(sesion, BorradorAtencion) == 2


def test_la_respuesta_de_otro_profesional_crea_un_borrador_nuevo(
    sesion, contexto, guardar_mensaje, crear_mensaje
):
    procesar(sesion, guardar_mensaje(id_externo="55667788:412", texto="Atendí a Tomás."), contexto)
    borrador = unico_borrador(sesion)
    otro = Profesional(nombre="Otro profesional", especialidad="nutrición")
    sesion.add(otro)
    sesion.commit()

    respuesta = registrar_mensaje_entrante(
        sesion,
        crear_mensaje(
            id_externo="99999999:5",
            remitente_externo="99999999",
            destino_respuesta="99999999",
            texto="Tomás Rivas",
            responde_a_id_externo=borrador.mensaje_bot_id_externo,
        ),
        otro.id,
    )
    sesion.commit()
    procesar(sesion, respuesta, contexto)

    assert contar(sesion, BorradorAtencion) == 2


# Consultas y borrado del chat


def test_una_consulta_no_crea_borrador(sesion, contexto, guardar_mensaje, canal_falso):
    mensaje = guardar_mensaje(texto="¿Qué alergias tiene Emilia Soto?")

    procesar(sesion, mensaje, contexto)

    assert contar(sesion, BorradorAtencion) == 0
    assert canal_falso.enviados == [("55667788", textos.SOLO_REGISTROS, "55667788:412")]
    assert mensaje.estado == EstadoMensaje.LISTO


def test_una_consulta_que_el_llm_anota_como_motivo_sigue_siendo_consulta(
    sesion, contexto, guardar_mensaje, canal_falso
):
    # Es lo que pasó con gpt-6-luna: anotó la pregunta como motivo.
    contexto.llm = ProveedorLLMFake(
        [json.dumps({"motivo": {"valor": "consulta por alergias", "fragmento": "alergias"}})]
    )

    procesar(sesion, guardar_mensaje(texto="¿Qué alergias tiene Emilia Soto?"), contexto)

    assert contar(sesion, BorradorAtencion) == 0
    assert canal_falso.enviados[0][1] == textos.SOLO_REGISTROS


def test_el_llm_puede_marcar_una_consulta_sin_signo_de_pregunta(
    sesion, contexto, guardar_mensaje, canal_falso
):
    contexto.llm = ProveedorLLMFake([json.dumps({"es_consulta": True})])

    procesar(sesion, guardar_mensaje(texto="Necesito saber las alergias de Emilia Soto"), contexto)

    assert contar(sesion, BorradorAtencion) == 0
    assert canal_falso.enviados[0][1] == textos.SOLO_REGISTROS


def test_un_registro_con_una_pregunta_en_medio_si_crea_borrador(sesion, contexto, guardar_mensaje):
    contexto.llm = ProveedorLLMFake(
        [
            json.dumps(
                {
                    "es_consulta": True,  # aunque el LLM se equivoque, hay datos de una atención
                    "diagnosticos": [
                        {"valor": "bronquiolitis resuelta", "fragmento": "bronquiolitis resuelta"}
                    ],
                }
            )
        ]
    )
    texto = "Control de Emilia Soto, ¿mejoró la tos? Sí, bronquiolitis resuelta."

    procesar(sesion, guardar_mensaje(texto=texto), contexto)

    borrador = unico_borrador(sesion)
    assert borrador.campos["diagnosticos"][0]["valor"] == "bronquiolitis resuelta"
    assert "es_consulta" not in borrador.campos


def test_con_la_opcion_activada_borra_del_chat_el_mensaje_procesado(
    sesion, contexto, guardar_mensaje, canal_falso
):
    contexto.borrar_mensajes_importados = True

    procesar(sesion, guardar_mensaje(texto=GUION_COMPLETO), contexto)

    assert canal_falso.borrados == [("55667788", "55667788:412")]


def test_sin_la_opcion_no_borra_nada(sesion, contexto, guardar_mensaje, canal_falso):
    procesar(sesion, guardar_mensaje(texto=GUION_COMPLETO), contexto)

    assert canal_falso.borrados == []


# Reglas de los faltantes


def test_un_registro_con_todo_no_tiene_faltantes():
    registro = RegistroExtraido.model_validate(
        RESPUESTA_COMPLETA | {"residente": {"valor": "RES-02", "fragmento": "[RES-02]"}}
    )

    assert calcular_faltantes(registro) == []


def test_faltantes_obligatorios_y_esperados():
    faltantes = calcular_faltantes(RegistroExtraido())

    assert [(f["descripcion"], f["obligatorio"]) for f in faltantes] == [
        ("residente", True),
        ("fecha de atención", True),
        ("diagnóstico o motivo", True),
        ("próximo control", False),
        ("acompañante (nombre y cargo)", False),
    ]


def test_basta_el_motivo_o_un_diagnostico():
    con_motivo = RegistroExtraido.model_validate({"motivo": {"valor": "control", "fragmento": "c"}})
    con_diagnostico = RegistroExtraido.model_validate(
        {"diagnosticos": [{"valor": "otitis", "fragmento": "otitis"}]}
    )

    for registro in (con_motivo, con_diagnostico):
        descripciones = [f["descripcion"] for f in calcular_faltantes(registro)]
        assert "diagnóstico o motivo" not in descripciones


def test_al_acompanante_le_puede_faltar_solo_el_cargo():
    registro = RegistroExtraido.model_validate(
        {"acompanante": {"nombre": "María Pérez", "cargo": None, "fragmento": "María Pérez"}}
    )

    assert "cargo del acompañante" in [f["descripcion"] for f in calcular_faltantes(registro)]


# Borradores sin actividad (regla 9)


@pytest.mark.parametrize(
    ("dias_sin_cambios", "estado", "marcado"),
    [
        (31, EstadoBorrador.PENDIENTE, True),
        (29, EstadoBorrador.PENDIENTE, False),
        # Un borrador descartado ya se revisó: no se marca aunque sea antiguo.
        (31, EstadoBorrador.DESCARTADO, False),
    ],
)
def test_un_borrador_pendiente_sin_cambios_en_30_dias_queda_marcado(
    dias_sin_cambios, estado, marcado
):
    borrador = BorradorAtencion(
        estado=estado, actualizado_en=ahora() - timedelta(days=dias_sin_cambios)
    )

    assert sin_actividad(borrador, dias=30) is marcado
