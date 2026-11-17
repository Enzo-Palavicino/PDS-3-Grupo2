"""Pruebas contra un PostgreSQL real, como el del servidor.

Solo corren si está definida TEST_POSTGRES_URL (en el CI, un PostgreSQL en un contenedor).
Revisan lo que cambia respecto de SQLite: las migraciones, el trigger de auditoría, los SAVEPOINT,
el índice único parcial de los vínculos y el largo máximo de los textos (SQLite no lo controla).
"""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier

import pytest
from alembic import command
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.db import crear_fabrica_de_sesiones, crear_motor
from app.modelos import (
    Atencion,
    BorradorAtencion,
    EstadoDocumento,
    EventoAuditoria,
    MensajeEntrante,
    Profesional,
    TipoActor,
    UsuarioWeb,
    VinculoCanal,
)
from app.nucleo.documentos import subir_documento
from app.nucleo.mensajes import registrar_mensaje_entrante
from app.nucleo.revision_documentos import (
    DocumentoDuplicado,
    DocumentoNoRevisable,
    verificar_documento,
)
from scripts.sembrar_datos import sembrar
from tests.nucleo.test_digitalizacion import CAMPOS
from tests.test_migraciones import insertar_datos_previos_a_la_0004
from tests.web.test_web_adjuntos import PNG

URL = os.environ.get("TEST_POSTGRES_URL")

pytestmark = pytest.mark.skipif(not URL, reason="sin TEST_POSTGRES_URL")


@pytest.fixture
def fabrica_postgres(configurar_alembic):
    configuracion = configurar_alembic(URL)
    command.downgrade(configuracion, "base")  # parte de una base de datos vacía
    command.upgrade(configuracion, "head")
    motor = crear_motor(URL)
    yield crear_fabrica_de_sesiones(motor)
    motor.dispose()
    command.downgrade(configuracion, "base")


@pytest.fixture
def profesional_postgres(fabrica_postgres) -> int:
    with fabrica_postgres.begin() as sesion:
        profesional = Profesional(nombre="Profesional de prueba", especialidad="pediatría")
        sesion.add(profesional)
        sesion.flush()
        return profesional.id


def test_los_modelos_coinciden_con_las_migraciones(fabrica_postgres, configurar_alembic):
    command.check(configurar_alembic(URL))


@pytest.mark.parametrize("mismo_documento", [True, False])
def test_verificacion_concurrente_no_duplica_historicos(fabrica_postgres, mismo_documento):
    with fabrica_postgres.begin() as sesion:
        sembrar(sesion, "clave-de-prueba")
        usuario = sesion.scalar(select(UsuarioWeb).where(UsuarioWeb.usuario == "encargada_salud"))
        ids = []
        for _ in range(2):
            documento = subir_documento(
                sesion, 2, PNG, "original.png", "Registro", usuario, date(2026, 8, 12)
            )
            documento.estado = EstadoDocumento.POR_REVISAR
            documento.campos = CAMPOS
            ids.append(documento.id)
    if mismo_documento:
        ids[1] = ids[0]
    inicio = Barrier(2)

    def intentar(documento_id):
        inicio.wait(timeout=10)
        try:
            with fabrica_postgres.begin() as sesion:
                verificar_documento(
                    sesion, documento_id, usuario, CAMPOS, "Dra. Ficticia", True
                )
            return "incorporado"
        except (DocumentoDuplicado, DocumentoNoRevisable):
            return "rechazado"

    with ThreadPoolExecutor(max_workers=2) as hilos:
        resultados = list(hilos.map(intentar, ids))
    assert sorted(resultados) == ["incorporado", "rechazado"]
    with fabrica_postgres() as sesion:
        assert sesion.scalar(select(func.count()).select_from(Atencion)) == 1
        assert sesion.scalar(select(func.count()).select_from(EventoAuditoria).where(
            EventoAuditoria.accion == "documento_incorporado"
        )) == 1


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE eventos_auditoria SET accion = 'modificada'",
        "DELETE FROM eventos_auditoria",
        "TRUNCATE eventos_auditoria",
    ],
)
def test_la_auditoria_es_solo_de_insercion(fabrica_postgres, sql):
    with fabrica_postgres.begin() as sesion:
        sesion.add(EventoAuditoria(actor_tipo=TipoActor.SISTEMA, accion="prueba"))

    with fabrica_postgres() as sesion, pytest.raises(DBAPIError, match="solo de inserción"):
        sesion.execute(text(sql))

    with fabrica_postgres() as sesion:
        assert sesion.scalar(select(func.count()).select_from(EventoAuditoria)) == 1


