"""Revisar y completar los borradores de la IA (E3-02), y editar una atención en borrador.

"Revisar y completar" abre el formulario de E3-01 prellenado con lo que extrajo la IA, con el
fragmento de origen de cada dato y los mensajes (y su transcripción) a la vista. Al guardar se
crea la atención en borrador, enlazada al borrador de la IA; desde ahí se sigue editando en
/atenciones/{id} hasta firmarla. Lo que extrajo la IA no cambia: queda en el borrador y en su
historial de extracciones, y es contra lo que se miden los campos cambiados a mano.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modelos import (
    Atencion,
    BorradorAtencion,
    BorradorMensaje,
    EstadoAtencion,
    EstadoBorrador,
    Extraccion,
    MensajeEntrante,
    OrigenAtencion,
    Residente,
    Rol,
    TipoActor,
    Transcripcion,
    UsuarioWeb,
)
from app.nucleo.atenciones import (
    DatosIncompletos,
    ErrorDeAtencion,
    actualizar_atencion,
    atencion_del_borrador,
    crear_atencion,
)
from app.nucleo.auditoria import Accion, registrar_evento
from app.nucleo.borradores import calcular_faltantes
from app.nucleo.campos import ETIQUETAS, ETIQUETAS_ANTECEDENTES
from app.nucleo.extraccion import RegistroExtraido
from app.nucleo.permisos import (
    profesional_asignado,
    puede_editar_atencion,
    puede_firmar,
    residentes_asignados,
)
from app.nucleo.tratamientos import hoy_en_chile
from app.web.atenciones import Formulario, campos_del_formulario
from app.web.autenticacion import SesionBD, exigir_rol, verificar_csrf
from app.web.borradores import _borrador_visible
from app.web.fichas import edad
from app.web.plantillas import MARCA_DE_RESIDENTE, pagina

router = APIRouter()
PersonalClinico = Depends(exigir_rol(Rol.ENCARGADA_SALUD, Rol.PROFESIONAL))

# Lo que el formulario muestra y reemplaza. El resto de los campos (los antecedentes que extrae
# la IA, el residente y la especialidad) se conserva tal como estaba.
DEL_FORMULARIO = set(ETIQUETAS) - {"residente", "especialidad"}


# Revisar un borrador de la IA


@router.get("/borradores/{borrador_id:int}/revisar")
def revisar(
    request: Request,
    borrador_id: int,
    sesion: SesionBD,
    usuario: UsuarioWeb = PersonalClinico,
    residente_id: int | None = None,
):
    borrador = _borrador_revisable(sesion, borrador_id, usuario)
    if (atencion := atencion_del_borrador(sesion, borrador.id)) is not None:
        return RedirectResponse(f"/atenciones/{atencion.id}", status_code=303)
    residente = _residente_elegido(sesion, borrador, residente_id)
    return _pagina_de_revision(request, sesion, usuario, borrador, residente, borrador.campos)


@router.post("/borradores/{borrador_id:int}/revisar", dependencies=[Depends(verificar_csrf)])
def guardar_revision(
    request: Request,
    borrador_id: int,
    sesion: SesionBD,
    datos: Formulario,
    usuario: UsuarioWeb = PersonalClinico,
):
    borrador = _borrador_revisable(sesion, borrador_id, usuario)
    if (atencion := atencion_del_borrador(sesion, borrador.id)) is not None:
        return RedirectResponse(f"/atenciones/{atencion.id}", status_code=303)
    try:
        residente_id = int(datos.get("residente_id", ""))
    except ValueError:
        residente_id = None
    residente = _residente_elegido(sesion, borrador, residente_id)
    del_formulario, errores = campos_del_formulario(datos)
    campos = combinar(borrador.campos, del_formulario)
    if residente is None:
        errores.insert(0, "Elige al residente de la atención.")
    elif datos.get("confirmo_identidad") != str(residente.id):
        errores.insert(0, f"Confirma que la atención es de {residente.nombres} {residente.apellidos}.")
    if errores:
        return _pagina_de_revision(
            request, sesion, usuario, borrador, residente, campos, errores, status_code=400
        )
    try:
        atencion = crear_atencion(
            sesion, residente.id, usuario, campos, OrigenAtencion(borrador.canal),
            borrador_id=borrador.id,
        )
    except DatosIncompletos as error:
        sesion.rollback()
        return _pagina_de_revision(
            request, sesion, usuario, borrador, residente, campos,
            [str(error)], error.faltantes, status_code=400,
        )
    except ErrorDeAtencion as error:
        sesion.rollback()
        return _pagina_de_revision(
            request, sesion, usuario, borrador, residente, campos, [str(error)], status_code=400
        )
    if atencion.campos_editados:
        # Lo que se cambió a mano respecto de la IA, solo con los nombres de los campos.
        registrar_evento(
            sesion,
            Accion.ATENCION_EDITADA,
            actor_tipo=TipoActor.USUARIO,
            actor_id=usuario.id,
            entidad="atencion",
            entidad_id=atencion.id,
            detalle={"campos": atencion.campos_editados},
        )
    borrador.faltantes = faltantes_de(atencion.campos)
    sesion.commit()
    request.session["atencion_exito"] = "Atención guardada en borrador. Revísala y fírmala."
    return RedirectResponse(f"/atenciones/{atencion.id}", status_code=303)


# Editar una atención en borrador


@router.get("/atenciones/{atencion_id:int}")
def ver_atencion(
    request: Request, atencion_id: int, sesion: SesionBD, usuario: UsuarioWeb = PersonalClinico
):
    atencion = _atencion_editable(sesion, atencion_id, usuario)
    if atencion.estado == EstadoAtencion.FIRMADA:
        return RedirectResponse(
            f"/residentes/{atencion.residente_id}#atencion-{atencion.id}", status_code=303
        )
    return _pagina_de_edicion(request, sesion, usuario, atencion, atencion.campos)


@router.post("/atenciones/{atencion_id:int}", dependencies=[Depends(verificar_csrf)])
def editar_atencion(
    request: Request,
    atencion_id: int,
    sesion: SesionBD,
    datos: Formulario,
    usuario: UsuarioWeb = PersonalClinico,
):
    atencion = _atencion_editable(sesion, atencion_id, usuario)
    if atencion.estado == EstadoAtencion.FIRMADA:
        raise HTTPException(409, "La atención ya está firmada: se corrige con una adenda.")
    del_formulario, errores = campos_del_formulario(datos)
    campos = combinar(atencion.campos, del_formulario)
    if errores:
        return _pagina_de_edicion(
            request, sesion, usuario, atencion, campos, errores, status_code=400
        )
    try:
        actualizar_atencion(sesion, atencion, campos, usuario)  # audita atencion_editada
    except DatosIncompletos as error:
        sesion.rollback()
        return _pagina_de_edicion(
            request, sesion, usuario, atencion, campos,
            [str(error)], error.faltantes, status_code=400,
        )
    except ErrorDeAtencion as error:
        sesion.rollback()
        return _pagina_de_edicion(
            request, sesion, usuario, atencion, campos, [str(error)], status_code=400
        )
    if atencion.borrador_id is not None:
        sesion.get(BorradorAtencion, atencion.borrador_id).faltantes = faltantes_de(atencion.campos)
    sesion.commit()
    request.session["atencion_exito"] = "Cambios guardados."
    return RedirectResponse(f"/atenciones/{atencion.id}", status_code=303)


# Campos


def combinar(anteriores: dict[str, Any] | None, del_formulario: dict[str, Any]) -> dict[str, Any]:
    """Los campos que quedan al guardar el formulario. Lo que el formulario muestra se reemplaza
    por lo enviado (si se vació, se quita); el resto se conserva. Si un dato no cambió, conserva
    su fragmento de origen, para que la trazabilidad a la fuente no se pierda al guardar."""
    anteriores = anteriores or {}
    campos = {k: v for k, v in anteriores.items() if k not in DEL_FORMULARIO}
    for clave, nuevo in del_formulario.items():
        campos[clave] = _con_fragmentos(anteriores.get(clave), nuevo)
    return campos


def _con_fragmentos(anterior: Any, nuevo: Any) -> Any:
    if isinstance(nuevo, list):
        previos = anterior if isinstance(anterior, list) else []
        return [_con_fragmentos(_igual(previos, item), item) for item in nuevo]
    mismo = isinstance(nuevo, dict) and isinstance(anterior, dict)
    if mismo and _sin_fragmento(anterior) == _sin_fragmento(nuevo):
        return nuevo | {"fragmento": anterior.get("fragmento")}
    return nuevo


def _igual(previos: list[Any], item: dict[str, Any]) -> Any:
    return next(
        (p for p in previos if isinstance(p, dict) and _sin_fragmento(p) == _sin_fragmento(item)),
        None,
    )


def _sin_fragmento(dato: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in dato.items() if k != "fragmento" and v not in (None, "")}


def faltantes_de(campos: dict[str, Any]) -> list[dict[str, Any]]:
    """Los faltantes, calculados con las mismas reglas que al extraer: obligatorios y esperados."""
    return calcular_faltantes(RegistroExtraido.model_validate(campos))


# Permisos


def _borrador_revisable(sesion: Session, borrador_id: int, usuario: UsuarioWeb) -> BorradorAtencion:
    """Un borrador pendiente que el usuario puede revisar: el de su profesional o, para la
    encargada de salud, cualquiera."""
    borrador = _borrador_visible(sesion, borrador_id, usuario)  # 404 y 403 como el detalle
    if borrador.estado != EstadoBorrador.PENDIENTE:
        raise HTTPException(409, "El borrador ya no está pendiente.")
    return borrador


def _atencion_editable(sesion: Session, atencion_id: int, usuario: UsuarioWeb) -> Atencion:
    atencion = sesion.get(Atencion, atencion_id)
    if atencion is None:
        raise HTTPException(404, "La atención no existe.")
    if atencion.estado == EstadoAtencion.FIRMADA:
        return atencion  # se muestra en la ficha, que revisa sus propios permisos
    if not puede_editar_atencion(usuario, atencion):
        raise HTTPException(403, "Solo su profesional o la encargada de salud pueden editarla.")
    return atencion


def _candidatos(sesion: Session, borrador: BorradorAtencion) -> list[Residente]:
    """Residentes que puede tener la atención: los asignados al profesional del borrador, que
    es quien la firma. Los que la IA mencionó van primero."""
    mencionados = _codigos_mencionados(borrador)
    residentes = sesion.scalars(
        select(Residente)
        .where(Residente.id.in_(residentes_asignados(borrador.profesional_id)))
        .order_by(Residente.apellidos, Residente.nombres)
    )
    return sorted(residentes, key=lambda r: r.codigo not in mencionados)


def _codigos_mencionados(borrador: BorradorAtencion) -> set[str]:
    valor = ((borrador.campos or {}).get("residente") or {}).get("valor") or ""
    marca = MARCA_DE_RESIDENTE.search(f"[{valor}]")
    return set(marca.group(1).split("|")) if marca else set()


def _residente_ambiguo(borrador: BorradorAtencion) -> bool:
    return borrador.residente_id is None or any(
        a.get("campo") == "residente" for a in borrador.ambiguedades or []
    )


def _residente_elegido(
    sesion: Session, borrador: BorradorAtencion, residente_id: int | None
) -> Residente | None:
    """El residente de la atención: el elegido de la lista si el de la IA quedó ambiguo o sin
    identificar; si no, el del borrador. Tiene que estar asignado al profesional del borrador."""
    if residente_id is None or not _residente_ambiguo(borrador):
        residente_id = borrador.residente_id
    if residente_id is None:
        return None
    if not profesional_asignado(sesion, borrador.profesional_id, residente_id):
        raise HTTPException(403, "El residente no está asignado al profesional del borrador.")
    return sesion.get(Residente, residente_id)


# Páginas


def _evidencia(sesion: Session, borrador_id: int | None) -> dict[str, Any]:
    if borrador_id is None:
        return {"mensajes": [], "extracciones": [], "borrador": None}
    mensajes = sesion.execute(
        select(MensajeEntrante, Transcripcion)
        .join(BorradorMensaje, BorradorMensaje.mensaje_id == MensajeEntrante.id)
        .outerjoin(Transcripcion, Transcripcion.mensaje_id == MensajeEntrante.id)
        .where(BorradorMensaje.borrador_id == borrador_id)
        .order_by(MensajeEntrante.recibido_en, MensajeEntrante.id)
    ).all()
    extracciones = sesion.scalars(
        select(Extraccion).where(Extraccion.borrador_id == borrador_id).order_by(Extraccion.id)
    ).all()
    return {
        "mensajes": mensajes,
        "extracciones": extracciones,
        "borrador": sesion.get(BorradorAtencion, borrador_id),
    }


def _pagina_de_revision(
    request, sesion, usuario, borrador, residente, campos,
    errores=None, faltantes=None, status_code=200,
):
    return pagina(
        request,
        "atencion_revisar.html",
        status_code=status_code,
        usuario=usuario,
        modo="revision",
        accion=f"/borradores/{borrador.id}/revisar",
        residente=residente,
        edad=edad(residente.fecha_nacimiento, hoy_en_chile()) if residente else None,
        elegir_residente=_residente_ambiguo(borrador),
        candidatos=_candidatos(sesion, borrador),
        mencionados=_codigos_mencionados(borrador),
        nombres=_nombres([*_candidatos(sesion, borrador), residente]),
        ambiguedades=borrador.ambiguedades or [],
        campos=campos,
        errores=errores or [],
        faltantes=faltantes or [],
        por_completar=faltantes_de(campos),
        campos_editados=[],
        puede_firmar=False,
        atencion=None,
        exito=None,
        etiquetas=ETIQUETAS | ETIQUETAS_ANTECEDENTES,
        **_evidencia(sesion, borrador.id),
    )


def _pagina_de_edicion(
    request, sesion, usuario, atencion, campos, errores=None, faltantes=None, status_code=200
):
    residente = sesion.get(Residente, atencion.residente_id)
    return pagina(
        request,
        "atencion_revisar.html",
        status_code=status_code,
        usuario=usuario,
        modo="edicion",
        accion=f"/atenciones/{atencion.id}",
        residente=residente,
        edad=edad(residente.fecha_nacimiento, hoy_en_chile()),
        elegir_residente=False,
        candidatos=[],
        mencionados=set(),
        nombres=_nombres([residente]),
        ambiguedades=[],
        campos=campos,
        errores=errores or [],
        faltantes=faltantes or [],
        por_completar=faltantes_de(campos),
        campos_editados=atencion.campos_editados or [],
        puede_firmar=puede_firmar(usuario, atencion),
        atencion=atencion,
        exito=request.session.pop("atencion_exito", None),
        etiquetas=ETIQUETAS | ETIQUETAS_ANTECEDENTES,
        **_evidencia(sesion, atencion.borrador_id),
    )


def _nombres(residentes: list[Residente | None]) -> dict[str, str]:
    """Para mostrar los fragmentos seudonimizados ("[RES-02]") con el nombre del residente."""
    return {r.codigo: f"{r.nombres} {r.apellidos}" for r in residentes if r is not None}
