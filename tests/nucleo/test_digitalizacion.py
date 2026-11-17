import json
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.modelos import (
    Adjunto,
    Atencion,
    DocumentoHistorico,
    EstadoAtencion,
    EstadoDocumento,
    EventoAuditoria,
    TipoActor,
)
from app.nucleo.digitalizacion import posibles_duplicados, procesar_documento
from app.nucleo.extraccion import ErrorExtraccion
from app.nucleo.worker import Worker
from app.proveedores.llm.fake import ProveedorLLMFake

TEXTO = (
    "Emilia Soto. Fecha 12/08/2026. Diagnóstico control sano. "
    "Peso 9,8 kg. Próximo control en dos semanas."
)
CAMPOS = {
    "fecha_atencion": {"valor": "2026-08-12", "fragmento": "Fecha 12/08/2026"},
    "diagnosticos": [{"valor": "control sano", "fragmento": "Diagnóstico control sano"}],
    "mediciones": {"peso_kg": 9.8, "fragmento": "Peso 9,8 kg"},
    "proximo_control": {
        "fecha": "2026-08-26", "descripcion": "en dos semanas",
        "fragmento": "Próximo control en dos semanas",
    },
}


def lector(texto=TEXTO, campos=None):
    return ProveedorLLMFake(
        [json.dumps(CAMPOS if campos is None else campos)], lecturas=[texto]
    )


def test_guarda_lectura_y_extraccion_sin_incorporar(sesion, crear_documento):
    documento = crear_documento()
    llm = lector()

    procesar_documento(sesion, documento.id, llm)

    assert documento.estado == EstadoDocumento.POR_REVISAR
    assert documento.texto_leido == TEXTO
    assert documento.modelo_lectura == "fake"
    assert documento.salida == CAMPOS
    assert documento.campos["mediciones"]["peso_kg"] == 9.8
    assert documento.campos["proximo_control"]["fecha"] == "2026-08-26"
    assert "[RES-02]" in documento.entrada_seudonimizada
    assert "Emilia Soto" not in documento.entrada_seudonimizada
    assert "2026-08-12 12:00" in documento.entrada_seudonimizada
    assert documento.atencion_id is None
    assert sesion.scalar(select(Atencion)) is None


def test_la_fecha_confirmada_prevalece_y_la_diferencia_se_advierte(sesion, crear_documento):
    documento = crear_documento()
    campos = CAMPOS | {
        "fecha_atencion": {"valor": "2016-08-12", "fragmento": "Fecha 12/08/2016"},
    }
    procesar_documento(sesion, documento.id, lector(TEXTO.replace("2026", "2016"), campos))

    assert documento.fecha_original == date(2026, 8, 12)
    assert documento.campos["fecha_atencion"]["valor"] == "2026-08-12"
    assert any(a["campo"] == "fecha_atencion" for a in documento.ambiguedades)


def test_el_residente_nunca_lo_cambia_la_ia(sesion, crear_documento):
    documento = crear_documento()

    procesar_documento(sesion, documento.id, lector(TEXTO.replace("Emilia Soto", "Martina Rojas")))

    assert documento.residente_id == 2
    assert documento.campos["residente"]["valor"] == "RES-02"
    assert any(a["campo"] == "residente" for a in documento.ambiguedades)


def test_sin_fecha_original_no_guarda_fechas_relativas_inventadas(sesion, crear_documento):
    documento = crear_documento(fecha=None)
    campos = CAMPOS | {"fecha_atencion": {"valor": "2026-11-17", "fragmento": "Hoy"}}

    procesar_documento(sesion, documento.id, lector(TEXTO.replace("Fecha 12/08/2026", "Hoy"), campos))

    assert documento.fecha_original is None
    assert documento.campos["fecha_atencion"] is None
    assert documento.campos["proximo_control"]["fecha"] is None
    assert documento.campos["proximo_control"]["descripcion"] == "en dos semanas"
    assert "No hay fecha de referencia" in documento.entrada_seudonimizada


def test_conserva_fechas_absolutas_aunque_la_fecha_original_no_se_conozca(
    sesion, crear_documento
):
    documento = crear_documento(fecha=None)
    procesar_documento(sesion, documento.id, lector())
    assert documento.campos["fecha_atencion"]["valor"] == "2026-08-12"
    assert documento.campos["proximo_control"]["fecha"] is None


def test_advierte_ilegibilidad(sesion, crear_documento):
    documento = crear_documento()
    procesar_documento(sesion, documento.id, lector(TEXTO + " Observación [ilegible]."))
    assert any(a["campo"] == "documento" for a in documento.ambiguedades)


def test_un_reintento_de_extraccion_reutiliza_la_lectura(sesion, crear_documento):
    documento = crear_documento()
    llm = ProveedorLLMFake(["no json", "no json", json.dumps(CAMPOS)], lecturas=[TEXTO])
    with pytest.raises(ErrorExtraccion):
        procesar_documento(sesion, documento.id, llm)
    sesion.rollback()
    sesion.refresh(documento)
    assert documento.estado == EstadoDocumento.LEIDO
    assert documento.texto_leido == TEXTO

    procesar_documento(sesion, documento.id, llm)
    procesar_documento(sesion, documento.id, llm)

    assert documento.estado == EstadoDocumento.POR_REVISAR
    assert len(llm.imagenes) == 1
    assert len(llm.entradas) == 3


