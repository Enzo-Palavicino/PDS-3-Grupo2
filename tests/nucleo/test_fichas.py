from datetime import UTC, date, datetime

import pytest

from app.modelos import (
    Antecedente,
    Atencion,
    Control,
    EstadoAtencion,
    EstadoControl,
    EstadoTratamiento,
    Medicion,
    Nivel,
    OrigenAtencion,
    Residente,
    TipoAntecedente,
    Tratamiento,
)
from app.nucleo.fichas import historial, resumen_de_ficha

HOY = date(2026, 11, 17)


@pytest.fixture
def atencion(sesion, residente, profesional):
    """Crea una atención del residente; por defecto, firmada."""

    def crear(estado=EstadoAtencion.FIRMADA, residente_id=None, **datos) -> Atencion:
        nueva = Atencion(
            residente_id=residente_id or residente.id,
            profesional_id=profesional.id,
            origen=datos.pop("origen", OrigenAtencion.WEB),
            estado=estado,
            **datos,
        )
        sesion.add(nueva)
        sesion.flush()
        return nueva

    return crear


@pytest.fixture
def firmada(atencion):
    return atencion(fecha_atencion=date(2026, 11, 10))


@pytest.fixture
def borrador(atencion):
    return atencion(EstadoAtencion.BORRADOR, fecha_atencion=date(2026, 11, 12))


@pytest.fixture
def otro_residente(sesion):
    otro = Residente(
        codigo="RES-02",
        nombres="Sofía",
        apellidos="Pérez",
        fecha_nacimiento=date(2022, 3, 2),
        nivel=Nivel.HETEROGENEO,
    )
    sesion.add(otro)
    sesion.flush()
    return otro


def antecedente(sesion, residente, tipo, descripcion, atencion=None, fecha=None):
    nuevo = Antecedente(
        residente_id=residente.id,
        atencion_id=atencion.id if atencion else None,
        tipo=tipo,
        descripcion=descripcion,
        fecha=fecha,
    )
    sesion.add(nuevo)
    sesion.flush()
    return nuevo


def descripciones(antecedentes):
    return [a.descripcion for a in antecedentes]


# Resumen


def test_una_ficha_sin_datos_tiene_un_resumen_vacio(sesion, residente):
    resumen = resumen_de_ficha(sesion, residente.id, HOY)

    assert resumen.residente.id == residente.id
    assert resumen.alergias == resumen.diagnosticos == []
    assert resumen.hospitalizaciones == resumen.vacunas == []
    assert resumen.tratamientos_activos == resumen.proximos_controles == []
    assert resumen.ultima_medicion is None


def test_un_residente_que_no_existe_no_tiene_ficha(sesion):
    with pytest.raises(LookupError):
        resumen_de_ficha(sesion, 999, HOY)


def test_los_antecedentes_se_agrupan_por_tipo(sesion, residente, firmada):
    antecedente(sesion, residente, TipoAntecedente.ALERGIA, "Penicilina", firmada)
    antecedente(sesion, residente, TipoAntecedente.DIAGNOSTICO_CRONICO, "Asma", firmada)
    antecedente(sesion, residente, TipoAntecedente.HOSPITALIZACION, "Bronquiolitis", firmada)
    antecedente(sesion, residente, TipoAntecedente.VACUNA, "Influenza 2026", firmada)
    antecedente(sesion, residente, TipoAntecedente.PERINATAL, "Prematuro", firmada)

    resumen = resumen_de_ficha(sesion, residente.id, HOY)

    assert descripciones(resumen.alergias) == ["Penicilina"]
    assert descripciones(resumen.diagnosticos) == ["Asma"]
    assert descripciones(resumen.hospitalizaciones) == ["Bronquiolitis"]
    assert descripciones(resumen.vacunas) == ["Influenza 2026"]


def test_los_antecedentes_van_del_mas_reciente_al_mas_antiguo(sesion, residente, firmada):
    alergia = TipoAntecedente.ALERGIA
    antecedente(sesion, residente, alergia, "Sin fecha", firmada)
    antecedente(sesion, residente, alergia, "Antigua", firmada, date(2025, 1, 5))
    antecedente(sesion, residente, alergia, "Reciente", firmada, date(2026, 10, 1))

    resumen = resumen_de_ficha(sesion, residente.id, HOY)

    assert descripciones(resumen.alergias) == ["Reciente", "Antigua", "Sin fecha"]


def test_un_antecedente_registrado_sin_atencion_es_confirmado(sesion, residente):
    antecedente(sesion, residente, TipoAntecedente.ALERGIA, "Látex")

    assert descripciones(resumen_de_ficha(sesion, residente.id, HOY).alergias) == ["Látex"]


