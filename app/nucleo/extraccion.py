"""Extracción con IA de los campos del "Registro de Atención y Control de Salud".

El LLM recibe el texto seudonimizado y devuelve los campos en JSON, cada uno con el fragmento del
texto que lo respalda. Todo lo que devuelve se valida antes de usarse:

- que cumpla el esquema (si no, se le pide una vez más);
- que cada fragmento aparezca de verdad en el texto (si no, el dato se descarta: podría ser
  inventado);
- que las fechas y horas tengan un formato válido.

El residente lo decide el sistema con lo que encontró la seudonimización, no el LLM: así un
nombre ambiguo o un segundo residente nunca pasan inadvertidos.
"""

import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ValidationError

from app.modelos import Residente
from app.nucleo.seudonimizacion import TextoSeudonimizado, normalizar, seudonimizar
from app.proveedores.llm.base import ProveedorLLM

logger = logging.getLogger(__name__)

ZONA_HORARIA = ZoneInfo("America/Santiago")
SIN_RESPALDO = "el fragmento citado no aparece en el texto"
FORMATO_INVALIDO = "fecha u hora con formato inválido"


# Esquema de la respuesta del LLM (sección 9.2 de la especificación). Cada dato trae el
# fragmento del texto que lo respalda. La especialidad no se le pide: se conoce por el vínculo.


class Campo(BaseModel):
    valor: str | None = None
    fragmento: str | None = None


class IndicacionFarmacologica(BaseModel):
    medicamento: str | None = None
    dosis: str | None = None
    frecuencia_horario: str | None = None
    via: str | None = None
    duracion: str | None = None
    fecha_inicio: str | None = None
    fecha_termino: str | None = None
    fragmento: str | None = None


class ProximoControl(BaseModel):
    fecha: str | None = None
    descripcion: str | None = None
    fragmento: str | None = None


class Acompanante(BaseModel):
    nombre: str | None = None
    cargo: str | None = None
    fragmento: str | None = None


class Ambiguedad(BaseModel):
    campo: str
    motivo: str


class RegistroExtraido(BaseModel):
    # True si el mensaje pide información en vez de informar una atención. No se guarda en el
    # borrador: solo sirve para que una pregunta no cree uno.
    es_consulta: bool = False
    residente: Campo | None = None
    fecha_atencion: Campo | None = None
    hora_atencion: Campo | None = None
    lugar: Campo | None = None
    motivo: Campo | None = None
    diagnosticos: list[Campo] = []
    evolucion_clinica: Campo | None = None
    observaciones: Campo | None = None
    indicaciones_farmacologicas: list[IndicacionFarmacologica] = []
    otras_indicaciones: list[Campo] = []
    examenes_solicitados: list[Campo] = []
    proximo_control: ProximoControl | None = None
    acompanante: Acompanante | None = None
    ambiguedades: list[Ambiguedad] = []


def esquema_estricto(modelo: type[BaseModel]) -> dict[str, Any]:
    """JSON Schema del modelo en la forma que exige el modo estricto del LLM: todas las
    propiedades obligatorias (las opcionales aceptan null), sin propiedades extra y sin
    "title" ni "default"."""
    esquema = modelo.model_json_schema()
    _ajustar_para_modo_estricto(esquema)
    return esquema


def _ajustar_para_modo_estricto(esquema: dict[str, Any]) -> None:
    esquema.pop("title", None)
    esquema.pop("default", None)
    if "properties" in esquema:
        esquema["required"] = list(esquema["properties"])
        esquema["additionalProperties"] = False
    hijos = [
        *esquema.get("properties", {}).values(),
        *esquema.get("$defs", {}).values(),
        *esquema.get("anyOf", []),
    ]
    if "items" in esquema:
        hijos.append(esquema["items"])
    for hijo in hijos:
        _ajustar_para_modo_estricto(hijo)


ESQUEMA = esquema_estricto(RegistroExtraido)

INSTRUCCIONES = """\
Extraes los datos de un registro de atención de salud de un niño o niña de 0 a 5 años que vive
en un hogar de protección en Chile. El registro lo dictó o escribió el profesional que hizo la
atención, en español de Chile. Si viene de una transcripción automática, puede tener errores.

Reglas:
1. No inventes. Si un dato no está en el texto, deja el campo en null o la lista vacía. Nunca
   deduzcas diagnósticos, medicamentos, dosis ni fechas que el texto no diga.
2. En cada dato, "fragmento" es la copia exacta de la parte del texto que lo respalda.
3. Los residentes aparecen como códigos entre corchetes, por ejemplo [RES-02]. En
   residente.valor escribe solo el código, sin corchetes. Una marca con varios códigos, como
   [RES-01|RES-04], significa que no se sabe cuál es: en ese caso deja residente en null.
4. [RUT], [TEL] y [EMAIL] reemplazan datos personales: no los uses como valores.
5. Escribe las fechas como AAAA-MM-DD y las horas como HH:MM (24 horas). Resuelve las
   expresiones relativas ("hoy", "ayer", "en dos semanas") con la fecha de referencia.
6. lugar es "Hogar", "CESFAM", "Hospital Luis Calvo Mackenna" u otro lugar que se nombre.
7. Cada medicamento indicado es un elemento de indicaciones_farmacologicas. Su fecha_inicio y
   su fecha_termino van solo si el texto las dice: no las calcules con la duración ni supongas
   que empieza hoy. Las demás indicaciones (aseo nasal, reposo, dieta) van en
   otras_indicaciones.
8. Si un dato es dudoso o contradictorio, agrégalo a ambiguedades con el campo y el motivo.
9. es_consulta es true solo si el mensaje pregunta o pide información (por ejemplo, "¿qué
   alergias tiene...?") en vez de informar una atención. En ese caso deja los demás campos
   vacíos.
"""

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
NIVELES = {
    "sala_cuna_menor": "sala cuna menor",
    "sala_cuna_mayor": "sala cuna mayor",
    "heterogeneo": "heterogéneo",
}


