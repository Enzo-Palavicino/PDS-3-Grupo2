import pytest
from sqlalchemy import select

from app.modelos import Atencion, EstadoAtencion, OrigenAtencion, Residente, UsuarioWeb
from app.nucleo.adendas import correcciones_de, crear_adenda
from app.nucleo.atenciones import crear_atencion, firmar_atencion
from app.web.plantillas import plantillas
from tests.web.conftest import PASSWORD, csrf_de

CAMPOS = {
    "fecha_atencion": {"valor": "2026-11-02", "fragmento": None},
    "motivo": {"valor": "Control pediátrico", "fragmento": None},
}


@pytest.fixture
def pediatra(sesion, datos_demo) -> UsuarioWeb:
    return sesion.scalar(select(UsuarioWeb).where(UsuarioWeb.usuario == "pediatra"))


@pytest.fixture
def crear(sesion, pediatra):
    """Crea una atención de la pediatra para Emilia Soto (RES-02), firmada o en borrador."""

    def atencion(firmada: bool = True) -> int:
        residente = sesion.scalar(select(Residente).where(Residente.codigo == "RES-02"))
        nueva = crear_atencion(sesion, residente.id, pediatra, CAMPOS, OrigenAtencion.WEB)
        if firmada:
            firmar_atencion(sesion, nueva, pediatra, PASSWORD)
        sesion.commit()
        return nueva.id

    return atencion


def adendas_de(sesion, atencion_id: int) -> list[Atencion]:
    sesion.expire_all()
    adendas = list(sesion.scalars(select(Atencion).where(Atencion.corrige_a_id == atencion_id)))
    sesion.commit()  # cierra la lectura: en SQLite bloquearía las escrituras de la aplicación
    return adendas


def corregir(cliente, atencion_id: int, motivo: str = "Dosis equivocada", con_csrf=True):
    ruta = f"/atenciones/{atencion_id}/corregir"
    datos = {"motivo": motivo}
    if con_csrf:
        datos["csrf"] = csrf_de(cliente.get("/cuenta/password").text)
    return cliente.post(ruta, data=datos, follow_redirects=False)


def test_la_autora_ve_el_formulario(cliente, entrar, crear):
    atencion_id = crear()
    entrar("pediatra")

    html = cliente.get(f"/atenciones/{atencion_id}/corregir").text

    assert f"Corregir la atención #{atencion_id}" in html
    assert 'name="motivo"' in html


def test_crear_la_correccion_lleva_a_editarla(cliente, entrar, sesion, crear):
    atencion_id = crear()
    entrar("pediatra")

    respuesta = corregir(cliente, atencion_id)

    [adenda] = adendas_de(sesion, atencion_id)
    assert respuesta.status_code == 303
    assert respuesta.headers["location"] == f"/atenciones/{adenda.id}"
    assert adenda.estado == EstadoAtencion.BORRADOR
    assert adenda.motivo_correccion == "Dosis equivocada"


def test_con_una_correccion_en_curso_lleva_a_esa(cliente, entrar, sesion, crear):
    atencion_id = crear()
    entrar("pediatra")
    corregir(cliente, atencion_id)
    [adenda] = adendas_de(sesion, atencion_id)

    respuesta_get = cliente.get(f"/atenciones/{atencion_id}/corregir", follow_redirects=False)
    respuesta_post = corregir(cliente, atencion_id, motivo="Otro motivo")

    assert respuesta_get.headers["location"] == f"/atenciones/{adenda.id}"
    assert respuesta_post.headers["location"] == f"/atenciones/{adenda.id}"
    assert len(adendas_de(sesion, atencion_id)) == 1


def test_una_atencion_ya_corregida_lleva_a_corregir_la_ultima_version(
    cliente, entrar, sesion, crear, pediatra
):
    atencion_id = crear()
    adenda = crear_adenda(sesion, sesion.get(Atencion, atencion_id), pediatra, "Dosis")
    firmar_atencion(sesion, adenda, pediatra, PASSWORD)
    sesion.commit()
    entrar("pediatra")

    respuesta_get = cliente.get(f"/atenciones/{atencion_id}/corregir", follow_redirects=False)
    respuesta_post = corregir(cliente, atencion_id, motivo="Otro error")

    assert respuesta_get.headers["location"] == f"/atenciones/{adenda.id}/corregir"
    assert respuesta_post.headers["location"] == f"/atenciones/{adenda.id}/corregir"
    assert len(adendas_de(sesion, atencion_id)) == 1


def test_sin_motivo_vuelve_con_el_error(cliente, entrar, sesion, crear):
    atencion_id = crear()
    entrar("pediatra")

    respuesta = corregir(cliente, atencion_id, motivo="   ")

    assert respuesta.status_code == 400
    assert "motivo" in respuesta.text
    assert adendas_de(sesion, atencion_id) == []


@pytest.mark.parametrize("usuario", ["nutricionista", "encargada_salud", "directora"])
def test_solo_la_autora_corrige(cliente, entrar, sesion, crear, usuario):
    atencion_id = crear()
    entrar(usuario)

    assert cliente.get(f"/atenciones/{atencion_id}/corregir").status_code == 403
    assert corregir(cliente, atencion_id).status_code == 403
    assert adendas_de(sesion, atencion_id) == []


def test_una_atencion_en_borrador_no_se_corrige(cliente, entrar, crear):
    atencion_id = crear(firmada=False)
    entrar("pediatra")

    assert cliente.get(f"/atenciones/{atencion_id}/corregir").status_code == 409


def test_una_atencion_que_no_existe_da_404(cliente, entrar):
    entrar("pediatra")

    assert cliente.get("/atenciones/999/corregir").status_code == 404


def test_sin_token_csrf_no_se_crea_la_correccion(cliente, entrar, sesion, crear):
    atencion_id = crear()
    entrar("pediatra")

    assert corregir(cliente, atencion_id, con_csrf=False).status_code == 403
    assert adendas_de(sesion, atencion_id) == []


# Componentes de la ficha

COMPONENTES = plantillas.env.from_string(
    '{% from "dominio/adendas.html" import corregida_por, corrige_a %}'
    "{{ corregida_por(correcciones) }}{{ corrige_a(atencion) }}"
)


def test_la_original_muestra_quien_la_corrigio(sesion, crear, pediatra):
    original = sesion.get(Atencion, crear())
    adenda = crear_adenda(sesion, original, pediatra, "Dosis equivocada")
    firmar_atencion(sesion, adenda, pediatra, PASSWORD)
    sesion.commit()

    html = COMPONENTES.render(correcciones=correcciones_de(sesion, original), atencion=original)

    assert f'href="/atenciones/{adenda.id}"' in html
    assert "Dosis equivocada" in html
    assert "Corrige la" not in html  # la original no corrige a nadie


def test_la_adenda_muestra_a_cual_corrige(sesion, crear, pediatra):
    original = sesion.get(Atencion, crear())
    adenda = crear_adenda(sesion, original, pediatra, "Dosis equivocada")

    html = COMPONENTES.render(correcciones=[], atencion=adenda)

    assert f"Corrige la <a href=\"/atenciones/{original.id}\">" in html
    assert "Corregida" not in html
