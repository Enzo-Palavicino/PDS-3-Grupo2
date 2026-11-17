from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier

import pytest
from sqlalchemy import func, select

from app.modelos import (
    Adjunto,
    Antecedente,
    Atencion,
    Control,
    DocumentoHistorico,
    EstadoDocumento,
    EstadoTratamiento,
    EventoAuditoria,
    Medicion,
    Tratamiento,
    UsuarioWeb,
)
from app.nucleo.atenciones import ErrorDeAtencion, incorporar_a_ficha
from app.nucleo.digitalizacion import procesar_documento
from app.nucleo.revision_documentos import (
    DocumentoDuplicado,
    DocumentoNoRevisable,
    descartar_documento,
    verificar_documento,
)
from tests.nucleo.test_digitalizacion import CAMPOS, lector


@pytest.fixture
def pendiente(sesion, crear_documento):
    documento = crear_documento()
    procesar_documento(sesion, documento.id, lector())
    return documento


@pytest.fixture
def encargada(sesion, pendiente):
    usuario = sesion.get(UsuarioWeb, pendiente.subido_por)
    sesion.commit()
    return usuario


def test_verifica_incorpora_y_conserva_evidencia_y_fechas(sesion, pendiente, encargada):
    original = sesion.get(Adjunto, pendiente.adjunto_id).contenido
    campos_ia = pendiente.campos.copy()
    campos = CAMPOS | {
        "alergias": [{"valor": "Látex", "fragmento": None}],
        "vacunas": [{"valor": "Influenza", "fragmento": None}],
        "hospitalizaciones": [{"valor": "Julio 2026", "fragmento": None}],
        "mediciones": {"peso_kg": 9.9, "talla_cm": 74},
        "indicaciones_farmacologicas": [{
            "medicamento": "Ficticio A", "fecha_inicio": "2026-08-12", "fecha_termino": "2026-08-17",
        }],
    }

    atencion = verificar_documento(sesion, pendiente.id, encargada, campos, "Dra. Ana Ejemplo", True)
    sesion.commit()

    assert atencion.origen == "historico" and atencion.estado == "firmada"
    assert atencion.fecha_atencion == date(2026, 8, 12)
    assert atencion.verificada_en.date() != atencion.fecha_atencion
    assert atencion.verificada_por == encargada.id
    assert atencion.profesional_texto == "Dra. Ana Ejemplo" and atencion.profesional_id is None
    assert atencion.firmada_por is None and atencion.hash_firma is None and atencion.firmada_en is None
    assert "mediciones" in atencion.campos_editados
    assert pendiente.estado == EstadoDocumento.INCORPORADO
    assert pendiente.campos == campos_ia
    assert pendiente.atencion_id == atencion.id
    assert sesion.get(Adjunto, pendiente.adjunto_id).contenido == original
    assert sesion.get(Adjunto, pendiente.adjunto_id).atencion_id == atencion.id
    assert sesion.scalar(select(Tratamiento)).estado == EstadoTratamiento.TERMINADO
    assert sesion.scalar(select(Control)).fecha == date(2026, 8, 26)
    assert sesion.scalar(select(Medicion)).peso_kg == 9.9
    assert sesion.scalar(select(func.count()).select_from(Antecedente)) == 3
    incorporar_a_ficha(sesion, atencion)
    sesion.flush()
    assert sesion.scalar(select(func.count()).select_from(Antecedente)) == 3
    auditoria = sesion.scalar(select(EventoAuditoria).where(
        EventoAuditoria.accion == "documento_incorporado"
    ))
    assert auditoria.actor_id == str(encargada.id)
    assert set(auditoria.detalle) == {"atencion_id"}


def test_admite_fecha_desconocida_y_correccion_de_fecha(sesion, pendiente, encargada):
    campos = CAMPOS | {"fecha_atencion": None, "proximo_control": {"descripcion": "en dos semanas"}}
    atencion = verificar_documento(sesion, pendiente.id, encargada, campos, "No consta", True)
    assert atencion.fecha_atencion is None
    assert pendiente.fecha_original is None
    assert sesion.scalar(select(Control)).fecha is None


