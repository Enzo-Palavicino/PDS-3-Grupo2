import pytest
from sqlalchemy import func, select
from starlette.datastructures import FormData

from app.modelos import Adjunto, Atencion, EstadoAtencion, Residente, UsuarioWeb
from app.web.atenciones import campos_del_formulario
from tests.web.conftest import csrf_de
from tests.web.test_web_adjuntos import PDF, PNG

FORMULARIO = {
    "fecha_atencion": "2026-11-17",
    "hora_atencion": "10:30",
    "lugar": "Enfermería del Hogar",
    "motivo": "Tos de tres días",
    "diagnosticos": "Bronquitis obstructiva\n\nRinitis",
    "evolucion_clinica": "Afebril, buena mecánica ventilatoria.",
    "observaciones": "Come bien.",
    "ind_medicamento": ["salbutamol", "paracetamol", ""],
    "ind_dosis": ["2 puff", "120 mg", ""],
    "ind_frecuencia_horario": ["cada 8 horas", "si hay fiebre", ""],
    "ind_via": ["inhalatoria", "oral", ""],
    "ind_duracion": ["5 días", "", ""],
    "ind_fecha_inicio": ["2026-11-17", "", ""],
    "ind_fecha_termino": ["2026-11-21", "", ""],
    "otras_indicaciones": "Aseo nasal\nControl de temperatura",
    "examenes_solicitados": "",
    "control_fecha": "2026-11-24",
    "control_descripcion": "Control broncopulmonar",
    "acompanante_nombre": "Ana Pérez",
    "acompanante_cargo": "Tía de sala",
    "tipo_adjunto": "receta",
    "emisor": "",
}


@pytest.fixture
def emilia(sesion, datos_demo) -> Residente:
    """Emilia Soto (RES-02): asignada a la pediatra y al nutricionista, no al kinesiólogo."""
    residente = sesion.scalar(select(Residente).where(Residente.codigo == "RES-02"))
    sesion.commit()
    return residente


def formulario(cliente, residente_id: int):
    return cliente.get(f"/atenciones/nueva?residente_id={residente_id}")


def enviar(cliente, residente, cambios=None, archivos=None, confirmar=True, con_csrf=True):
    datos = FORMULARIO | {"residente_id": str(residente.id)} | (cambios or {})
    if confirmar:
        datos["confirmo_identidad"] = str(residente.id)
    if con_csrf:
        datos["csrf"] = csrf_de(formulario(cliente, residente.id).text)
    return cliente.post(
        "/atenciones/nueva", data=datos, files=archivos or [], follow_redirects=False
    )


def atenciones(sesion) -> list[Atencion]:
    sesion.commit()
    filas = list(sesion.scalars(select(Atencion).order_by(Atencion.id)))
    sesion.commit()
    return filas


def contar_adjuntos(sesion) -> int:
    sesion.commit()
    total = sesion.scalar(select(func.count()).select_from(Adjunto))
    sesion.commit()
    return total


# Formulario


def test_el_profesional_abre_el_formulario_desde_la_ficha(cliente, entrar, emilia):
    entrar("pediatra")
    ficha = cliente.get(f"/residentes/{emilia.id}").text
    assert f'href="/atenciones/nueva?residente_id={emilia.id}"' in ficha

    html = formulario(cliente, emilia.id).text

    for nombre in (
        "fecha_atencion", "hora_atencion", "lugar", "motivo", "diagnosticos",
        "evolucion_clinica", "observaciones", "ind_medicamento", "ind_dosis",
        "ind_frecuencia_horario", "ind_via", "ind_duracion", "ind_fecha_inicio",
        "ind_fecha_termino", "otras_indicaciones", "examenes_solicitados", "control_fecha",
        "control_descripcion", "acompanante_nombre", "acompanante_cargo", "archivos",
    ):
        assert f'name="{nombre}"' in html, nombre
    assert "Confirmo que la atención es de <strong>Emilia Soto</strong>" in html
    assert 'enctype="multipart/form-data"' in html


