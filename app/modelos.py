"""Modelos de la base de datos: cada clase es una tabla.

Los roles y estados se guardan como texto; sus valores posibles están en las clases StrEnum.
"""

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Date,
    Float,
    ForeignKey,
    Index,
    LargeBinary,
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
    CONFIRMADO = "confirmado"  # se convirtió en una atención firmada


class TipoActor(StrEnum):
    USUARIO = "usuario"  # usuario de la web
    PROFESIONAL = "profesional"  # profesional que escribe por un canal de mensajería
    SISTEMA = "sistema"


class EstadoResidente(StrEnum):
    ACTIVO = "activo"
    EGRESADO = "egresado"


class OrigenAtencion(StrEnum):
    WEB = "web"
    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"
    HISTORICO = "historico"  # digitalizada desde un documento antiguo


class EstadoAtencion(StrEnum):
    BORRADOR = "borrador"
    FIRMADA = "firmada"


class EstadoTratamiento(StrEnum):
    ACTIVO = "activo"
    TERMINADO = "terminado"
    SUSPENDIDO = "suspendido"


class EstadoControl(StrEnum):
    PENDIENTE = "pendiente"
    REALIZADO = "realizado"
    ANULADO = "anulado"  # lo reemplazó una corrección (adenda) de su atención


class TipoAntecedente(StrEnum):
    ALERGIA = "alergia"
    DIAGNOSTICO_CRONICO = "diagnostico_cronico"
    HOSPITALIZACION = "hospitalizacion"
    VACUNA = "vacuna"
    PERINATAL = "perinatal"
    OTRO = "otro"


class TipoAdjunto(StrEnum):
    RECETA = "receta"
    EXAMEN = "examen"
    INFORME = "informe"
    DOCUMENTO_HISTORICO = "documento_historico"
    OTRO = "otro"


class EstadoDocumento(StrEnum):
    """Estados de un documento histórico. En la web, "subido" y "leido" se muestran como
    "procesando"."""

    SUBIDO = "subido"
    LEIDO = "leido"  # ya se obtuvo su texto; falta extraer los campos
    POR_REVISAR = "por_revisar"
    INCORPORADO = "incorporado"
    DESCARTADO = "descartado"
    ERROR = "error"


class Profesional(Base):
    __tablename__ = "profesionales"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120))
    especialidad: Mapped[str] = mapped_column(String(60))
    # Registro profesional (por ejemplo, el de la Superintendencia de Salud). Va en el timbre.
    registro: Mapped[str | None] = mapped_column(Text)
    activo: Mapped[bool] = mapped_column(default=True)
    # Imagen del timbre que acompaña su firma; si no hay, se genera uno con su nombre.
    # deferred: la imagen no se lee de la base de datos hasta que se usa.
    timbre_imagen: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    timbre_mime: Mapped[str | None] = mapped_column(String(30))
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
    """Niño o niña residente del Hogar. En desarrollo y pruebas, solo datos ficticios.

    Egresar no borra nada: el residente queda como egresado, y un reingreso reactiva su ficha.
    """

    __tablename__ = "residentes"

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(10), unique=True)  # RES-01, RES-02, ...
    nombres: Mapped[str] = mapped_column(String(120))
    apellidos: Mapped[str] = mapped_column(String(120))
    apodo: Mapped[str | None] = mapped_column(String(60))
    fecha_nacimiento: Mapped[date] = mapped_column(Date)
    nivel: Mapped[str] = mapped_column(String(20))  # valores de Nivel
    fecha_ingreso: Mapped[date | None] = mapped_column(Date)
    # server_default: los residentes que ya existían al crear la columna quedan activos.
    estado: Mapped[str] = mapped_column(
        String(20), default=EstadoResidente.ACTIVO, server_default=EstadoResidente.ACTIVO.value
    )
    fecha_egreso: Mapped[date | None] = mapped_column(Date)


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


# Ficha clínica. El texto que escribe una persona o que extrae la IA va en columnas Text, sin
# largo máximo: SQLite no controla el largo de un String y PostgreSQL sí, así que un largo fijo
# solo falla en el servidor.


