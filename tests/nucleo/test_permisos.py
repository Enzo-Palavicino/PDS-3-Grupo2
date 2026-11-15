import pytest

from app.modelos import Atencion, EstadoAtencion, OrigenAtencion, Rol, UsuarioWeb
from app.nucleo.permisos import puede_editar_atencion, puede_firmar, puede_ver_ficha

AUTOR = UsuarioWeb(usuario="pediatra", rol=Rol.PROFESIONAL, profesional_id=1)
OTRO_PROFESIONAL = UsuarioWeb(usuario="nutricionista", rol=Rol.PROFESIONAL, profesional_id=2)
ENCARGADA = UsuarioWeb(usuario="encargada_salud", rol=Rol.ENCARGADA_SALUD)
DIRECTORA = UsuarioWeb(usuario="directora", rol=Rol.DIRECTORA)


def atencion(estado: EstadoAtencion) -> Atencion:
    return Atencion(residente_id=1, profesional_id=1, origen=OrigenAtencion.WEB, estado=estado)


@pytest.mark.parametrize(
    ("usuario", "puede"),
    [(AUTOR, True), (OTRO_PROFESIONAL, True), (ENCARGADA, True), (DIRECTORA, False)],
)
def test_la_directora_no_ve_el_historial_clinico(sesion, usuario, puede):
    assert puede_ver_ficha(sesion, usuario, residente_id=1) is puede


@pytest.mark.parametrize(
    ("usuario", "puede"),
    [(AUTOR, True), (ENCARGADA, True), (OTRO_PROFESIONAL, False), (DIRECTORA, False)],
)
def test_editan_un_borrador_su_autor_y_la_encargada(usuario, puede):
    assert puede_editar_atencion(usuario, atencion(EstadoAtencion.BORRADOR)) is puede


@pytest.mark.parametrize(
    ("usuario", "puede"),
    [(AUTOR, True), (ENCARGADA, False), (OTRO_PROFESIONAL, False), (DIRECTORA, False)],
)
def test_firma_solo_el_profesional_autor(usuario, puede):
    assert puede_firmar(usuario, atencion(EstadoAtencion.BORRADOR)) is puede


@pytest.mark.parametrize("usuario", [AUTOR, ENCARGADA])
def test_una_atencion_firmada_no_se_edita_ni_se_vuelve_a_firmar(usuario):
    firmada = atencion(EstadoAtencion.FIRMADA)

    assert not puede_editar_atencion(usuario, firmada)
    assert not puede_firmar(usuario, firmada)


def test_un_usuario_profesional_sin_profesional_no_es_autor_de_nada():
    sin_profesional = UsuarioWeb(usuario="incompleto", rol=Rol.PROFESIONAL, profesional_id=None)
    huerfana = Atencion(residente_id=1, origen=OrigenAtencion.HISTORICO, estado="borrador")

    assert not puede_firmar(sin_profesional, huerfana)
