import json
from datetime import UTC, datetime

import pytest

from app.nucleo.extraccion import (
    ESQUEMA,
    FORMATO_INVALIDO,
    SIN_RESPALDO,
    ErrorExtraccion,
    extraer_registro,
)
from app.proveedores.llm.fake import ProveedorLLMFake

REFERENCIA = datetime(2026, 11, 2, 15, 40, tzinfo=UTC)  # lunes, 12:40 en Chile

GUION_COMPLETO = (
    "Hoy atendí a Emilia Soto en el Hogar. Control pediátrico, cuadro de bronquiolitis leve. "
    "Indico salbutamol dos puff cada seis horas por cinco días y aseo nasal. Control en dos "
    "semanas. La acompañó la educadora María Pérez."
)

# Lo que respondería un LLM bien portado ante el guion completo.
RESPUESTA_COMPLETA = {
    "residente": {"valor": "RES-02", "fragmento": "atendí a [RES-02]"},
    "fecha_atencion": {"valor": "2026-11-02", "fragmento": "Hoy"},
    "hora_atencion": None,
    "lugar": {"valor": "Hogar", "fragmento": "en el Hogar"},
    "motivo": {"valor": "Control pediátrico", "fragmento": "Control pediátrico"},
    "diagnosticos": [{"valor": "Bronquiolitis leve", "fragmento": "cuadro de bronquiolitis leve"}],
    "evolucion_clinica": None,
    "observaciones": None,
    "indicaciones_farmacologicas": [
        {
            "medicamento": "salbutamol",
            "dosis": "2 puff",
            "frecuencia_horario": "cada 6 horas",
            "via": None,
            "duracion": "5 días",
            "fecha_inicio": None,
            "fecha_termino": None,
            "fragmento": "salbutamol dos puff cada seis horas por cinco días",
        }
    ],
    "otras_indicaciones": [{"valor": "Aseo nasal", "fragmento": "aseo nasal"}],
    "examenes_solicitados": [],
    "proximo_control": {
        "fecha": "2026-11-16",
        "descripcion": "Control en dos semanas",
        "fragmento": "Control en dos semanas",
    },
    "acompanante": {
        "nombre": "María Pérez",
        "cargo": "educadora",
        "fragmento": "la educadora María Pérez",
    },
    "ambiguedades": [],
}


def extraer(texto, residentes, *respuestas):
    llm = ProveedorLLMFake([json.dumps(r) if isinstance(r, dict) else r for r in respuestas])
    return extraer_registro(texto, residentes, "pediatría", REFERENCIA, llm)


def motivos(resultado) -> set[tuple[str, str]]:
    return {(a.campo, a.motivo) for a in resultado.registro.ambiguedades}


# Lo que recibe el LLM


def test_el_llm_recibe_el_texto_seudonimizado_y_el_contexto(residentes):
    llm = ProveedorLLMFake()

    extraer_registro(GUION_COMPLETO, residentes, "pediatría", REFERENCIA, llm)

    entrada = llm.entradas[0]
    assert "Hoy atendí a [RES-02] en el Hogar." in entrada
    assert "Emilia" not in entrada and "Soto" not in entrada
    assert "Fecha y hora de referencia: lunes 2026-11-02 12:40" in entrada
    assert "Especialidad del profesional: pediatría." in entrada
    assert "- RES-01: heterogéneo, 3 años" in entrada
    assert "- RES-02: sala cuna menor, 10 meses" in entrada
    assert "- RES-03: sala cuna mayor, 20 meses" in entrada


def test_el_esquema_cumple_el_modo_estricto():
    def revisar(nodo):
        assert "title" not in nodo and "default" not in nodo
        if "properties" in nodo:
            assert nodo["required"] == list(nodo["properties"])
            assert nodo["additionalProperties"] is False
        hijos = [*nodo.get("properties", {}).values(), *nodo.get("$defs", {}).values()]
        hijos += [*nodo.get("anyOf", []), *([nodo["items"]] if "items" in nodo else [])]
        for hijo in hijos:
            revisar(hijo)

    revisar(ESQUEMA)
    # La especialidad se conoce por el vínculo del profesional: no se le pide al LLM.
    assert "especialidad" not in ESQUEMA["properties"]


# Validación de la respuesta


def test_conserva_los_datos_respaldados_por_el_texto(residentes):
    resultado = extraer(GUION_COMPLETO, residentes, RESPUESTA_COMPLETA)
    registro = resultado.registro

    assert resultado.residente_id == 2
    assert registro.residente.valor == "RES-02"
    assert registro.fecha_atencion.valor == "2026-11-02"
    assert [d.valor for d in registro.diagnosticos] == ["Bronquiolitis leve"]
    assert registro.indicaciones_farmacologicas[0].medicamento == "salbutamol"
    assert registro.proximo_control.fecha == "2026-11-16"
    assert registro.acompanante.cargo == "educadora"
    assert registro.ambiguedades == []
    assert resultado.salida == RESPUESTA_COMPLETA
    assert (resultado.proveedor, resultado.modelo) == ("fake", "fake")


