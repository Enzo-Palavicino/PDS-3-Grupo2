import pytest

from app.nucleo.seudonimizacion import seudonimizar


def texto(entrada: str, residentes) -> str:
    return seudonimizar(entrada, residentes).texto


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("Hoy atendí a Emilia Soto en el Hogar.", "Hoy atendí a [RES-02] en el Hogar."),
        ("Control de Tomas Rivas", "Control de [RES-01]"),  # sin tilde
        ("EMILIA SOTO llegó con fiebre", "[RES-02] llegó con fiebre"),  # en mayúsculas
        ("La Emi está mejor", "La [RES-02] está mejor"),  # apodo
        ("Atendí a la marti", "Atendí a la [RES-03]"),  # apodo en minúsculas
        ("Emila Soto, control sano", "[RES-02], control sano"),  # error de transcripción
        ("Martna tiene tos", "[RES-03] tiene tos"),  # error en el nombre solo
        ("Tomás Díaz, control", "[RES-04], control"),  # el nombre completo resuelve
        ("El niño Rivas comió bien", "El niño [RES-01] comió bien"),  # apellido con mayúscula
    ],
)
def test_reemplaza_a_los_residentes_por_su_codigo(entrada, esperado, residentes):
    assert texto(entrada, residentes) == esperado


def test_un_nombre_que_comparten_dos_residentes_queda_ambiguo(residentes):
    resultado = seudonimizar("Atendí a Tomás por una otitis", residentes)

    assert resultado.texto == "Atendí a [RES-01|RES-04] por una otitis"
    assert [mencion.ambigua for mencion in resultado.menciones] == [True]


def test_un_apellido_en_minuscula_es_una_palabra_comun(residentes):
    entrada = "Martina Rojas presenta manchas rojas en la piel"

    assert texto(entrada, residentes) == "[RES-03] presenta manchas rojas en la piel"


@pytest.mark.parametrize(
    "entrada",
    [
        "Debe tomar paracetamol cada 8 horas",
        "Se queda solo en la sala",
        "Control en 15 días",
        "Indico salbutamol dos puff",
    ],
)
def test_no_toca_palabras_parecidas_a_un_nombre(entrada, residentes):
    assert texto(entrada, residentes) == entrada


def test_reemplaza_rut_telefono_y_correo(residentes):
    entrada = (
        "RUT 12.345.678-5, otro 12345678-K, fono +56 9 1234 5678 o 912345678, "
        "correo ana.perez@correo.cl"
    )

    assert texto(entrada, residentes) == (
        "RUT [RUT], otro [RUT], fono [TEL] o [TEL], correo [EMAIL]"
    )


def test_los_nombres_de_quienes_no_son_residentes_no_se_detectan(residentes):
    # Limitación documentada: la acompañante no está en la lista de residentes.
    entrada = "La acompañó la educadora María Pérez"

    assert texto(entrada, residentes) == entrada


GUION_COMPLETO = (
    "Hoy atendí a Emilia Soto en el Hogar. Control pediátrico, cuadro de bronquiolitis leve. "
    "Indico salbutamol dos puff cada seis horas por cinco días y aseo nasal. Control en dos "
    "semanas. La acompañó la educadora María Pérez."
)
GUION_CON_FALTANTES = (
    "Martina Rojas, evaluación nutricional, peso adecuado para su edad, se mantiene la minuta "
    "actual."
)
GUION_AMBIGUO = "Atendí a Tomás por una otitis, amoxicilina cada doce horas por diez días."


@pytest.mark.parametrize(
    ("guion", "nombre", "codigo"),
    [
        (GUION_COMPLETO, "Emilia Soto", "[RES-02]"),
        (GUION_CON_FALTANTES, "Martina Rojas", "[RES-03]"),
        (GUION_AMBIGUO, "Tomás", "[RES-01|RES-04]"),
    ],
)
def test_en_los_tres_guiones_de_la_demo_solo_cambia_el_residente(
    guion, nombre, codigo, residentes
):
    assert texto(guion, residentes) == guion.replace(nombre, codigo)
