from datetime import date

import pytest
from sqlalchemy import select

from app.modelos import (
    Adjunto,
    BorradorAtencion,
    DocumentoHistorico,
    EstadoAtencion,
    EstadoBorrador,
    EventoAuditoria,
    OrigenAtencion,
    Rol,
    TipoAdjunto,
    UsuarioWeb,
)
from app.nucleo.atenciones import (
    AtencionFirmada,
    DatosIncompletos,
    ErrorDeAtencion,
    actualizar_atencion,
    atencion_del_borrador,
    crear_atencion,
    faltantes_obligatorios,
)

CAMPOS = {
    "fecha_atencion": {"valor": "2026-11-16", "fragmento": "hoy"},
    "motivo": {"valor": "control por tos", "fragmento": "vino por tos"},
    "diagnosticos": [{"valor": "bronquitis obstructiva", "fragmento": "bronquitis obstructiva"}],
}


@pytest.fixture
def autor(sesion, profesional) -> UsuarioWeb:
    usuario = UsuarioWeb(
        usuario="pediatra", rol=Rol.PROFESIONAL, profesional_id=profesional.id, hash_password="x"
    )
    sesion.add(usuario)
    sesion.commit()
    return usuario


@pytest.fixture
def encargada(sesion) -> UsuarioWeb:
    usuario = UsuarioWeb(usuario="encargada_salud", rol=Rol.ENCARGADA_SALUD, hash_password="x")
    sesion.add(usuario)
    sesion.commit()
    return usuario


@pytest.fixture
def borrador(sesion, profesional, residente) -> BorradorAtencion:
    """Borrador de la IA, con los campos como los extrae el LLM."""
    borrador = BorradorAtencion(
        profesional_id=profesional.id,
        residente_id=residente.id,
        canal="whatsapp",
        campos={
            **CAMPOS,
            "residente": {"valor": "RES-01", "fragmento": "[RES-01]"},
            "especialidad": {"valor": "pediatría", "fragmento": None},
            "lugar": {"valor": "Hogar", "fragmento": "en el hogar"},
        },
    )
    sesion.add(borrador)
    sesion.commit()
    return borrador


def eventos(sesion, accion: str) -> list[EventoAuditoria]:
    return list(sesion.scalars(select(EventoAuditoria).where(EventoAuditoria.accion == accion)))


# Crear


def test_crea_una_atencion_web_en_borrador(sesion, residente, autor, profesional):
    atencion = crear_atencion(sesion, residente.id, autor, CAMPOS, OrigenAtencion.WEB)
    sesion.commit()

    assert atencion.estado == EstadoAtencion.BORRADOR
    assert atencion.profesional_id == profesional.id
    assert atencion.fecha_atencion == date(2026, 11, 16)
    assert atencion.campos["residente"] == {"valor": "RES-01", "fragmento": None}
    assert atencion.campos["especialidad"]["valor"] == "pediatría"
    assert atencion.campos_editados == []


def test_no_modifica_los_campos_que_recibe(sesion, residente, autor):
    campos = {"motivo": {"valor": "control sano", "fragmento": None}}

    crear_atencion(sesion, residente.id, autor, campos, OrigenAtencion.WEB, date(2026, 11, 16))

    assert campos == {"motivo": {"valor": "control sano", "fragmento": None}}


def test_la_fecha_queda_igual_en_la_columna_y_en_los_campos(sesion, residente, autor):
    campos = {"motivo": {"valor": "control sano", "fragmento": None}}

    atencion = crear_atencion(
        sesion, residente.id, autor, campos, OrigenAtencion.WEB, fecha_atencion=date(2026, 11, 2)
    )

    assert atencion.fecha_atencion == date(2026, 11, 2)
    assert atencion.campos["fecha_atencion"] == {"valor": "2026-11-02", "fragmento": None}


@pytest.mark.parametrize(
    ("cambios", "faltantes"),
    [
        ({"fecha_atencion": None}, ["fecha_atencion"]),
        ({"motivo": None, "diagnosticos": []}, ["diagnostico_o_motivo"]),
        (
            {"motivo": {"valor": "", "fragmento": None}, "diagnosticos": None},
            ["diagnostico_o_motivo"],
        ),
        (
            {"fecha_atencion": None, "motivo": None, "diagnosticos": []},
            ["fecha_atencion", "diagnostico_o_motivo"],
        ),
    ],
)
def test_sin_datos_obligatorios_no_se_crea(sesion, residente, autor, cambios, faltantes):
    with pytest.raises(DatosIncompletos) as error:
        crear_atencion(sesion, residente.id, autor, CAMPOS | cambios, OrigenAtencion.WEB)

    assert error.value.faltantes == faltantes


