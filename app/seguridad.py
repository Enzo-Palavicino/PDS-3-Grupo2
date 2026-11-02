"""Contraseñas: se guarda solo un hash con sal, nunca la contraseña.

Se usa scrypt, de la biblioteca estándar de Python: una función diseñada para ser costosa de
calcular, lo que hace muy lento probar contraseñas por fuerza bruta.
"""

import base64
import hashlib
import hmac
import secrets

# Parámetros de scrypt: n (costo), r (tamaño de bloque) y p (paralelismo). Con estos valores,
# cada cálculo usa unos 16 MB de memoria.
_N, _R, _P = 2**14, 8, 1


def hashear_password(password: str) -> str:
    """Devuelve el texto que se guarda en la base de datos: "scrypt$n$r$p$sal$hash"."""
    # La sal es aleatoria: dos usuarios con la misma contraseña quedan con hashes distintos.
    sal = secrets.token_bytes(16)
    hash_ = hashlib.scrypt(password.encode(), salt=sal, n=_N, r=_R, p=_P)
    return f"scrypt${_N}${_R}${_P}${_codificar(sal)}${_codificar(hash_)}"


def verificar_password(password: str, guardado: str) -> bool:
    try:
        algoritmo, n, r, p, sal, hash_ = guardado.split("$")
    except ValueError:
        return False
    if algoritmo != "scrypt":
        return False
    esperado = _decodificar(hash_)
    calculado = hashlib.scrypt(
        password.encode(),
        salt=_decodificar(sal),
        n=int(n),
        r=int(r),
        p=int(p),
        dklen=len(esperado),
    )
    # compare_digest tarda lo mismo acierte o no: el tiempo no revela cuánto coincide.
    return hmac.compare_digest(calculado, esperado)


def _codificar(datos: bytes) -> str:
    return base64.b64encode(datos).decode()


def _decodificar(texto: str) -> bytes:
    return base64.b64decode(texto)
