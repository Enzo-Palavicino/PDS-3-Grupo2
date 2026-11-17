import re
from datetime import date

import pytest
from sqlalchemy import select

from app.modelos import (
    Adjunto,
    DocumentoHistorico,
    EventoAuditoria,
    OrigenAtencion,
    Residente,
    TipoAdjunto,
    UsuarioWeb,
)
from app.nucleo.atenciones import crear_atencion, firmar_atencion
from app.web.fichas import edad
from tests.web.conftest import PASSWORD
from tests.web.test_web_adjuntos import PNG

CAMPOS = {
    "fecha_atencion": {"valor": "2026-11-16", "fragmento": None},
    "motivo": {"valor": "Control por tos", "fragmento": None},
    "diagnosticos": [{"valor": "bronquitis obstructiva", "fragmento": None}],
    "indicaciones_farmacologicas": [{"medicamento": "salbutamol", "dosis": "dos puff"}],
    "proximo_control": {"fecha": "2026-11-30", "descripcion": "Control broncopulmonar"},
    "alergias": [{"valor": "penicilina", "fragmento": None}],
    "mediciones": {"peso_kg": 8.4, "talla_cm": 71.0, "fragmento": None},
}


def usuario(sesion, nombre: str) -> UsuarioWeb:
    return sesion.scalar(select(UsuarioWeb).where(UsuarioWeb.usuario == nombre))


@pytest.fixture
def emilia(sesion, datos_demo) -> Residente:
    """Emilia Soto (RES-02): asignada a la pediatra y al nutricionista, no al kinesiólogo."""
    residente = sesion.scalar(select(Residente).where(Residente.codigo == "RES-02"))
    sesion.commit()
    return residente


@pytest.fixture
def firmada(sesion, emilia):
    """Una atención web de la pediatra, firmada: sus datos ya pasaron a la ficha."""
    autor = usuario(sesion, "pediatra")
    atencion = crear_atencion(sesion, emilia.id, autor, CAMPOS, OrigenAtencion.WEB)
    firmar_atencion(sesion, atencion, autor, PASSWORD)
    sesion.commit()
    return atencion


@pytest.fixture
def sin_firmar(sesion, emilia):
    """Una atención de la pediatra que sigue en borrador, con un diagnóstico propio."""
    campos = CAMPOS | {
        "motivo": {"valor": "Consulta sin firmar", "fragmento": None},
        "alergias": [{"valor": "látex", "fragmento": None}],
    }
    atencion = crear_atencion(sesion, emilia.id, usuario(sesion, "pediatra"), campos, "web")
    sesion.commit()
    return atencion


def seccion(html: str, id_: str) -> str:
    """El HTML de la sección con aria-labelledby=id_."""
    patron = rf'<section[^>]*aria-labelledby="{id_}".*?</section>'
    return re.search(patron, html, re.DOTALL).group(0)


def eventos_de_ficha(sesion) -> list[EventoAuditoria]:
    sesion.commit()
    eventos = list(
        sesion.scalars(select(EventoAuditoria).where(EventoAuditoria.accion == "ficha_leida"))
    )
    sesion.commit()
    return eventos


# Permisos y auditoría


@pytest.mark.parametrize("cuenta", ["encargada_salud", "pediatra", "nutricionista"])
def test_quien_tiene_acceso_abre_la_ficha(cliente, entrar, emilia, cuenta):
    entrar(cuenta)

    respuesta = cliente.get(f"/residentes/{emilia.id}")

    assert respuesta.status_code == 200
    assert "Emilia Soto" in respuesta.text
    assert "RES-02" in respuesta.text


@pytest.mark.parametrize("cuenta", ["kinesiologo", "directora"])
def test_sin_permiso_sobre_la_ficha_da_403_y_no_queda_como_leida(
    cliente, entrar, sesion, emilia, cuenta
):
    entrar(cuenta)

    assert cliente.get(f"/residentes/{emilia.id}").status_code == 403
    assert eventos_de_ficha(sesion) == []


