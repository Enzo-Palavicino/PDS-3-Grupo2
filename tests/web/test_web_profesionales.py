import json

import pytest
from sqlalchemy import func, select

from app.modelos import EventoAuditoria, Profesional, UsuarioWeb, VinculoCanal
from app.nucleo.ingesta import procesar_mensaje
from app.nucleo.vinculacion import canjear_codigo, generar_codigo
from app.seguridad import verificar_password
from tests.web.conftest import PASSWORD

DATOS = {
    "nombre": "Profesional ficticia",
    "especialidad": "Kinesiología",
    "registro": "REG-123",
    "cuenta": "kinesiologa",
    "password": "clave-inicial-segura",
}


def test_crear_profesional_y_usuario(cliente, entrar, csrf, sesion, acciones):
    entrar("directora")
    respuesta = cliente.post(
        "/profesionales", data={**DATOS, "csrf": csrf("/profesionales")}
    )
    assert respuesta.status_code == 200
    assert "Profesional ficticia" in respuesta.text
    cuenta = sesion.scalar(
        select(UsuarioWeb).where(UsuarioWeb.usuario == "kinesiologa")
    )
    assert cuenta.rol == "profesional"
    assert verificar_password(DATOS["password"], cuenta.hash_password)
    profesional = sesion.get(Profesional, cuenta.profesional_id)
    assert profesional.registro == "REG-123"
    assert profesional.activo
    sesion.commit()
    assert "profesional_creado" in acciones()
    assert entrar("kinesiologa", password=DATOS["password"]).status_code == 303


@pytest.mark.parametrize("rol", ["pediatra", "encargada_salud"])
def test_solo_directora_administra(cliente, entrar, csrf, rol):
    entrar(rol)
    token = csrf()
    assert cliente.get("/profesionales").status_code == 403
    assert (
        cliente.post("/profesionales", data={**DATOS, "csrf": token}).status_code == 403
    )
    assert (
        cliente.post("/profesionales/1/desactivar", data={"csrf": token}).status_code
        == 403
    )


@pytest.mark.parametrize(
    "cambio",
    [
        {"cuenta": "pediatra"},
        {"nombre": " "},
        {"especialidad": "x" * 61},
        {"password": "corta"},
        {"password": " " * 12},
        {"cuenta": "con espacio"},
        {"registro": "x" * 121},
    ],
)
def test_formulario_invalido_no_deja_profesional_huerfano(
    cliente, entrar, csrf, sesion, cambio
):
    entrar("directora")
    antes = sesion.scalar(select(func.count()).select_from(Profesional))
    sesion.commit()
    respuesta = cliente.post(
        "/profesionales", data={**DATOS, **cambio, "csrf": csrf("/profesionales")}
    )
    assert respuesta.status_code == 400
    assert DATOS["password"] not in respuesta.text
    assert sesion.scalar(select(func.count()).select_from(Profesional)) == antes
    assert (
        sesion.scalar(
            select(EventoAuditoria).where(
                EventoAuditoria.accion == "profesional_creado"
            )
        )
        is None
    )


def test_desactivar_revoca_accesos_y_conserva_autoria(
    cliente,
    entrar,
    csrf,
    sesion,
    id_profesional,
    crear_borrador,
    crear_mensaje,
    acciones,
):
    borrador = crear_borrador()
    pid = id_profesional("pediatra")
    profesional = sesion.get(Profesional, pid)
    nombre = profesional.nombre
    codigo = generar_codigo(sesion, pid)
    sesion.flush()
    codigo_texto = codigo.codigo
    for canal in ("telegram", "whatsapp"):
        sesion.add(VinculoCanal(profesional_id=pid, canal=canal, id_externo="1234"))
    sesion.commit()
    entrar("pediatra")
    cookie_anterior = cliente.cookies.get("session")
    entrar("directora")
    assert "WhatsApp" in cliente.get("/profesionales").text
    assert "Telegram" in cliente.get("/profesionales").text
    token = csrf("/profesionales")
    assert (
        cliente.post(
            f"/profesionales/{pid}/desactivar", data={"csrf": token}
        ).status_code
        == 200
    )
    sesion.expire_all()
    assert not profesional.activo
    assert profesional.nombre == nombre
    assert borrador.profesional_id == pid
    assert not sesion.scalar(
        select(UsuarioWeb).where(UsuarioWeb.profesional_id == pid)
    ).activo
    for vinculo in sesion.scalars(
        select(VinculoCanal).where(VinculoCanal.profesional_id == pid)
    ):
        assert not vinculo.activo and vinculo.revocado_en
    assert canjear_codigo(sesion, "telegram", "otro", codigo_texto) is None
    for canal in ("telegram", "whatsapp"):
        respuestas = procesar_mensaje(
            sesion, crear_mensaje(canal=canal, remitente_externo="1234")
        )
        assert "no está autorizada" in respuestas[0].texto
    sesion.commit()
    assert acciones().count("vinculo_revocado") == 2
    assert acciones().count("profesional_desactivado") == 1
    # Repetir no genera eventos ni elimina registros.
    cliente.post(f"/profesionales/{pid}/desactivar", data={"csrf": token})
    assert acciones().count("profesional_desactivado") == 1
    cliente.cookies.clear()
    cliente.cookies.set("session", cookie_anterior)
    assert cliente.get("/borradores", follow_redirects=False).status_code == 303
    cliente.cookies.clear()
    assert entrar("pediatra").status_code == 401


