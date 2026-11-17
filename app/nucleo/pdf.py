"""Validación y rasterización local de PDF históricos de una sola página."""

from contextlib import closing
from io import BytesIO
from math import isfinite
from threading import Lock

import pypdfium2 as pdfium

from app.nucleo.adjuntos import ArchivoNoPermitido

# PDFium no admite llamadas simultáneas, ni siquiera sobre documentos diferentes.
_PDFIUM = Lock()
MAXIMO_LADO_PIXELES = 2000


def _exigir_una_pagina(pdf: pdfium.PdfDocument) -> None:
    if len(pdf) != 1:
        raise ArchivoNoPermitido(
            "La digitalización admite PDF de una sola página. "
            "Separa las fichas en archivos individuales."
        )


def validar_pdf(contenido: bytes) -> None:
    try:
        with _PDFIUM, pdfium.PdfDocument(contenido) as pdf:
            _exigir_una_pagina(pdf)
    except pdfium.PdfiumError:
        raise ArchivoNoPermitido(
            "No se pudo abrir el PDF. Debe ser válido y no estar protegido con contraseña."
        ) from None


def imagen_del_pdf(contenido: bytes) -> bytes:
    """Devuelve un PNG en memoria, sin modificar ni escribir el original."""
    try:
        with _PDFIUM, pdfium.PdfDocument(contenido) as pdf:
            _exigir_una_pagina(pdf)
            with closing(pdf[0]) as pagina:
                ancho, alto = pagina.get_size()
                if not all(isfinite(lado) and lado > 0 for lado in (ancho, alto)):
                    raise ArchivoNoPermitido("El PDF tiene dimensiones de página inválidas.")
                escala = min(2.0, MAXIMO_LADO_PIXELES / max(ancho, alto))
                with closing(pagina.render(scale=escala)) as bitmap, bitmap.to_pil() as imagen:
                    salida = BytesIO()
                    imagen.save(salida, format="PNG")
                    return salida.getvalue()
    except pdfium.PdfiumError:
        raise ArchivoNoPermitido("No se pudo convertir la página del PDF en una imagen.") from None