def test_descarta_los_datos_cuyo_fragmento_no_esta_en_el_texto(residentes):
    respuesta = RESPUESTA_COMPLETA | {
        "diagnosticos": [
            {"valor": "Bronquiolitis leve", "fragmento": "cuadro de bronquiolitis leve"},
            {"valor": "Neumonía", "fragmento": "neumonía grave"},
        ],
        "observaciones": {"valor": "Muy decaída", "fragmento": "muy decaída"},
    }

    resultado = extraer(GUION_COMPLETO, residentes, respuesta)

    assert [d.valor for d in resultado.registro.diagnosticos] == ["Bronquiolitis leve"]
    assert resultado.registro.observaciones is None
    assert motivos(resultado) == {("diagnosticos", SIN_RESPALDO), ("observaciones", SIN_RESPALDO)}


def test_el_fragmento_se_compara_sin_importar_mayusculas_tildes_ni_espacios(residentes):
    respuesta = RESPUESTA_COMPLETA | {
        "diagnosticos": [{"valor": "Bronquiolitis", "fragmento": "Cuadro de  BRONQUIOLITIS leve."}]
    }

    resultado = extraer(GUION_COMPLETO, residentes, respuesta)

    assert [d.valor for d in resultado.registro.diagnosticos] == ["Bronquiolitis"]


def test_descarta_las_fechas_con_formato_invalido(residentes):
    respuesta = RESPUESTA_COMPLETA | {
        "fecha_atencion": {"valor": "2 de noviembre", "fragmento": "Hoy"},
        "proximo_control": {
            "fecha": "en dos semanas",
            "descripcion": "Control en dos semanas",
            "fragmento": "Control en dos semanas",
        },
    }

    resultado = extraer(GUION_COMPLETO, residentes, respuesta)

    assert resultado.registro.fecha_atencion is None
    assert resultado.registro.proximo_control.fecha is None
    assert resultado.registro.proximo_control.descripcion == "Control en dos semanas"
    assert motivos(resultado) == {
        ("fecha_atencion", FORMATO_INVALIDO),
        ("proximo_control", FORMATO_INVALIDO),
    }


def test_si_la_respuesta_no_cumple_el_esquema_se_pide_otra_vez(residentes):
    llm = ProveedorLLMFake(["esto no es JSON", json.dumps(RESPUESTA_COMPLETA)])

    resultado = extraer_registro(GUION_COMPLETO, residentes, "pediatría", REFERENCIA, llm)

    assert len(llm.entradas) == 2
    assert resultado.registro.lugar.valor == "Hogar"


def test_si_falla_dos_veces_se_rinde(residentes):
    with pytest.raises(ErrorExtraccion):
        extraer(GUION_COMPLETO, residentes, "esto no es JSON", '{"diagnosticos": "texto"}')


def test_conserva_las_ambiguedades_que_reporta_el_llm(residentes):
    respuesta = RESPUESTA_COMPLETA | {
        "ambiguedades": [{"campo": "dosis", "motivo": "no dice la concentración"}]
    }

    resultado = extraer(GUION_COMPLETO, residentes, respuesta)

    assert motivos(resultado) == {("dosis", "no dice la concentración")}


# Residente


def test_un_nombre_ambiguo_deja_el_residente_sin_identificar(residentes):
    resultado = extraer("Atendí a Tomás por una otitis.", residentes)

    assert resultado.residente_id is None
    assert resultado.registro.residente is None
    assert motivos(resultado) == {("residente", "residente ambiguo: puede ser RES-01 o RES-04")}


def test_el_nombre_completo_en_la_respuesta_resuelve_la_ambiguedad(residentes):
    resultado = extraer("Atendí a Tomás por una otitis.\nTomás Rivas", residentes)

    assert resultado.residente_id == 1
    assert motivos(resultado) == set()


def test_dos_residentes_en_un_mensaje_es_una_ambiguedad(residentes):
    resultado = extraer("Control de Emilia Soto y Martina Rojas", residentes)

    assert resultado.residente_id is None
    assert motivos(resultado) == {("residente", "más de un residente")}


def test_sin_residente_reconocible_queda_no_identificado(residentes):
    resultado = extraer("Control sano, sin novedades.", residentes)

    assert motivos(resultado) == {("residente", "residente no identificado")}


def test_el_residente_lo_decide_la_seudonimizacion_y_no_el_llm(residentes):
    respuesta = RESPUESTA_COMPLETA | {"residente": {"valor": "RES-03", "fragmento": "Hoy"}}

    resultado = extraer(GUION_COMPLETO, residentes, respuesta)

    assert resultado.residente_id == 2
    assert resultado.registro.residente.valor == "RES-02"
    assert resultado.registro.residente.fragmento == "[RES-02]"