@pytest.mark.parametrize("rol", ["directora", "encargada_salud", "pediatra"])
def test_cambiar_password_para_cualquier_rol(
    cliente, entrar, csrf, sesion, acciones, rol
):
    entrar(rol)
    respuesta = cliente.post(
        "/cuenta/password",
        data={
            "csrf": csrf("/cuenta/password"),
            "actual": PASSWORD,
            "nueva": "nueva-clave-segura",
            "confirmacion": "nueva-clave-segura",
        },
        follow_redirects=False,
    )
    assert respuesta.status_code == 303
    assert respuesta.headers["location"] == "/login"
    assert entrar(rol, password=PASSWORD).status_code == 401
    assert entrar(rol, password="nueva-clave-segura").status_code == 303
    assert "contrasena_cambiada" in acciones()
    eventos = list(sesion.scalars(select(EventoAuditoria)))
    assert "nueva-clave-segura" not in json.dumps([e.detalle for e in eventos])


@pytest.mark.parametrize(
    "actual,nueva,confirmacion",
    [
        ("incorrecta", "nueva-clave-segura", "nueva-clave-segura"),
        (PASSWORD, "nueva-clave-segura", "otra-clave-segura"),
        (PASSWORD, "corta", "corta"),
        (PASSWORD, PASSWORD, PASSWORD),
    ],
)
def test_cambio_password_invalido(cliente, entrar, csrf, actual, nueva, confirmacion):
    entrar("pediatra")
    respuesta = cliente.post(
        "/cuenta/password",
        data={
            "csrf": csrf("/cuenta/password"),
            "actual": actual,
            "nueva": nueva,
            "confirmacion": confirmacion,
        },
    )
    assert respuesta.status_code == 400
    assert entrar("pediatra").status_code == 303


def test_formularios_exigen_csrf(cliente, entrar):
    entrar("directora")
    for ruta in ("/profesionales", "/profesionales/1/desactivar", "/cuenta/password"):
        assert cliente.post(ruta, data=DATOS).status_code == 403


def test_sin_sesion_no_se_puede_administrar(cliente):
    for ruta in ("/profesionales", "/cuenta/password"):
        assert cliente.get(ruta, follow_redirects=False).status_code == 303


def test_desactivar_conserva_atencion_firmada_y_nombre_del_autor(
    cliente,
    entrar,
    csrf,
    sesion,
    id_profesional,
):
    from datetime import date

    from app.db import ahora
    from app.modelos import Atencion, EstadoAtencion, OrigenAtencion

    pid = id_profesional("pediatra")
    autor = sesion.scalar(select(UsuarioWeb).where(UsuarioWeb.profesional_id == pid))
    profesional = sesion.get(Profesional, pid)
    nombre = profesional.nombre
    atencion = Atencion(
        residente_id=2,
        profesional_id=pid,
        origen=OrigenAtencion.WEB,
        estado=EstadoAtencion.FIRMADA,
        fecha_atencion=date(2026, 11, 15),
        campos={"motivo": {"valor": "Control ficticio"}},
        firmada_por=autor.id,
        firmada_en=ahora(),
        hash_firma="a" * 64,
    )
    sesion.add(atencion)
    sesion.commit()
    aid = atencion.id
    firma = (atencion.firmada_por, atencion.firmada_en, atencion.hash_firma)
    sesion.commit()
    entrar("directora")
    respuesta = cliente.post(
        f"/profesionales/{pid}/desactivar", data={"csrf": csrf("/profesionales")}
    )
    assert respuesta.status_code == 200
    sesion.expire_all()
    conservada = sesion.get(Atencion, aid)
    assert conservada.estado == EstadoAtencion.FIRMADA
    assert conservada.profesional_id == pid
    assert (
        conservada.firmada_por,
        conservada.firmada_en,
        conservada.hash_firma,
    ) == firma
    assert conservada.campos == {"motivo": {"valor": "Control ficticio"}}
    assert sesion.get(Profesional, conservada.profesional_id).nombre == nombre


def test_registro_es_opcional(cliente, entrar, csrf, sesion):
    entrar("directora")
    assert (
        cliente.post(
            "/profesionales",
            data={
                **DATOS,
                "registro": "",
                "csrf": csrf("/profesionales"),
            },
        ).status_code
        == 200
    )
    cuenta = sesion.scalar(
        select(UsuarioWeb).where(UsuarioWeb.usuario == DATOS["cuenta"])
    )
    assert sesion.get(Profesional, cuenta.profesional_id).registro is None
