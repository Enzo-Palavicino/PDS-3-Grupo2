import json
from datetime import date

import pytest
from sqlalchemy import func, select

from app.modelos import Asignacion, Atencion, EstadoAtencion, EventoAuditoria, Residente
from app.nucleo.borradores import armar_borrador
from app.nucleo.mensajes import registrar_mensaje_entrante
from app.proveedores.llm.fake import ProveedorLLMFake

DATOS = {
    "nombres": "Luciana",
    "apellidos": "Prueba",
    "apodo": "Luchi",
    "fecha_nacimiento": "2024-01-01",
    "fecha_ingreso": "2026-01-01",
    "nivel": "heterogeneo",
}


def crear(cliente, csrf, **cambios):
    return cliente.post(
        "/residentes/nuevo",
        data={**DATOS, **cambios, "csrf": csrf("/residentes/nuevo")},
    )


@pytest.mark.parametrize("rol", ["directora", "encargada_salud"])
def test_crear_y_editar(cliente, entrar, csrf, sesion, acciones, rol):
    entrar(rol)
    assert crear(cliente, csrf).status_code == 200
    residente = sesion.scalar(select(Residente).where(Residente.nombres == "Luciana"))
    assert residente.codigo == "RES-05" and residente.estado == "activo"
    rid = residente.id
    sesion.commit()
    respuesta = cliente.post(
        f"/residentes/{rid}/editar",
        data={
            **DATOS,
            "apodo": "Lulu",
            "csrf": csrf(f"/residentes/{rid}/editar"),
            "codigo": "RES-99",
        },
    )
    assert respuesta.status_code == 200
    sesion.expire_all()
    assert residente.apodo == "Lulu" and residente.codigo == "RES-05"
    assert "residente_creado" in acciones() and "residente_editado" in acciones()


def test_advertencia_duplicado_no_guarda_sin_confirmacion(
    cliente, entrar, csrf, sesion
):
    entrar("directora")
    assert crear(cliente, csrf).status_code == 200
    respuesta = crear(cliente, csrf, nombres="  LUCIÁNA  ", apellidos="prueba")
    assert respuesta.status_code == 409
    assert "Ya existe un residente" in respuesta.text and "RES-05" in respuesta.text
    assert sesion.scalar(select(func.count()).select_from(Residente)) == 5
    sesion.commit()
    assert crear(cliente, csrf, confirmar_duplicado="true").status_code == 200
    assert sesion.scalar(select(func.count()).select_from(Residente)) == 6


@pytest.mark.parametrize(
    "cambios",
    [
        {"nombres": " "},
        {"apellidos": "x" * 121},
        {"apodo": "x" * 61},
        {"nivel": "otro"},
        {"fecha_nacimiento": "invalida"},
        {"fecha_ingreso": "2020-01-01"},
        {"fecha_nacimiento": "2099-01-01"},
        {"fecha_ingreso": "2099-01-01"},
    ],
)
def test_validacion_no_crea_filas(cliente, entrar, csrf, sesion, cambios):
    entrar("directora")
    assert crear(cliente, csrf, **cambios).status_code == 400
    assert sesion.scalar(select(func.count()).select_from(Residente)) == 4
    assert (
        sesion.scalar(
            select(EventoAuditoria).where(EventoAuditoria.accion == "residente_creado")
        )
        is None
    )


def test_profesional_no_administra(cliente, entrar, csrf):
    entrar("pediatra")
    token = csrf("/borradores")
    for ruta in ("/residentes", "/residentes/nuevo", "/residentes/1/editar"):
        assert cliente.get(ruta).status_code == 403
    for ruta in ("/residentes/nuevo", "/residentes/1/editar", "/residentes/1/estado"):
        assert cliente.post(ruta, data={**DATOS, "csrf": token}).status_code == 403


def test_csrf_y_sesion(cliente, entrar):
    assert cliente.get("/residentes", follow_redirects=False).status_code == 303
    entrar("directora")
    for ruta in ("/residentes/nuevo", "/residentes/1/editar", "/residentes/1/estado"):
        assert cliente.post(ruta, data=DATOS).status_code == 403


def test_filtros(cliente, entrar):
    entrar("directora")
    pagina = cliente.get(
        "/residentes",
        params={"buscar": "RES-02", "nivel": "sala_cuna_menor", "estado": "activo"},
    )
    assert pagina.status_code == 200 and "1 de 4 residentes" in pagina.text
    assert "Emilia" in pagina.text and "Martina" not in pagina.text
    assert (
        "2 de 4 residentes"
        in cliente.get("/residentes", params={"buscar": "tomas"}).text
    )
    assert (
        "No hay residentes que coincidan"
        in cliente.get("/residentes", params={"estado": "egresado"}).text
    )