@pytest.mark.parametrize("campos", [
    CAMPOS | {"fecha_atencion": {"valor": "2026-02-30"}},
    CAMPOS | {"hora_atencion": {"valor": "25:99"}},
    CAMPOS | {"mediciones": {"peso_kg": -1}},
    CAMPOS | {"mediciones": {"peso_kg": 0}},
    CAMPOS | {"mediciones": {"peso_kg": "9.8"}},
    CAMPOS | {"mediciones": {"peso_kg": float("inf")}},
    CAMPOS | {"estado": "firmada"},
    CAMPOS | {"indicaciones_farmacologicas": [{"dosis": "sin medicamento"}]},
    CAMPOS | {"indicaciones_farmacologicas": [{
        "medicamento": "ficticio", "fecha_inicio": "2026-08-20", "fecha_termino": "2026-08-17",
    }]},
])
def test_rechaza_campos_invalidos_sin_crear_atencion(sesion, pendiente, encargada, campos):
    with pytest.raises(ErrorDeAtencion):
        verificar_documento(sesion, pendiente.id, encargada, campos, "Ficticia", True)
    assert sesion.scalar(select(Atencion)) is None
    assert pendiente.estado == EstadoDocumento.POR_REVISAR


def test_exige_revision_y_profesional(sesion, pendiente, encargada):
    for profesional, verificado in [("", True), ("Dra. Ejemplo", False)]:
        with pytest.raises(ErrorDeAtencion):
            verificar_documento(sesion, pendiente.id, encargada, CAMPOS, profesional, verificado)
    assert sesion.scalar(select(Atencion)) is None


def test_acepta_mediciones_positivas_sin_un_minimo_inventado(sesion, pendiente, encargada):
    campos = CAMPOS | {"mediciones": {"peso_kg": 0.0001, "talla_cm": 0.0001}}
    atencion = verificar_documento(sesion, pendiente.id, encargada, campos, "No consta en el original", True)
    assert atencion.campos["mediciones"]["peso_kg"] == 0.0001


@pytest.mark.parametrize("estado", ["subido", "leido", "error", "descartado", "incorporado"])
def test_solo_se_verifican_documentos_por_revisar(sesion, pendiente, encargada, estado):
    pendiente.estado = estado
    sesion.commit()
    with pytest.raises(DocumentoNoRevisable):
        verificar_documento(sesion, pendiente.id, encargada, CAMPOS, "Dra. Ejemplo", True)
    assert sesion.scalar(select(Atencion)) is None


def test_descarte_admite_error_pero_no_interrumpe_procesamiento(sesion, pendiente, encargada):
    for estado in (EstadoDocumento.SUBIDO, EstadoDocumento.LEIDO):
        pendiente.estado = estado
        sesion.commit()
        with pytest.raises(DocumentoNoRevisable):
            descartar_documento(sesion, pendiente.id, encargada, "motivo")
    pendiente.estado = EstadoDocumento.ERROR
    sesion.commit()
    descartar_documento(sesion, pendiente.id, encargada, "No se pudo leer")
    assert pendiente.estado == EstadoDocumento.DESCARTADO


def test_recalcula_duplicados_al_incorporar(sesion, pendiente, encargada):
    duplicado = Atencion(
        residente_id=2, origen="web", estado="firmada", fecha_atencion=date(2026, 8, 12),
        campos={"diagnosticos": CAMPOS["diagnosticos"]},
    )
    sesion.add(duplicado)
    sesion.commit()
    assert pendiente.posibles_duplicados == []

    with pytest.raises(DocumentoDuplicado) as error:
        verificar_documento(sesion, pendiente.id, encargada, CAMPOS, "Dra. Ejemplo", True)
    assert error.value.ids == [duplicado.id]
    assert pendiente.atencion_id is None

    campos_corregidos = CAMPOS | {"fecha_atencion": {"valor": "2026-08-13"}}
    atencion = verificar_documento(sesion, pendiente.id, encargada, campos_corregidos, "Dra. Ejemplo", True)
    assert atencion.id != duplicado.id
    assert pendiente.posibles_duplicados == []
    assert pendiente.fecha_original == date(2026, 8, 13)


