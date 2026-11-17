from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.modelos import (
    Atencion,
    BorradorAtencion,
    BorradorMensaje,
    EstadoAtencion,
    EventoAuditoria,
    Extraccion,
    MensajeEntrante,
    Transcripcion,
)
from app.web.revision import combinar
from tests.web.conftest import csrf_de
from tests.web.test_web_atenciones import FORMULARIO

CAMPOS_DE_LA_IA = {
    "residente": {"valor": "RES-02", "fragmento": "atendí a [RES-02]"},
    "fecha_atencion": {"valor": "2026-11-16", "fragmento": "hoy 16 de noviembre"},
    "motivo": {"valor": "tos", "fragmento": "por tos hace tres días"},
    "diagnosticos": [{"valor": "bronquiolitis leve", "fragmento": "cuadro de bronquiolitis leve"}],
    "indicaciones_farmacologicas": [
        {"medicamento": "salbutamol", "dosis": "2 puff", "frecuencia_horario": "cada 8 horas",
         "via": None, "duracion": None, "fecha_inicio": None, "fecha_termino": None,
         "fragmento": "salbutamol dos puff cada ocho horas"}
    ],
    "alergias": [{"valor": "penicilina", "fragmento": "es alérgica a la penicilina"}],
    "especialidad": {"valor": "pediatría", "fragmento": None},
}


@pytest.fixture
def borrador(sesion, crear_borrador):
    """Un borrador de la pediatra para Emilia Soto (RES-02), con un audio transcrito y una
    extracción de la IA."""
    borrador = crear_borrador("pediatra")
    borrador.campos = CAMPOS_DE_LA_IA
    borrador.faltantes = [{"campo": "acompanante", "descripcion": "acompañante (nombre y cargo)",
                           "obligatorio": False}]
    mensaje = MensajeEntrante(
        canal="telegram", id_externo="1:1", remitente_externo="1", destino_respuesta="1",
        profesional_id=borrador.profesional_id, tipo="audio", audio_ref="AwAC",
        recibido_en=datetime(2026, 11, 16, 15, 0, tzinfo=UTC),
    )
    sesion.add(mensaje)
    sesion.flush()
    sesion.add_all([
        BorradorMensaje(borrador_id=borrador.id, mensaje_id=mensaje.id),
        Transcripcion(mensaje_id=mensaje.id, texto="Hoy atendí a Emilia por tos",
                      proveedor="fake", modelo="fake-stt"),
        Extraccion(borrador_id=borrador.id, entrada_seudonimizada="Hoy atendí a [RES-02]",
                   salida={"motivo": "tos"}, proveedor="fake", modelo="fake-llm"),
    ])
    sesion.commit()
    return borrador


def revision(cliente, borrador_id, residente_id=None):
    ruta = f"/borradores/{borrador_id}/revisar"
    return cliente.get(ruta + (f"?residente_id={residente_id}" if residente_id else ""))


def guardar(cliente, borrador, cambios=None, confirmar=True, residente_id=2):
    datos = FORMULARIO | {
        "residente_id": str(residente_id),
        "motivo": "tos",
        "diagnosticos": "bronquiolitis leve",
        "ind_medicamento": ["salbutamol", ""],
        "ind_dosis": ["2 puff", ""],
        "ind_frecuencia_horario": ["cada 8 horas", ""],
        "ind_via": ["", ""],
        "ind_duracion": ["", ""],
        "ind_fecha_inicio": ["", ""],
        "ind_fecha_termino": ["", ""],
        "fecha_atencion": "2026-11-16",
    } | (cambios or {})
    if confirmar:
        datos["confirmo_identidad"] = str(residente_id)
    datos["csrf"] = csrf_de(cliente.get("/borradores").text)
    return cliente.post(f"/borradores/{borrador.id}/revisar", data=datos, follow_redirects=False)


def leer(sesion, modelo, id_):
    sesion.expire_all()
    fila = sesion.get(modelo, id_)
    sesion.commit()
    return fila