def test_pdf_se_renderiza_y_el_original_se_conserva(sesion, crear_documento, crear_pdf):
    pdf = crear_pdf()
    documento = crear_documento(contenido=pdf)
    llm = lector()

    procesar_documento(sesion, documento.id, llm)

    assert llm.imagenes[0][1] == "image/png"
    assert llm.imagenes[0][0].startswith(b"\x89PNG")
    assert sesion.get(Adjunto, documento.adjunto_id).contenido == pdf
    assert documento.estado == EstadoDocumento.POR_REVISAR


def test_duplicados_exigen_residente_fecha_y_diagnostico_confirmado(sesion, crear_documento):
    documento = crear_documento()
    filas = []
    for residente_id, fecha, estado, diagnostico in [
        (2, date(2026, 8, 12), EstadoAtencion.FIRMADA, "CONTROL  SÁNO"),
        (3, date(2026, 8, 12), EstadoAtencion.FIRMADA, "control sano"),
        (2, date(2026, 8, 13), EstadoAtencion.FIRMADA, "control sano"),
        (2, date(2026, 8, 12), EstadoAtencion.BORRADOR, "control sano"),
        (2, date(2026, 8, 12), EstadoAtencion.FIRMADA, "otro diagnóstico"),
    ]:
        atencion = Atencion(
            residente_id=residente_id, fecha_atencion=fecha, origen="web", estado=estado,
            campos={"diagnosticos": [{"valor": diagnostico}]},
        )
        sesion.add(atencion)
        filas.append(atencion)
    sesion.commit()

    procesar_documento(sesion, documento.id, lector())

    assert documento.posibles_duplicados == [filas[0].id]
    assert posibles_duplicados(sesion, 2, date(2026, 8, 12), []) == []
    assert posibles_duplicados(sesion, 2, None, ["control sano"]) == []


def test_el_worker_funciona_sin_canales(crear_documento, fabrica_de_sesiones, contexto):
    documento = crear_documento()
    contexto.adaptadores = {}
    contexto.llm = lector()

    assert Worker(fabrica_de_sesiones, contexto).procesar_pendientes() == 1
    with fabrica_de_sesiones() as sesion:
        assert sesion.get(DocumentoHistorico, documento.id).estado == EstadoDocumento.POR_REVISAR


def test_reintentos_exactos_y_error_al_tercer_fallo_sin_filtrar_contenido(
    crear_documento, fabrica_de_sesiones, contexto, monkeypatch, caplog
):
    class Fallido(ProveedorLLMFake):
        def leer_imagen(self, contenido, mime):
            raise RuntimeError("CONTENIDO_CLINICO_QUE_NO_DEBE_LOGUEARSE")

    documento = crear_documento()
    contexto.llm = Fallido()
    worker = Worker(fabrica_de_sesiones, contexto)
    momento = datetime(2026, 11, 17, 20, tzinfo=UTC)
    caplog.set_level("DEBUG")
    for numero, espera in [(1, 10), (2, 60), (3, None)]:
        monkeypatch.setattr("app.nucleo.worker.ahora", lambda instante=momento: instante)
        assert worker.procesar_pendientes() == 1
        with fabrica_de_sesiones() as sesion:
            fila = sesion.get(DocumentoHistorico, documento.id)
            assert fila.intentos == numero
            assert fila.ultimo_error == "RuntimeError"
            assert fila.estado == (EstadoDocumento.ERROR if espera is None else EstadoDocumento.SUBIDO)
            assert fila.proximo_intento_en == (
                momento + timedelta(seconds=espera) if espera is not None else None
            )
        assert worker.procesar_pendientes() == 0
        if espera is not None:
            momento += timedelta(seconds=espera)
    assert "CONTENIDO_CLINICO_QUE_NO_DEBE_LOGUEARSE" not in caplog.text


def test_la_ia_no_mantiene_una_transaccion_abierta(sesion, crear_documento, fabrica_de_sesiones):
    class Concurrente(ProveedorLLMFake):
        def escribir(self):
            with fabrica_de_sesiones.begin() as otra:
                otra.add(EventoAuditoria(actor_tipo=TipoActor.SISTEMA, accion="prueba"))

        def leer_imagen(self, contenido, mime):
            self.escribir()
            return super().leer_imagen(contenido, mime)

        def generar_json(self, instrucciones, entrada, esquema):
            self.escribir()
            return super().generar_json(instrucciones, entrada, esquema)

    documento = crear_documento()
    llm = Concurrente([json.dumps(CAMPOS)], lecturas=[TEXTO])
    procesar_documento(sesion, documento.id, llm)
    assert documento.estado == EstadoDocumento.POR_REVISAR
