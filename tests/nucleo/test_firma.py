import pytest
from sqlalchemy import select, update

from app.modelos import (
    Atencion,
    BorradorAtencion,
    EstadoAtencion,
    EstadoBorrador,
    EventoAuditoria,
    OrigenAtencion,
    Profesional,
    Rol,
    Tratamiento,
    UsuarioWeb,
)
from app.nucleo import incorporacion
from app.nucleo.atenciones import (
    AtencionFirmada,
    DatosIncompletos,
    ErrorDeAtencion,
    PasswordIncorrecta,
    calcular_hash,
    crear_atencion,
    firmar_atencion,
    verificar_integridad,
)
from app.seguridad import hashear_password

PASSWORD = "clave-de-la-pediatra"
CAMPOS = {
    "fecha_atencion": {"valor": "2026-11-02", "fragmento": "Hoy"},
    "motivo": {"valor": "Control pediátrico", "fragmento": "Control pediátrico"},
    "diagnosticos": [{"valor": "bronquiolitis leve", "fragmento": "bronquiolitis leve"}],
    "indicaciones_farmacologicas": [
        {"medicamento": "salbutamol", "dosis": "dos puff", "fragmento": "salbutamol dos puff"}
    ],
}


def usuario_web(sesion, nombre: str, rol: Rol, profesional_id: int | None = None) -> UsuarioWeb:
    usuario = UsuarioWeb(
        usuario=nombre,
        rol=rol,
        profesional_id=profesional_id,
        hash_password=hashear_password(PASSWORD),
    )
    sesion.add(usuario)
    sesion.commit()
    return usuario


@pytest.fixture
def autor(sesion, profesional) -> UsuarioWeb:
    return usuario_web(sesion, "pediatra", Rol.PROFESIONAL, profesional.id)


@pytest.fixture
def borrador(sesion, profesional, residente) -> BorradorAtencion:
    borrador = BorradorAtencion(profesional_id=profesional.id, canal="whatsapp", campos=CAMPOS)
    sesion.add(borrador)
    sesion.commit()
    return borrador


@pytest.fixture
def atencion(sesion, residente, autor, borrador) -> Atencion:
    atencion = crear_atencion(
        sesion, residente.id, autor, CAMPOS, OrigenAtencion.WHATSAPP, borrador_id=borrador.id
    )
    sesion.commit()
    return atencion


def acciones(sesion) -> list[str]:
    return list(sesion.scalars(select(EventoAuditoria.accion)))


def test_firmar_deja_la_atencion_firmada_y_en_la_ficha(sesion, atencion, autor, borrador):
    firmar_atencion(sesion, atencion, autor, PASSWORD)
    sesion.commit()

    assert atencion.estado == EstadoAtencion.FIRMADA
    assert atencion.firmada_por == autor.id
    assert atencion.firmada_en is not None
    assert len(atencion.hash_firma) == 64
    assert borrador.estado == EstadoBorrador.CONFIRMADO
    assert sesion.scalar(select(Tratamiento.medicamento)) == "salbutamol"
    [evento] = sesion.scalars(
        select(EventoAuditoria).where(EventoAuditoria.accion == "atencion_firmada")
    )
    assert evento.detalle == {"hash": atencion.hash_firma}


def test_la_integridad_se_verifica_despues_de_leerla_de_la_base(sesion, atencion, autor):
    firmar_atencion(sesion, atencion, autor, PASSWORD)
    sesion.commit()
    sesion.expire_all()  # obliga a leer de nuevo desde la base de datos

    assert verificar_integridad(sesion.get(Atencion, atencion.id))


def test_un_cambio_despues_de_la_firma_rompe_la_integridad(sesion, atencion, autor):
    firmar_atencion(sesion, atencion, autor, PASSWORD)
    sesion.commit()

    # Alguien modifica la base de datos directamente, saltándose el servicio.
    campos = {**atencion.campos, "motivo": {"valor": "otro motivo", "fragmento": None}}
    sesion.execute(update(Atencion).where(Atencion.id == atencion.id).values(campos=campos))
    sesion.commit()
    sesion.expire_all()

    assert not verificar_integridad(sesion.get(Atencion, atencion.id))


def test_una_atencion_sin_firmar_no_tiene_integridad_verificada(atencion):
    assert not verificar_integridad(atencion)


def test_el_hash_no_depende_del_orden_de_los_campos(sesion, atencion, autor):
    firmar_atencion(sesion, atencion, autor, PASSWORD)
    original = calcular_hash(atencion)

    atencion.campos = dict(reversed(list(atencion.campos.items())))

    assert calcular_hash(atencion) == original


def test_con_una_contrasena_incorrecta_no_se_firma(sesion, atencion, autor, borrador):
    with pytest.raises(PasswordIncorrecta):
        firmar_atencion(sesion, atencion, autor, "otra-clave")

    assert atencion.estado == EstadoAtencion.BORRADOR
    assert borrador.estado == EstadoBorrador.PENDIENTE
    assert "atencion_firmada" not in acciones(sesion)


def test_solo_firma_el_profesional_autor(sesion, atencion):
    otro = Profesional(nombre="Otra profesional", especialidad="nutrición")
    sesion.add(otro)
    sesion.commit()
    nutricionista = usuario_web(sesion, "nutricionista", Rol.PROFESIONAL, otro.id)
    encargada = usuario_web(sesion, "encargada_salud", Rol.ENCARGADA_SALUD)

    for usuario in (nutricionista, encargada):
        with pytest.raises(ErrorDeAtencion, match="Solo el profesional"):
            firmar_atencion(sesion, atencion, usuario, PASSWORD)
    assert atencion.estado == EstadoAtencion.BORRADOR


def test_una_atencion_firmada_no_se_vuelve_a_firmar(sesion, atencion, autor):
    firmar_atencion(sesion, atencion, autor, PASSWORD)

    with pytest.raises(AtencionFirmada):
        firmar_atencion(sesion, atencion, autor, PASSWORD)


def test_sin_los_datos_obligatorios_no_se_firma(sesion, atencion, autor):
    atencion.campos = {**atencion.campos, "motivo": None, "diagnosticos": []}

    with pytest.raises(DatosIncompletos):
        firmar_atencion(sesion, atencion, autor, PASSWORD)


def test_si_falla_la_incorporacion_no_queda_nada_firmado(
    sesion, atencion, autor, borrador, monkeypatch
):
    def fallar(sesion, atencion):
        raise RuntimeError("falla al incorporar")

    monkeypatch.setattr(incorporacion, "incorporar", fallar)

    with pytest.raises(RuntimeError):
        firmar_atencion(sesion, atencion, autor, PASSWORD)
    sesion.commit()  # quien llama puede seguir usando la sesión
    sesion.expire_all()

    guardada = sesion.get(Atencion, atencion.id)
    assert guardada.estado == EstadoAtencion.BORRADOR
    assert (guardada.firmada_por, guardada.hash_firma) == (None, None)
    assert sesion.get(BorradorAtencion, borrador.id).estado == EstadoBorrador.PENDIENTE
    assert "atencion_firmada" not in acciones(sesion)