def test_egreso_reingreso_conservan_historial(
    cliente, entrar, csrf, sesion, id_profesional, acciones
):
    pid = id_profesional("pediatra")
    atencion = Atencion(
        residente_id=1,
        profesional_id=pid,
        origen="web",
        estado=EstadoAtencion.FIRMADA,
        campos={"motivo": {"valor": "Control"}},
        hash_firma="a" * 64,
    )
    sesion.add(atencion)
    sesion.commit()
    aid = atencion.id
    original = sesion.get(Residente, 1)
    codigo, ingreso = original.codigo, original.fecha_ingreso
    sesion.commit()
    entrar("encargada_salud")
    token = csrf("/residentes/1/editar")
    assert (
        cliente.post(
            "/residentes/1/estado",
            data={"csrf": token, "accion": "egresar", "fecha": "2026-10-01"},
        ).status_code
        == 200
    )
    sesion.expire_all()
    assert original.estado == "egresado" and original.fecha_egreso == date(2026, 10, 1)
    sesion.commit()
    assert (
        cliente.post(
            "/residentes/1/estado",
            data={"csrf": token, "accion": "reingresar", "fecha": "2026-11-01"},
        ).status_code
        == 200
    )
    sesion.expire_all()
    assert original.estado == "activo" and original.fecha_egreso is None
    assert original.codigo == codigo and original.fecha_ingreso == ingreso
    assert sesion.get(Atencion, aid).hash_firma == "a" * 64
    assert "residente_egresado" in acciones()
    evento = sesion.scalar(
        select(EventoAuditoria).where(EventoAuditoria.accion == "residente_editado")
    )
    assert evento.detalle == {
        "operacion": "reingresar",
        "fecha": "2026-11-01",
        "egreso_anterior": "2026-10-01",
    }


@pytest.mark.parametrize(
    "accion,fecha",
    [
        ("reingresar", "2026-01-01"),
        ("egresar", "2000-01-01"),
        ("egresar", "2099-01-01"),
        ("egresar", "no-fecha"),
    ],
)
def test_estado_invalido(cliente, entrar, csrf, sesion, accion, fecha):
    entrar("directora")
    assert (
        cliente.post(
            "/residentes/1/estado",
            data={
                "csrf": csrf("/residentes/1/editar"),
                "accion": accion,
                "fecha": fecha,
            },
        ).status_code
        == 400
    )
    assert sesion.get(Residente, 1).estado == "activo"


def test_nuevo_residente_se_seudonimiza_en_extraccion_real(
    cliente, entrar, csrf, sesion, id_profesional, crear_mensaje
):
    entrar("directora")
    assert crear(cliente, csrf).status_code == 200
    pid = id_profesional("pediatra")
    nuevo = sesion.scalar(select(Residente).where(Residente.codigo == "RES-05"))
    sesion.add(Asignacion(residente_id=nuevo.id, profesional_id=pid))
    sesion.commit()
    mensaje = registrar_mensaje_entrante(
        sesion,
        crear_mensaje(texto="Atendí a Luciana Prueba por tos. Luchi está bien."),
        pid,
    )
    sesion.commit()
    llm = ProveedorLLMFake(
        [json.dumps({"diagnosticos": [{"valor": "tos", "fragmento": "tos"}]})]
    )
    armar_borrador(sesion, mensaje, llm)
    assert llm.entradas
    assert "RES-05" in llm.entradas[0]
    assert "Luciana" not in llm.entradas[0] and "Luchi" not in llm.entradas[0]


def test_codigo_sigue_maximo_no_cantidad(cliente, entrar, csrf, sesion):
    sesion.get(Residente, 4).codigo = "RES-99"
    sesion.commit()
    entrar("directora")
    assert crear(cliente, csrf).status_code == 200
    assert (
        sesion.scalar(select(Residente).where(Residente.codigo == "RES-100"))
        is not None
    )


def test_fechas_entre_reingresos(cliente, entrar, csrf):
    entrar("directora")
    token = csrf("/residentes/1/editar")

    def cambiar(accion, fecha):
        return cliente.post(
            "/residentes/1/estado",
            data={"csrf": token, "accion": accion, "fecha": fecha},
        )

    assert cambiar("egresar", "2026-09-01").status_code == 200
    assert cambiar("reingresar", "2026-08-01").status_code == 400
    assert cambiar("reingresar", "2026-10-01").status_code == 200
    assert cambiar("egresar", "2026-09-15").status_code == 400
    assert cambiar("egresar", "2026-11-01").status_code == 200
