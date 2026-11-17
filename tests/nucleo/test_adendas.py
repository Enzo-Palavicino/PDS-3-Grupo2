import pytest
from sqlalchemy import select

from app.modelos import (
    Antecedente,
    Atencion,
    Control,
    EstadoAtencion,
    EstadoControl,
    EstadoTratamiento,
    EventoAuditoria,
    Medicion,
    OrigenAtencion,
    Profesional,
    Rol,
    Tratamiento,
    UsuarioWeb,
)
from app.nucleo.adendas import (
    AtencionYaCorregida,
    CorreccionEnCurso,
    adenda_en_curso,
    correcciones_de,
    crear_adenda,
    ultima_version,
)
from app.nucleo.atenciones import (
    ErrorDeAtencion,
    actualizar_atencion,
    crear_atencion,
    firmar_atencion,
    verificar_integridad,
)
from app.seguridad import hashear_password

PASSWORD = "clave-de-la-pediatra"
CAMPOS = {
    "fecha_atencion": {"valor": "2026-11-02", "fragmento": None},
    "motivo": {"valor": "Control pediátrico", "fragmento": None},
    "indicaciones_farmacologicas": [{"medicamento": "salbutamol", "dosis": "dos puff"}],
    "proximo_control": {"fecha": "2026-11-16", "descripcion": "Control en dos semanas"},
    "alergias": [{"valor": "penicilina", "fragmento": None}],
    "mediciones": {"peso_kg": 9.8, "talla_cm": 74, "fragmento": None},
}


def usuario_web(sesion, nombre: str, profesional_id: int) -> UsuarioWeb:
    usuario = UsuarioWeb(
        usuario=nombre,
        rol=Rol.PROFESIONAL,
        profesional_id=profesional_id,
        hash_password=hashear_password(PASSWORD),
    )
    sesion.add(usuario)
    sesion.commit()
    return usuario


@pytest.fixture
def autor(sesion, profesional) -> UsuarioWeb:
    return usuario_web(sesion, "pediatra", profesional.id)


@pytest.fixture
def original(sesion, residente, autor) -> Atencion:
    """Atención firmada: deja salbutamol activo y un control pendiente en la ficha."""
    atencion = crear_atencion(sesion, residente.id, autor, CAMPOS, OrigenAtencion.WHATSAPP)
    firmar_atencion(sesion, atencion, autor, PASSWORD)
    sesion.commit()
    return atencion


CAMBIO_DE_MEDICAMENTO = {
    "indicaciones_farmacologicas": [{"medicamento": "amoxicilina", "dosis": "5 ml"}],
    "proximo_control": {"fecha": "2026-11-09", "descripcion": "Control en una semana"},
}


def corregir(sesion, original, autor, cambios=CAMBIO_DE_MEDICAMENTO) -> Atencion:
    """Crea la adenda con esos cambios respecto de la original y la firma."""
    adenda = crear_adenda(sesion, original, autor, "Medicamento equivocado")
    actualizar_atencion(sesion, adenda, {**adenda.campos, **cambios}, autor)
    firmar_atencion(sesion, adenda, autor, PASSWORD)
    sesion.commit()
    return adenda


def test_la_adenda_parte_con_una_copia_de_la_original(sesion, original, autor):
    adenda = crear_adenda(sesion, original, autor, "  Medicamento equivocado ")

    assert adenda.estado == EstadoAtencion.BORRADOR
    assert adenda.corrige_a_id == original.id
    assert adenda.motivo_correccion == "Medicamento equivocado"
    assert adenda.campos == original.campos
    assert adenda.fecha_atencion == original.fecha_atencion
    assert adenda.campos_editados == []
    assert adenda_en_curso(sesion, original) == adenda
    [evento] = sesion.scalars(
        select(EventoAuditoria).where(
            EventoAuditoria.accion == "atencion_creada",
            EventoAuditoria.entidad_id == str(adenda.id),
        )
    )
    assert evento.detalle["corrige_a"] == original.id


def test_lo_editado_se_mide_contra_la_original(sesion, original, autor):
    adenda = corregir(sesion, original, autor)

    assert adenda.campos_editados == ["indicaciones_farmacologicas", "proximo_control"]


def test_al_firmar_la_adenda_la_ficha_reemplaza_lo_corregido(sesion, original, autor):
    adenda = corregir(sesion, original, autor)

    tratamientos = {t.medicamento: t for t in sesion.scalars(select(Tratamiento))}
    assert tratamientos["salbutamol"].estado == EstadoTratamiento.SUSPENDIDO
    assert tratamientos["salbutamol"].motivo_suspension == f"Corregido por la atención #{adenda.id}"
    assert tratamientos["salbutamol"].suspendido_por == autor.id
    assert tratamientos["amoxicilina"].estado == EstadoTratamiento.ACTIVO
    controles = {c.atencion_id: c.estado for c in sesion.scalars(select(Control))}
    assert controles == {original.id: EstadoControl.ANULADO, adenda.id: EstadoControl.PENDIENTE}


