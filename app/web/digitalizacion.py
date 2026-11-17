"""Ingreso y seguimiento de documentos históricos. E4-03 consume la cola en la base."""

import logging
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select

from app.logs import trazas_habilitadas
from app.modelos import Adjunto, DocumentoHistorico, Residente, Rol, UsuarioWeb
from app.nucleo.adjuntos import TAMANO_MAXIMO_BYTES, ArchivoNoPermitido
from app.nucleo.documentos import MAXIMO_ARCHIVOS, MAXIMO_LOTE_BYTES, subir_documento
from app.web.autenticacion import SesionBD, exigir_rol, verificar_csrf
from app.web.plantillas import pagina

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/digitalizacion")
EncargadaSalud = Annotated[UsuarioWeb, Depends(exigir_rol(Rol.ENCARGADA_SALUD))]
ESTADOS = {
    "subido": "Subido",
    "leido": "Procesando",
    "procesando": "Procesando",
    "por_revisar": "Por revisar",
    "incorporado": "Incorporado",
    "error": "Error",
    "descartado": "Descartado",
}


def _residente(sesion, residente_id):
    residente = sesion.get(Residente, residente_id)
    if residente is None:
        raise HTTPException(404, "Residente no encontrado.")
    return residente


def _documentos(sesion, residente_id):
    # Solo metadatos: no se carga la imagen, el texto leído ni el resultado clínico.
    filas = sesion.execute(
        select(
            DocumentoHistorico.id,
            DocumentoHistorico.adjunto_id,
            DocumentoHistorico.tipo_documento,
            DocumentoHistorico.fecha_original,
            DocumentoHistorico.estado,
            DocumentoHistorico.intentos,
            Adjunto.nombre_archivo,
        )
        .join(Adjunto, Adjunto.id == DocumentoHistorico.adjunto_id)
        .where(DocumentoHistorico.residente_id == residente_id)
        .order_by(DocumentoHistorico.id.desc())
    ).all()
    return [
        {
            "id": f.id,
            "adjunto_id": f.adjunto_id,
            "nombre": f.nombre_archivo,
            "tipo": f.tipo_documento or "Sin tipo",
            "fecha": str(f.fecha_original)
            if f.fecha_original
            else "Sin fecha conocida",
            "estado": ESTADOS.get(f.estado, "Pendiente"),
            "intentos": f.intentos,
        }
        for f in filas
    ]


def _pagina(
    request,
    sesion,
    usuario,
    residente_id=None,
    error=None,
    valores=None,
    status_code=200,
):
    residente = _residente(sesion, residente_id) if residente_id is not None else None
    # Vincula la confirmación del formulario al residente que se mostró en pantalla.
    if residente:
        request.session["digitalizacion_residente"] = residente.id
    respuesta = pagina(
        request,
        "digitalizacion.html",
        usuario=usuario,
        residentes=list(
            sesion.scalars(
                select(Residente).order_by(Residente.apellidos, Residente.nombres)
            )
        ),
        residente=residente,
        documentos=_documentos(sesion, residente_id) if residente else [],
        valores=valores or {},
        error=error,
        status_code=status_code,
        exito=request.session.pop("digitalizacion_exito", None),
    )
    respuesta.headers["Cache-Control"] = "no-store"
    return respuesta


@router.get("")
def listar(
    request: Request,
    sesion: SesionBD,
    usuario: EncargadaSalud,
    residente_id: int | None = None,
):
    return _pagina(request, sesion, usuario, residente_id)


@router.get("/estados")
def estados(sesion: SesionBD, usuario: EncargadaSalud, residente_id: int):
    _residente(sesion, residente_id)
    return JSONResponse(
        {"documentos": _documentos(sesion, residente_id)},
        headers={"Cache-Control": "no-store, private"},
    )


@router.post("", dependencies=[Depends(verificar_csrf)])
def subir(
    request: Request,
    sesion: SesionBD,
    usuario: EncargadaSalud,
    residente_id: Annotated[int, Form()],
    archivos: Annotated[list[UploadFile], File()],
    tipo_documento: Annotated[str, Form()] = "",
    fecha_original: Annotated[str, Form()] = "",
    confirmar_identidad: Annotated[bool, Form()] = False,
):
    valores = {"tipo_documento": tipo_documento, "fecha_original": fecha_original}
    try:
        _residente(sesion, residente_id)
        if (
            not confirmar_identidad
            or request.session.get("digitalizacion_residente") != residente_id
        ):
            raise ValueError(
                "Selecciona al residente y confirma su identidad antes de subir documentos."
            )
        if not 1 <= len(archivos) <= MAXIMO_ARCHIVOS:
            raise ValueError("Selecciona entre 1 y 10 archivos por carga.")
        try:
            fecha = date.fromisoformat(fecha_original) if fecha_original else None
        except ValueError:
            raise ValueError(
                "Indica una fecha original válida o deja el campo vacío."
            ) from None
        total = 0
        for archivo in archivos:
            contenido = archivo.file.read(TAMANO_MAXIMO_BYTES + 1)
            total += len(contenido)
            if total > MAXIMO_LOTE_BYTES:
                raise ValueError("La carga completa no puede superar 50 MB.")
            subir_documento(
                sesion,
                residente_id,
                contenido,
                archivo.filename or "documento",
                tipo_documento,
                usuario,
                fecha,
            )
        sesion.commit()  # el worker solo se avisa después de persistir todo el lote
    except (ValueError, ArchivoNoPermitido) as exc:
        sesion.rollback()
        return _pagina(
            request,
            sesion,
            usuario,
            residente_id,
            error=str(exc),
            valores=valores,
            status_code=400,
        )
    finally:
        for archivo in archivos:
            archivo.file.close()
    avisar_documentos_pendientes(request)
    request.session["digitalizacion_exito"] = (
        f"{len(archivos)} documento(s) guardado(s) y en cola para procesar."
    )
    return RedirectResponse(
        f"/digitalizacion?residente_id={residente_id}", status_code=303
    )


def avisar_documentos_pendientes(request: Request) -> None:
    """E4-03 registra app.state.worker_documentos con despertar().

    Sin ese worker, la cola queda persistida en subido. No se llama al procesador
    pendiente ni se simula una transición. Un worker que consulta la base puede
    recoger la cola aunque esta notificación falle o el servidor se reinicie.
    """
    worker = getattr(request.app.state, "worker_documentos", None)
    if worker is not None:
        try:
            worker.despertar()
        except Exception as error:
            # La subida ya fue confirmada; no inducir una segunda carga por un aviso fallido.
            logger.warning(
                "No se pudo despertar el worker de documentos (%s)",
                type(error).__name__,
                exc_info=trazas_habilitadas(),
            )