def test_basta_un_diagnostico_sin_motivo(sesion, residente, autor):
    atencion = crear_atencion(
        sesion, residente.id, autor, CAMPOS | {"motivo": None}, OrigenAtencion.WEB
    )

    assert atencion.id is not None


def test_avisa_lo_que_falta_antes_de_guardar():
    faltantes = faltantes_obligatorios(None, {}, None, OrigenAtencion.WEB)

    assert faltantes == ["residente", "fecha_atencion", "diagnostico_o_motivo"]


@pytest.mark.parametrize(
    ("campos", "mensaje"),
    [
        ({**CAMPOS, "peso": {"valor": "12 kg"}}, "Campo desconocido: peso"),
        ({**CAMPOS, "fecha_atencion": {"valor": "16/11/2026"}}, "AAAA-MM-DD"),
        ({**CAMPOS, "fecha_atencion": {"valor": "2026-02-30"}}, "no existe"),
        ({**CAMPOS, "diagnosticos": {"valor": "bronquitis"}}, "forma esperada"),
    ],
)
def test_rechaza_datos_invalidos(sesion, residente, autor, campos, mensaje):
    with pytest.raises(ErrorDeAtencion, match=mensaje):
        crear_atencion(sesion, residente.id, autor, campos, OrigenAtencion.WEB)


def test_rechaza_un_residente_que_no_existe(sesion, autor):
    with pytest.raises(ErrorDeAtencion, match="residente no existe"):
        crear_atencion(sesion, 999, autor, CAMPOS, OrigenAtencion.WEB)


# Desde un borrador de la IA


def test_desde_un_borrador_anota_lo_que_se_cambio_a_mano(
    sesion, residente, encargada, borrador, profesional
):
    campos = {**borrador.campos, "lugar": {"valor": "CESFAM", "fragmento": None}}

    atencion = crear_atencion(
        sesion, residente.id, encargada, campos, OrigenAtencion.WHATSAPP, borrador_id=borrador.id
    )

    # El profesional es el del borrador aunque la cree la encargada de salud.
    assert atencion.profesional_id == profesional.id
    assert atencion.campos_editados == ["lugar"]
    assert atencion_del_borrador(sesion, borrador.id) == atencion
    # El borrador se confirma recién al firmar.
    assert borrador.estado == EstadoBorrador.PENDIENTE


def test_un_fragmento_perdido_en_el_formulario_no_cuenta_como_edicion(
    sesion, residente, autor, borrador
):
    campos = {
        nombre: {k: v for k, v in dato.items() if k != "fragmento"}
        if isinstance(dato, dict)
        else dato
        for nombre, dato in borrador.campos.items()
    }

    atencion = crear_atencion(
        sesion, residente.id, autor, campos, OrigenAtencion.WHATSAPP, borrador_id=borrador.id
    )

    assert atencion.campos_editados == []


def test_un_borrador_no_genera_dos_atenciones(sesion, residente, autor, borrador):
    crear_atencion(
        sesion,
        residente.id,
        autor,
        borrador.campos,
        OrigenAtencion.WHATSAPP,
        borrador_id=borrador.id,
    )

    with pytest.raises(ErrorDeAtencion, match="Ya existe una atención"):
        crear_atencion(
            sesion,
            residente.id,
            autor,
            borrador.campos,
            OrigenAtencion.WHATSAPP,
            borrador_id=borrador.id,
        )


@pytest.mark.parametrize(
    ("estado", "origen", "mensaje"),
    [
        (EstadoBorrador.DESCARTADO, OrigenAtencion.WHATSAPP, "ya no está pendiente"),
        (EstadoBorrador.PENDIENTE, OrigenAtencion.TELEGRAM, "no coincide con el canal"),
    ],
)
def test_rechaza_un_borrador_que_no_corresponde(
    sesion, residente, autor, borrador, estado, origen, mensaje
):
    borrador.estado = estado

    with pytest.raises(ErrorDeAtencion, match=mensaje):
        crear_atencion(sesion, residente.id, autor, CAMPOS, origen, borrador_id=borrador.id)


