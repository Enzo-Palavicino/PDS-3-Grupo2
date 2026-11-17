import hashlib
from datetime import date

import pytest
from sqlalchemy import func, select
from starlette.datastructures import FormData

from app.modelos import Adjunto, Atencion, EstadoDocumento, UsuarioWeb
from app.nucleo.digitalizacion import procesar_documento
from app.nucleo.documentos import subir_documento
from app.web.formulario_documentos import campos_del_formulario, filas_de_edicion
from tests.nucleo.test_digitalizacion import CAMPOS, TEXTO, lector
from tests.web.test_web_adjuntos import PNG


@pytest.fixture
def documento(sesion, datos_demo):
    usuario = sesion.scalar(select(UsuarioWeb).where(UsuarioWeb.usuario == "encargada_salud"))
    documento = subir_documento(sesion, 2, PNG, "original.png", "Registro", usuario, date(2026, 8, 12))
    sesion.commit()
    procesar_documento(sesion, documento.id, lector(TEXTO + " Observaciones [ilegible]."))
    return documento


def formulario(campos, **cambios):
    datos = {"profesional_texto": "Dra. Ana Ejemplo", "verificado": "true"}
    for seccion in filas_de_edicion(campos):
        for nombre, _, _ in seccion["columnas"]:
            datos[f'{seccion["clave"]}.{nombre}'] = [
                str(fila["valores"][nombre]) for fila in seccion["filas"]
            ]
    return datos | cambios


def test_original_campos_editables_fragmentos_y_advertencias(
    cliente, entrar, documento, acciones
):
    entrar("encargada_salud")
    respuesta = cliente.get(f"/digitalizacion/{documento.id}")
    assert respuesta.status_code == 200
    assert f'src="/digitalizacion/{documento.id}/original"' in respuesta.text
    assert 'name="mediciones.peso_kg"' in respuesta.text
    assert 'name="diagnosticos.valor"' in respuesta.text
    assert "Peso 9,8 kg" in respuesta.text
    assert "[ilegible]" in respuesta.text and "dig-ilegible" in respuesta.text
    assert "Verificado contra el original" in respuesta.text
    assert respuesta.headers["cache-control"] == "no-store, private"
    assert acciones()[-1] == "documento_leido"
    original = cliente.get(f"/digitalizacion/{documento.id}/original")
    assert original.content == PNG and original.headers["content-type"] == "image/png"
    assert original.headers["cache-control"] == "no-store, private"


@pytest.mark.parametrize("nombre", ["directora", "pediatra", "nutricionista"])
def test_solo_encargada_accede_a_revision_original_y_acciones(cliente, entrar, csrf, documento, nombre):
    entrar(nombre)
    token = csrf("/cuenta/password")
    for sufijo in ("", "/original"):
        assert cliente.get(f"/digitalizacion/{documento.id}{sufijo}").status_code == 403
    for accion in ("incorporar", "descartar"):
        assert cliente.post(f"/digitalizacion/{documento.id}/{accion}", data={"csrf": token}).status_code == 403


def test_incorpora_ediciones_y_muestra_origen_verificador_y_original_en_ficha(
    cliente, entrar, csrf, documento, sesion
):
    entrar("encargada_salud")
    datos = formulario(documento.campos, csrf=csrf(), **{"mediciones.peso_kg": "10.2"})
    respuesta = cliente.post(f"/digitalizacion/{documento.id}/incorporar", data=datos, follow_redirects=False)
    assert respuesta.status_code == 303
    sesion.refresh(documento)
    atencion = sesion.get(Atencion, documento.atencion_id)
    assert atencion.campos["mediciones"]["peso_kg"] == 10.2
    assert atencion.campos["mediciones"]["fragmento"] is None
    assert documento.campos["mediciones"]["peso_kg"] == 9.8
    assert "mediciones" in atencion.campos_editados
    sesion.commit()

    ficha = cliente.get(respuesta.headers["location"])
    assert ficha.status_code == 200
    assert "Digitalizado" in ficha.text
    assert "1 confirmada" in ficha.text
    assert "Dra. Ana Ejemplo" in ficha.text
    assert "por encargada_salud" in ficha.text
    assert "12-08-2026" in ficha.text
    assert f'/adjuntos/{documento.adjunto_id}/descargar' in ficha.text
    assert "Ver documento original" in ficha.text
    assert cliente.post(f"/digitalizacion/{documento.id}/incorporar", data=datos).status_code == 409


def test_csrf_confirmacion_y_errores_conservan_valores(cliente, entrar, csrf, documento, sesion):
    entrar("encargada_salud")
    datos = formulario(documento.campos)
    assert cliente.post(f"/digitalizacion/{documento.id}/incorporar", data=datos).status_code == 403
    datos.update(csrf=csrf(), verificado="false")
    respuesta = cliente.post(f"/digitalizacion/{documento.id}/incorporar", data=datos)
    assert respuesta.status_code == 400 and "Debes verificar" in respuesta.text
    datos.update(verificado="true")
    datos["mediciones.peso_kg"] = "-4"
    respuesta = cliente.post(f"/digitalizacion/{documento.id}/incorporar", data=datos)
    assert respuesta.status_code == 400
    assert 'value="-4"' in respuesta.text
    assert sesion.scalar(select(Atencion)) is None