def la_atencion(sesion, borrador) -> Atencion | None:
    sesion.commit()
    atencion = sesion.scalar(select(Atencion).where(Atencion.borrador_id == borrador.id))
    sesion.commit()
    return atencion


def eventos(sesion, accion: str) -> list[EventoAuditoria]:
    sesion.commit()
    filas = list(sesion.scalars(select(EventoAuditoria).where(EventoAuditoria.accion == accion)))
    sesion.commit()
    return filas


# Revisar y completar


def test_el_borrador_ofrece_revisar_y_completar(cliente, entrar, borrador):
    entrar("pediatra")

    html = cliente.get(f"/borradores/{borrador.id}").text

    assert f'href="/borradores/{borrador.id}/revisar"' in html


def test_el_formulario_viene_prellenado_con_su_fragmento_y_la_transcripcion(
    cliente, entrar, borrador
):
    entrar("pediatra")

    html = revision(cliente, borrador.id).text

    assert 'value="2026-11-16"' in html
    assert 'value="tos"' in html
    assert ">bronquiolitis leve</textarea>" in html
    assert 'value="salbutamol"' in html
    assert "«por tos hace tres días»" in html  # el fragmento junto al campo
    assert "«salbutamol dos puff cada ocho horas»" in html
    assert "Hoy atendí a Emilia por tos" in html  # la transcripción del audio
    assert "Confirmo que la atención es de <strong>Emilia Soto</strong>" in html


def test_guardar_crea_la_atencion_enlazada_al_borrador(cliente, entrar, sesion, borrador):
    entrar("pediatra")

    respuesta = guardar(cliente, borrador)

    atencion = la_atencion(sesion, borrador)
    assert respuesta.status_code == 303
    assert respuesta.headers["location"] == f"/atenciones/{atencion.id}"
    assert atencion.estado == EstadoAtencion.BORRADOR
    assert atencion.origen == "telegram"
    assert atencion.profesional_id == borrador.profesional_id


def test_queda_registrado_que_se_cambio_a_mano(cliente, entrar, sesion, borrador):
    entrar("pediatra")

    guardar(cliente, borrador, {"motivo": "tos y fiebre", "lugar": "Enfermería"})

    atencion = la_atencion(sesion, borrador)
    # Lo que se escribió o cambió respecto de la IA. El diagnóstico, la fecha y la indicación
    # quedaron iguales, así que no cuentan.
    assert atencion.campos_editados == sorted([
        "acompanante", "evolucion_clinica", "hora_atencion", "lugar", "motivo",
        "observaciones", "otras_indicaciones", "proximo_control",
    ])
    [evento] = eventos(sesion, "atencion_editada")
    assert evento.detalle["campos"] == atencion.campos_editados


def test_lo_que_no_cambio_conserva_su_fragmento_y_sus_antecedentes(
    cliente, entrar, sesion, borrador
):
    entrar("pediatra")

    guardar(cliente, borrador)

    campos = la_atencion(sesion, borrador).campos
    assert campos["diagnosticos"][0]["fragmento"] == "cuadro de bronquiolitis leve"
    assert campos["indicaciones_farmacologicas"][0]["fragmento"].startswith("salbutamol")
    assert campos["alergias"] == CAMPOS_DE_LA_IA["alergias"]  # no está en el formulario


def test_la_respuesta_de_la_ia_no_cambia(cliente, entrar, sesion, borrador):
    entrar("pediatra")

    guardar(cliente, borrador, {"motivo": "otra cosa"})

    assert leer(sesion, BorradorAtencion, borrador.id).campos == CAMPOS_DE_LA_IA
    sesion.commit()
    [extraccion] = sesion.scalars(select(Extraccion).where(Extraccion.borrador_id == borrador.id))
    assert extraccion.salida == {"motivo": "tos"}
    sesion.commit()


