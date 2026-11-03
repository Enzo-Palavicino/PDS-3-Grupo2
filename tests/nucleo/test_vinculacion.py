import json
import re
from datetime import timedelta

from sqlalchemy import select

from app.db import ahora
from app.modelos import CodigoVinculacion, EventoAuditoria, Profesional, TipoActor
from app.nucleo.auditoria import Accion
from app.nucleo.vinculacion import (
    buscar_vinculo_activo,
    canjear_codigo,
    generar_codigo,
    revocar_vinculo,
)

CUENTA = "55667788"


def nuevo_codigo(sesion, profesional_id: int) -> str:
    codigo = generar_codigo(sesion, profesional_id).codigo
    sesion.commit()
    return codigo


def test_el_codigo_solo_usa_caracteres_que_telegram_acepta(sesion, profesional):
    # Los enlaces t.me/<bot>?start=<código> admiten hasta 64 caracteres A-Z a-z 0-9 _ -
    assert re.fullmatch(r"[A-Za-z0-9_-]{1,64}", nuevo_codigo(sesion, profesional.id))


def test_canjear_un_codigo_valido_vincula_la_cuenta(sesion, profesional):
    codigo = nuevo_codigo(sesion, profesional.id)

    vinculo = canjear_codigo(sesion, "telegram", CUENTA, codigo)
    sesion.commit()

    assert vinculo.profesional_id == profesional.id
    assert buscar_vinculo_activo(sesion, "telegram", CUENTA) is vinculo
    assert sesion.get(CodigoVinculacion, codigo).usado_en is not None


def test_un_codigo_no_se_puede_usar_dos_veces(sesion, profesional):
    codigo = nuevo_codigo(sesion, profesional.id)

    assert canjear_codigo(sesion, "telegram", CUENTA, codigo) is not None
    assert canjear_codigo(sesion, "telegram", "99999999", codigo) is None
    sesion.commit()

    assert buscar_vinculo_activo(sesion, "telegram", "99999999") is None


def test_un_codigo_vencido_no_sirve(sesion, profesional):
    codigo = generar_codigo(sesion, profesional.id)
    codigo.expira_en = ahora() - timedelta(seconds=1)
    sesion.commit()

    assert canjear_codigo(sesion, "telegram", CUENTA, codigo.codigo) is None


def test_un_codigo_inexistente_no_sirve(sesion):
    assert canjear_codigo(sesion, "telegram", CUENTA, "codigo-que-no-existe") is None


def test_revocar_desactiva_el_vinculo_de_inmediato(sesion, profesional):
    vinculo = canjear_codigo(sesion, "telegram", CUENTA, nuevo_codigo(sesion, profesional.id))
    sesion.commit()

    revocar_vinculo(sesion, vinculo, actor_tipo=TipoActor.USUARIO, actor_id=1)
    sesion.commit()

    assert buscar_vinculo_activo(sesion, "telegram", CUENTA) is None
    assert vinculo.revocado_en is not None


def test_vincular_la_cuenta_a_otro_profesional_cierra_el_vinculo_anterior(sesion, profesional):
    otro = Profesional(nombre="Otro profesional", especialidad="nutrición")
    sesion.add(otro)
    sesion.commit()

    anterior = canjear_codigo(sesion, "telegram", CUENTA, nuevo_codigo(sesion, profesional.id))
    nuevo = canjear_codigo(sesion, "telegram", CUENTA, nuevo_codigo(sesion, otro.id))
    sesion.commit()

    assert anterior.activo is False
    assert buscar_vinculo_activo(sesion, "telegram", CUENTA) is nuevo
    assert nuevo.profesional_id == otro.id


def test_la_auditoria_registra_la_vinculacion_pero_no_el_codigo(sesion, profesional):
    codigo = nuevo_codigo(sesion, profesional.id)
    canjear_codigo(sesion, "telegram", CUENTA, codigo)
    canjear_codigo(sesion, "telegram", CUENTA, "codigo-falso")
    sesion.commit()

    eventos = sesion.scalars(select(EventoAuditoria).order_by(EventoAuditoria.id)).all()

    assert [evento.accion for evento in eventos] == [
        Accion.CODIGO_GENERADO,
        Accion.VINCULO_CREADO,
        Accion.CODIGO_RECHAZADO,
    ]
    # El código funciona como una contraseña temporal: no se guarda en la auditoría.
    for evento in eventos:
        assert codigo not in json.dumps(evento.detalle or {})