# Desde un documento histórico


def test_desde_un_documento_historico_puede_no_tener_fecha(sesion, residente, encargada):
    adjunto = Adjunto(
        residente_id=residente.id,
        nombre_archivo="registro.jpg",
        tipo=TipoAdjunto.DOCUMENTO_HISTORICO,
        mime="image/jpeg",
        tamano_bytes=3,
        sha256="0" * 64,
        contenido=b"jpg",
    )
    sesion.add(adjunto)
    sesion.flush()
    documento = DocumentoHistorico(
        residente_id=residente.id, adjunto_id=adjunto.id, campos={"motivo": CAMPOS["motivo"]}
    )
    sesion.add(documento)
    sesion.flush()
    campos = {"motivo": CAMPOS["motivo"]}

    atencion = crear_atencion(
        sesion, residente.id, encargada, campos, OrigenAtencion.HISTORICO, documento_id=documento.id
    )

    assert atencion.fecha_atencion is None
    assert atencion.profesional_id is None
    assert documento.atencion_id == atencion.id
    assert atencion.campos_editados == []


# Editar


def test_editar_reemplaza_los_campos_y_audita_solo_los_nombres(sesion, residente, autor):
    atencion = crear_atencion(sesion, residente.id, autor, CAMPOS, OrigenAtencion.WEB)
    campos = {**atencion.campos, "observaciones": {"valor": "tolera bien la alimentación"}}

    actualizar_atencion(sesion, atencion, campos, autor)
    sesion.commit()

    assert atencion.campos["observaciones"]["valor"] == "tolera bien la alimentación"
    [evento] = eventos(sesion, "atencion_editada")
    assert evento.detalle == {"campos": ["observaciones"]}


def test_editar_sin_cambios_no_audita(sesion, residente, autor):
    atencion = crear_atencion(sesion, residente.id, autor, CAMPOS, OrigenAtencion.WEB)

    actualizar_atencion(sesion, atencion, atencion.campos, autor)

    assert eventos(sesion, "atencion_editada") == []


def test_editar_recalcula_lo_cambiado_respecto_de_la_ia(sesion, residente, autor, borrador):
    atencion = crear_atencion(
        sesion,
        residente.id,
        autor,
        borrador.campos,
        OrigenAtencion.WHATSAPP,
        borrador_id=borrador.id,
    )

    actualizar_atencion(sesion, atencion, {**atencion.campos, "lugar": None}, autor)
    assert atencion.campos_editados == ["lugar"]

    # Volver al valor de la IA deja el campo como no editado.
    actualizar_atencion(
        sesion, atencion, {**atencion.campos, "lugar": borrador.campos["lugar"]}, autor
    )
    assert atencion.campos_editados == []


def test_una_atencion_firmada_no_se_edita(sesion, residente, autor):
    atencion = crear_atencion(sesion, residente.id, autor, CAMPOS, OrigenAtencion.WEB)
    atencion.estado = EstadoAtencion.FIRMADA

    with pytest.raises(AtencionFirmada):
        actualizar_atencion(sesion, atencion, {**CAMPOS, "lugar": {"valor": "Hogar"}}, autor)


def test_editar_tambien_exige_los_datos_obligatorios(sesion, residente, autor):
    atencion = crear_atencion(sesion, residente.id, autor, CAMPOS, OrigenAtencion.WEB)

    with pytest.raises(DatosIncompletos):
        actualizar_atencion(sesion, atencion, {**CAMPOS, "motivo": None, "diagnosticos": []}, autor)


# Auditoría


def test_la_auditoria_no_lleva_contenido_clinico(sesion, residente, autor):
    atencion = crear_atencion(sesion, residente.id, autor, CAMPOS, OrigenAtencion.WEB)
    sesion.commit()

    [evento] = eventos(sesion, "atencion_creada")
    assert (evento.actor_id, evento.entidad, evento.entidad_id) == (
        str(autor.id),
        "atencion",
        str(atencion.id),
    )
    assert evento.detalle == {"origen": "web", "residente_id": residente.id}
