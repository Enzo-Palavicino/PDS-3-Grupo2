"""Atenciones desde la web (E3-01): el formulario del Registro de Atención.

El mismo formulario se reutiliza para revisar los borradores de la IA (E3-02): la plantilla
dominio/formulario_atencion.html recibe los campos con el formato de app/nucleo/campos.py, y
campos_del_formulario hace el camino inverso, de lo enviado a ese formato.
"""

import re
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from starlette.datastructures import FormData, UploadFile

from app.modelos import OrigenAtencion, Residente, Rol, TipoAdjunto, UsuarioWeb
from app.nucleo.adjuntos import TAMANO_MAXIMO_BYTES, ArchivoNoPermitido, guardar_adjunto
from app.nucleo.atenciones import DatosIncompletos, ErrorDeAtencion, crear_atencion
from app.nucleo.permisos import puede_registrar_atencion
from app.nucleo.tratamientos import hoy_en_chile
from app.web.autenticacion import SesionBD, exigir_rol, verificar_csrf
from app.web.fichas import edad
from app.web.plantillas import pagina

router = APIRouter(prefix="/atenciones")
PersonalClinico = Annotated[
    UsuarioWeb, Depends(exigir_rol(Rol.ENCARGADA_SALUD, Rol.PROFESIONAL))
]
UsuarioProfesional = Annotated[UsuarioWeb, Depends(exigir_rol(Rol.PROFESIONAL))]

HORA = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d")
MAXIMO_ARCHIVOS = 10
# Campos de una indicación farmacológica, en el orden de las columnas del formulario.
INDICACION = (
    "medicamento",
    "dosis",
    "frecuencia_horario",
    "via",
    "duracion",
    "fecha_inicio",
    "fecha_termino",
)
TIPOS_DE_ADJUNTO = [
    (TipoAdjunto.RECETA, "Receta"),
    (TipoAdjunto.EXAMEN, "Examen"),
    (TipoAdjunto.INFORME, "Informe"),
    (TipoAdjunto.OTRO, "Otro"),
]


async def formulario(request: Request) -> FormData:
    """El formulario enviado, con varios valores por nombre (indicaciones y archivos). Starlette
    lo guarda en el request, así que leerlo aquí y en verificar_csrf no lo lee dos veces."""
    return await request.form()


Formulario = Annotated[FormData, Depends(formulario)]


@router.get("")
def listar(request: Request, usuario: PersonalClinico):
    return pagina(
        request, "pendiente.html", usuario=usuario, titulo="Atenciones", status_code=501
    )


@router.get("/nueva")
def nueva(request: Request, sesion: SesionBD, usuario: UsuarioProfesional, residente_id: int):
    residente = _residente_para_registrar(sesion, usuario, residente_id)
    return _pagina(request, residente, usuario, campos={})


@router.post("/nueva", dependencies=[Depends(verificar_csrf)])
def registrar(request: Request, sesion: SesionBD, usuario: UsuarioProfesional, datos: Formulario):
    try:
        residente_id = int(datos.get("residente_id", ""))
    except ValueError:
        raise HTTPException(400, "Falta el residente.") from None
    residente = _residente_para_registrar(sesion, usuario, residente_id)
    campos, errores = campos_del_formulario(datos)
    archivos = [a for a in datos.getlist("archivos") if isinstance(a, UploadFile) and a.filename]
    if datos.get("confirmo_identidad") != str(residente.id):
        nombre = f"{residente.nombres} {residente.apellidos}"
        errores.insert(0, f"Confirma que la atención es de {nombre}.")
    if len(archivos) > MAXIMO_ARCHIVOS:
        errores.append(f"Adjunta hasta {MAXIMO_ARCHIVOS} archivos.")
    extra = {"tipo_adjunto": datos.get("tipo_adjunto", ""), "emisor": datos.get("emisor", "")}
    if errores:
        return _pagina(
            request, residente, usuario, campos,
            errores=errores, status_code=400, valores_extra=extra,
        )

    try:
        atencion = crear_atencion(sesion, residente.id, usuario, campos, OrigenAtencion.WEB)
        for archivo in archivos:
            guardar_adjunto(
                sesion,
                residente.id,
                archivo.file.read(TAMANO_MAXIMO_BYTES + 1),
                archivo.filename,
                datos.get("tipo_adjunto", ""),
                usuario,
                atencion_id=atencion.id,
                emisor=datos.get("emisor", ""),
            )
        sesion.commit()
    except DatosIncompletos as error:
        sesion.rollback()
        return _pagina(
            request, residente, usuario, campos,
            errores=[str(error)], faltantes=error.faltantes, status_code=400,
            valores_extra=extra,
        )
    except (ErrorDeAtencion, ArchivoNoPermitido, ValueError, PermissionError) as error:
        # Nada queda a medias: ni la atención ni los archivos que alcanzaron a guardarse.
        sesion.rollback()
        return _pagina(
            request, residente, usuario, campos,
            errores=[str(error)], status_code=400, valores_extra=extra,
        )
    finally:
        for archivo in archivos:
            archivo.file.close()
    # Queda en borrador, lista para firmar (E3-03).
    return RedirectResponse(f"/atenciones/{atencion.id}/firmar", status_code=303)