def test_un_mensaje_duplicado_no_crea_otra_fila(
    fabrica_postgres, profesional_postgres, crear_mensaje
):
    with fabrica_postgres.begin() as sesion:
        assert registrar_mensaje_entrante(sesion, crear_mensaje(), profesional_postgres)
        assert registrar_mensaje_entrante(sesion, crear_mensaje(), profesional_postgres) is None

    with fabrica_postgres() as sesion:
        assert sesion.scalar(select(func.count()).select_from(MensajeEntrante)) == 1


def test_una_cuenta_no_puede_tener_dos_vinculos_activos(fabrica_postgres, profesional_postgres):
    def vincular(activo: bool) -> None:
        with fabrica_postgres.begin() as sesion:
            sesion.add(
                VinculoCanal(
                    profesional_id=profesional_postgres,
                    canal="telegram",
                    id_externo="55667788",
                    activo=activo,
                )
            )

    vincular(activo=False)  # un vínculo revocado no impide uno nuevo
    vincular(activo=True)
    with pytest.raises(IntegrityError):
        vincular(activo=True)


@pytest.mark.parametrize("largo", [80, 255])  # 80: lo que mide un wamid de WhatsApp en Android
def test_guarda_ids_de_whatsapp_largos(
    fabrica_postgres, profesional_postgres, crear_mensaje, largo
):
    def wamid(relleno: str) -> str:
        return "wamid." + relleno * (largo - len("wamid."))

    with fabrica_postgres.begin() as sesion:
        mensaje = registrar_mensaje_entrante(
            sesion,
            crear_mensaje(
                canal="whatsapp", id_externo=wamid("A"), responde_a_id_externo=wamid("B")
            ),
            profesional_postgres,
        )
        borrador = BorradorAtencion(
            profesional_id=profesional_postgres, canal="whatsapp", mensaje_bot_id_externo=wamid("C")
        )
        sesion.add(borrador)

    with fabrica_postgres() as sesion:
        guardado = sesion.get(MensajeEntrante, mensaje.id)
        assert (guardado.id_externo, guardado.responde_a) == (wamid("A"), wamid("B"))
        assert sesion.get(BorradorAtencion, borrador.id).mensaje_bot_id_externo == wamid("C")

    # Con ids de más de 64 caracteres guardados, la migración 0003 no se puede revertir, y la
    # fixture revierte todas al terminar.
    with fabrica_postgres.begin() as sesion:
        sesion.execute(delete(BorradorAtencion))
        sesion.execute(delete(MensajeEntrante))


def test_la_0004_deja_activos_los_residentes_que_ya_existian(configurar_alembic):
    # Como en el servidor de Render: ya hay residentes y profesionales cuando se aplica la 0004.
    configuracion = configurar_alembic(URL)
    command.downgrade(configuracion, "base")
    command.upgrade(configuracion, "0003")
    motor = crear_motor(URL)
    try:
        insertar_datos_previos_a_la_0004(motor)
        command.upgrade(configuracion, "head")
        with motor.connect() as conexion:
            assert conexion.execute(text("SELECT codigo, estado FROM residentes")).one() == (
                "RES-01",
                "activo",
            )
    finally:
        motor.dispose()
        command.downgrade(configuracion, "base")
