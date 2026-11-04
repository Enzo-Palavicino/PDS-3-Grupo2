"""Modelos de la base de datos: cada clase es una tabla.

Los roles y estados se guardan como texto; sus valores posibles están en las clases StrEnum.
"""

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Date,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, FechaHoraUTC, ahora


class Rol(StrEnum):
    DIRECTORA = "directora"
    ENCARGADA_SALUD = "encargada_salud"
    PROFESIONAL = "profesional"


class Nivel(StrEnum):
    SALA_CUNA_MENOR = "sala_cuna_menor"
    SALA_CUNA_MAYOR = "sala_cuna_mayor"
    HETEROGENEO = "heterogeneo"


class EstadoMensaje(StrEnum):
    RECIBIDO = "recibido"
    DESCARGADO = "descargado"  # solo audios
    TRANSCRITO = "transcrito"
    EXTRAIDO = "extraido"
    LISTO = "listo"
    ERROR = "error"
    RECHAZADO = "rechazado"  # remitente no vinculado
    IGNORADO = "ignorado"  # tipo no soportado o chat no privado


class EstadoBorrador(StrEnum):
    PENDIENTE = "pendiente"
    DESCARTADO = "descartado"


class TipoActor(StrEnum):
    USUARIO = "usuario"  # usuario de la web
    PROFESIONAL = "profesional"  # profesional que escribe por un canal de mensajería
    SISTEMA = "sistema"


class Profesional(Base):
    __tablename__ = "profesionales"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120))
    especialidad: Mapped[str] = mapped_column(String(60))
    activo: Mapped[bool] = mapped_column(default=True)
    creado_en: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora)


class UsuarioWeb(Base):
    __tablename__ = "usuarios_web"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario: Mapped[str] = mapped_column(String(60), unique=True)  # nombre para iniciar sesión
    rol: Mapped[str] = mapped_column(String(20))  # valores de Rol
    # Solo los usuarios con rol "profesional" corresponden a un profesional.
    profesional_id: Mapped[int | None] = mapped_column(ForeignKey("profesionales.id"))
    hash_password: Mapped[str] = mapped_column(String(255))
    activo: Mapped[bool] = mapped_column(default=True)
    creado_en: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora)


class Residente(Base):
    """Niño o niña residente del Hogar. En desarrollo y pruebas, solo datos ficticios."""

    __tablename__ = "residentes"

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(10), unique=True)  # RES-01, RES-02, ...
    nombres: Mapped[str] = mapped_column(String(120))
    apellidos: Mapped[str] = mapped_column(String(120))
    apodo: Mapped[str | None] = mapped_column(String(60))
    fecha_nacimiento: Mapped[date] = mapped_column(Date)
    nivel: Mapped[str] = mapped_column(String(20))  # valores de Nivel


class VinculoCanal(Base):
    """Cuenta de mensajería (por ejemplo, un usuario de Telegram) autorizada a enviar registros
    en nombre de un profesional. Al revocarla se desactiva, pero queda como historial."""

    __tablename__ = "vinculos_canal"
    __table_args__ = (
        # Cada cuenta puede tener un solo vínculo activo; los revocados no cuentan.
        Index(
            "uq_vinculos_canal_cuenta_activa",
            "canal",
            "id_externo",
            unique=True,
            sqlite_where=text("activo"),
            postgresql_where=text("activo"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    profesional_id: Mapped[int] = mapped_column(ForeignKey("profesionales.id"))
    canal: Mapped[str] = mapped_column(String(20))
    id_externo: Mapped[str] = mapped_column(String(64))  # en Telegram, from.id
    activo: Mapped[bool] = mapped_column(default=True)
    creado_en: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora)
    revocado_en: Mapped[datetime | None] = mapped_column(FechaHoraUTC)


class CodigoVinculacion(Base):
    """Código de un solo uso para vincular una cuenta de mensajería. Vence a los 10 minutos."""

    __tablename__ = "codigos_vinculacion"

    codigo: Mapped[str] = mapped_column(String(64), primary_key=True)
    profesional_id: Mapped[int] = mapped_column(ForeignKey("profesionales.id"))
    # Usuario web que lo generó; vacío si se generó desde la consola.
    creado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios_web.id"))
    creado_en: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora)
    expira_en: Mapped[datetime] = mapped_column(FechaHoraUTC)
    usado_en: Mapped[datetime | None] = mapped_column(FechaHoraUTC)


class MensajeEntrante(Base):
    """Mensaje recibido por un canal. Esta tabla es también la cola de trabajo: el worker
    procesa los mensajes según su estado."""

    __tablename__ = "mensajes_entrantes"
    __table_args__ = (
        # Un reintento del canal trae la misma clave, y nunca se guarda dos veces.
        UniqueConstraint("canal", "id_externo"),
        Index("ix_mensajes_entrantes_cola", "estado", "proximo_intento_en"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    canal: Mapped[str] = mapped_column(String(20))
    # 255 y no 64: los ids de WhatsApp (wamid) miden más de 64 caracteres, unos 80 en Android.
    id_externo: Mapped[str] = mapped_column(String(255))
    remitente_externo: Mapped[str] = mapped_column(String(64))
    destino_respuesta: Mapped[str] = mapped_column(String(64))
    profesional_id: Mapped[int | None] = mapped_column(ForeignKey("profesionales.id"))
    tipo: Mapped[str] = mapped_column(String(20))  # texto, audio, comando o no_soportado
    texto: Mapped[str | None] = mapped_column(Text)
    audio_ref: Mapped[str | None] = mapped_column(String(255))
    audio_mime: Mapped[str | None] = mapped_column(String(60))
    audio_tamano_bytes: Mapped[int | None]
    audio_duracion_seg: Mapped[int | None]
    # Archivo temporal del audio descargado; se borra apenas se transcribe.
    ruta_audio: Mapped[str | None] = mapped_column(String(255))
    responde_a: Mapped[str | None] = mapped_column(String(255))  # id externo del mensaje respondido
    recibido_en: Mapped[datetime] = mapped_column(FechaHoraUTC)
    estado: Mapped[str] = mapped_column(String(20), default=EstadoMensaje.RECIBIDO)
    intentos: Mapped[int] = mapped_column(default=0)
    proximo_intento_en: Mapped[datetime | None] = mapped_column(FechaHoraUTC)
    # Solo el tipo de error, nunca el contenido del mensaje.
    ultimo_error: Mapped[str | None] = mapped_column(String(255))
    creado_en: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora)
    actualizado_en: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora, onupdate=ahora)


class Transcripcion(Base):
    __tablename__ = "transcripciones"

    id: Mapped[int] = mapped_column(primary_key=True)
    mensaje_id: Mapped[int] = mapped_column(ForeignKey("mensajes_entrantes.id"), unique=True)
    texto: Mapped[str] = mapped_column(Text)
    # Fragmentos con su tiempo de inicio y fin, si el proveedor los entrega.
    segmentos: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    proveedor: Mapped[str] = mapped_column(String(30))
    modelo: Mapped[str] = mapped_column(String(60))
    duracion_seg: Mapped[float | None]
    creado_en: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora)