def campos_del_formulario(datos: FormData) -> tuple[dict[str, Any], list[str]]:
    """Convierte lo enviado al formato de app/nucleo/campos.py. Devuelve los campos (aunque
    tengan errores, para volver a mostrarlos) y los errores de formato. Los obligatorios los
    revisa crear_atencion. Lo escrito a mano no tiene fragmento de origen."""
    errores: list[str] = []

    def texto(nombre: str) -> str:
        valor = datos.get(nombre, "")
        return valor.strip() if isinstance(valor, str) else ""

    def dato(valor: str) -> dict[str, Any] | None:
        return {"valor": valor, "fragmento": None} if valor else None

    def lista(nombre: str) -> list[dict[str, Any]] | None:
        lineas = [linea.strip() for linea in texto(nombre).splitlines() if linea.strip()]
        return [dato(linea) for linea in lineas] or None

    def fecha(valor: str, etiqueta: str) -> str:
        if valor:
            try:
                date.fromisoformat(valor)
            except ValueError:
                errores.append(f"{etiqueta}: indica una fecha válida.")
        return valor

    campos: dict[str, Any] = {
        "fecha_atencion": dato(fecha(texto("fecha_atencion"), "Fecha de atención")),
        "hora_atencion": dato(texto("hora_atencion")),
        "lugar": dato(texto("lugar")),
        "motivo": dato(texto("motivo")),
        "diagnosticos": lista("diagnosticos"),
        "evolucion_clinica": dato(texto("evolucion_clinica")),
        "observaciones": dato(texto("observaciones")),
        "indicaciones_farmacologicas": _indicaciones(datos, fecha, errores),
        "otras_indicaciones": lista("otras_indicaciones"),
        "examenes_solicitados": lista("examenes_solicitados"),
    }
    if (hora := texto("hora_atencion")) and not HORA.fullmatch(hora):
        errores.append("Hora: usa el formato HH:MM.")

    control = {
        "fecha": fecha(texto("control_fecha"), "Próximo control") or None,
        "descripcion": texto("control_descripcion") or None,
    }
    if any(control.values()):
        campos["proximo_control"] = control | {"fragmento": None}
    acompanante = {
        "nombre": texto("acompanante_nombre") or None,
        "cargo": texto("acompanante_cargo") or None,
    }
    if any(acompanante.values()):
        campos["acompanante"] = acompanante | {"fragmento": None}
    return {clave: valor for clave, valor in campos.items() if valor}, errores


def _indicaciones(datos: FormData, fecha, errores: list[str]) -> list[dict[str, Any]] | None:
    """Una indicación por fila del formulario. Las filas vacías se ignoran."""
    columnas = [datos.getlist(f"ind_{nombre}") for nombre in INDICACION]
    indicaciones = []
    for numero, fila in enumerate(zip(*columnas, strict=False), start=1):
        valores = {
            nombre: (v.strip() if isinstance(v, str) else "")
            for nombre, v in zip(INDICACION, fila, strict=True)
        }
        if not any(valores.values()):
            continue
        if not valores["medicamento"]:
            errores.append(f"Indicación {numero}: falta el medicamento.")
        fecha(valores["fecha_inicio"], f"Indicación {numero}, inicio")
        fecha(valores["fecha_termino"], f"Indicación {numero}, término")
        indicacion = {nombre: valor or None for nombre, valor in valores.items()}
        indicaciones.append(indicacion | {"fragmento": None})
    return indicaciones or None


def _residente_para_registrar(sesion, usuario: UsuarioWeb, residente_id: int) -> Residente:
    if not puede_registrar_atencion(sesion, usuario, residente_id):
        raise HTTPException(403, "No puedes registrar atenciones para este residente.")
    return sesion.get(Residente, residente_id)


def _pagina(
    request: Request,
    residente: Residente,
    usuario: UsuarioWeb,
    campos: dict[str, Any],
    errores: list[str] | None = None,
    faltantes: list[str] | None = None,
    status_code: int = 200,
    valores_extra: dict[str, str] | None = None,
):
    """valores_extra: lo enviado que no es parte de los campos (tipo de adjunto y emisor)."""
    return pagina(
        request,
        "atencion_nueva.html",
        status_code=status_code,
        usuario=usuario,
        residente=residente,
        edad=edad(residente.fecha_nacimiento, hoy_en_chile()),
        campos=campos,
        errores=errores or [],
        faltantes=faltantes or [],
        tipos_de_adjunto=TIPOS_DE_ADJUNTO,
        valores_extra=valores_extra or {},
    )
