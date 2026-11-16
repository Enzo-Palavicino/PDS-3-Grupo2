from datetime import UTC, date, datetime

import pytest
from sqlalchemy import func, select

from app.modelos import (
    Antecedente,
    Atencion,
    Control,
    EstadoAtencion,
    EstadoControl,
    EstadoTratamiento,
    Medicion,
    OrigenAtencion,
    TipoAntecedente,
    Tratamiento,
)
from app.nucleo.atenciones import incorporar_a_ficha
from app.nucleo.incorporacion import incorporar

# Guion 1 de la demo: "Hoy atendí a Emilia Soto en el Hogar. Control pediátrico, cuadro de
# bronquiolitis leve. Indico salbutamol dos puff cada seis horas por cinco días y aseo nasal.
# Control en dos semanas."
GUION_1 = {
    "fecha_atencion": {"valor": "2026-11-02", "fragmento": "Hoy"},
    "motivo": {"valor": "Control pediátrico", "fragmento": "Control pediátrico"},
    "diagnosticos": [{"valor": "bronquiolitis leve", "fragmento": "bronquiolitis leve"}],
    "indicaciones_farmacologicas": [
        {
            "medicamento": "salbutamol",
            "dosis": "dos puff",
            "frecuencia_horario": "cada seis horas",
            "via": None,
            "duracion": "cinco días",
            "fecha_inicio": None,
            "fecha_termino": None,
            "fragmento": "salbutamol dos puff cada seis horas por cinco días",
        }
    ],
    "otras_indicaciones": [{"valor": "aseo nasal", "fragmento": "aseo nasal"}],
    "proximo_control": {
        "fecha": "2026-11-16",
        "descripcion": "Control en dos semanas",
        "fragmento": "Control en dos semanas",
    },
}
MOMENTO = datetime(2026, 11, 16, 15, 0, tzinfo=UTC)


@pytest.fixture
def atencion(sesion, residente, profesional):
    def crear(
        campos: dict, origen: OrigenAtencion = OrigenAtencion.WHATSAPP, fecha=date(2026, 11, 2)
    ) -> Atencion:
        atencion = Atencion(
            residente_id=residente.id,
            profesional_id=profesional.id,
            origen=origen,
            estado=EstadoAtencion.FIRMADA,
            fecha_atencion=fecha,
            campos=campos,
        )
        sesion.add(atencion)
        sesion.flush()
        return atencion

    return crear


def contar(sesion, modelo) -> int:
    return sesion.scalar(select(func.count()).select_from(modelo))


def test_el_guion_1_deja_el_tratamiento_activo_y_el_control_pendiente(sesion, atencion):
    firmada = atencion(GUION_1)

    incorporar_a_ficha(sesion, firmada)
    sesion.commit()

    [tratamiento] = sesion.scalars(select(Tratamiento))
    assert tratamiento.medicamento == "salbutamol"
    assert tratamiento.dosis == "dos puff"
    assert tratamiento.frecuencia_horario == "cada seis horas"
    assert tratamiento.duracion == "cinco días"
    assert tratamiento.estado == EstadoTratamiento.ACTIVO
    # Indicado el día de la atención; el inicio y el término no se calculan.
    assert tratamiento.indicado_en == date(2026, 11, 2)
    assert (tratamiento.fecha_inicio, tratamiento.fecha_termino) == (None, None)
    [control] = sesion.scalars(select(Control))
    assert control.fecha == date(2026, 11, 16)
    assert control.estado == EstadoControl.PENDIENTE
    assert firmada.incorporada_en is not None


def test_incorporar_dos_veces_no_duplica_nada(sesion, atencion):
    firmada = atencion(GUION_1)

    incorporar_a_ficha(sesion, firmada)
    incorporar_a_ficha(sesion, firmada)
    sesion.commit()

    assert contar(sesion, Tratamiento) == 1
    assert contar(sesion, Control) == 1


def test_una_atencion_historica_deja_sus_tratamientos_terminados(sesion, atencion):
    indicaciones = [
        {"medicamento": "amoxicilina", "fecha_termino": "2024-05-10"},
        {"medicamento": "paracetamol"},  # sin término: tampoco es una indicación vigente
        {"medicamento": "fierro", "fecha_termino": "2027-01-31"},  # termina en el futuro
    ]
    historica = atencion(
        {"indicaciones_farmacologicas": indicaciones},
        origen=OrigenAtencion.HISTORICO,
        fecha=date(2024, 5, 3),
    )

    incorporar(sesion, historica, momento=MOMENTO)

    estados = {t.medicamento: t.estado for t in sesion.scalars(select(Tratamiento))}
    assert estados == {
        "amoxicilina": EstadoTratamiento.TERMINADO,
        "paracetamol": EstadoTratamiento.TERMINADO,
        "fierro": EstadoTratamiento.ACTIVO,
    }


def test_los_antecedentes_y_las_mediciones_pasan_a_la_ficha(sesion, atencion):
    campos = {
        **GUION_1,
        "alergias": [{"valor": "penicilina", "fragmento": "alérgica a la penicilina"}],
        "vacunas": [{"valor": "influenza", "fragmento": "vacuna influenza"}],
        "hospitalizaciones": [{"valor": "", "fragmento": None}],  # vacía: se ignora
        "mediciones": {"peso_kg": "9,8", "talla_cm": 74, "fragmento": "pesa 9,8 kg y mide 74"},
    }

    incorporar_a_ficha(sesion, atencion(campos))

    antecedentes = {(a.tipo, a.descripcion) for a in sesion.scalars(select(Antecedente))}
    assert antecedentes == {
        (TipoAntecedente.ALERGIA, "penicilina"),
        (TipoAntecedente.VACUNA, "influenza"),
    }
    [medicion] = sesion.scalars(select(Medicion))
    assert (medicion.peso_kg, medicion.talla_cm, medicion.fecha) == (9.8, 74.0, date(2026, 11, 2))


def test_un_dato_mal_escrito_no_impide_incorporar_el_resto(sesion, atencion):
    campos = {
        "indicaciones_farmacologicas": [
            {"medicamento": "salbutamol", "fecha_inicio": "mañana"},
            {"medicamento": "", "dosis": "5 ml"},  # sin medicamento: no es un tratamiento
        ],
        "proximo_control": {"fecha": "16/11/2026", "descripcion": "en dos semanas"},
        "mediciones": {"peso_kg": "no se pesó", "talla_cm": None},
    }

    incorporar_a_ficha(sesion, atencion(campos))

    [tratamiento] = sesion.scalars(select(Tratamiento))
    assert tratamiento.fecha_inicio is None
    [control] = sesion.scalars(select(Control))
    assert (control.fecha, control.descripcion) == (None, "en dos semanas")
    assert contar(sesion, Medicion) == 0


def test_una_atencion_sin_indicaciones_no_agrega_nada(sesion, atencion):
    firmada = atencion({"motivo": {"valor": "control sano", "fragmento": None}})

    incorporar_a_ficha(sesion, firmada)

    for modelo in (Tratamiento, Control, Antecedente, Medicion):
        assert contar(sesion, modelo) == 0
    assert firmada.incorporada_en is not None
