"""Seudonimización: quita los datos identificables del texto antes de enviarlo al LLM.

- Los nombres, apellidos y apodos de los residentes se reemplazan por su código, como [RES-02].
  La comparación no distingue mayúsculas ni tildes, y tolera errores menores de transcripción.
- Si una mención puede ser de más de un residente (por ejemplo, "Tomás" cuando hay dos), se
  reemplaza por todos sus códigos posibles, [RES-01|RES-04], y queda marcada como ambigua.
- RUT, teléfonos y correos se reemplazan por [RUT], [TEL] y [EMAIL].

Limitación: los nombres de personas que no son residentes (por ejemplo, familiares o
funcionarios) no se detectan y llegan al LLM tal como están.
"""

import re
import unicodedata
from dataclasses import dataclass

from app.modelos import Residente

RUT = re.compile(r"\b\d{1,2}(?:\.\d{3}){2}-[\dkK]\b|\b\d{7,8}-[\dkK]\b")
CORREO = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Celulares (9 XXXX XXXX) y fijos de Santiago (2 XXXX XXXX), con o sin +56.
TELEFONO = re.compile(r"(?<!\d)(?:\+?56[\s-]?)?[29][\s-]?\d{4}[\s-]?\d{4}(?!\d)")
PALABRA = re.compile(r"\w+")
# Palabras de los apellidos compuestos ("de la Fuente") que no identifican a nadie por sí solas.
PARTICULAS = {"de", "del", "la", "las", "los", "y"}


@dataclass(frozen=True)
class Mencion:
    """Parte del texto que nombra a un residente, con los códigos de quienes podrían ser."""

    codigos: frozenset[str]

    @property
    def ambigua(self) -> bool:
        return len(self.codigos) > 1


@dataclass(frozen=True)
class TextoSeudonimizado:
    texto: str
    menciones: tuple[Mencion, ...] = ()


@dataclass(frozen=True)
class _Patron:
    palabras: tuple[str, ...]  # normalizadas: minúsculas y sin tildes
    codigo: str
    # Un apellido suelto solo cuenta si está escrito con mayúscula: "Rojas" es un apellido,
    # pero "manchas rojas" no habla de nadie.
    exige_mayuscula: bool = False


def normalizar(texto: str) -> str:
    """Minúsculas y sin tildes: "Tomás" y "tomas" quedan iguales."""
    descompuesto = unicodedata.normalize("NFD", texto.lower())
    return "".join(letra for letra in descompuesto if unicodedata.category(letra) != "Mn")


def seudonimizar(texto: str, residentes: list[Residente]) -> TextoSeudonimizado:
    texto = RUT.sub("[RUT]", texto)
    texto = CORREO.sub("[EMAIL]", texto)
    texto = TELEFONO.sub("[TEL]", texto)

    patrones = _patrones(residentes)
    largo_maximo = max((len(patron.palabras) for patron in patrones), default=0)
    palabras = list(PALABRA.finditer(texto))
    encontradas: list[tuple[int, int, frozenset[str]]] = []  # (inicio, fin, códigos)
    i = 0
    while i < len(palabras):
        # Se prueba primero la coincidencia más larga: "Tomás Díaz" gana sobre "Tomás".
        for largo in range(min(largo_maximo, len(palabras) - i), 0, -1):
            tramo = palabras[i : i + largo]
            codigos = frozenset(
                patron.codigo
                for patron in patrones
                if len(patron.palabras) == largo and _coincide(tramo, patron)
            )
            if codigos:
                encontradas.append((tramo[0].start(), tramo[-1].end(), codigos))
                i += largo
                break
        else:
            i += 1

    # Se reemplaza de atrás hacia adelante, para que las posiciones anteriores sigan valiendo.
    for inicio, fin, codigos in reversed(encontradas):
        texto = f"{texto[:inicio]}[{'|'.join(sorted(codigos))}]{texto[fin:]}"
    return TextoSeudonimizado(texto, tuple(Mencion(codigos) for _, _, codigos in encontradas))


def _patrones(residentes: list[Residente]) -> list[_Patron]:
    """Formas en que se puede nombrar a cada residente."""
    patrones = []
    for residente in residentes:
        nombres = _palabras(residente.nombres)
        apellidos = _palabras(residente.apellidos)
        patrones += [
            _Patron((*nombres, *apellidos), residente.codigo),  # nombre completo
            _Patron((nombres[0], apellidos[0]), residente.codigo),  # primer nombre y apellido
            _Patron((nombres[0],), residente.codigo),  # nombre solo
        ]
        patrones += [
            _Patron((apellido,), residente.codigo, exige_mayuscula=True)
            for apellido in apellidos
            if apellido not in PARTICULAS
        ]
        if residente.apodo:
            patrones.append(_Patron(tuple(_palabras(residente.apodo)), residente.codigo))
    return patrones


def _palabras(texto: str) -> list[str]:
    return [normalizar(palabra) for palabra in PALABRA.findall(texto)]


def _coincide(tramo: list[re.Match], patron: _Patron) -> bool:
    con_mayuscula = tramo[0].group()[0].isupper()
    if patron.exige_mayuscula and not con_mayuscula:
        return False
    if len(patron.palabras) > 1:
        # Nombre completo: se tolera un error en cada palabra de 4 letras o más ("Emila Soto").
        return all(
            _parecidas(normalizar(palabra.group()), esperada, len(esperada) >= 4)
            for palabra, esperada in zip(tramo, patron.palabras, strict=True)
        )
    # Palabra suelta: solo se tolera un error si está con mayúscula y el nombre es largo, porque
    # las palabras cortas se confunden con otras ("Tomás" y "tomar", "Soto" y "solo").
    esperada = patron.palabras[0]
    tolerar = con_mayuscula and len(esperada) >= 6 and not patron.exige_mayuscula
    return _parecidas(normalizar(tramo[0].group()), esperada, tolerar)


def _parecidas(palabra: str, esperada: str, tolerar_un_error: bool) -> bool:
    if palabra == esperada:
        return True
    # Se exige la misma primera letra, para no confundir palabras distintas.
    return tolerar_un_error and palabra[:1] == esperada[:1] and _a_lo_mas_un_error(palabra, esperada)


def _a_lo_mas_un_error(a: str, b: str) -> bool:
    """True si a y b difieren en a lo más una letra agregada, quitada o cambiada (distancia de
    edición o de Levenshtein menor o igual a 1)."""
    if abs(len(a) - len(b)) > 1:
        return False
    anterior = list(range(len(b) + 1))
    for i, letra_a in enumerate(a, start=1):
        actual = [i]
        for j, letra_b in enumerate(b, start=1):
            actual.append(
                min(anterior[j] + 1, actual[j - 1] + 1, anterior[j - 1] + (letra_a != letra_b))
            )
        anterior = actual
    return anterior[-1] <= 1
