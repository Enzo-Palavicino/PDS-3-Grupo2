"""Fichas clínicas (E1-02): el listado de fichas y la ficha de cada residente.

La ficha muestra primero el resumen y después el historial de atenciones firmadas. Lo que falta
firmar (borradores de la IA y atenciones en borrador) va en una sección aparte, nunca como
información confirmada. Cada apertura de una ficha queda en la auditoría (ficha_leida).
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modelos import (
    Adjunto,
    Atencion,
    BorradorAtencion,
    DocumentoHistorico,
    EstadoAtencion,
    EstadoBorrador,
    Profesional,
    Residente,
    Rol,
    TipoActor,
    TipoAdjunto,
    UsuarioWeb,
)
from app.nucleo.atenciones import verificar_integridad
from app.nucleo.auditoria import Accion, registrar_evento
from app.nucleo.fichas import historial, resumen_de_ficha
from app.nucleo.permisos import (
    puede_firmar,
    puede_registrar_atencion,
    puede_suspender_tratamiento,
    puede_ver_ficha,
    residentes_asignados,
)
from app.nucleo.tratamientos import hoy_en_chile, tratamientos_del_residente
from app.web.autenticacion import SesionBD, exigir_rol
from app.web.borradores import filas_de_campos
from app.web.digitalizacion import ESTADOS as ESTADOS_DE_DOCUMENTO
from app.web.plantillas import pagina

router = APIRouter()
PersonalClinico = Annotated[
    UsuarioWeb, Depends(exigir_rol(Rol.ENCARGADA_SALUD, Rol.PROFESIONAL))
]


@router.get("/fichas")
def listar(request: Request, sesion: SesionBD, usuario: PersonalClinico):
    """Las fichas que el usuario puede abrir: todas para la encargada de salud; para un
    profesional, solo las de sus residentes asignados."""
    consulta = select(Residente).order_by(Residente.apellidos, Residente.nombres)
    if usuario.rol == Rol.PROFESIONAL:
        consulta = consulta.where(Residente.id.in_(residentes_asignados(usuario.profesional_id)))
    return pagina(
        request,
        "fichas.html",
        usuario=usuario,
        residentes=list(sesion.scalars(consulta)),
        hoy=hoy_en_chile(),
    )


# El convertidor int evita que esta ruta capture /residentes/nuevo, que pertenece a E2-01.
@router.get("/residentes/{residente_id:int}")
def ver(residente_id: int, request: Request, sesion: SesionBD, usuario: PersonalClinico):
    if not puede_ver_ficha(sesion, usuario, residente_id):
        raise HTTPException(403, "No tienes acceso a esta ficha.")
    hoy = hoy_en_chile()
    resumen = resumen_de_ficha(sesion, residente_id, hoy)
    atenciones = historial(sesion, residente_id)
    sin_firmar = _atenciones_sin_firmar(sesion, residente_id, usuario)
    documentos = _documentos(sesion, residente_id)
    originales = {d.atencion_id: adj.id for d, adj in documentos if d.atencion_id}
    verificadores = {
        u.id: u.usuario for u in sesion.scalars(select(UsuarioWeb).where(
            UsuarioWeb.id.in_([a.verificada_por for a in atenciones if a.verificada_por])
        ))
    }

    # Cada lectura queda registrada: quién abrió qué ficha y cuándo (D41, art. 9).
    registrar_evento(
        sesion,
        Accion.FICHA_LEIDA,
        actor_tipo=TipoActor.USUARIO,
        actor_id=usuario.id,
        entidad="residente",
        entidad_id=residente_id,
    )
    sesion.commit()

    return pagina(
        request,
        "ficha.html",
        usuario=usuario,
        resumen=resumen,
        residente=resumen.residente,
        edad=edad(resumen.residente.fecha_nacimiento, hoy),
        tratamientos=tratamientos_del_residente(sesion, residente_id, hoy),
        puede_suspender=puede_suspender_tratamiento(usuario),
        atenciones=[
            {
                "atencion": atencion,
                "integra": verificar_integridad(atencion),
                "original_id": originales.get(atencion.id),
                "verificador": verificadores.get(atencion.verificada_por),
                "filas": [fila for fila in filas_de_campos(atencion.campos or {}) if fila["valor"]],
            }
            for atencion in atenciones
        ],
        profesionales=_profesionales(sesion, atenciones + sin_firmar),
        borradores=_borradores_pendientes(sesion, residente_id, usuario),
        sin_firmar=[(a, puede_firmar(usuario, a)) for a in sin_firmar],
        adjuntos=_adjuntos(sesion, residente_id),
        documentos=documentos,
        estados_de_documento=ESTADOS_DE_DOCUMENTO,
        puede_registrar=puede_registrar_atencion(sesion, usuario, residente_id),
        puede_digitalizar=usuario.rol == Rol.ENCARGADA_SALUD,
    )


def edad(nacimiento: date | None, hoy: date) -> str:
    """Edad legible: en meses hasta los 2 años ("10 meses") y en años desde ahí ("3 años")."""
    if nacimiento is None:
        return "Sin fecha de nacimiento"
    meses = (hoy.year - nacimiento.year) * 12 + hoy.month - nacimiento.month
    if hoy.day < nacimiento.day:
        meses -= 1
    meses = max(meses, 0)
    if meses < 24:
        return "1 mes" if meses == 1 else f"{meses} meses"
    return f"{meses // 12} años"


def _profesionales(sesion: Session, atenciones: list[Atencion]) -> dict[int, Profesional]:
    ids = {a.profesional_id for a in atenciones if a.profesional_id is not None}
    if not ids:
        return {}
    return {p.id: p for p in sesion.scalars(select(Profesional).where(Profesional.id.in_(ids)))}


def _borradores_pendientes(
    sesion: Session, residente_id: int, usuario: UsuarioWeb
) -> list[BorradorAtencion]:
    """Borradores de la IA pendientes de este residente. Igual que en /borradores, un
    profesional solo ve los suyos."""
    consulta = select(BorradorAtencion).where(
        BorradorAtencion.residente_id == residente_id,
        BorradorAtencion.estado == EstadoBorrador.PENDIENTE,
    )
    if usuario.rol == Rol.PROFESIONAL:
        consulta = consulta.where(BorradorAtencion.profesional_id == usuario.profesional_id)
    return list(sesion.scalars(consulta.order_by(BorradorAtencion.id.desc())))


def _atenciones_sin_firmar(
    sesion: Session, residente_id: int, usuario: UsuarioWeb
) -> list[Atencion]:
    """Atenciones de este residente que siguen en borrador. Un profesional solo ve las suyas."""
    consulta = select(Atencion).where(
        Atencion.residente_id == residente_id,
        Atencion.estado == EstadoAtencion.BORRADOR,
    )
    if usuario.rol == Rol.PROFESIONAL:
        consulta = consulta.where(Atencion.profesional_id == usuario.profesional_id)
    return list(sesion.scalars(consulta.order_by(Atencion.id.desc())))


def _adjuntos(sesion: Session, residente_id: int) -> list[Adjunto]:
    """Adjuntos del residente, sin las fotos de documentos históricos (que van aparte). El
    contenido del archivo no se carga: es una columna diferida."""
    return list(
        sesion.scalars(
            select(Adjunto)
            .where(
                Adjunto.residente_id == residente_id,
                Adjunto.tipo != TipoAdjunto.DOCUMENTO_HISTORICO,
            )
            .order_by(Adjunto.subido_en.desc(), Adjunto.id.desc())
        )
    )


def _documentos(sesion: Session, residente_id: int) -> list[tuple[DocumentoHistorico, Adjunto]]:
    filas = sesion.execute(
        select(DocumentoHistorico, Adjunto)
        .join(Adjunto, Adjunto.id == DocumentoHistorico.adjunto_id)
        .where(DocumentoHistorico.residente_id == residente_id)
        .order_by(DocumentoHistorico.id.desc())
    )
    return [(documento, adjunto) for documento, adjunto in filas]