def test_un_residente_que_no_existe_da_403(cliente, entrar):
    entrar("encargada_salud")

    assert cliente.get("/residentes/999").status_code == 403


def test_cada_apertura_queda_en_la_auditoria(cliente, entrar, sesion, emilia):
    entrar("pediatra")

    cliente.get(f"/residentes/{emilia.id}")
    cliente.get(f"/residentes/{emilia.id}")

    eventos = eventos_de_ficha(sesion)
    assert len(eventos) == 2
    assert {(e.entidad, e.entidad_id, e.actor_id) for e in eventos} == {
        ("residente", str(emilia.id), str(usuario(sesion, "pediatra").id))
    }


# Contenido


def test_muestra_los_datos_del_residente(cliente, entrar, emilia):
    entrar("encargada_salud")

    datos = seccion(cliente.get(f"/residentes/{emilia.id}").text, "datos-residente")

    assert "RES-02" in datos
    assert "Sala cuna menor" in datos
    assert "Activo" in datos
    assert re.search(r"\d+ meses", datos)


def test_el_resumen_trae_lo_que_dejo_la_atencion_firmada(cliente, entrar, emilia, firmada):
    entrar("pediatra")

    resumen = seccion(cliente.get(f"/residentes/{emilia.id}").text, "resumen")

    assert "penicilina" in resumen
    assert "salbutamol" in resumen
    assert "8.4 kg" in resumen
    assert "71.0 cm" in resumen
    assert "30-11-2026" in resumen
    assert "Control broncopulmonar" in resumen


def test_el_historial_muestra_origen_profesional_y_timbre(cliente, entrar, emilia, firmada):
    entrar("pediatra")

    historial = seccion(cliente.get(f"/residentes/{emilia.id}").text, "historial")

    assert f'id="atencion-{firmada.id}"' in historial
    assert "16-11-2026" in historial
    assert "Web" in historial
    assert "Carolina Fuentes" in historial
    assert "Control por tos" in historial
    assert f"/profesionales/{firmada.profesional_id}/timbre" in historial
    assert "Integridad verificada" in historial


def test_lo_sin_firmar_va_aparte_y_nunca_como_confirmado(
    cliente, entrar, emilia, sin_firmar, crear_borrador
):
    borrador = crear_borrador("pediatra")
    entrar("pediatra")

    html = cliente.get(f"/residentes/{emilia.id}").text

    for confirmado in ("resumen", "historial"):
        assert "látex" not in seccion(html, confirmado)
        assert "Consulta sin firmar" not in seccion(html, confirmado)
    pendiente = seccion(html, "pendiente")
    assert f'href="/borradores/{borrador.id}"' in pendiente
    assert f'href="/atenciones/{sin_firmar.id}/firmar"' in pendiente
    assert "no es información confirmada" in pendiente


def test_un_profesional_solo_ve_sus_borradores_en_la_ficha(
    cliente, entrar, emilia, sin_firmar, crear_borrador
):
    borrador = crear_borrador("pediatra")
    entrar("nutricionista")  # también tiene a Emilia asignada

    pendiente = seccion(cliente.get(f"/residentes/{emilia.id}").text, "pendiente")

    assert f"/borradores/{borrador.id}" not in pendiente
    assert f"Atención #{sin_firmar.id}" not in pendiente


def test_la_encargada_ve_todo_lo_pendiente_pero_no_puede_firmar(
    cliente, entrar, emilia, sin_firmar, crear_borrador
):
    borrador = crear_borrador("pediatra")
    entrar("encargada_salud")

    pendiente = seccion(cliente.get(f"/residentes/{emilia.id}").text, "pendiente")

    assert f'href="/borradores/{borrador.id}"' in pendiente
    assert f"Atención #{sin_firmar.id}" in pendiente
    assert f"/atenciones/{sin_firmar.id}/firmar" not in pendiente


