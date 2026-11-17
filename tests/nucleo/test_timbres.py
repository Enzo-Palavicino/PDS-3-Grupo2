import pytest
from sqlalchemy import select

from app.modelos import EventoAuditoria, Rol, UsuarioWeb
from app.nucleo.timbres import (
    MIME_SVG,
    TAMANO_MAXIMO_BYTES,
    TimbreNoValido,
    guardar_timbre,
    timbre_de,
    timbre_generado,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 32


@pytest.fixture
def usuario(sesion, profesional) -> UsuarioWeb:
    usuario = UsuarioWeb(
        usuario="pediatra", rol=Rol.PROFESIONAL, profesional_id=profesional.id, hash_password="x"
    )
    sesion.add(usuario)
    sesion.commit()
    return usuario


@pytest.mark.parametrize(("contenido", "mime"), [(PNG, "image/png"), (JPG, "image/jpeg")])
def test_guarda_un_timbre_png_o_jpg(sesion, profesional, usuario, contenido, mime):
    guardar_timbre(sesion, profesional, contenido, usuario)
    sesion.commit()

    assert timbre_de(profesional) == (contenido, mime)
    [evento] = sesion.scalars(
        select(EventoAuditoria).where(EventoAuditoria.accion == "timbre_subido")
    )
    assert evento.detalle == {"mime": mime, "tamano_bytes": len(contenido)}


@pytest.mark.parametrize(
    ("contenido", "mensaje"),
    [
        (b"", "vacío"),
        (b"<svg onload='alert(1)'></svg>", "PNG o JPG"),
        (b"GIF89a" + b"\x00" * 10, "PNG o JPG"),
        (PNG + b"\x00" * TAMANO_MAXIMO_BYTES, "1 MB"),
    ],
)
def test_rechaza_lo_que_no_es_un_timbre_valido(sesion, profesional, usuario, contenido, mensaje):
    with pytest.raises(TimbreNoValido, match=mensaje):
        guardar_timbre(sesion, profesional, contenido, usuario)

    assert profesional.timbre_imagen is None


def test_sin_imagen_se_genera_un_timbre_con_sus_datos(profesional):
    profesional.registro = "SIS-90001"

    contenido, mime = timbre_de(profesional)

    assert mime == MIME_SVG
    svg = contenido.decode()
    assert "Profesional de prueba" in svg
    assert "Pediatría" in svg
    assert "Registro SIS-90001" in svg


def test_el_timbre_generado_escapa_el_texto(profesional):
    profesional.nombre = 'Ana "<b>" & <script>alert(1)</script>'

    svg = timbre_generado(profesional)

    assert "<script>" not in svg
    assert "&lt;script&gt;" in svg
    assert 'aria-label="Timbre de Ana &quot;&lt;b&gt;&quot; &amp; ' in svg