@pytest.mark.parametrize("cuenta", ["encargada_salud", "directora", "kinesiologo"])
def test_solo_un_profesional_asignado_abre_el_formulario(cliente, entrar, emilia, cuenta):
    entrar(cuenta)

    assert formulario(cliente, emilia.id).status_code == 403


# Registro


def test_registra_la_atencion_en_borrador_y_lleva_a_firmar(
    cliente, entrar, sesion, emilia, acciones
):
    entrar("pediatra")

    respuesta = enviar(cliente, emilia)

    [atencion] = atenciones(sesion)
    assert respuesta.status_code == 303
    assert respuesta.headers["location"] == f"/atenciones/{atencion.id}/firmar"
    assert atencion.estado == EstadoAtencion.BORRADOR
    assert atencion.origen == "web"
    assert atencion.residente_id == emilia.id
    pediatra = sesion.scalar(select(UsuarioWeb).where(UsuarioWeb.usuario == "pediatra"))
    assert atencion.profesional_id == pediatra.profesional_id
    assert str(atencion.fecha_atencion) == "2026-11-17"
    assert "atencion_creada" in acciones()


def test_guarda_todos_los_campos_con_el_formato_de_la_ia(cliente, entrar, sesion, emilia):
    entrar("pediatra")

    enviar(cliente, emilia)

    campos = atenciones(sesion)[0].campos
    assert campos["residente"]["valor"] == "RES-02"
    assert campos["hora_atencion"] == {"valor": "10:30", "fragmento": None}
    assert campos["lugar"]["valor"] == "Enfermería del Hogar"
    assert [d["valor"] for d in campos["diagnosticos"]] == ["Bronquitis obstructiva", "Rinitis"]
    assert campos["evolucion_clinica"]["valor"].startswith("Afebril")
    assert [i["medicamento"] for i in campos["indicaciones_farmacologicas"]] == [
        "salbutamol", "paracetamol"
    ]
    salbutamol = campos["indicaciones_farmacologicas"][0]
    assert salbutamol["frecuencia_horario"] == "cada 8 horas"
    assert salbutamol["fecha_termino"] == "2026-11-21"
    assert campos["indicaciones_farmacologicas"][1]["duracion"] is None
    assert [d["valor"] for d in campos["otras_indicaciones"]] == [
        "Aseo nasal", "Control de temperatura"
    ]
    assert "examenes_solicitados" not in campos
    assert campos["proximo_control"]["fecha"] == "2026-11-24"
    assert campos["acompanante"] == {"nombre": "Ana Pérez", "cargo": "Tía de sala", "fragmento": None}
    assert campos["especialidad"]["valor"] == "pediatría"


def test_basta_un_diagnostico_sin_motivo(cliente, entrar, sesion, emilia):
    entrar("pediatra")

    respuesta = enviar(cliente, emilia, {"motivo": ""})

    assert respuesta.status_code == 303
    assert len(atenciones(sesion)) == 1


@pytest.mark.parametrize(
    ("cambios", "invalido"),
    [
        ({"fecha_atencion": ""}, 'id="campo-fecha_atencion"'),
        ({"motivo": "", "diagnosticos": ""}, 'id="campo-motivo"'),
    ],
)
def test_sin_los_obligatorios_no_se_guarda_y_se_marca_lo_que_falta(
    cliente, entrar, sesion, emilia, cambios, invalido
):
    entrar("pediatra")

    respuesta = enviar(cliente, emilia, cambios)

    assert respuesta.status_code == 400
    assert "Faltan datos obligatorios" in respuesta.text
    campo = respuesta.text[respuesta.text.index(invalido):]
    assert 'aria-invalid="true"' in campo[: campo.index(">")]
    assert "Enfermería del Hogar" in respuesta.text  # conserva lo escrito
    assert atenciones(sesion) == []


