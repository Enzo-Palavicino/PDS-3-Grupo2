from datetime import date

import pytest
from sqlalchemy import select

from app.modelos import (
    Atencion,
    EstadoAtencion,
    EstadoTratamiento,
    OrigenAtencion,
    Residente,
    Tratamiento,
)
from app.nucleo.tratamientos import tratamientos_del_residente
from app.web.plantillas import plantillas
from tests.web.conftest import csrf_de


@pytest.fixture
def tratamiento(sesion, datos_demo, id_profesional):
    """Salbutamol activo de Emilia Soto (RES-02), de una atención firmada de la pediatra."""
    residente = sesion.scalar(select(Residente).where(Residente.codigo == "RES-02"))
    atencion = Atencion(
        residente_id=residente.id,
        profesional_id=id_profesional("pediatra"),
        origen=OrigenAtencion.WEB,
        estado=EstadoAtencion.FIRMADA,
    )
    sesion.add(atencion)
    sesion.flush()
    tratamiento = Tratamiento(
        residente_id=residente.id,
        atencion_id=atencion.id,
        medicamento="salbutamol",
        dosis="dos puff",
        indicado_en=date(2026, 11, 2),
    )
    sesion.add(tratamiento)
    sesion.commit()
    return tratamiento


def suspender(cliente, tratamiento_id: int, motivo: str = "Sin síntomas", con_csrf=True):
    datos = {"motivo": motivo}
    if con_csrf:
        datos["csrf"] = csrf_de(cliente.get("/borradores").text)
    return cliente.post(
        f"/tratamientos/{tratamiento_id}/suspender", data=datos, follow_redirects=False
    )


def leer(sesion, tratamiento_id: int) -> Tratamiento:
    sesion.expire_all()
    tratamiento = sesion.get(Tratamiento, tratamiento_id)
    sesion.commit()  # cierra la lectura: en SQLite bloquearía las escrituras de la aplicación
    return tratamiento


def test_un_profesional_suspende_y_vuelve_a_la_ficha(cliente, entrar, sesion, tratamiento):
    entrar("nutricionista")  # cualquier profesional, no solo quien lo indicó

    respuesta = suspender(cliente, tratamiento.id)

    assert respuesta.status_code == 303
    assert respuesta.headers["location"] == f"/residentes/{tratamiento.residente_id}"
    guardado = leer(sesion, tratamiento.id)
    assert guardado.estado == EstadoTratamiento.SUSPENDIDO
    assert guardado.motivo_suspension == "Sin síntomas"


@pytest.mark.parametrize("usuario", ["directora", "encargada_salud"])
def test_la_directora_y_la_encargada_no_suspenden(cliente, entrar, sesion, tratamiento, usuario):
    entrar(usuario)
    csrf = csrf_de(cliente.get("/cuenta/password").text)

    respuesta = cliente.post(
        f"/tratamientos/{tratamiento.id}/suspender", data={"motivo": "x", "csrf": csrf}
    )

    assert respuesta.status_code == 403
    assert leer(sesion, tratamiento.id).estado == EstadoTratamiento.ACTIVO


def test_sin_motivo_responde_400(cliente, entrar, sesion, tratamiento):
    entrar("pediatra")

    respuesta = suspender(cliente, tratamiento.id, motivo="  ")

    assert respuesta.status_code == 400
    assert "motivo" in respuesta.text
    assert leer(sesion, tratamiento.id).estado == EstadoTratamiento.ACTIVO


def test_un_tratamiento_ya_suspendido_responde_409(cliente, entrar, tratamiento):
    entrar("pediatra")
    suspender(cliente, tratamiento.id)

    assert suspender(cliente, tratamiento.id).status_code == 409


def test_sin_token_csrf_no_se_suspende(cliente, entrar, sesion, tratamiento):
    entrar("pediatra")

    assert suspender(cliente, tratamiento.id, con_csrf=False).status_code == 403
    assert leer(sesion, tratamiento.id).estado == EstadoTratamiento.ACTIVO


def test_un_tratamiento_que_no_existe_da_404(cliente, entrar):
    entrar("pediatra")

    assert suspender(cliente, 999).status_code == 404


# Componente de la ficha

COMPONENTE = plantillas.env.from_string(
    '{% from "dominio/tratamientos.html" import lista_de_tratamientos %}'
    '{{ lista_de_tratamientos(tratamientos, puede_suspender, "token") }}'
)


def test_el_componente_muestra_los_vigentes_con_su_formulario(sesion, tratamiento):
    tratamientos = tratamientos_del_residente(sesion, tratamiento.residente_id)

    html = COMPONENTE.render(tratamientos=tratamientos, puede_suspender=True)

    assert "salbutamol" in html
    assert "Indicado el 02-11-2026" in html
    assert f'action="/tratamientos/{tratamiento.id}/suspender"' in html
    assert "<details" not in html  # sin historial todavía


def test_sin_permiso_el_componente_no_muestra_el_formulario(sesion, tratamiento):
    tratamientos = tratamientos_del_residente(sesion, tratamiento.residente_id)

    html = COMPONENTE.render(tratamientos=tratamientos, puede_suspender=False)

    assert "salbutamol" in html
    assert "/suspender" not in html


def test_el_historial_va_plegado_con_el_motivo(cliente, entrar, sesion, tratamiento):
    entrar("pediatra")
    suspender(cliente, tratamiento.id, motivo="Sin síntomas hace 3 días")
    sesion.expire_all()  # lee lo que guardó la aplicación
    tratamientos = tratamientos_del_residente(sesion, tratamiento.residente_id)
    sesion.commit()

    html = COMPONENTE.render(tratamientos=tratamientos, puede_suspender=True)

    assert "Sin tratamientos activos" in html
    assert "Historial de tratamientos (1)" in html
    assert "Sin síntomas hace 3 días" in html