def test_lista_los_adjuntos_y_los_documentos_historicos(cliente, entrar, sesion, emilia):
    encargada = usuario(sesion, "encargada_salud")

    def adjunto(nombre, tipo):
        nuevo = Adjunto(
            residente_id=emilia.id,
            nombre_archivo=nombre,
            tipo=tipo,
            mime="image/png",
            tamano_bytes=len(PNG),
            sha256="0" * 64,
            contenido=PNG,
            subido_por=encargada.id,
        )
        sesion.add(nuevo)
        sesion.flush()
        return nuevo

    receta = adjunto("receta.png", TipoAdjunto.RECETA)
    foto = adjunto("registro-2024.png", TipoAdjunto.DOCUMENTO_HISTORICO)
    sesion.add(
        DocumentoHistorico(
            residente_id=emilia.id,
            adjunto_id=foto.id,
            tipo_documento="Ficha CESFAM",
            fecha_original=date(2024, 5, 2),
            subido_por=encargada.id,
        )
    )
    sesion.commit()
    entrar("pediatra")

    archivos = seccion(cliente.get(f"/residentes/{emilia.id}").text, "archivos")

    assert f'href="/adjuntos/{receta.id}/descargar"' in archivos
    assert "Receta" in archivos
    assert f'href="/adjuntos/{foto.id}/descargar"' in archivos
    assert "Ficha CESFAM" in archivos
    assert "02-05-2024" in archivos
    assert "Subido" in archivos
    assert archivos.count("registro-2024.png") == 1  # la foto no se repite como adjunto


def test_los_accesos_dependen_del_rol(cliente, entrar, emilia):
    nueva = f'href="/atenciones/nueva?residente_id={emilia.id}"'
    digitalizar = f'href="/digitalizacion?residente_id={emilia.id}"'

    entrar("pediatra")
    html = cliente.get(f"/residentes/{emilia.id}").text
    assert nueva in html
    assert digitalizar not in html

    # "Nueva atención" sigue a permisos.puede_registrar_atencion, que hoy incluye a la encargada.
    entrar("encargada_salud")
    assert digitalizar in cliente.get(f"/residentes/{emilia.id}").text


# Listado de fichas y enlaces


def test_un_profesional_lista_solo_las_fichas_de_sus_residentes(cliente, entrar):
    entrar("pediatra")

    html = cliente.get("/fichas").text

    assert "Tomás Rivas" in html
    assert "Emilia Soto" in html
    assert "Martina Rojas" not in html
    assert "Tomás Díaz" not in html


def test_la_encargada_lista_todas_las_fichas(cliente, entrar):
    entrar("encargada_salud")

    html = cliente.get("/fichas").text

    for nombre in ("Tomás Rivas", "Emilia Soto", "Martina Rojas", "Tomás Díaz"):
        assert nombre in html


def test_desde_la_lista_de_borradores_se_abre_la_ficha(cliente, entrar, emilia, crear_borrador):
    crear_borrador("pediatra")
    entrar("pediatra")

    assert f'href="/residentes/{emilia.id}"' in cliente.get("/borradores").text


def test_desde_residentes_la_encargada_abre_la_ficha(cliente, entrar, emilia):
    entrar("encargada_salud")
    assert f'href="/residentes/{emilia.id}"' in cliente.get("/residentes").text

    entrar("directora")  # la dirección administra residentes, pero no ve fichas
    assert f'href="/residentes/{emilia.id}"' not in cliente.get("/residentes").text


# Edad


@pytest.mark.parametrize(
    ("nacimiento", "texto"),
    [
        (date(2025, 12, 28), "10 meses"),
        (date(2026, 10, 17), "1 mes"),
        (date(2026, 11, 1), "0 meses"),
        (date(2024, 11, 18), "23 meses"),  # cumple 2 años mañana
        (date(2024, 11, 17), "2 años"),
        (date(2023, 7, 14), "3 años"),
    ],
)
def test_la_edad_se_muestra_en_meses_hasta_los_dos_anios(nacimiento, texto):
    assert edad(nacimiento, date(2026, 11, 17)) == texto


def test_el_historial_cuenta_en_singular_y_plural(cliente, entrar, sesion, emilia, firmada):
    entrar("pediatra")

    assert "1 confirmada<" in seccion(cliente.get(f"/residentes/{emilia.id}").text, "historial")