def test_al_guardar_se_recalculan_los_faltantes(cliente, entrar, sesion, borrador):
    entrar("pediatra")

    guardar(cliente, borrador, {"acompanante_nombre": "", "acompanante_cargo": "",
                                "control_fecha": "", "control_descripcion": ""})

    faltantes = {f["campo"] for f in leer(sesion, BorradorAtencion, borrador.id).faltantes}
    assert faltantes == {"acompanante", "proximo_control"}

    guardar_edicion = la_atencion(sesion, borrador)
    datos = FORMULARIO | {"csrf": csrf_de(cliente.get(f"/atenciones/{guardar_edicion.id}").text)}
    cliente.post(f"/atenciones/{guardar_edicion.id}", data=datos)

    assert leer(sesion, BorradorAtencion, borrador.id).faltantes == []


def test_volver_a_revisar_abre_la_atencion_ya_creada(cliente, entrar, sesion, borrador):
    entrar("pediatra")
    guardar(cliente, borrador)
    atencion = la_atencion(sesion, borrador)

    respuesta = cliente.get(f"/borradores/{borrador.id}/revisar", follow_redirects=False)

    assert respuesta.headers["location"] == f"/atenciones/{atencion.id}"
    assert guardar(cliente, borrador).headers["location"] == f"/atenciones/{atencion.id}"
    sesion.commit()
    assert len(list(sesion.scalars(select(Atencion)))) == 1
    sesion.commit()


def test_sin_confirmar_la_identidad_no_se_guarda(cliente, entrar, sesion, borrador):
    entrar("pediatra")

    respuesta = guardar(cliente, borrador, confirmar=False)

    assert respuesta.status_code == 400
    assert la_atencion(sesion, borrador) is None


# Residente ambiguo


@pytest.fixture
def sin_residente(sesion, borrador):
    borrador.residente_id = None
    borrador.campos = CAMPOS_DE_LA_IA | {"residente": {"valor": "RES-01|RES-02", "fragmento": "Tomi o Emi"}}
    borrador.ambiguedades = [{"campo": "residente", "motivo": "nombra a dos residentes"}]
    sesion.commit()
    return borrador


def test_si_el_residente_es_ambiguo_se_elige_de_una_lista(cliente, entrar, sin_residente):
    entrar("pediatra")

    html = revision(cliente, sin_residente.id).text

    assert "nombra a dos residentes" in html
    assert 'name="residente_id"' in html
    assert "Tomás Rivas · RES-01 (mencionado)" in html
    assert "Emilia Soto · RES-02 (mencionado)" in html
    assert "Martina Rojas" not in html  # no está asignada a la pediatra
    assert 'name="confirmo_identidad"' not in html  # primero se elige

    elegido = revision(cliente, sin_residente.id, residente_id=1).text
    assert "Confirmo que la atención es de <strong>Tomás Rivas</strong>" in elegido


def test_la_atencion_queda_con_el_residente_elegido(cliente, entrar, sesion, sin_residente):
    entrar("pediatra")

    guardar(cliente, sin_residente, residente_id=1)

    atencion = la_atencion(sesion, sin_residente)
    assert atencion.residente_id == 1
    assert atencion.campos["residente"]["valor"] == "RES-01"


def test_no_se_puede_elegir_un_residente_no_asignado(cliente, entrar, sesion, sin_residente):
    entrar("pediatra")

    assert revision(cliente, sin_residente.id, residente_id=3).status_code == 403
    assert guardar(cliente, sin_residente, residente_id=3).status_code == 403
    assert la_atencion(sesion, sin_residente) is None


# Edición de la atención


@pytest.fixture
def atencion(cliente, entrar, sesion, borrador):
    entrar("pediatra")
    guardar(cliente, borrador)
    return la_atencion(sesion, borrador)


