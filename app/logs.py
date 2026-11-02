"""Configuración de los logs.

Regla del proyecto: los logs registran solo ids y estados, nunca el contenido de los mensajes,
las transcripciones ni datos clínicos.
"""

import logging


def configurar_logs(nivel: str) -> None:
    logging.basicConfig(level=nivel, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # Los clientes HTTP (httpx2 y httpx, con sus capas httpcore) registran cada URL que consultan,
    # y las URL de la Bot API de Telegram llevan el token del bot. Por eso de estas librerías
    # solo se registran advertencias y errores.
    for nombre in ("httpx2", "httpcore2", "httpx", "httpcore"):
        logging.getLogger(nombre).setLevel(logging.WARNING)


def trazas_habilitadas() -> bool:
    """Indica si se puede registrar la traza completa de un error (exc_info).

    Una traza puede incluir datos de los mensajes, así que solo se registra con LOG_LEVEL=DEBUG,
    que es para desarrollo con datos ficticios.
    """
    return logging.getLogger().isEnabledFor(logging.DEBUG)