def test_la_original_no_cambia_y_sigue_integra(sesion, original, autor):
    campos_originales = dict(original.campos)

    adenda = corregir(sesion, original, autor)
    sesion.expire_all()
    leida = sesion.get(Atencion, original.id)

    assert leida.estado == EstadoAtencion.FIRMADA
    assert leida.campos == campos_originales
    assert verificar_integridad(leida)
    assert verificar_integridad(sesion.get(Atencion, adenda.id))
    assert correcciones_de(sesion, leida) == [sesion.get(Atencion, adenda.id)]
    assert adenda_en_curso(sesion, leida) is None


def test_una_adenda_sin_firmar_no_cuenta_como_correccion(sesion, original, autor):
    crear_adenda(sesion, original, autor, "Medicamento equivocado")

    assert correcciones_de(sesion, original) == []


@pytest.mark.parametrize("motivo", ["", "   ", None])
def test_corregir_exige_un_motivo(sesion, original, autor, motivo):
    with pytest.raises(ErrorDeAtencion, match="motivo"):
        crear_adenda(sesion, original, autor, motivo)


def test_una_atencion_sin_firmar_se_edita_no_se_corrige(sesion, residente, autor):
    borrador = crear_atencion(sesion, residente.id, autor, CAMPOS, OrigenAtencion.WEB)

    with pytest.raises(ErrorDeAtencion, match="Solo se corrige una atención firmada"):
        crear_adenda(sesion, borrador, autor, "Medicamento equivocado")


def test_solo_el_autor_corrige(sesion, original):
    otro = Profesional(nombre="Otra profesional", especialidad="nutrición")
    sesion.add(otro)
    sesion.commit()

    with pytest.raises(ErrorDeAtencion, match="Solo el profesional"):
        crear_adenda(sesion, original, usuario_web(sesion, "nutricionista", otro.id), "Error")


def test_no_se_abren_dos_correcciones_a_la_vez(sesion, original, autor):
    en_curso = crear_adenda(sesion, original, autor, "Medicamento equivocado")

    with pytest.raises(CorreccionEnCurso) as error:
        crear_adenda(sesion, original, autor, "Otro motivo")

    assert error.value.adenda == en_curso


# Lo que reportó la revisión del PR #30


def test_corregir_una_dosis_no_duplica_la_alergia_ni_la_medicion(sesion, original, autor):
    adenda = corregir(
        sesion,
        original,
        autor,
        {"indicaciones_farmacologicas": [{"medicamento": "salbutamol", "dosis": "un puff"}]},
    )

    alergias = list(sesion.scalars(select(Antecedente)))
    assert [(a.descripcion, a.atencion_id) for a in alergias] == [("penicilina", adenda.id)]
    assert [m.atencion_id for m in sesion.scalars(select(Medicion))] == [adenda.id]


def test_corregir_una_alergia_mal_registrada_deja_solo_la_correcta(sesion, original, autor):
    corregir(sesion, original, autor, {"alergias": [{"valor": "amoxicilina", "fragmento": None}]})

    assert list(sesion.scalars(select(Antecedente.descripcion))) == ["amoxicilina"]


def test_no_se_corrige_dos_veces_la_misma_atencion(sesion, original, autor):
    primera = corregir(sesion, original, autor)

    with pytest.raises(AtencionYaCorregida) as error:
        crear_adenda(sesion, original, autor, "Otro error")

    assert error.value.ultima == primera


def test_en_una_cadena_solo_queda_vigente_lo_de_la_ultima_version(sesion, original, autor):
    primera = corregir(sesion, original, autor)
    segunda = corregir(
        sesion,
        primera,
        autor,
        {"indicaciones_farmacologicas": [{"medicamento": "cefadroxilo", "dosis": "4 ml"}]},
    )

    estados = {t.medicamento: t.estado for t in sesion.scalars(select(Tratamiento))}
    assert estados == {
        "salbutamol": EstadoTratamiento.SUSPENDIDO,
        "amoxicilina": EstadoTratamiento.SUSPENDIDO,
        "cefadroxilo": EstadoTratamiento.ACTIVO,
    }
    assert ultima_version(sesion, original) == segunda
    assert [a.atencion_id for a in sesion.scalars(select(Antecedente))] == [segunda.id]


def test_la_original_se_bloquea_antes_de_revisar_las_correcciones(
    sesion, original, autor, monkeypatch
):
    # Con FOR UPDATE, dos envíos simultáneos en PostgreSQL esperan uno al otro.
    bloqueos = []
    refrescar = sesion.refresh

    def espiar(objeto, *args, **kwargs):
        bloqueos.append((objeto, kwargs.get("with_for_update")))
        return refrescar(objeto, *args, **kwargs)

    monkeypatch.setattr(sesion, "refresh", espiar)

    crear_adenda(sesion, original, autor, "Medicamento equivocado")

    assert bloqueos[0] == (original, True)