def test_la_atencion_se_sigue_editando_y_se_puede_firmar(cliente, entrar, sesion, atencion):
    html = cliente.get(f"/atenciones/{atencion.id}").text
    assert 'value="2026-11-16"' in html
    assert f'href="/atenciones/{atencion.id}/firmar"' in html
    assert "Hoy atendí a Emilia por tos" in html

    datos = FORMULARIO | {"motivo": "control", "csrf": csrf_de(html)}
    respuesta = cliente.post(f"/atenciones/{atencion.id}", data=datos, follow_redirects=False)

    assert respuesta.status_code == 303
    assert leer(sesion, Atencion, atencion.id).campos["motivo"]["valor"] == "control"
    assert "Cambios guardados." in cliente.get(f"/atenciones/{atencion.id}").text
    assert len(eventos(sesion, "atencion_editada")) == 2


def test_la_encargada_puede_editar_pero_no_firmar(cliente, entrar, sesion, atencion):
    entrar("encargada_salud")

    html = cliente.get(f"/atenciones/{atencion.id}").text
    datos = FORMULARIO | {"motivo": "revisado por la encargada", "csrf": csrf_de(html)}

    assert f"/atenciones/{atencion.id}/firmar" not in html
    assert cliente.post(f"/atenciones/{atencion.id}", data=datos).status_code == 200
    assert leer(sesion, Atencion, atencion.id).campos["motivo"]["valor"] == "revisado por la encargada"


@pytest.mark.parametrize("cuenta", ["nutricionista", "directora"])
def test_otro_profesional_no_edita_ni_revisa(cliente, entrar, csrf, sesion, borrador, atencion, cuenta):
    entrar(cuenta)

    assert cliente.get(f"/atenciones/{atencion.id}").status_code == 403
    assert cliente.get(f"/borradores/{borrador.id}/revisar").status_code == 403
    datos = FORMULARIO | {"csrf": csrf("/cuenta/password")}
    assert cliente.post(f"/atenciones/{atencion.id}", data=datos).status_code == 403


def test_una_atencion_firmada_lleva_a_la_ficha(cliente, entrar, sesion, atencion):
    atencion = leer(sesion, Atencion, atencion.id)
    atencion.estado = EstadoAtencion.FIRMADA
    sesion.merge(atencion)
    sesion.commit()

    respuesta = cliente.get(f"/atenciones/{atencion.id}", follow_redirects=False)

    assert respuesta.headers["location"] == f"/residentes/2#atencion-{atencion.id}"


# Combinar campos


def test_combinar_reemplaza_lo_del_formulario_y_conserva_el_resto():
    anteriores = {
        "motivo": {"valor": "tos", "fragmento": "por tos"},
        "lugar": {"valor": "Enfermería", "fragmento": "en enfermería"},
        "alergias": [{"valor": "penicilina", "fragmento": "alérgica"}],
        "especialidad": {"valor": "pediatría", "fragmento": None},
    }
    del_formulario = {"motivo": {"valor": "tos", "fragmento": None}}

    campos = combinar(anteriores, del_formulario)

    assert campos == {
        "motivo": {"valor": "tos", "fragmento": "por tos"},  # no cambió: conserva su fragmento
        "alergias": anteriores["alergias"],
        "especialidad": anteriores["especialidad"],
    }  # "lugar" se vació en el formulario, así que se quita


# El borrador después de revisarlo


def test_con_la_atencion_creada_el_boton_dice_continuar(cliente, entrar, borrador, atencion):
    html = cliente.get(f"/borradores/{borrador.id}").text

    assert "Continuar revisión" in html
    assert "La web no edita campos" not in html


def test_un_borrador_firmado_se_ve_confirmado(cliente, entrar, sesion, borrador, atencion):
    sesion.get(BorradorAtencion, borrador.id).estado = "confirmado"
    sesion.commit()

    lista = cliente.get("/borradores").text
    detalle = cliente.get(f"/borradores/{borrador.id}").text

    assert "Confirmado" in lista
    assert "Pendiente" not in lista
    assert f'href="/atenciones/{atencion.id}"' in detalle
    assert "Revisar y completar" not in detalle