def test_duplicados_se_muestran_y_bloquean_incorporacion(cliente, entrar, csrf, documento, sesion):
    duplicado = Atencion(
        residente_id=2, origen="web", estado="firmada", fecha_atencion=date(2026, 8, 12),
        campos={"diagnosticos": CAMPOS["diagnosticos"]},
    )
    sesion.add(duplicado)
    sesion.commit()
    entrar("encargada_salud")
    datos = formulario(documento.campos, csrf=csrf())
    vista = cliente.get(f"/digitalizacion/{documento.id}")
    assert "Posibles duplicados" in vista.text
    assert "La incorporación está bloqueada" in vista.text
    respuesta = cliente.post(f"/digitalizacion/{documento.id}/incorporar", data=datos)
    assert respuesta.status_code == 409
    assert "Posibles duplicados" in respuesta.text
    assert f"#atencion-{duplicado.id}" in respuesta.text
    assert 'name="confirmar_duplicados"' not in respuesta.text
    datos["confirmar_duplicados"] = "true"
    assert cliente.post(f"/digitalizacion/{documento.id}/incorporar", data=datos).status_code == 409
    assert sesion.scalar(select(func.count()).select_from(Atencion)) == 1


def test_descarta_con_motivo_y_no_admite_incorporar_despues(cliente, entrar, csrf, documento, sesion):
    entrar("encargada_salud")
    token = csrf()
    url = f"/digitalizacion/{documento.id}/descartar"
    assert cliente.post(url, data={"motivo": "sin csrf"}).status_code == 403
    assert cliente.post(url, data={"csrf": token, "motivo": " "}).status_code == 400
    respuesta = cliente.post(url, data={"csrf": token, "motivo": "Documento repetido"})
    assert respuesta.status_code == 200 and "Documento repetido" in respuesta.text
    sesion.refresh(documento)
    assert documento.estado == EstadoDocumento.DESCARTADO
    sesion.commit()
    assert cliente.post(
        f"/digitalizacion/{documento.id}/incorporar", data=formulario(documento.campos, csrf=token),
    ).status_code == 409
    assert sesion.scalar(select(func.count()).select_from(Atencion)) == 0


def test_vista_previa_pdf_no_modifica_original(cliente, entrar, documento, sesion, crear_pdf):
    pdf = crear_pdf()
    adjunto = sesion.get(Adjunto, documento.adjunto_id)
    adjunto.contenido = pdf
    adjunto.mime = "application/pdf"
    adjunto.tamano_bytes = len(pdf)
    adjunto.sha256 = hashlib.sha256(pdf).hexdigest()
    sesion.commit()
    entrar("encargada_salud")

    respuesta = cliente.get(f"/digitalizacion/{documento.id}/original")

    assert respuesta.status_code == 200 and respuesta.content.startswith(b"\x89PNG")
    assert sesion.get(Adjunto, documento.adjunto_id).contenido == pdf


def test_enlaces_de_revision_en_seguimiento_y_ficha(cliente, entrar, documento):
    entrar("encargada_salud")
    for url in ("/digitalizacion?residente_id=2", "/residentes/2"):
        respuesta = cliente.get(url)
        assert f'href="/digitalizacion/{documento.id}"' in respuesta.text
    assert cliente.get("/digitalizacion/999999").status_code == 404


def test_quitar_y_agregar_filas_no_reasigna_fragmentos():
    campos = CAMPOS | {"diagnosticos": [
        {"valor": "Primero", "fragmento": "Fragmento primero"},
        {"valor": "Segundo", "fragmento": "Fragmento segundo"},
    ]}
    datos = formulario(campos, **{"diagnosticos.valor": ["", "Segundo", "Nuevo"]})
    pares = [
        (nombre, valor)
        for nombre, valores in datos.items()
        for valor in (valores if isinstance(valores, list) else [valores])
    ]
    form = FormData(pares)
    revisados = campos_del_formulario(form, campos)
    assert revisados["diagnosticos"] == [
        {"valor": "Segundo", "fragmento": "Fragmento segundo"},
        {"valor": "Nuevo", "fragmento": None},
    ]
    filas = next(s["filas"] for s in filas_de_edicion(campos, form) if s["clave"] == "diagnosticos")
    assert [fila["valores"]["valor"] for fila in filas] == ["", "Segundo", "Nuevo"]
    assert [fila["fragmento"] for fila in filas] == ["Fragmento primero", "Fragmento segundo", None]


def test_campos_incompletos_no_producen_perdidas_silenciosas():
    with pytest.raises(ValueError, match="solo dato"):
        campos_del_formulario(FormData(), CAMPOS)
