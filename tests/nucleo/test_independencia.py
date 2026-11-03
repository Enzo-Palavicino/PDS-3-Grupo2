import ast
from pathlib import Path

CARPETA_NUCLEO = Path(__file__).resolve().parents[2] / "app" / "nucleo"


def modulos_importados(archivo: Path) -> list[str]:
    modulos = []
    for nodo in ast.walk(ast.parse(archivo.read_text(encoding="utf-8"))):
        if isinstance(nodo, ast.Import):
            modulos += [alias.name for alias in nodo.names]
        elif isinstance(nodo, ast.ImportFrom) and nodo.module:
            modulos.append(nodo.module)
    return modulos


def test_el_nucleo_no_depende_de_ningun_canal_en_particular():
    # Agregar WhatsApp debe ser solo escribir su adaptador: de los canales, el núcleo solo
    # conoce la interfaz común (app.canales.base).
    for archivo in CARPETA_NUCLEO.rglob("*.py"):
        for modulo in modulos_importados(archivo):
            if modulo.startswith("app.canales"):
                assert modulo == "app.canales.base", f"{archivo.name} importa {modulo}"
