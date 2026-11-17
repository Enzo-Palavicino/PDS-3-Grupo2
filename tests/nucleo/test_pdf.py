from io import BytesIO

import pytest
from PIL import Image

from app.nucleo.adjuntos import ArchivoNoPermitido
from app.nucleo.pdf import MAXIMO_LADO_PIXELES, imagen_del_pdf, validar_pdf


@pytest.mark.parametrize("ancho,alto", [(612, 792), (3000, 4000)])
def test_renderiza_una_pagina_en_memoria_y_limita_los_pixeles(crear_pdf, ancho, alto):
    pdf = crear_pdf(ancho=ancho, alto=alto)
    validar_pdf(pdf)

    resultado = imagen_del_pdf(pdf)

    with Image.open(BytesIO(resultado)) as imagen:
        assert imagen.format == "PNG"
        assert 0 < max(imagen.size) <= MAXIMO_LADO_PIXELES
    validar_pdf(pdf)  # el original se conserva


@pytest.mark.parametrize("operacion", [validar_pdf, imagen_del_pdf])
def test_rechaza_pdf_multipagina(crear_pdf, operacion):
    with pytest.raises(ArchivoNoPermitido, match="una sola página"):
        operacion(crear_pdf(2))


@pytest.mark.parametrize("operacion", [validar_pdf, imagen_del_pdf])
def test_rechaza_pdf_invalido(operacion):
    with pytest.raises(ArchivoNoPermitido, match="PDF"):
        operacion(b"%PDF-1.7\nno es un PDF completo\n%%EOF")