class BorradorAtencion(Base):
    """Borrador de un registro de atención generado por la IA. Nunca es una atención
    registrada: un profesional tiene que revisarlo en la web."""

    __tablename__ = "borradores_atencion"

    id: Mapped[int] = mapped_column(primary_key=True)
    profesional_id: Mapped[int] = mapped_column(ForeignKey("profesionales.id"))
    residente_id: Mapped[int | None] = mapped_column(ForeignKey("residentes.id"))
    canal: Mapped[str] = mapped_column(String(20))
    # Campos del Registro de Atención extraídos por la IA, cada uno con su fragmento de origen.
    campos: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    faltantes: Mapped[list[str]] = mapped_column(JSON, default=list)
    ambiguedades: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    estado: Mapped[str] = mapped_column(String(20), default=EstadoBorrador.PENDIENTE)
    # Último mensaje del bot sobre este borrador: si el profesional le responde, se completa.
    mensaje_bot_id_externo: Mapped[str | None] = mapped_column(String(255))
    creado_en: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora)
    actualizado_en: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora, onupdate=ahora)


class BorradorMensaje(Base):
    """Mensajes que alimentan cada borrador: puede completarse con varios."""

    __tablename__ = "borrador_mensajes"

    borrador_id: Mapped[int] = mapped_column(
        ForeignKey("borradores_atencion.id"), primary_key=True
    )
    # unique: cada mensaje alimenta un solo borrador.
    mensaje_id: Mapped[int] = mapped_column(
        ForeignKey("mensajes_entrantes.id"), primary_key=True, unique=True
    )


class Extraccion(Base):
    """Cada ejecución del LLM sobre un borrador, como historial: qué entrada recibió (ya
    seudonimizada), qué devolvió y con qué modelo."""

    __tablename__ = "extracciones"

    id: Mapped[int] = mapped_column(primary_key=True)
    borrador_id: Mapped[int] = mapped_column(ForeignKey("borradores_atencion.id"))
    entrada_seudonimizada: Mapped[str] = mapped_column(Text)
    salida: Mapped[dict[str, Any]] = mapped_column(JSON)
    proveedor: Mapped[str] = mapped_column(String(30))
    modelo: Mapped[str] = mapped_column(String(60))
    creado_en: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora)


class EventoAuditoria(Base):
    """Registro de auditoría. Solo admite inserciones: la base de datos rechaza modificarlo o
    borrarlo (ver la migración inicial)."""

    __tablename__ = "eventos_auditoria"

    id: Mapped[int] = mapped_column(primary_key=True)
    ocurrido_en: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora)
    actor_tipo: Mapped[str] = mapped_column(String(20))  # valores de TipoActor
    actor_id: Mapped[str | None] = mapped_column(String(64))
    accion: Mapped[str] = mapped_column(String(60))
    entidad: Mapped[str | None] = mapped_column(String(40))
    entidad_id: Mapped[str | None] = mapped_column(String(64))
    # Datos adicionales del evento, nunca contenido clínico.
    detalle: Mapped[dict[str, Any] | None] = mapped_column(JSON)