def test_el_resumen_nunca_muestra_datos_de_una_atencion_sin_firmar(sesion, residente, borrador):
    antecedente(sesion, residente, TipoAntecedente.ALERGIA, "Penicilina", borrador)
    sesion.add_all(
        [
            Tratamiento(
                residente_id=residente.id, atencion_id=borrador.id, medicamento="salbutamol"
            ),
            Control(residente_id=residente.id, atencion_id=borrador.id, fecha=date(2026, 12, 1)),
            Medicion(
                residente_id=residente.id,
                atencion_id=borrador.id,
                fecha=date(2026, 11, 12),
                peso_kg=14.2,
            ),
        ]
    )
    sesion.flush()

    resumen = resumen_de_ficha(sesion, residente.id, HOY)

    assert resumen.alergias == []
    assert resumen.tratamientos_activos == []
    assert resumen.proximos_controles == []
    assert resumen.ultima_medicion is None


def test_el_resumen_no_mezcla_residentes(sesion, residente, otro_residente, atencion):
    del_otro = atencion(residente_id=otro_residente.id, fecha_atencion=date(2026, 11, 1))
    antecedente(sesion, otro_residente, TipoAntecedente.ALERGIA, "Maní", del_otro)
    sesion.add(
        Medicion(residente_id=otro_residente.id, atencion_id=del_otro.id, peso_kg=20.0)
    )
    sesion.flush()

    resumen = resumen_de_ficha(sesion, residente.id, HOY)

    assert resumen.alergias == []
    assert resumen.ultima_medicion is None


def test_solo_aparecen_los_tratamientos_vigentes(sesion, residente, firmada):
    def tratamiento(medicamento, **datos):
        return Tratamiento(
            residente_id=residente.id, atencion_id=firmada.id, medicamento=medicamento, **datos
        )

    sesion.add_all(
        [
            tratamiento("salbutamol"),
            tratamiento("amoxicilina", fecha_termino=date(2026, 11, 16)),  # terminó ayer
            tratamiento("paracetamol", estado=EstadoTratamiento.SUSPENDIDO),
            tratamiento("budesonida", fecha_termino=HOY),  # termina hoy: sigue vigente
        ]
    )
    sesion.flush()

    resumen = resumen_de_ficha(sesion, residente.id, HOY)

    assert {t.medicamento for t in resumen.tratamientos_activos} == {"salbutamol", "budesonida"}


def test_la_ultima_medicion_es_la_mas_reciente(sesion, residente, firmada):
    def medicion(fecha, peso):
        nueva = Medicion(
            residente_id=residente.id, atencion_id=firmada.id, fecha=fecha, peso_kg=peso
        )
        sesion.add(nueva)
        sesion.flush()
        return nueva

    medicion(date(2026, 9, 1), 13.0)
    medicion(None, 99.0)  # sin fecha: nunca gana a una con fecha
    medicion(date(2026, 11, 10), 13.8)
    ultima = medicion(date(2026, 11, 10), 14.1)  # mismo día: gana la registrada después

    assert resumen_de_ficha(sesion, residente.id, HOY).ultima_medicion.id == ultima.id


def test_los_proximos_controles_son_los_pendientes_en_orden(sesion, residente, firmada):
    def control(fecha, estado=EstadoControl.PENDIENTE, descripcion=None):
        return Control(
            residente_id=residente.id,
            atencion_id=firmada.id,
            fecha=fecha,
            descripcion=descripcion,
            estado=estado,
        )

    sesion.add_all(
        [
            control(None, descripcion="Sin fecha"),
            control(date(2026, 12, 20), descripcion="Diciembre"),
            control(date(2026, 11, 1), descripcion="Atrasado"),
            control(date(2026, 11, 25), EstadoControl.REALIZADO, "Realizado"),
            control(date(2026, 11, 30), descripcion="Fin de mes"),
        ]
    )
    sesion.flush()

    controles = resumen_de_ficha(sesion, residente.id, HOY).proximos_controles

    assert [c.descripcion for c in controles] == ["Atrasado", "Fin de mes", "Diciembre", "Sin fecha"]


# Historial


def test_el_historial_tiene_solo_atenciones_firmadas(sesion, residente, firmada, borrador):
    assert historial(sesion, residente.id) == [firmada]


def test_el_historial_va_de_la_mas_reciente_a_la_mas_antigua(sesion, residente, atencion):
    sin_fecha = atencion(origen=OrigenAtencion.HISTORICO)  # documento sin fecha conocida
    antigua = atencion(fecha_atencion=date(2025, 6, 3), origen=OrigenAtencion.HISTORICO)
    temprano = atencion(
        fecha_atencion=date(2026, 11, 10),
        firmada_en=datetime(2026, 11, 10, 12, 0, tzinfo=UTC),
        origen=OrigenAtencion.TELEGRAM,
    )
    tarde = atencion(
        fecha_atencion=date(2026, 11, 10),
        firmada_en=datetime(2026, 11, 10, 18, 0, tzinfo=UTC),
        origen=OrigenAtencion.WHATSAPP,
    )
    reciente = atencion(fecha_atencion=date(2026, 11, 15))

    assert historial(sesion, residente.id) == [reciente, tarde, temprano, antigua, sin_fecha]


def test_el_historial_no_mezcla_residentes(sesion, residente, otro_residente, atencion):
    propia = atencion(fecha_atencion=date(2026, 11, 1))
    atencion(residente_id=otro_residente.id, fecha_atencion=date(2026, 11, 2))

    assert historial(sesion, residente.id) == [propia]
