"""Administración de residentes por la directora y la encargada de salud."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.modelos import EstadoResidente, Nivel, Residente, Rol, UsuarioWeb
from app.nucleo import residentes as servicio
from app.web.autenticacion import SesionBD, exigir_rol, verificar_csrf
from app.web.plantillas import pagina

router = APIRouter(prefix="/residentes")
Administracion = Annotated[
    UsuarioWeb, Depends(exigir_rol(Rol.DIRECTORA, Rol.ENCARGADA_SALUD))
]
NIVELES = [(n.value, n.value.replace("_", " ").capitalize()) for n in Nivel]


def obtener(sesion, residente_id):
    residente = sesion.scalar(
        select(Residente).where(Residente.id == residente_id).with_for_update()
    )
    if residente is None:
        raise HTTPException(404, "Residente no encontrado.")
    return residente


def formulario(request, usuario, residente=None, valores=None, **extra):
    if valores is None:
        valores = (
            {
                campo: getattr(residente, campo) or ""
                for campo in (
                    "nombres",
                    "apellidos",
                    "apodo",
                    "nivel",
                    "fecha_nacimiento",
                    "fecha_ingreso",
                )
            }
            if residente
            else {}
        )
    return pagina(
        request,
        "residente_formulario.html",
        usuario=usuario,
        residente=residente,
        valores=valores,
        niveles=NIVELES,
        hoy=servicio.hoy(),
        **extra,
    )


@router.get("")
def listar(
    request: Request,
    sesion: SesionBD,
    usuario: Administracion,
    buscar: str = "",
    nivel: str = "",
    estado: str = "",
):
    if (
        nivel
        and nivel not in set(Nivel)
        or estado
        and estado not in set(EstadoResidente)
    ):
        raise HTTPException(400, "Filtro no válido.")
    todos = list(
        sesion.scalars(
            select(Residente).order_by(Residente.apellidos, Residente.nombres)
        )
    )
    consulta = servicio.normalizar(buscar)
    filas = [
        r
        for r in todos
        if (
            not consulta
            or consulta in servicio.normalizar(f"{r.nombres} {r.apellidos} {r.codigo}")
        )
        and (not nivel or r.nivel == nivel)
        and (not estado or r.estado == estado)
    ]
    return pagina(
        request,
        "residentes.html",
        usuario=usuario,
        residentes=filas,
        total=len(todos),
        buscar=buscar,
        nivel=nivel,
        estado=estado,
        niveles=NIVELES,
        exito=request.session.pop("residente_exito", None),
    )


@router.get("/nuevo")
def nuevo(request: Request, usuario: Administracion):
    return formulario(request, usuario)


@router.get("/{residente_id}/editar")
def editar(
    residente_id: int, request: Request, sesion: SesionBD, usuario: Administracion
):
    return formulario(request, usuario, obtener(sesion, residente_id))


@router.post("/nuevo", dependencies=[Depends(verificar_csrf)])
@router.post("/{residente_id}/editar", dependencies=[Depends(verificar_csrf)])
def guardar(
    request: Request,
    sesion: SesionBD,
    usuario: Administracion,
    residente_id: int | None = None,
    nombres: Annotated[str, Form()] = "",
    apellidos: Annotated[str, Form()] = "",
    apodo: Annotated[str, Form()] = "",
    nivel: Annotated[str, Form()] = "",
    fecha_nacimiento: Annotated[str, Form()] = "",
    fecha_ingreso: Annotated[str, Form()] = "",
    confirmar_duplicado: Annotated[bool, Form()] = False,
):
    residente = obtener(sesion, residente_id) if residente_id is not None else None
    valores = {
        "nombres": nombres,
        "apellidos": apellidos,
        "apodo": apodo,
        "nivel": nivel,
        "fecha_nacimiento": fecha_nacimiento,
        "fecha_ingreso": fecha_ingreso,
    }
    try:
        datos = servicio.datos_validos(valores)
        coincidencias = servicio.duplicados(sesion, datos, residente_id)
        if coincidencias and not confirmar_duplicado:
            return formulario(
                request,
                usuario,
                residente,
                valores,
                duplicados=coincidencias,
                status_code=409,
            )
        servicio.guardar(sesion, datos, usuario.id, residente)
        sesion.commit()
    except ValueError as exc:
        sesion.rollback()
        return formulario(
            request, usuario, residente, valores, error=str(exc), status_code=400
        )
    request.session["residente_exito"] = (
        "Residente actualizado exitosamente."
        if residente
        else "Residente creado exitosamente."
    )
    return RedirectResponse("/residentes", status_code=303)


@router.post("/{residente_id}/estado", dependencies=[Depends(verificar_csrf)])
def estado(
    residente_id: int,
    request: Request,
    sesion: SesionBD,
    usuario: Administracion,
    accion: Annotated[str, Form()] = "",
    fecha: Annotated[str, Form()] = "",
):
    residente = obtener(sesion, residente_id)
    try:
        servicio.cambiar_estado(sesion, residente, accion, fecha, usuario.id)
        sesion.commit()
    except ValueError as exc:
        sesion.rollback()
        return formulario(request, usuario, residente, error=str(exc), status_code=400)
    request.session["residente_exito"] = (
        "Egreso registrado. El historial se conserva."
        if accion == "egresar"
        else "Reingreso registrado en la misma ficha."
    )
    return RedirectResponse("/residentes", status_code=303)