class ErrorExtraccion(Exception):
    """El LLM no devolvió una respuesta válida, ni siquiera al pedírsela de nuevo."""


@dataclass
class ResultadoExtraccion:
    registro: RegistroExtraido  # validado; sus ambigüedades incluyen las que agregó el sistema
    residente_id: int | None
    entrada: str  # lo que recibió el LLM: el contexto y el texto seudonimizado
    salida: dict[str, Any]  # lo que devolvió el LLM, tal cual, para el historial
    proveedor: str
    modelo: str


def extraer_registro(
    texto: str,
    residentes: list[Residente],
    especialidad: str,
    referencia: datetime,
    llm: ProveedorLLM,
) -> ResultadoExtraccion:
    """Seudonimiza el texto, le pide los campos al LLM y valida su respuesta.

    referencia es el momento en que se recibió el mensaje: con ella se resuelven expresiones
    como "hoy" o "en dos semanas".
    """
    seudonimizado = seudonimizar(texto, residentes)
    entrada = armar_entrada(seudonimizado.texto, residentes, especialidad, referencia)
    registro, salida, modelo = _pedir_registro(llm, entrada)

    # Las ambigüedades sobre el residente las decide el sistema, no el LLM.
    ambiguedades = [a for a in registro.ambiguedades if a.campo != "residente"]
    _descartar_datos_sin_respaldo(registro, seudonimizado.texto, ambiguedades)
    _descartar_fechas_invalidas(registro, ambiguedades)
    codigo = _decidir_residente(registro, seudonimizado, ambiguedades)
    registro.ambiguedades = ambiguedades

    ids = {residente.codigo: residente.id for residente in residentes}
    return ResultadoExtraccion(
        registro=registro,
        residente_id=ids.get(codigo) if codigo else None,
        entrada=entrada,
        salida=salida,
        proveedor=llm.nombre,
        modelo=modelo,
    )


def armar_entrada(
    texto: str, residentes: list[Residente], especialidad: str, referencia: datetime
) -> str:
    """Mensaje para el LLM: la fecha de referencia, la especialidad, los códigos de los
    residentes (con nivel y edad, nunca nombres) y el texto ya seudonimizado."""
    local = referencia.astimezone(ZONA_HORARIA)
    lista = "\n".join(
        f"- {r.codigo}: {NIVELES.get(r.nivel, r.nivel)}, {_edad(r.fecha_nacimiento, local.date())}"
        for r in residentes
    )
    return (
        f"Fecha y hora de referencia: {DIAS[local.weekday()]} {local:%Y-%m-%d %H:%M}, "
        "hora de Chile.\n"
        f"Especialidad del profesional: {especialidad}.\n"
        f"Residentes del Hogar (código, nivel y edad):\n{lista}\n\n"
        f"Registro:\n{texto}"
    )


def _edad(nacimiento: date, hoy: date) -> str:
    meses = (hoy.year - nacimiento.year) * 12 + hoy.month - nacimiento.month
    meses -= hoy.day < nacimiento.day  # el mes en curso todavía no se cumple
    if meses < 24:
        return "1 mes" if meses == 1 else f"{meses} meses"
    return f"{meses // 12} años"


def _pedir_registro(llm: ProveedorLLM, entrada: str) -> tuple[RegistroExtraido, Any, str]:
    # Si la respuesta no cumple el esquema, se pide una vez más antes de rendirse.
    for intento in (1, 2):
        resultado = llm.generar_json(INSTRUCCIONES, entrada, ESQUEMA)
        try:
            salida = json.loads(resultado.texto)
            return RegistroExtraido.model_validate(salida), salida, resultado.modelo
        except (ValueError, ValidationError):
            # Solo el número de intento: la respuesta trae datos del registro.
            logger.warning("El LLM devolvió una respuesta inválida (intento %s de 2)", intento)
    raise ErrorExtraccion("el LLM no devolvió una respuesta válida")


CAMPOS_SIMPLES = (
    "fecha_atencion",
    "hora_atencion",
    "lugar",
    "motivo",
    "evolucion_clinica",
    "observaciones",
    "proximo_control",
    "acompanante",
)
LISTAS = ("diagnosticos", "indicaciones_farmacologicas", "otras_indicaciones", "examenes_solicitados")


