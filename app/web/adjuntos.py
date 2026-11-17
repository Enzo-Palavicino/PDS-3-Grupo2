"""Carga y descarga de adjuntos privados. No hay rutas de borrado ni reemplazo."""

from datetime import date
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select

from app.modelos import Adjunto, Atencion, Residente, Rol, TipoAdjunto, UsuarioWeb
from app.nucleo.adjuntos import (
    EXTENSIONES,
    TAMANO_MAXIMO_BYTES,
    ArchivoNoPermitido,
    exigir_acceso,
    guardar_adjunto,
    leer_adjunto,
    validar_destino,
)
from app.nucleo.permisos import residentes_asignados
from app.nucleo.residentes import normalizar
from app.web.autenticacion import SesionBD, exigir_rol, verificar_csrf
from app.web.plantillas import pagina

router = APIRouter(prefix="/adjuntos")
PersonalClinico = Annotated[
    UsuarioWeb, Depends(exigir_rol(Rol.ENCARGADA_SALUD, Rol.PROFESIONAL))
]


def _pagina(
    request,
    sesion,
    usuario,
    residente_id=None,
    atencion_id=None,
    error=None,
    valores=None,
    status_code=200,
    buscar="",
):
    consulta = select(Residente).order_by(Residente.apellidos, Residente.nombres)
    if usuario.rol == Rol.PROFESIONAL:
        consulta = consulta.where(
            Residente.id.in_(residentes_asignados(usuario.profesional_id))
        )
    residentes = list(sesion.scalars(consulta))
    residente = None
    adjuntos = []
    atenciones = []
    if residente_id is not None:
        try:
            validar_destino(sesion, usuario, residente_id, atencion_id)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        residente = sesion.get(Residente, residente_id)
        adjuntos = list(
            sesion.scalars(
                select(Adjunto)
                .where(Adjunto.residente_id == residente_id)
                .order_by(Adjunto.subido_en.desc(), Adjunto.id.desc())
            )
        )
        consulta_atenciones = (
            select(Atencion)
            .where(Atencion.residente_id == residente_id)
            .order_by(Atencion.id.desc())
        )
        if usuario.rol == Rol.PROFESIONAL:
            consulta_atenciones = consulta_atenciones.where(
                Atencion.profesional_id == usuario.profesional_id
            )
        atenciones = list(sesion.scalars(consulta_atenciones))
    total = len(adjuntos)
    consulta_busqueda = normalizar(buscar)
    if consulta_busqueda:
        adjuntos = [a for a in adjuntos if consulta_busqueda in normalizar(
            f"{a.nombre_archivo} {a.tipo.replace('_', ' ')} {a.emisor or ''}")]
    respuesta = pagina(
        request,
        "adjuntos.html",
        usuario=usuario,
        residentes=residentes,
        residente=residente,
        adjuntos=adjuntos,
        buscar=buscar, total_documentos=total,
        atenciones=atenciones,
        atencion_id=atencion_id,
        tipos=[(t.value, t.value.replace("_", " ").capitalize()) for t in TipoAdjunto],
        valores=valores or {},
        error=error,
        status_code=status_code,
        exito=request.session.pop("adjunto_exito", None),
    )
    respuesta.headers["Cache-Control"] = "no-store"
    return respuesta


@router.get("")
def listar(
    request: Request,
    sesion: SesionBD,
    usuario: PersonalClinico,
    residente_id: int | None = None,
    atencion_id: int | None = None,
    buscar: str = "",
):
    if atencion_id is not None and residente_id is None:
        raise HTTPException(400, "Selecciona primero un residente.")
    return _pagina(request, sesion, usuario, residente_id, atencion_id, buscar=buscar.strip())


@router.post("", dependencies=[Depends(verificar_csrf)])
def subir(
    request: Request,
    sesion: SesionBD,
    usuario: PersonalClinico,
    residente_id: Annotated[int, Form()],
    archivo: Annotated[UploadFile, File()],
    tipo: Annotated[str, Form()],
    emisor: Annotated[str, Form()] = "",
    fecha_emision: Annotated[str, Form()] = "",
    atencion_id: Annotated[str, Form()] = "",
):
    valores = {"tipo": tipo, "emisor": emisor, "fecha_emision": fecha_emision}
    atencion = None
    destino_validado = False
    try:
        exigir_acceso(sesion, usuario, residente_id)
        try:
            atencion = int(atencion_id) if atencion_id else None
        except ValueError:
            raise ValueError("Selecciona una atención válida.") from None
        validar_destino(sesion, usuario, residente_id, atencion)
        destino_validado = True
        try:
            fecha = date.fromisoformat(fecha_emision) if fecha_emision else None
        except ValueError:
            raise ValueError("Indica una fecha de emisión válida.") from None
        if not emisor.strip() or fecha is None:
            raise ValueError("Indica el emisor y la fecha de emisión del documento.")
        contenido = archivo.file.read(TAMANO_MAXIMO_BYTES + 1)
        guardar_adjunto(
            sesion,
            residente_id,
            contenido,
            archivo.filename or "documento",
            tipo,
            usuario,
            atencion_id=atencion,
            emisor=emisor,
            fecha_emision=fecha,
        )
        sesion.commit()
    except PermissionError as exc:
        sesion.rollback()
        raise HTTPException(403, str(exc)) from exc
    except (ArchivoNoPermitido, ValueError) as exc:
        sesion.rollback()
        # Un destino inválido no se vuelve a usar para renderizar el formulario.
        return _pagina(
            request,
            sesion,
            usuario,
            residente_id,
            atencion_id=atencion if destino_validado else None,
            error=str(exc),
            valores=valores,
            status_code=400,
        )
    finally:
        archivo.file.close()
    request.session["adjunto_exito"] = "Documento adjuntado exitosamente."
    return RedirectResponse(f"/adjuntos?residente_id={residente_id}", status_code=303)


@router.get("/{adjunto_id}/descargar")
def descargar(adjunto_id: int, request: Request, sesion: SesionBD):
    usuario_id = request.session.get("usuario_id")
    usuario = sesion.get(UsuarioWeb, usuario_id) if usuario_id else None
    if usuario is None or not usuario.activo:
        raise HTTPException(
            403, "Inicia sesión con una cuenta autorizada para descargar."
        )
    try:
        adjunto = leer_adjunto(sesion, adjunto_id, usuario)
        contenido = adjunto.contenido
        disposicion = f"attachment; filename=\"adjunto{EXTENSIONES[adjunto.mime]}\"; filename*=UTF-8''{quote(adjunto.nombre_archivo, safe='')}"
        sesion.commit()
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return Response(
        contenido,
        media_type=adjunto.mime,
        headers={
            "Content-Disposition": disposicion,
            "Cache-Control": "no-store, private",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox",
        },
    )
