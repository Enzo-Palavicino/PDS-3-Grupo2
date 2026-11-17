from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from app.modelos import (
    Atencion,
    EstadoAtencion,
    EstadoTratamiento,
    EventoAuditoria,
    OrigenAtencion,
    Rol,
    Tratamiento,
    UsuarioWeb,
)
from app.nucleo.permisos import puede_suspender_tratamiento
from app.nucleo.tratamientos import (
    ErrorDeTratamiento,
    TratamientoNoVigente,
    estado_vigente,
    suspender_tratamiento,
    tratamientos_del_residente,
)

HOY = date(2026, 11, 17)
MOMENTO = datetime(2026, 11, 17, 15, 0, tzinfo=UTC)


@pytest.fixture
def crear(sesion, residente, profesional):
    atencion = Atencion(
        residente_id=residente.id,
        profesional_id=profesional.id,
        origen=OrigenAtencion.WEB,
        estado=EstadoAtencion.FIRMADA,
    )
    sesion.add(atencion)
    sesion.flush()

    def tratamiento(medicamento: str, **datos) -> Tratamiento:
        nuevo = Tratamiento(
            residente_id=residente.id, atencion_id=atencion.id, medicamento=medicamento, **datos
        )
        sesion.add(nuevo)
        sesion.flush()
        return nuevo

    return tratamiento


@pytest.fixture
def pediatra(sesion, profesional) -> UsuarioWeb:
    usuario = UsuarioWeb(
        usuario="pediatra", rol=Rol.PROFESIONAL, profesional_id=profesional.id, hash_password="x"
    )
    sesion.add(usuario)
    sesion.commit()
    return usuario


@pytest.mark.parametrize(
    ("termino", "estado"),
    [
        (None, EstadoTratamiento.ACTIVO),
        (date(2026, 11, 17), EstadoTratamiento.ACTIVO),  # termina hoy: sigue vigente hoy
        (date(2026, 11, 16), EstadoTratamiento.TERMINADO),
    ],
)
def test_un_tratamiento_cuyo_termino_ya_paso_esta_terminado(crear, termino, estado):
    assert estado_vigente(crear("salbutamol", fecha_termino=termino), HOY) == estado


def test_un_suspendido_sigue_suspendido_aunque_tenga_fecha_futura(crear):
    tratamiento = crear(
        "salbutamol", estado=EstadoTratamiento.SUSPENDIDO, fecha_termino=date(2026, 12, 1)
    )

    assert estado_vigente(tratamiento, HOY) == EstadoTratamiento.SUSPENDIDO


def test_los_vigentes_van_aparte_del_historial_y_del_mas_reciente(sesion, residente, crear):
    antiguo = crear("amoxicilina", indicado_en=date(2026, 9, 1))
    reciente = crear("salbutamol", indicado_en=date(2026, 11, 2))
    sin_fecha = crear("vitamina D")
    terminado = crear(
        "paracetamol", indicado_en=date(2026, 10, 1), fecha_termino=date(2026, 10, 5)
    )
    suspendido = crear(
        "fierro", indicado_en=date(2026, 11, 1), estado=EstadoTratamiento.SUSPENDIDO
    )

    vigentes, historial = tratamientos_del_residente(sesion, residente.id, HOY)

    assert vigentes == [reciente, antiguo, sin_fecha]
    assert historial == [suspendido, terminado]


def test_suspender_guarda_quien_cuando_y_por_que(sesion, crear, pediatra):
    tratamiento = crear("salbutamol")

    suspender_tratamiento(sesion, tratamiento, pediatra, "  Sin síntomas hace 3 días ", MOMENTO)
    sesion.commit()

    assert tratamiento.estado == EstadoTratamiento.SUSPENDIDO
    assert tratamiento.suspendido_por == pediatra.id
    assert tratamiento.suspendido_en == MOMENTO
    assert tratamiento.motivo_suspension == "Sin síntomas hace 3 días"
    [evento] = sesion.scalars(
        select(EventoAuditoria).where(EventoAuditoria.accion == "tratamiento_suspendido")
    )
    assert evento.entidad_id == str(tratamiento.id)
    assert "Sin síntomas" not in str(evento.detalle)


@pytest.mark.parametrize("motivo", ["", "   ", None])
def test_suspender_exige_un_motivo(sesion, crear, pediatra, motivo):
    tratamiento = crear("salbutamol")

    with pytest.raises(ErrorDeTratamiento, match="motivo"):
        suspender_tratamiento(sesion, tratamiento, pediatra, motivo, MOMENTO)
    assert tratamiento.estado == EstadoTratamiento.ACTIVO


@pytest.mark.parametrize(
    "datos",
    [
        {"fecha_termino": date(2026, 11, 10)},
        {"estado": EstadoTratamiento.SUSPENDIDO},
    ],
)
def test_no_se_suspende_un_tratamiento_que_ya_no_esta_vigente(sesion, crear, pediatra, datos):
    tratamiento = crear("salbutamol", **datos)

    with pytest.raises(TratamientoNoVigente):
        suspender_tratamiento(sesion, tratamiento, pediatra, "ya no lo necesita", MOMENTO)


@pytest.mark.parametrize(
    ("rol", "puede"),
    [(Rol.PROFESIONAL, True), (Rol.ENCARGADA_SALUD, False), (Rol.DIRECTORA, False)],
)
def test_solo_un_profesional_suspende_tratamientos(rol, puede):
    assert puede_suspender_tratamiento(UsuarioWeb(usuario="x", rol=rol)) is puede
