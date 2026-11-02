import json

from sqlalchemy import func, select

from app.canales.base import Ignorado
from app.modelos import (
    EstadoMensaje,
    EventoAuditoria,
    MensajeEntrante,
    TipoActor,
    VinculoCanal,
)
from app.nucleo import textos
from app.nucleo.auditoria import Accion
from app.nucleo.ingesta import (
    TAMANO_MAXIMO_AUDIO_BYTES,
    Respuesta,
    enviar_respuestas,
    ingerir,
    procesar_mensaje,
)
from app.nucleo.vinculacion import (
    buscar_vinculo_activo,
    generar_codigo,
    revocar_vinculo,
)


def vincular(sesion, profesional) -> VinculoCanal:
    vinculo = VinculoCanal(profesional_id=profesional.id, canal="telegram", id_externo="55667788")
    sesion.add(vinculo)
    sesion.commit()
    return vinculo


def textos_de(respuestas: list[Respuesta]) -> list[str]:
    return [respuesta.texto for respuesta in respuestas]


def contar_mensajes(sesion) -> int:
    return sesion.scalar(select(func.count()).select_from(MensajeEntrante))


# Vinculación


def test_start_sin_codigo_explica_como_vincularse(sesion, crear_mensaje):
    respuestas = procesar_mensaje(sesion, crear_mensaje(tipo="comando", texto="/start"))

    assert textos_de(respuestas) == [textos.START_SIN_CODIGO]


def test_start_con_un_codigo_valido_vincula_la_cuenta(sesion, profesional, crear_mensaje):
    codigo = generar_codigo(sesion, profesional.id).codigo
    sesion.commit()

    respuestas = procesar_mensaje(sesion, crear_mensaje(tipo="comando", texto=f"/start {codigo}"))
    sesion.commit()

    assert textos_de(respuestas) == [textos.VINCULACION_EXITOSA]
    assert buscar_vinculo_activo(sesion, "telegram", "55667788").profesional_id == profesional.id


def test_start_con_un_codigo_invalido(sesion, crear_mensaje):
    respuestas = procesar_mensaje(sesion, crear_mensaje(tipo="comando", texto="/start inventado"))

    assert textos_de(respuestas) == [textos.CODIGO_INVALIDO]


# Autorización


def test_un_remitente_no_vinculado_se_rechaza_sin_guardar_su_mensaje(sesion, crear_mensaje):
    respuestas = procesar_mensaje(sesion, crear_mensaje(texto="Texto de prueba"))
    sesion.commit()

    assert textos_de(respuestas) == [textos.NO_AUTORIZADO]
    assert contar_mensajes(sesion) == 0
    evento = sesion.scalar(select(EventoAuditoria))
    assert evento.accion == Accion.MENSAJE_RECHAZADO
    assert "Texto de prueba" not in json.dumps(evento.detalle)


def test_un_vinculo_revocado_ya_no_puede_enviar_registros(sesion, profesional, crear_mensaje):
    vinculo = vincular(sesion, profesional)
    revocar_vinculo(sesion, vinculo, actor_tipo=TipoActor.USUARIO, actor_id=1)
    sesion.commit()

    respuestas = procesar_mensaje(sesion, crear_mensaje())

    assert textos_de(respuestas) == [textos.NO_AUTORIZADO]


# Mensajes de un profesional vinculado


def test_un_texto_se_guarda_y_se_confirma(sesion, profesional, crear_mensaje):
    vincular(sesion, profesional)

    respuestas = procesar_mensaje(sesion, crear_mensaje())
    sesion.commit()

    assert respuestas == [Respuesta("55667788", textos.RECIBIDO, responder_a="55667788:412")]
    fila = sesion.scalar(select(MensajeEntrante))
    assert fila.estado == EstadoMensaje.RECIBIDO
    assert fila.profesional_id == profesional.id
    acciones = sesion.scalars(select(EventoAuditoria.accion)).all()
    assert acciones == [Accion.MENSAJE_RECIBIDO]


def test_un_audio_se_guarda_con_su_referencia(sesion, profesional, crear_mensaje):
    vincular(sesion, profesional)

    respuestas = procesar_mensaje(
        sesion, crear_mensaje(tipo="audio", texto=None, audio_ref="AwAC", audio_tamano_bytes=28417)
    )
    sesion.commit()

    assert textos_de(respuestas) == [textos.RECIBIDO]
    assert sesion.scalar(select(MensajeEntrante.audio_ref)) == "AwAC"


def test_un_mensaje_duplicado_no_se_guarda_ni_se_responde_otra_vez(
    sesion, profesional, crear_mensaje
):
    vincular(sesion, profesional)

    assert textos_de(procesar_mensaje(sesion, crear_mensaje())) == [textos.RECIBIDO]
    assert procesar_mensaje(sesion, crear_mensaje()) == []
    sesion.commit()

    assert contar_mensajes(sesion) == 1


def test_un_tipo_no_soportado_se_avisa_y_no_se_guarda(sesion, profesional, crear_mensaje):
    vincular(sesion, profesional)

    respuestas = procesar_mensaje(sesion, crear_mensaje(tipo="no_soportado", texto=None))

    assert textos_de(respuestas) == [textos.TIPO_NO_SOPORTADO]
    assert contar_mensajes(sesion) == 0


def test_un_audio_de_mas_de_20_mb_se_avisa_y_no_se_guarda(sesion, profesional, crear_mensaje):
    vincular(sesion, profesional)

    respuestas = procesar_mensaje(
        sesion,
        crear_mensaje(
            tipo="audio", texto=None, audio_ref="AwAC", audio_tamano_bytes=TAMANO_MAXIMO_AUDIO_BYTES + 1
        ),
    )

    assert textos_de(respuestas) == [textos.AUDIO_DEMASIADO_LARGO]
    assert contar_mensajes(sesion) == 0


def test_los_comandos_de_una_cuenta_vinculada_muestran_la_ayuda(sesion, profesional, crear_mensaje):
    vincular(sesion, profesional)

    for comando in ["/ayuda", "/start", "/otro"]:
        respuestas = procesar_mensaje(sesion, crear_mensaje(tipo="comando", texto=comando))
        assert textos_de(respuestas) == [textos.AYUDA]


def test_un_mensaje_ignorado_no_tiene_respuesta(sesion):
    assert procesar_mensaje(sesion, Ignorado("chat no privado")) == []


# De punta a punta, con un canal falso


def test_ingerir_guarda_en_su_propia_transaccion_y_se_envia_la_respuesta(
    fabrica_de_sesiones, sesion, profesional, crear_mensaje, canal_falso
):
    vincular(sesion, profesional)
    canal_falso.mensaje = crear_mensaje()

    enviar_respuestas(canal_falso, ingerir(fabrica_de_sesiones, canal_falso, {"update_id": 1}))

    assert canal_falso.enviados == [("55667788", textos.RECIBIDO, "55667788:412")]
    assert contar_mensajes(sesion) == 1