class Atencion(Base):
    """Registro de una atención de salud. Mientras es un borrador se puede editar; una vez
    firmada ya no cambia, y se corrige con una adenda (otra atención que la corrige)."""

    __tablename__ = "atenciones"
    __table_args__ = (Index("ix_atenciones_historial", "residente_id", "fecha_atencion"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    residente_id: Mapped[int] = mapped_column(ForeignKey("residentes.id"))
    # En una atención histórica el profesional puede no ser usuario del sistema: queda su nombre
    # tal como aparece en el documento.
    profesional_id: Mapped[int | None] = mapped_column(ForeignKey("profesionales.id"))
    profesional_texto: Mapped[str | None] = mapped_column(Text)
    origen: Mapped[str] = mapped_column(String(20))  # valores de OrigenAtencion
    estado: Mapped[str] = mapped_column(String(20), default=EstadoAtencion.BORRADOR)
    # Puede faltar en un documento histórico sin fecha; para las demás la exige el servicio.
    fecha_atencion: Mapped[date | None] = mapped_column(Date)
    # Campos del Registro de Atención, con el mismo formato que los borradores de la IA:
    # {"motivo": {"valor": ..., "fragmento": ...}, ...}. Los nombres están en app/nucleo/campos.py.
    campos: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Campos que alguien cambió a mano respecto de lo que extrajo la IA.
    campos_editados: Mapped[list[str]] = mapped_column(JSON, default=list)
    # El borrador de la IA del que viene, si llegó por mensajería. unique: un borrador se
    # convierte en a lo más una atención. (Si viene de un documento histórico, es el documento
    # el que apunta a la atención: al revés, las claves foráneas formarían un ciclo.)
    borrador_id: Mapped[int | None] = mapped_column(
        ForeignKey("borradores_atencion.id"), unique=True
    )
    # Adenda: la atención firmada que esta corrige, y por qué.
    corrige_a_id: Mapped[int | None] = mapped_column(ForeignKey("atenciones.id"))
    motivo_correccion: Mapped[str | None] = mapped_column(Text)
    creado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios_web.id"))
    # Firma: quién, cuándo y el hash SHA-256 de lo que se firmó.
    firmada_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios_web.id"))
    firmada_en: Mapped[datetime | None] = mapped_column(FechaHoraUTC)
    hash_firma: Mapped[str | None] = mapped_column(String(64))
    # Atención histórica: quién la verificó contra el documento original y cuándo. verificada_en
    # es la fecha de digitalización, distinta de fecha_atencion.
    verificada_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios_web.id"))
    verificada_en: Mapped[datetime | None] = mapped_column(FechaHoraUTC)
    # Cuándo se pasaron sus datos a la ficha (tratamientos, controles, antecedentes): así no se
    # incorporan dos veces.
    incorporada_en: Mapped[datetime | None] = mapped_column(FechaHoraUTC)
    creado_en: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora)
    actualizado_en: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora, onupdate=ahora)


class Tratamiento(Base):
    """Medicamento indicado en una atención. No se borra: termina en su fecha o lo suspende un
    profesional."""

    __tablename__ = "tratamientos"

    id: Mapped[int] = mapped_column(primary_key=True)
    residente_id: Mapped[int] = mapped_column(ForeignKey("residentes.id"))
    atencion_id: Mapped[int] = mapped_column(ForeignKey("atenciones.id"))
    medicamento: Mapped[str] = mapped_column(Text)
    dosis: Mapped[str | None] = mapped_column(Text)
    frecuencia_horario: Mapped[str | None] = mapped_column(Text)
    via: Mapped[str | None] = mapped_column(Text)
    duracion: Mapped[str | None] = mapped_column(Text)
    # Fecha de la atención en que se indicó. El inicio y el término, solo si se indicaron.
    indicado_en: Mapped[date | None] = mapped_column(Date)
    fecha_inicio: Mapped[date | None] = mapped_column(Date)
    fecha_termino: Mapped[date | None] = mapped_column(Date)
    estado: Mapped[str] = mapped_column(String(20), default=EstadoTratamiento.ACTIVO)
    suspendido_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios_web.id"))
    suspendido_en: Mapped[datetime | None] = mapped_column(FechaHoraUTC)
    motivo_suspension: Mapped[str | None] = mapped_column(Text)
    creado_en: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora)


class Control(Base):
    """Próximo control indicado en una atención: queda pendiente en la ficha."""

    __tablename__ = "controles"

    id: Mapped[int] = mapped_column(primary_key=True)
    residente_id: Mapped[int] = mapped_column(ForeignKey("residentes.id"))
    atencion_id: Mapped[int] = mapped_column(ForeignKey("atenciones.id"))
    fecha: Mapped[date | None] = mapped_column(Date)
    descripcion: Mapped[str | None] = mapped_column(Text)
    estado: Mapped[str] = mapped_column(String(20), default=EstadoControl.PENDIENTE)
    creado_en: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora)


class Antecedente(Base):
    """Antecedente de salud del residente: alergias, diagnósticos crónicos, hospitalizaciones,
    vacunas y antecedentes perinatales."""

    __tablename__ = "antecedentes"

    id: Mapped[int] = mapped_column(primary_key=True)
    residente_id: Mapped[int] = mapped_column(ForeignKey("residentes.id"))
    # La atención de la que salió; vacío si se registró directamente (por ejemplo, al ingreso).
    atencion_id: Mapped[int | None] = mapped_column(ForeignKey("atenciones.id"))
    tipo: Mapped[str] = mapped_column(String(30))  # valores de TipoAntecedente
    descripcion: Mapped[str] = mapped_column(Text)
    fecha: Mapped[date | None] = mapped_column(Date)
    registrado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios_web.id"))
    creado_en: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora)


