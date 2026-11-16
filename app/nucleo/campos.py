"""Campos del "Registro de Atención y Control de Salud".

Un borrador de la IA, una atención y un documento histórico guardan sus campos con el mismo
formato, así que el formulario web, la extracción con IA y la revisión de documentos usan estos
nombres. Cada dato lleva el fragmento del texto que lo respalda (vacío si se escribió a mano):

    {
        "motivo": {"valor": "control sano", "fragmento": "vino a control sano"},
        "diagnosticos": [{"valor": "bronquitis", "fragmento": "..."}],
        "indicaciones_farmacologicas": [
            {"medicamento": "salbutamol", "dosis": "2 puff", "frecuencia_horario": "cada 8 horas",
             "via": "inhalatoria", "duracion": "5 días", "fecha_inicio": None,
             "fecha_termino": None, "fragmento": "..."}
        ],
        "proximo_control": {"fecha": "2026-11-16", "descripcion": "...", "fragmento": "..."},
        "acompanante": {"nombre": "...", "cargo": "...", "fragmento": "..."},
        ...
    }

Las fechas van como AAAA-MM-DD y las horas como HH:MM. Si se cambia la forma de un campo, hay que
avisar a quien usa estos nombres: incorporar_a_ficha (app/nucleo/atenciones.py) los lee al firmar.
"""

# Campos del Registro de Atención, en el orden en que se muestran.
ETIQUETAS = {
    "residente": "Residente",
    "fecha_atencion": "Fecha de atención",
    "hora_atencion": "Hora",
    "lugar": "Lugar",
    "especialidad": "Especialidad",
    "motivo": "Motivo",
    "diagnosticos": "Diagnósticos",
    "evolucion_clinica": "Evolución clínica",
    "observaciones": "Observaciones",
    "indicaciones_farmacologicas": "Indicaciones farmacológicas",
    "otras_indicaciones": "Otras indicaciones",
    "examenes_solicitados": "Exámenes solicitados",
    "proximo_control": "Próximo control",
    "acompanante": "Acompañante",
}

# Antecedentes que puede traer una atención (E3-05). Al firmar, pasan a la ficha como
# antecedentes y mediciones. Formas:
#   alergias, vacunas, hospitalizaciones: [{"valor": ..., "fragmento": ...}, ...]
#   mediciones: {"peso_kg": 12.4, "talla_cm": 88.0, "fragmento": ...}
ETIQUETAS_ANTECEDENTES = {
    "alergias": "Alergias",
    "mediciones": "Peso y talla",
    "vacunas": "Vacunas",
    "hospitalizaciones": "Hospitalizaciones",
}

CAMPOS_ATENCION = [*ETIQUETAS, *ETIQUETAS_ANTECEDENTES]

# Campos que son listas; el resto es un solo dato.
CAMPOS_LISTA = {
    "diagnosticos",
    "indicaciones_farmacologicas",
    "otras_indicaciones",
    "examenes_solicitados",
    "alergias",
    "vacunas",
    "hospitalizaciones",
}
