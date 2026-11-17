"""Edición de los campos compartidos, conservando la evidencia original del documento."""

from typing import Any

from starlette.datastructures import FormData

from app.nucleo.atenciones import ErrorDeAtencion
from app.nucleo.campos import CAMPOS_LISTA, ETIQUETAS, ETIQUETAS_ANTECEDENTES

SUBCAMPOS = {
    "fecha_atencion": [("valor", "Fecha original de atención (opcional)", "date")],
    "hora_atencion": [("valor", "Hora", "time")],
    "lugar": [("valor", "Lugar", "text")],
    "especialidad": [("valor", "Especialidad del documento", "text")],
    "indicaciones_farmacologicas": [
        ("medicamento", "Medicamento", "text"), ("dosis", "Dosis", "text"),
        ("frecuencia_horario", "Frecuencia / horario", "text"), ("via", "Vía", "text"),
        ("duracion", "Duración", "text"), ("fecha_inicio", "Fecha de inicio", "date"),
        ("fecha_termino", "Fecha de término", "date"),
    ],
    "proximo_control": [("fecha", "Fecha del control", "date"), ("descripcion", "Descripción", "text")],
    "acompanante": [("nombre", "Nombre", "text"), ("cargo", "Cargo", "text")],
    "mediciones": [("peso_kg", "Peso (kg)", "number"), ("talla_cm", "Talla (cm)", "number")],
}
ETIQUETAS_EDICION = {k: v for k, v in (ETIQUETAS | ETIQUETAS_ANTECEDENTES).items() if k != "residente"}


def subcampos(clave: str) -> list[tuple[str, str, str]]:
    return SUBCAMPOS.get(clave, [("valor", "Valor", "textarea")])


def _originales(campos: dict[str, Any], clave: str) -> list[dict[str, Any]]:
    dato = campos.get(clave)
    return (dato or []) if clave in CAMPOS_LISTA else [dato or {}]


def filas_de_edicion(
    campos: dict[str, Any], formulario: FormData | None = None
) -> list[dict[str, Any]]:
    secciones = []
    for clave, etiqueta in ETIQUETAS_EDICION.items():
        columnas = subcampos(clave)
        originales = _originales(campos, clave)
        cantidad = max(
            len(originales),
            len(formulario.getlist(f"{clave}.{columnas[0][0]}")) if formulario is not None else 0,
            1,
        )
        filas = []
        for indice in range(cantidad):
            original = originales[indice] if indice < len(originales) else {}
            valores = {}
            for nombre, _, _ in columnas:
                enviados = formulario.getlist(f"{clave}.{nombre}") if formulario is not None else []
                valor = enviados[indice] if indice < len(enviados) else (
                    original.get(nombre) if formulario is None else None
                )
                valores[nombre] = valor if isinstance(valor, (str, int, float)) else ""
            filas.append({"valores": valores, "fragmento": original.get("fragmento")})
        secciones.append({
            "clave": clave, "etiqueta": etiqueta, "lista": clave in CAMPOS_LISTA,
            "columnas": columnas, "filas": filas,
        })
    return secciones


def campos_del_formulario(datos: FormData, originales: dict[str, Any]) -> dict[str, Any]:
    campos: dict[str, Any] = {}
    for clave, etiqueta in ETIQUETAS_EDICION.items():
        columnas = subcampos(clave)
        valores = [datos.getlist(f"{clave}.{nombre}") for nombre, _, _ in columnas]
        if len({len(columna) for columna in valores}) != 1:
            raise ValueError(f"{etiqueta}: el formulario está incompleto.")
        if clave not in CAMPOS_LISTA and len(valores[0]) != 1:
            raise ValueError(f"{etiqueta}: envía un solo dato.")
        anteriores = _originales(originales, clave)
        filas = []
        for indice, fila in enumerate(zip(*valores, strict=True)):
            dato = {}
            for (nombre, _, tipo), valor in zip(columnas, fila, strict=True):
                if not isinstance(valor, str):
                    raise ErrorDeAtencion(f"{etiqueta}: el valor debe ser texto.")
                valor = valor.strip()
                try:
                    dato[nombre] = float(valor.replace(",", ".")) if valor and tipo == "number" else valor or None
                except ValueError:
                    raise ValueError(f"{etiqueta}: indica un número válido.") from None
            if not any(v is not None for v in dato.values()):
                continue
            anterior = anteriores[indice] if indice < len(anteriores) else {}
            dato["fragmento"] = (
                anterior.get("fragmento")
                if all(anterior.get(nombre) == valor for nombre, valor in dato.items()) else None
            )
            filas.append(dato)
        campos[clave] = filas if clave in CAMPOS_LISTA else (filas[0] if filas else None)
    return campos
