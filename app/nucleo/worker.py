"""Worker: procesa en segundo plano los mensajes que guardó la ingesta.

La tabla mensajes_entrantes funciona como cola. El worker toma los mensajes pendientes en orden
de llegada y los procesa de a uno, en un hilo aparte, para que recibir mensajes nunca tenga que
esperar a la transcripción ni a la IA. Si un mensaje falla, guarda el tipo de error y lo
reintenta más tarde, con esperas cada vez más largas. Si falla 3 veces, lo deja en "error" y le
avisa al profesional.
"""

import logging
import threading
from datetime import timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, sessionmaker

from app.db import ahora
from app.logs import trazas_habilitadas
from app.modelos import EstadoMensaje, MensajeEntrante
from app.nucleo import textos
from app.nucleo.procesamiento import ESTADOS_PENDIENTES, Contexto, procesar

logger = logging.getLogger(__name__)

MAXIMO_INTENTOS = 3
# Cuánto esperar antes de reintentar: tras el primer fallo, 10 s; tras el segundo, 60 s.
ESPERAS_ENTRE_INTENTOS = (timedelta(seconds=10), timedelta(seconds=60))


class Worker:
    def __init__(
        self,
        fabrica_de_sesiones: sessionmaker[Session],
        contexto: Contexto,
        intervalo_seg: float = 5,
    ):
        self._fabrica = fabrica_de_sesiones
        self._contexto = contexto
        # Cada cuánto revisar la cola aunque nadie lo despierte, por ejemplo para los reintentos.
        self._intervalo_seg = intervalo_seg
        self._hay_trabajo = threading.Event()
        self._detenido = threading.Event()

    def iniciar(self) -> None:
        # daemon: el hilo no impide que el proceso termine.
        threading.Thread(target=self.ejecutar, name="worker-mensajes", daemon=True).start()

    def despertar(self) -> None:
        """Avisa que llegó un mensaje, para procesarlo sin esperar a la próxima revisión."""
        self._hay_trabajo.set()

    def detener(self) -> None:
        self._detenido.set()
        self._hay_trabajo.set()

    def ejecutar(self) -> None:
        """Procesa la cola hasta que se llame a detener()."""
        self._borrar_audios_de_intentos_interrumpidos()
        while not self._detenido.is_set():
            self._hay_trabajo.clear()
            try:
                pendientes = self.procesar_pendientes()
            except Exception as error:
                # Por ejemplo, si la base de datos no responde: se intenta en la próxima revisión.
                logger.error(
                    "Error al revisar la cola (%s)",
                    type(error).__name__,
                    exc_info=trazas_habilitadas(),
                )
                pendientes = 0
            if pendientes == 0:
                self._hay_trabajo.wait(self._intervalo_seg)

    def procesar_pendientes(self) -> int:
        """Procesa una vez cada mensaje pendiente y devuelve cuántos había."""
        ids = self._ids_pendientes()
        for mensaje_id in ids:
            if self._detenido.is_set():
                break
            self._procesar(mensaje_id)
        return len(ids)

    def _ids_pendientes(self) -> list[int]:
        consulta = (
            select(MensajeEntrante.id)
            .where(
                or_(
                    MensajeEntrante.estado.in_(ESTADOS_PENDIENTES),
                    and_(
                        MensajeEntrante.estado == EstadoMensaje.ERROR,
                        MensajeEntrante.intentos < MAXIMO_INTENTOS,
                    ),
                ),
                or_(
                    MensajeEntrante.proximo_intento_en.is_(None),
                    MensajeEntrante.proximo_intento_en <= ahora(),
                ),
            )
            .order_by(MensajeEntrante.id)
        )
        with self._fabrica() as sesion:
            return list(sesion.scalars(consulta))

    def _procesar(self, mensaje_id: int) -> None:
        try:
            with self._fabrica.begin() as sesion:
                procesar(sesion, sesion.get(MensajeEntrante, mensaje_id), self._contexto)
        except Exception as error:
            # Solo el tipo de error: su mensaje podría incluir datos del registro.
            logger.warning(
                "Falló el procesamiento del mensaje %s (%s)",
                mensaje_id,
                type(error).__name__,
                exc_info=trazas_habilitadas(),
            )
            self._registrar_fallo(mensaje_id, type(error).__name__)
        else:
            logger.info("Mensaje %s procesado", mensaje_id)

    def _registrar_fallo(self, mensaje_id: int, tipo_de_error: str) -> None:
        with self._fabrica.begin() as sesion:
            mensaje = sesion.get(MensajeEntrante, mensaje_id)
            mensaje.estado = EstadoMensaje.ERROR
            mensaje.intentos += 1
            mensaje.ultimo_error = tipo_de_error
            if mensaje.intentos < MAXIMO_INTENTOS:
                mensaje.proximo_intento_en = ahora() + ESPERAS_ENTRE_INTENTOS[mensaje.intentos - 1]
                return
            mensaje.proximo_intento_en = None
            canal, destino, id_externo = mensaje.canal, mensaje.destino_respuesta, mensaje.id_externo
        logger.error("El mensaje %s quedó en error tras %s intentos", mensaje_id, MAXIMO_INTENTOS)
        self._avisar_error(canal, destino, id_externo)

    def _avisar_error(self, canal: str, destino: str, id_externo: str) -> None:
        try:
            self._contexto.adaptadores[canal].enviar_texto(destino, textos.ERROR, id_externo)
        except Exception as error:
            logger.warning(
                "No se pudo avisar el error del mensaje %s (%s)",
                id_externo,
                type(error).__name__,
                exc_info=trazas_habilitadas(),
            )

    def _borrar_audios_de_intentos_interrumpidos(self) -> None:
        """Un audio solo existe en disco mientras dura su intento. Si al arrancar queda alguno,
        es de un intento que se interrumpió (por ejemplo, al cerrar la aplicación) y se borra."""
        carpeta = self._contexto.carpeta_audios
        if not carpeta.is_dir():
            return
        for archivo in carpeta.iterdir():
            if archivo.is_file():
                archivo.unlink(missing_ok=True)