class Medicion(Base):
    """Peso y talla del residente en una fecha."""

    __tablename__ = "mediciones"

    id: Mapped[int] = mapped_column(primary_key=True)
    residente_id: Mapped[int] = mapped_column(ForeignKey("residentes.id"))
    atencion_id: Mapped[int | None] = mapped_column(ForeignKey("atenciones.id"))
    fecha: Mapped[date | None] = mapped_column(Date)
    peso_kg: Mapped[float | None] = mapped_column(Float)
    talla_cm: Mapped[float | None] = mapped_column(Float)
    creado_en: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora)


class Adjunto(Base):
    """Archivo de la ficha (receta, examen, informe o foto de un documento histórico).

    Se guarda en la base de datos porque el disco del plan gratuito de Render no es persistente,
    y solo se descarga con sesión iniciada y permiso sobre la ficha, nunca desde una URL pública.
    """

    __tablename__ = "adjuntos"

    id: Mapped[int] = mapped_column(primary_key=True)
    residente_id: Mapped[int] = mapped_column(ForeignKey("residentes.id"), index=True)
    # La atención a la que pertenece; vacío si se adjuntó directamente a la ficha.
    atencion_id: Mapped[int | None] = mapped_column(ForeignKey("atenciones.id"))
    nombre_archivo: Mapped[str] = mapped_column(Text)
    tipo: Mapped[str] = mapped_column(String(30))  # valores de TipoAdjunto
    emisor: Mapped[str | None] = mapped_column(Text)  # por ejemplo, el CESFAM o el hospital
    fecha_emision: Mapped[date | None] = mapped_column(Date)
    mime: Mapped[str] = mapped_column(String(60))
    tamano_bytes: Mapped[int]
    sha256: Mapped[str] = mapped_column(String(64))
    # deferred: el archivo no se lee de la base de datos hasta que se descarga.
    contenido: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    subido_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios_web.id"))
    subido_en: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora)


class DocumentoHistorico(Base):
    """Foto de un registro antiguo del residente. La IA lee su texto y extrae los campos, y una
    persona los revisa contra la imagen antes de incorporarlos a la ficha.

    Como mensajes_entrantes, la tabla es también la cola de procesamiento del worker.
    """

    __tablename__ = "documentos_historicos"
    __table_args__ = (Index("ix_documentos_historicos_cola", "estado", "proximo_intento_en"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # El residente lo elige quien sube el documento; la IA nunca lo deduce.
    residente_id: Mapped[int] = mapped_column(ForeignKey("residentes.id"))
    adjunto_id: Mapped[int] = mapped_column(ForeignKey("adjuntos.id"), unique=True)
    tipo_documento: Mapped[str | None] = mapped_column(Text)
    # Fecha del documento, si se conoce. Con ella se resuelven las fechas relativas.
    fecha_original: Mapped[date | None] = mapped_column(Date)
    subido_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios_web.id"))
    subido_en: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora)
    estado: Mapped[str] = mapped_column(String(20), default=EstadoDocumento.SUBIDO)
    intentos: Mapped[int] = mapped_column(default=0)
    proximo_intento_en: Mapped[datetime | None] = mapped_column(FechaHoraUTC)
    # Solo el tipo de error, nunca el contenido del documento.
    ultimo_error: Mapped[str | None] = mapped_column(String(255))
    # Texto literal leído de la imagen, con lo ilegible marcado, y el modelo que lo leyó.
    texto_leido: Mapped[str | None] = mapped_column(Text)
    modelo_lectura: Mapped[str | None] = mapped_column(String(60))
    # Resultado de la extracción, con el mismo formato que los borradores, y su historial.
    campos: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    ambiguedades: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    entrada_seudonimizada: Mapped[str | None] = mapped_column(Text)
    salida: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    # Ids de atenciones de la ficha con la misma fecha y diagnóstico.
    posibles_duplicados: Mapped[list[int]] = mapped_column(JSON, default=list)
    motivo_descarte: Mapped[str | None] = mapped_column(Text)
    revisado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios_web.id"))
    revisado_en: Mapped[datetime | None] = mapped_column(FechaHoraUTC)
    # La atención que se creó al incorporarlo a la ficha. unique: un documento genera a lo más una.
    atencion_id: Mapped[int | None] = mapped_column(ForeignKey("atenciones.id"), unique=True)


class Asignacion(Base):
    """Profesional que atiende a un residente: puede ver su ficha y registrarle atenciones."""

    __tablename__ = "asignaciones"
    __table_args__ = (UniqueConstraint("residente_id", "profesional_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    residente_id: Mapped[int] = mapped_column(ForeignKey("residentes.id"))
    profesional_id: Mapped[int] = mapped_column(ForeignKey("profesionales.id"))
    asignado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios_web.id"))
    asignado_en: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora)