def _descartar_datos_sin_respaldo(
    registro: RegistroExtraido, texto: str, ambiguedades: list[Ambiguedad]
) -> None:
    """Quita los datos cuyo fragmento no aparece en el texto: el LLM podría haberlos inventado.
    También quita los datos vacíos (todos sus valores en null)."""
    texto_comparable = _comparable(texto)

    def respaldado(dato: BaseModel) -> bool:
        return bool(dato.fragmento) and _comparable(dato.fragmento) in texto_comparable

    for nombre in CAMPOS_SIMPLES:
        dato = getattr(registro, nombre)
        if dato is None:
            continue
        if not _tiene_contenido(dato):
            setattr(registro, nombre, None)
        elif not respaldado(dato):
            setattr(registro, nombre, None)
            ambiguedades.append(Ambiguedad(campo=nombre, motivo=SIN_RESPALDO))

    for nombre in LISTAS:
        datos = [dato for dato in getattr(registro, nombre) if _tiene_contenido(dato)]
        respaldados = [dato for dato in datos if respaldado(dato)]
        if len(respaldados) < len(datos):
            ambiguedades.append(Ambiguedad(campo=nombre, motivo=SIN_RESPALDO))
        setattr(registro, nombre, respaldados)


def _tiene_contenido(dato: BaseModel) -> bool:
    return any(valor is not None for nombre, valor in dato if nombre != "fragmento")


def _comparable(texto: str) -> str:
    """Para comparar fragmentos sin importar mayúsculas, tildes, espacios ni la puntuación de
    los extremos."""
    return " ".join(normalizar(texto).split()).strip(" .,;:\"'«»")


FECHA = re.compile(r"\d{4}-\d{2}-\d{2}")
HORA = re.compile(r"([01]\d|2[0-3]):[0-5]\d")


def _descartar_fechas_invalidas(registro: RegistroExtraido, ambiguedades: list[Ambiguedad]) -> None:
    if registro.fecha_atencion and not _es_fecha(registro.fecha_atencion.valor):
        registro.fecha_atencion = None
        ambiguedades.append(Ambiguedad(campo="fecha_atencion", motivo=FORMATO_INVALIDO))
    if registro.hora_atencion and not HORA.fullmatch(registro.hora_atencion.valor or ""):
        registro.hora_atencion = None
        ambiguedades.append(Ambiguedad(campo="hora_atencion", motivo=FORMATO_INVALIDO))
    control = registro.proximo_control
    if control and control.fecha is not None and not _es_fecha(control.fecha):
        control.fecha = None  # se conserva la descripción ("en dos semanas")
        ambiguedades.append(Ambiguedad(campo="proximo_control", motivo=FORMATO_INVALIDO))
    for indicacion in registro.indicaciones_farmacologicas:
        for campo in ("fecha_inicio", "fecha_termino"):
            valor = getattr(indicacion, campo)
            if valor is not None and not _es_fecha(valor):
                setattr(indicacion, campo, None)
                ambiguedades.append(
                    Ambiguedad(campo="indicaciones_farmacologicas", motivo=FORMATO_INVALIDO)
                )


def _es_fecha(valor: str | None) -> bool:
    if valor is None or not FECHA.fullmatch(valor):
        return False
    try:
        date.fromisoformat(valor)
    except ValueError:  # por ejemplo, 2026-02-30
        return False
    return True


def _decidir_residente(
    registro: RegistroExtraido, seudonimizado: TextoSeudonimizado, ambiguedades: list[Ambiguedad]
) -> str | None:
    """Decide el residente con las menciones que encontró la seudonimización."""
    identificados = {
        next(iter(mencion.codigos)) for mencion in seudonimizado.menciones if not mencion.ambigua
    }
    # Una mención ambigua queda resuelta si uno de sus códigos aparece nombrado sin ambigüedad
    # (por ejemplo, "Tomás" en el registro y "Tomás Rivas" en la respuesta que lo completa).
    sin_resolver = [
        mencion.codigos
        for mencion in seudonimizado.menciones
        if mencion.ambigua and not mencion.codigos & identificados
    ]

    if len(identificados) > 1 or (identificados and sin_resolver):
        motivo = "más de un residente"
    elif identificados:
        codigo = identificados.pop()
        # Se conserva el fragmento del LLM si eligió el mismo residente.
        anterior = registro.residente
        coincide = anterior is not None and (anterior.valor or "").strip("[]") == codigo
        registro.residente = Campo(
            valor=codigo, fragmento=anterior.fragmento if coincide else f"[{codigo}]"
        )
        return codigo
    elif sin_resolver:
        posibles = sorted(set().union(*sin_resolver))
        motivo = f"residente ambiguo: puede ser {' o '.join(posibles)}"
    else:
        motivo = "residente no identificado"
    registro.residente = None
    ambiguedades.append(Ambiguedad(campo="residente", motivo=motivo))
    return None
