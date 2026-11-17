import pytest
from sqlalchemy import select, update

from app.modelos import Atencion, EstadoAtencion, OrigenAtencion, Residente, UsuarioWeb
from app.nucleo.atenciones import crear_atencion, verificar_integridad
from app.web.plantillas import plantillas
from tests.web.conftest import PASSWORD, csrf_de

CAMPOS = {
    "fecha_atencion": {"valor": "2026-11-16", "fragmento": None},
    "motivo": {"valor": "Control pediátrico", "fragmento": None},
    "indicaciones_farmacologicas": [{"medicamento": "salbutamol", "dosis": "dos puff"}],
}


@pytest.fixture
def atencion_id(sesion, datos_demo) -> int:
    """Una atención en borrador de la pediatra, para Emilia Soto (RES-02)."""
    autor = sesion.scalar(select(UsuarioWeb).where(UsuarioWeb.usuario == "pediatra"))
    residente = sesion.scalar(select(Residente).where(Residente.codigo == "RES-02"))
    atencion = crear_atencion(sesion, residente.id, autor, CAMPOS, OrigenAtencion.WEB)
    sesion.commit()
    return atencion.id


def leer(sesion, atencion_id: int) -> Atencion:
    sesion.expire_all()
    atencion = sesion.get(Atencion, atencion_id)
    sesion.commit()  # cierra la lectura: en SQLite bloquearía las escrituras de la aplicación
    return atencion


def firmar(cliente, atencion_id: int, password: str = PASSWORD, con_csrf: bool = True):
    ruta = f"/atenciones/{atencion_id}/firmar"
    datos = {"password": password}
    if con_csrf:
        datos["csrf"] = csrf_de(cliente.get(ruta).text)
    return cliente.post(ruta, data=datos, follow_redirects=False)


def test_la_pantalla_muestra_el_resumen_y_el_timbre(cliente, entrar, atencion_id):
    entrar("pediatra")

    html = cliente.get(f"/atenciones/{atencion_id}/firmar").text

    assert "Emilia Soto" in html
    assert "Control pediátrico" in html
    assert "salbutamol" in html
    assert "/timbre" in html
    assert 'name="password"' in html


def test_firmar_lleva_a_la_ficha_y_deja_la_atencion_firmada(
    cliente, entrar, sesion, atencion_id
):
    entrar("pediatra")

    respuesta = firmar(cliente, atencion_id)

    atencion = leer(sesion, atencion_id)
    assert respuesta.status_code == 303
    assert respuesta.headers["location"] == f"/residentes/{atencion.residente_id}"
    assert atencion.estado == EstadoAtencion.FIRMADA
    assert verificar_integridad(atencion)


def test_con_una_contrasena_incorrecta_vuelve_con_el_error(cliente, entrar, sesion, atencion_id):
    entrar("pediatra")

    respuesta = firmar(cliente, atencion_id, password="otra-clave")

    assert respuesta.status_code == 400
    assert "La contraseña no es correcta" in respuesta.text
    assert leer(sesion, atencion_id).estado == EstadoAtencion.BORRADOR


@pytest.mark.parametrize("usuario", ["nutricionista", "encargada_salud", "directora"])
def test_solo_la_autora_puede_abrir_y_enviar_la_firma(
    cliente, entrar, sesion, atencion_id, usuario
):
    entrar(usuario)

    assert cliente.get(f"/atenciones/{atencion_id}/firmar").status_code == 403
    respuesta = cliente.post(f"/atenciones/{atencion_id}/firmar", data={"password": PASSWORD})
    assert respuesta.status_code == 403
    assert leer(sesion, atencion_id).estado == EstadoAtencion.BORRADOR


def test_una_atencion_firmada_responde_409(cliente, entrar, atencion_id):
    entrar("pediatra")
    firmar(cliente, atencion_id)

    respuesta = cliente.get(f"/atenciones/{atencion_id}/firmar")

    assert respuesta.status_code == 409
    assert "se corrige agregando una adenda" in respuesta.text


def test_una_atencion_que_no_existe_da_404(cliente, entrar):
    entrar("pediatra")

    assert cliente.get("/atenciones/999/firmar").status_code == 404


def test_sin_token_csrf_no_se_firma(cliente, entrar, sesion, atencion_id):
    entrar("pediatra")

    respuesta = firmar(cliente, atencion_id, con_csrf=False)

    assert respuesta.status_code == 403
    assert leer(sesion, atencion_id).estado == EstadoAtencion.BORRADOR


# Componente de la ficha

COMPONENTE = plantillas.env.from_string(
    '{% from "dominio/firma.html" import firma_de_atencion %}'
    "{{ firma_de_atencion(atencion, integra) }}"
)


def test_el_componente_muestra_la_firma_verificada(cliente, entrar, sesion, atencion_id):
    entrar("pediatra")
    firmar(cliente, atencion_id)
    atencion = leer(sesion, atencion_id)

    html = COMPONENTE.render(atencion=atencion, integra=verificar_integridad(atencion))

    assert atencion.hash_firma[:12] in html
    assert f"/profesionales/{atencion.profesional_id}/timbre" in html
    assert "Integridad verificada" in html


def test_el_componente_avisa_si_el_contenido_cambio(cliente, entrar, sesion, atencion_id):
    entrar("pediatra")
    firmar(cliente, atencion_id)
    campos = {**CAMPOS, "motivo": {"valor": "otro motivo", "fragmento": None}}
    sesion.execute(update(Atencion).where(Atencion.id == atencion_id).values(campos=campos))
    sesion.commit()
    atencion = leer(sesion, atencion_id)

    html = COMPONENTE.render(atencion=atencion, integra=verificar_integridad(atencion))

    assert "no coincide con lo que se firmó" in html
    assert "Integridad verificada" not in html