def test_sin_confirmar_la_identidad_no_se_guarda(cliente, entrar, sesion, emilia):
    entrar("pediatra")

    respuesta = enviar(cliente, emilia, confirmar=False)

    assert respuesta.status_code == 400
    assert "Confirma que la atención es de Emilia Soto" in respuesta.text
    assert "salbutamol" in respuesta.text
    assert atenciones(sesion) == []


def test_la_confirmacion_debe_ser_del_mismo_residente(cliente, entrar, sesion, emilia):
    entrar("pediatra")

    respuesta = enviar(cliente, emilia, {"confirmo_identidad": "1"}, confirmar=False)

    assert respuesta.status_code == 400
    assert atenciones(sesion) == []


@pytest.mark.parametrize(
    ("cambios", "mensaje"),
    [
        ({"ind_medicamento": ["", "paracetamol", ""]}, "Indicación 1: falta el medicamento."),
        ({"hora_atencion": "25:00"}, "Hora: usa el formato HH:MM."),
        ({"control_fecha": "2026-02-30"}, "Próximo control: indica una fecha válida."),
    ],
)
def test_los_datos_mal_escritos_se_avisan(cliente, entrar, sesion, emilia, cambios, mensaje):
    entrar("pediatra")

    respuesta = enviar(cliente, emilia, cambios)

    assert respuesta.status_code == 400
    assert mensaje in respuesta.text
    assert atenciones(sesion) == []


# Adjuntos


def test_los_archivos_quedan_adjuntos_a_la_atencion(cliente, entrar, sesion, emilia):
    entrar("pediatra")

    enviar(
        cliente,
        emilia,
        {"emisor": "CESFAM"},
        archivos=[
            ("archivos", ("receta.png", PNG, "image/png")),
            ("archivos", ("informe.pdf", PDF, "application/pdf")),
        ],
    )

    [atencion] = atenciones(sesion)
    adjuntos = list(sesion.scalars(select(Adjunto).order_by(Adjunto.id)))
    sesion.commit()
    assert [a.nombre_archivo for a in adjuntos] == ["receta.png", "informe.pdf"]
    assert {(a.atencion_id, a.residente_id, a.tipo, a.emisor) for a in adjuntos} == {
        (atencion.id, emilia.id, "receta", "CESFAM")
    }


def test_un_archivo_invalido_deshace_todo(cliente, entrar, sesion, emilia):
    entrar("pediatra")

    respuesta = enviar(
        cliente,
        emilia,
        archivos=[
            ("archivos", ("receta.png", PNG, "image/png")),
            ("archivos", ("virus.png", b"no es una imagen", "image/png")),
        ],
    )

    assert respuesta.status_code == 400
    assert "vuelve a seleccionarlos" in respuesta.text
    assert atenciones(sesion) == []
    assert contar_adjuntos(sesion) == 0


# Seguridad


def test_sin_token_csrf_no_se_guarda(cliente, entrar, sesion, emilia):
    entrar("pediatra")
    formulario(cliente, emilia.id)

    assert enviar(cliente, emilia, con_csrf=False).status_code == 403
    assert atenciones(sesion) == []


@pytest.mark.parametrize("cuenta", ["encargada_salud", "kinesiologo"])
def test_solo_un_profesional_asignado_registra(cliente, entrar, csrf, sesion, emilia, cuenta):
    entrar(cuenta)
    datos = FORMULARIO | {
        "residente_id": str(emilia.id),
        "confirmo_identidad": str(emilia.id),
        "csrf": csrf("/fichas"),
    }

    respuesta = cliente.post("/atenciones/nueva", data=datos, follow_redirects=False)

    assert respuesta.status_code == 403
    assert atenciones(sesion) == []


# Conversión del formulario


def test_lo_vacio_no_queda_en_los_campos():
    datos = FormData(
        [("motivo", "  Control sano  "), ("diagnosticos", "\n \n"), ("lugar", "")]
        + [(f"ind_{n}", "") for n in ("medicamento", "dosis", "via")]
    )

    campos, errores = campos_del_formulario(datos)

    assert campos == {"motivo": {"valor": "Control sano", "fragmento": None}}
    assert errores == []
