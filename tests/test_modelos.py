from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError, StatementError

from app.modelos import EventoAuditoria, Profesional, TipoActor, VinculoCanal

# Auditoría solo de inserción


def test_un_evento_de_auditoria_no_se_puede_modificar(sesion):
    evento = EventoAuditoria(actor_tipo=TipoActor.SISTEMA, accion="prueba")
    sesion.add(evento)
    sesion.commit()

    evento.accion = "modificada"
    with pytest.raises(DBAPIError, match="solo de inserción"):
        sesion.commit()


def test_un_evento_de_auditoria_no_se_puede_borrar(sesion):
    sesion.add(EventoAuditoria(actor_tipo=TipoActor.SISTEMA, accion="prueba"))
    sesion.commit()

    with pytest.raises(DBAPIError, match="solo de inserción"):
        sesion.execute(text("DELETE FROM eventos_auditoria"))
    sesion.rollback()

    assert sesion.scalar(select(func.count()).select_from(EventoAuditoria)) == 1


# Vínculos


def test_una_cuenta_no_puede_tener_dos_vinculos_activos(sesion, profesional):
    sesion.add(VinculoCanal(profesional_id=profesional.id, canal="telegram", id_externo="55667788"))
    sesion.commit()

    sesion.add(VinculoCanal(profesional_id=profesional.id, canal="telegram", id_externo="55667788"))
    with pytest.raises(IntegrityError):
        sesion.commit()


def test_una_cuenta_revocada_se_puede_volver_a_vincular(sesion, profesional):
    sesion.add(
        VinculoCanal(
            profesional_id=profesional.id,
            canal="telegram",
            id_externo="55667788",
            activo=False,
            revocado_en=datetime.now(UTC),
        )
    )
    sesion.add(VinculoCanal(profesional_id=profesional.id, canal="telegram", id_externo="55667788"))
    sesion.commit()

    assert sesion.scalar(select(func.count()).select_from(VinculoCanal)) == 2


# Fechas


def test_las_fechas_se_guardan_en_utc_y_vuelven_con_zona_horaria(sesion):
    hora_chile = datetime(2026, 11, 2, 12, 40, tzinfo=timezone(timedelta(hours=-3)))
    profesional = Profesional(nombre="Prueba", especialidad="pediatría", creado_en=hora_chile)
    sesion.add(profesional)
    sesion.commit()
    sesion.expire_all()  # obliga a leer de nuevo desde la base de datos

    leido = sesion.get(Profesional, profesional.id)

    assert leido.creado_en == datetime(2026, 11, 2, 15, 40, tzinfo=UTC)
    assert leido.creado_en.tzinfo == UTC


def test_una_fecha_sin_zona_horaria_se_rechaza(sesion):
    sesion.add(
        Profesional(nombre="Prueba", especialidad="pediatría", creado_en=datetime(2026, 11, 2))
    )

    with pytest.raises(StatementError, match="zona horaria"):
        sesion.commit()
