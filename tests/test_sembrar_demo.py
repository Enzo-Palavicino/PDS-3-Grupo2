"""Datos de la demo de la entrega 2 (scripts.sembrar_datos.sembrar_demo, con SEED_DEMO=true)."""

import pytest
from sqlalchemy import delete, func, select

from app.modelos import (
    Antecedente,
    Asignacion,
    Atencion,
    Control,
    EstadoAtencion,
    EstadoTratamiento,
    Medicion,
    Profesional,
    Residente,
    Tratamiento,
    UsuarioWeb,
)
from app.nucleo.atenciones import verificar_integridad
from app.nucleo.permisos import profesional_asignado
from app.nucleo.tratamientos import tratamientos_del_residente
from app.seguridad import hashear_password
from scripts.sembrar_datos import ASIGNACIONES, sembrar, sembrar_demo

PASSWORD = "clave-de-prueba"


@pytest.fixture
def base(sesion):
    """La base con los datos de siempre (sembrar), sobre la que se carga la demo."""
    sembrar(sesion, PASSWORD)
    sesion.commit()
    return sesion


def contar(sesion, modelo) -> int:
    return sesion.scalar(select(func.count()).select_from(modelo))


def residente(sesion, codigo: str) -> Residente:
    return sesion.scalar(select(Residente).where(Residente.codigo == codigo))


def profesional_de(sesion, usuario: str) -> int:
    return sesion.scalar(select(UsuarioWeb.profesional_id).where(UsuarioWeb.usuario == usuario))


def test_sin_seed_demo_no_hay_ficha_de_demo(base):
    assert contar(base, Atencion) == 0
    assert contar(base, Antecedente) == 0


def test_carga_antecedentes_mediciones_y_tres_atenciones_firmadas(base):
    avisos = sembrar_demo(base, PASSWORD)
    base.commit()

    assert avisos == []
    assert contar(base, Antecedente) == 7
    # 3 mediciones sueltas y la de la atención de nutrición.
    assert contar(base, Medicion) == 4
    atenciones = list(base.scalars(select(Atencion)))
    assert len(atenciones) == 3
    assert all(a.estado == EstadoAtencion.FIRMADA for a in atenciones)
    assert all(verificar_integridad(a) for a in atenciones)
    assert contar(base, Control) == 2


def test_tomas_rivas_tiene_un_tratamiento_vigente_y_otro_terminado(base):
    sembrar_demo(base, PASSWORD)

    vigentes, historial = tratamientos_del_residente(base, residente(base, "RES-01").id)

    assert [t.medicamento for t in vigentes] == ["Budesonida"]
    assert [(t.medicamento, t.estado) for t in historial] == [
        ("Salbutamol", EstadoTratamiento.ACTIVO)  # terminado por fecha, no suspendido
    ]


def test_emilia_soto_queda_sin_atenciones_para_la_demo_en_vivo(base):
    sembrar_demo(base, PASSWORD)
    emilia = residente(base, "RES-02")

    assert base.scalar(select(Atencion).where(Atencion.residente_id == emilia.id)) is None
    assert profesional_asignado(base, profesional_de(base, "pediatra"), emilia.id)


def test_correr_dos_veces_no_duplica_nada(base):
    sembrar_demo(base, PASSWORD)
    base.commit()
    antes = [contar(base, m) for m in (Asignacion, Antecedente, Medicion, Atencion, Tratamiento)]

    sembrar_demo(base, PASSWORD)
    base.commit()

    assert [
        contar(base, m) for m in (Asignacion, Antecedente, Medicion, Atencion, Tratamiento)
    ] == antes


def test_completa_las_asignaciones_de_una_base_como_la_del_servidor(base):
    # En el servidor los profesionales existían antes de las asignaciones: no tienen ninguna.
    base.execute(delete(Asignacion))
    base.commit()

    sembrar_demo(base, PASSWORD)

    for usuario, codigos in ASIGNACIONES.items():
        for codigo in codigos:
            assert profesional_asignado(
                base, profesional_de(base, usuario), residente(base, codigo).id
            ), (usuario, codigo)


def test_no_cambia_las_asignaciones_que_alguien_ya_eligio(base):
    pediatra = profesional_de(base, "pediatra")
    base.execute(delete(Asignacion).where(Asignacion.profesional_id == pediatra))
    base.add(Asignacion(residente_id=residente(base, "RES-02").id, profesional_id=pediatra))
    base.commit()

    sembrar_demo(base, PASSWORD)

    asignados = base.scalars(
        select(Asignacion.residente_id).where(Asignacion.profesional_id == pediatra)
    )
    assert list(asignados) == [residente(base, "RES-02").id]


def test_si_alguien_cambio_su_contrasena_se_salta_su_atencion_sin_romper(base):
    pediatra = base.scalar(select(UsuarioWeb).where(UsuarioWeb.usuario == "pediatra"))
    pediatra.hash_password = hashear_password("otra-clave-elegida")
    base.commit()

    avisos = sembrar_demo(base, PASSWORD)
    base.commit()

    assert avisos == ["No se cargó la atención de RES-01: pediatra ya no usa SEED_PASSWORD."]
    assert contar(base, Atencion) == 2  # ni siquiera queda el borrador de la que falló
    profesionales = {
        base.get(Profesional, a.profesional_id).nombre for a in base.scalars(select(Atencion))
    }
    assert profesionales == {"Felipe Araya", "Javiera Muñoz"}
