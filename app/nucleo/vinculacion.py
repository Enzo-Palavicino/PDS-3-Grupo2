"""Vinculación de cuentas de mensajería con profesionales.

La directora genera un código de un solo uso para un profesional. El profesional lo canjea
abriendo el enlace del bot, que envía "/start <código>", y desde ese momento su cuenta queda
autorizada para enviar registros. Revocar el vínculo lo desactiva de inmediato.
"""

import secrets
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db import ahora
from app.modelos import CodigoVinculacion, TipoActor, VinculoCanal
from app.nucleo.auditoria import Accion, registrar_evento

VIGENCIA_CODIGO = timedelta(minutes=10)


def generar_codigo(
    sesion: Session, profesional_id: int, creado_por: int | None = None
) -> CodigoVinculacion:
    """Crea un código de un solo uso que vence en 10 minutos.

    creado_por es el usuario web que lo pidió, o None si se generó desde la consola.
    """
    codigo = CodigoVinculacion(
        # token_urlsafe usa solo A-Z, a-z, 0-9, "_" y "-", los caracteres que Telegram acepta en
        # los enlaces ?start=. Con 24 bytes aleatorios da 32 caracteres: imposible de adivinar.
        codigo=secrets.token_urlsafe(24),
        profesional_id=profesional_id,
        creado_por=creado_por,
        expira_en=ahora() + VIGENCIA_CODIGO,
    )
    sesion.add(codigo)
    registrar_evento(
        sesion,
        Accion.CODIGO_GENERADO,
        actor_tipo=TipoActor.USUARIO if creado_por else TipoActor.SISTEMA,
        actor_id=creado_por,
        entidad="profesional",
        entidad_id=profesional_id,
    )
    return codigo


def canjear_codigo(
    sesion: Session, canal: str, id_externo: str, codigo: str
) -> VinculoCanal | None:
    """Vincula la cuenta (canal, id_externo) con el profesional del código.

    Devuelve el vínculo creado, o None si el código no existe, ya se usó o venció.
    """
    momento = ahora()
    # El código se marca como usado en una sola operación que exige que siga sin usar y vigente.
    # Si dos personas lo canjean a la vez, solo una lo logra (la otra modifica 0 filas).
    marcado = sesion.execute(
        update(CodigoVinculacion)
        .where(
            CodigoVinculacion.codigo == codigo,
            CodigoVinculacion.usado_en.is_(None),
            CodigoVinculacion.expira_en > momento,
        )
        .values(usado_en=momento)
    )
    if marcado.rowcount != 1:
        registrar_evento(
            sesion,
            Accion.CODIGO_RECHAZADO,
            actor_tipo=TipoActor.SISTEMA,
            detalle={"canal": canal, "id_externo": id_externo},
        )
        return None

    profesional_id = sesion.scalar(
        select(CodigoVinculacion.profesional_id).where(CodigoVinculacion.codigo == codigo)
    )
    anterior = buscar_vinculo_activo(sesion, canal, id_externo)
    if anterior is not None:
        # La cuenta ya estaba vinculada (por ejemplo, a otro profesional): ese vínculo se cierra.
        revocar_vinculo(sesion, anterior, actor_tipo=TipoActor.SISTEMA)
        sesion.flush()  # la desactivación tiene que quedar antes de crear el vínculo nuevo

    vinculo = VinculoCanal(profesional_id=profesional_id, canal=canal, id_externo=id_externo)
    sesion.add(vinculo)
    sesion.flush()  # asigna vinculo.id, que va en la auditoría
    registrar_evento(
        sesion,
        Accion.VINCULO_CREADO,
        actor_tipo=TipoActor.PROFESIONAL,
        actor_id=profesional_id,
        entidad="vinculo",
        entidad_id=vinculo.id,
        detalle={"canal": canal},
    )
    return vinculo


def buscar_vinculo_activo(sesion: Session, canal: str, id_externo: str) -> VinculoCanal | None:
    return sesion.scalar(
        select(VinculoCanal).where(
            VinculoCanal.canal == canal,
            VinculoCanal.id_externo == id_externo,
            VinculoCanal.activo,
        )
    )


def revocar_vinculo(
    sesion: Session, vinculo: VinculoCanal, actor_tipo: TipoActor, actor_id: int | None = None
) -> None:
    """Desactiva el vínculo de inmediato. Lo que la cuenta envió antes conserva su autoría."""
    vinculo.activo = False
    vinculo.revocado_en = ahora()
    registrar_evento(
        sesion,
        Accion.VINCULO_REVOCADO,
        actor_tipo=actor_tipo,
        actor_id=actor_id,
        entidad="vinculo",
        entidad_id=vinculo.id,
        detalle={"canal": vinculo.canal},
    )