def test_repetir_incorporacion_o_descartar_incorporado_da_conflicto(sesion, pendiente, encargada):
    verificar_documento(sesion, pendiente.id, encargada, CAMPOS, "Dra. Ejemplo", True)
    sesion.commit()
    with pytest.raises(DocumentoNoRevisable):
        verificar_documento(sesion, pendiente.id, encargada, CAMPOS, "Dra. Ejemplo", True)
    with pytest.raises(DocumentoNoRevisable):
        descartar_documento(sesion, pendiente.id, encargada, "motivo")
    assert sesion.scalar(select(func.count()).select_from(Atencion)) == 1


def test_descarte_exige_motivo_no_borra_y_no_loguea_el_motivo(sesion, pendiente, encargada):
    with pytest.raises(ErrorDeAtencion):
        descartar_documento(sesion, pendiente.id, encargada, " ")
    descartar_documento(sesion, pendiente.id, encargada, "Motivo clínico ficticio reservado")
    sesion.commit()
    assert pendiente.estado == EstadoDocumento.DESCARTADO
    assert pendiente.motivo_descarte == "Motivo clínico ficticio reservado"
    assert sesion.get(Adjunto, pendiente.adjunto_id) is not None
    evento = sesion.scalar(select(EventoAuditoria).where(EventoAuditoria.accion == "documento_descartado"))
    assert evento.detalle is None
    assert sesion.scalar(select(Atencion)) is None


def test_solo_encargada_activa_puede_incorporar_o_descartar(sesion, pendiente, encargada):
    for nombre in ("pediatra", "directora"):
        usuario = sesion.scalar(select(UsuarioWeb).where(UsuarioWeb.usuario == nombre))
        with pytest.raises(PermissionError):
            verificar_documento(sesion, pendiente.id, usuario, CAMPOS, "Dra. Ejemplo", True)
        with pytest.raises(PermissionError):
            descartar_documento(sesion, pendiente.id, usuario, "motivo")
    encargada.activo = False
    with pytest.raises(PermissionError):
        verificar_documento(sesion, pendiente.id, encargada, CAMPOS, "Dra. Ejemplo", True)


def test_fallo_de_incorporacion_revierte_toda_la_operacion(sesion, pendiente, encargada, monkeypatch):
    def fallar(*args):
        raise RuntimeError("fallo de prueba")
    monkeypatch.setattr("app.nucleo.revision_documentos.incorporar_a_ficha", fallar)
    with pytest.raises(RuntimeError):
        verificar_documento(sesion, pendiente.id, encargada, CAMPOS, "Dra. Ejemplo", True)
    sesion.rollback()
    sesion.refresh(pendiente)
    assert pendiente.estado == EstadoDocumento.POR_REVISAR
    assert pendiente.atencion_id is None
    assert sesion.scalar(select(Atencion)) is None
    assert sesion.scalar(select(EventoAuditoria).where(EventoAuditoria.accion == "atencion_creada")) is None


def test_dos_verificaciones_simultaneas_no_duplican_la_atencion(
    sesion, pendiente, encargada, fabrica_de_sesiones
):
    documento_id, usuario_id = pendiente.id, encargada.id
    sesion.commit()
    inicio = Barrier(2)
    def intentar():
        inicio.wait(timeout=5)
        try:
            with fabrica_de_sesiones.begin() as otra:
                verificar_documento(
                    otra, documento_id, otra.get(UsuarioWeb, usuario_id), CAMPOS, "Dra. Ejemplo", True,
                )
            return "incorporado"
        except DocumentoNoRevisable:
            return "conflicto"
    with ThreadPoolExecutor(max_workers=2) as hilos:
        resultados = list(hilos.map(lambda _: intentar(), range(2)))
    assert sorted(resultados) == ["conflicto", "incorporado"]
    assert sesion.scalar(select(func.count()).select_from(Atencion)) == 1
    sesion.refresh(pendiente)
    assert sesion.get(DocumentoHistorico, documento_id).atencion_id is not None
