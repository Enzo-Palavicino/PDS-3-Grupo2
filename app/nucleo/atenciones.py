"""Atenciones: todo lo que las crea, las edita, las firma y las pasa a la ficha.

Una atención en borrador se puede editar. Firmada, ya no cambia: se corrige con una adenda. Las
funciones validan los datos y la inmutabilidad, pero no los permisos del usuario: eso lo revisa
la web con app/nucleo/permisos.py antes de llamarlas. Ninguna hace commit: lo hace quien llama.

Contrato del esqueleto (E1-01): las firmas no cambian sin avisar a quien las usa.
"""

import copy
import hashlib
import hmac
import json
import re
from datetime import UTC, date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import ahora
from app.modelos import (
    Atencion,
    BorradorAtencion,
    DocumentoHistorico,
    EstadoAtencion,
    EstadoBorrador,
    OrigenAtencion,
    Profesional,
    Residente,
    Rol,
    TipoActor,
    UsuarioWeb,
)
from app.nucleo import incorporacion
from app.nucleo.auditoria import Accion, registrar_evento
from app.nucleo.campos import CAMPOS_ATENCION, CAMPOS_LISTA
from app.seguridad import verificar_password

FECHA = re.compile(r"\d{4}-\d{2}-\d{2}")
# Campos que completa el servicio aunque no vengan: el residente (con su código) y la
# especialidad (la del profesional).
COMPLETADOS_POR_EL_SISTEMA = {"residente", "especialidad"}

# Datos sin los que una atención no se puede guardar. Las claves son las mismas que usa
# calcular_faltantes en los borradores de la IA.
OBLIGATORIOS = {
    "residente": "residente",
    "fecha_atencion": "fecha de atención",
    "diagnostico_o_motivo": "diagnóstico o motivo",
}


class ErrorDeAtencion(Exception):
    """Error de una operación sobre una atención. Su mensaje se puede mostrar en la web."""


class AtencionFirmada(ErrorDeAtencion):
    """Se intentó modificar una atención firmada. En la web corresponde a un 409."""


class DatosIncompletos(ErrorDeAtencion):
    """Faltan datos obligatorios: el residente, la fecha y el motivo o el diagnóstico.

    faltantes tiene las claves de OBLIGATORIOS, para marcar los campos en el formulario.
    """

    def __init__(self, faltantes: list[str]):
        descripciones = ", ".join(OBLIGATORIOS[clave] for clave in faltantes)
        super().__init__(f"Faltan datos obligatorios: {descripciones}.")
        self.faltantes = faltantes


class PasswordIncorrecta(ErrorDeAtencion):
    """La contraseña que se reingresó para firmar no es la del usuario."""


def faltantes_obligatorios(
    residente_id: int | None,
    campos: dict[str, Any],
    fecha_atencion: date | None,
    origen: OrigenAtencion,
) -> list[str]:
    """Las claves de OBLIGATORIOS que faltan, para avisarlas en el formulario antes de guardar.
    En una atención histórica la fecha puede faltar: el documento puede no tenerla."""
    faltantes = []
    if residente_id is None:
        faltantes.append("residente")
    if fecha_atencion is None and origen != OrigenAtencion.HISTORICO:
        faltantes.append("fecha_atencion")
    diagnosticos = [d for d in campos.get("diagnosticos") or [] if _tiene_valor(d)]
    if not _tiene_valor(campos.get("motivo")) and not diagnosticos:
        faltantes.append("diagnostico_o_motivo")
    return faltantes


def atencion_del_borrador(sesion: Session, borrador_id: int) -> Atencion | None:
    """La atención que ya se creó desde un borrador de la IA, si existe: "Revisar y completar"
    debe abrirla en vez de crear otra."""
    return sesion.scalar(select(Atencion).where(Atencion.borrador_id == borrador_id))


def crear_atencion(
    sesion: Session,
    residente_id: int,
    autor: UsuarioWeb,
    campos: dict[str, Any],
    origen: OrigenAtencion,
    fecha_atencion: date | None = None,
    borrador_id: int | None = None,
    documento_id: int | None = None,
    corrige_a_id: int | None = None,
    motivo_correccion: str | None = None,
) -> Atencion:
    """Crea una atención en borrador y la audita (atencion_creada).

    - autor: el usuario web que la registra. Si es un profesional, queda como profesional de la
      atención; si viene de un borrador de la IA, el profesional es el del borrador.
    - campos: con el formato de app/nucleo/campos.py. La fecha se puede pasar en fecha_atencion
      o en campos["fecha_atencion"]; las dos quedan iguales.
    - borrador_id: el borrador de la IA del que viene. Tiene que estar pendiente y sin atención.
    - documento_id: el documento histórico del que viene; el documento queda apuntando a la
      atención.
    - corrige_a_id y motivo_correccion: si es una adenda, la atención firmada que corrige y por
      qué. Para crear una adenda se usa app/nucleo/adendas.crear_adenda, que valida la original.

    Lanza DatosIncompletos si faltan el residente, la fecha o el motivo o diagnóstico (en una
    atención histórica la fecha puede faltar), y ErrorDeAtencion si algún dato no es válido.
    """
    origen = OrigenAtencion(origen)
    residente = sesion.get(Residente, residente_id)
    if residente is None:
        raise ErrorDeAtencion("El residente no existe.")
    borrador = _borrador_disponible(sesion, borrador_id, origen) if borrador_id else None
    documento = (
        _documento_disponible(sesion, documento_id, residente_id) if documento_id else None
    )

    if borrador is not None:
        profesional_id = borrador.profesional_id
    elif autor.rol == Rol.PROFESIONAL:
        profesional_id = autor.profesional_id
    else:
        profesional_id = None
    campos, fecha = _preparar(sesion, campos, fecha_atencion, residente, profesional_id, origen)
    if borrador is not None:
        original = borrador.campos
    elif documento is not None:
        original = documento.campos
    elif corrige_a_id is not None:
        original = sesion.get(Atencion, corrige_a_id).campos
    else:
        original = None

    atencion = Atencion(
        residente_id=residente_id,
        profesional_id=profesional_id,
        origen=origen,
        estado=EstadoAtencion.BORRADOR,
        fecha_atencion=fecha,
        campos=campos,
        campos_editados=_campos_distintos(original, campos) if original is not None else [],
        borrador_id=borrador_id,
        corrige_a_id=corrige_a_id,
        motivo_correccion=motivo_correccion,
        creado_por=autor.id,
    )
    sesion.add(atencion)
    sesion.flush()  # asigna atencion.id
    if documento is not None:
        documento.atencion_id = atencion.id
    registrar_evento(
        sesion,
        Accion.ATENCION_CREADA,
        actor_tipo=TipoActor.USUARIO,
        actor_id=autor.id,
        entidad="atencion",
        entidad_id=atencion.id,
        detalle={"origen": origen, "residente_id": residente_id}
        | ({"corrige_a": corrige_a_id} if corrige_a_id is not None else {}),
    )
    return atencion


def actualizar_atencion(
    sesion: Session,
    atencion: Atencion,
    campos: dict[str, Any],
    usuario: UsuarioWeb,
    fecha_atencion: date | None = None,
) -> Atencion:
    """Reemplaza los campos de una atención en borrador, anota cuáles difieren de lo que extrajo
    la IA y audita la edición (atencion_editada) con los nombres de los campos que cambiaron,
    nunca con sus valores. Si nada cambió, no hace nada.

    Lanza AtencionFirmada si ya está firmada, DatosIncompletos si faltan datos obligatorios y
    ErrorDeAtencion si algún dato no es válido.
    """
    if atencion.estado == EstadoAtencion.FIRMADA:
        raise AtencionFirmada("La atención ya está firmada: se corrige con una adenda.")
    residente = sesion.get(Residente, atencion.residente_id)
    origen = OrigenAtencion(atencion.origen)
    campos, fecha = _preparar(
        sesion, campos, fecha_atencion, residente, atencion.profesional_id, origen
    )
    cambiados = _campos_distintos(atencion.campos, campos)
    if not cambiados:
        return atencion

    original = _original_de(sesion, atencion)
    atencion.campos = campos
    atencion.fecha_atencion = fecha
    atencion.campos_editados = _campos_distintos(original, campos) if original is not None else []
    registrar_evento(
        sesion,
        Accion.ATENCION_EDITADA,
        actor_tipo=TipoActor.USUARIO,
        actor_id=usuario.id,
        entidad="atencion",
        entidad_id=atencion.id,
        detalle={"campos": cambiados},
    )
    return atencion


def firmar_atencion(
    sesion: Session, atencion: Atencion, usuario: UsuarioWeb, password: str
) -> Atencion:
    """Firma la atención con la contraseña del profesional autor, todo en una transacción:

    - guarda quién firmó, cuándo y el hash SHA-256 de lo firmado;
    - pasa el borrador de IA de origen, si hay, al estado confirmado;
    - llama a incorporar_a_ficha;
    - audita atencion_firmada.

    Lanza PasswordIncorrecta, AtencionFirmada o DatosIncompletos, y ErrorDeAtencion si quien
    firma no es el profesional autor. Si algo falla, no queda nada firmado.
    """
    if atencion.estado == EstadoAtencion.FIRMADA:
        raise AtencionFirmada("La atención ya está firmada.")
    # La web ya lo revisa con permisos.puede_firmar; esta es una segunda barrera.
    es_autor = (
        usuario.rol == Rol.PROFESIONAL
        and usuario.profesional_id is not None
        and usuario.profesional_id == atencion.profesional_id
    )
    if not es_autor:
        raise ErrorDeAtencion("Solo el profesional que hizo la atención puede firmarla.")
    if not verificar_password(password, usuario.hash_password):
        raise PasswordIncorrecta("La contraseña no es correcta.")
    faltantes = faltantes_obligatorios(
        atencion.residente_id,
        atencion.campos,
        atencion.fecha_atencion,
        OrigenAtencion(atencion.origen),
    )
    if faltantes:
        raise DatosIncompletos(faltantes)

    # SAVEPOINT: si algo falla de aquí en adelante (por ejemplo, al incorporar los datos a la
    # ficha), se deshace todo este bloque y la atención sigue en borrador.
    with sesion.begin_nested():
        atencion.estado = EstadoAtencion.FIRMADA
        atencion.firmada_por = usuario.id
        atencion.firmada_en = ahora()
        atencion.hash_firma = calcular_hash(atencion)
        if atencion.borrador_id is not None:
            sesion.get(BorradorAtencion, atencion.borrador_id).estado = EstadoBorrador.CONFIRMADO
        incorporar_a_ficha(sesion, atencion)
        registrar_evento(
            sesion,
            Accion.ATENCION_FIRMADA,
            actor_tipo=TipoActor.USUARIO,
            actor_id=usuario.id,
            entidad="atencion",
            entidad_id=atencion.id,
            detalle={"hash": atencion.hash_firma},
        )
    return atencion


def verificar_integridad(atencion: Atencion) -> bool:
    """Recalcula el hash de una atención firmada y lo compara con el guardado al firmar. False si
    el contenido cambió después de la firma o si la atención no está firmada."""
    if atencion.estado != EstadoAtencion.FIRMADA or not atencion.hash_firma:
        return False
    return hmac.compare_digest(calcular_hash(atencion), atencion.hash_firma)


def calcular_hash(atencion: Atencion) -> str:
    """SHA-256 de lo que se firma: quién y cuándo, el residente y todo el contenido de la
    atención. Se calcula sobre un JSON con las claves ordenadas, así que el orden en que se
    guardaron los campos no cambia el resultado."""
    firmado = {
        "residente_id": atencion.residente_id,
        "profesional_id": atencion.profesional_id,
        "origen": str(atencion.origen),
        "fecha_atencion": atencion.fecha_atencion.isoformat() if atencion.fecha_atencion else None,
        "campos": atencion.campos,
        "corrige_a_id": atencion.corrige_a_id,
        "firmada_por": atencion.firmada_por,
        "firmada_en": atencion.firmada_en.astimezone(UTC).isoformat(),
    }
    texto = json.dumps(firmado, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(texto.encode()).hexdigest()


def incorporar_a_ficha(sesion: Session, atencion: Atencion) -> None:
    """Pasa los datos de una atención a la ficha del residente: tratamientos, próximo control,
    antecedentes (alergias, vacunas, hospitalizaciones) y mediciones (peso y talla).

    La llaman firmar_atencion y la incorporación de un documento histórico (E4-04). Si la
    atención ya se incorporó, no hace nada. No hace commit. Detalle en app/nucleo/incorporacion.py.
    """
    incorporacion.incorporar(sesion, atencion)


def _preparar(
    sesion: Session,
    campos: dict[str, Any],
    fecha_atencion: date | None,
    residente: Residente,
    profesional_id: int | None,
    origen: OrigenAtencion,
) -> tuple[dict[str, Any], date | None]:
    """Valida los campos y los completa: la fecha queda igual en la columna y en los campos, el
    residente con su código y la especialidad con la del profesional. No modifica los campos que
    recibe: devuelve una copia."""
    if not isinstance(campos, dict):
        raise ErrorDeAtencion("Los campos de la atención no son válidos.")
    desconocidos = sorted(set(campos) - set(CAMPOS_ATENCION))
    if desconocidos:
        raise ErrorDeAtencion(f"Campo desconocido: {', '.join(desconocidos)}.")
    for nombre, dato in campos.items():
        forma = list if nombre in CAMPOS_LISTA else dict
        if dato is not None and not isinstance(dato, forma):
            raise ErrorDeAtencion(f"El campo {nombre} no tiene la forma esperada.")
    campos = copy.deepcopy(campos)

    fecha = fecha_atencion or _fecha_de_los_campos(campos)
    if fecha is not None:
        campos["fecha_atencion"] = _con_valor(campos.get("fecha_atencion"), fecha.isoformat())
    campos["residente"] = _con_valor(campos.get("residente"), residente.codigo)
    if not _tiene_valor(campos.get("especialidad")) and profesional_id is not None:
        especialidad = sesion.get(Profesional, profesional_id).especialidad
        campos["especialidad"] = {"valor": especialidad, "fragmento": None}

    faltantes = faltantes_obligatorios(residente.id, campos, fecha, origen)
    if faltantes:
        raise DatosIncompletos(faltantes)
    return campos, fecha


def _con_valor(anterior: dict[str, Any] | None, valor: str) -> dict[str, Any]:
    """El dato con ese valor. Conserva el fragmento de origen solo si el valor no cambió."""
    anterior = anterior or {}
    fragmento = anterior.get("fragmento") if anterior.get("valor") == valor else None
    return {"valor": valor, "fragmento": fragmento}


def _fecha_de_los_campos(campos: dict[str, Any]) -> date | None:
    valor = (campos.get("fecha_atencion") or {}).get("valor")
    if not valor:
        return None
    if not isinstance(valor, str) or not FECHA.fullmatch(valor):
        raise ErrorDeAtencion("La fecha de atención debe tener el formato AAAA-MM-DD.")
    try:
        return date.fromisoformat(valor)
    except ValueError:
        raise ErrorDeAtencion("La fecha de atención no existe.") from None


def _borrador_disponible(
    sesion: Session, borrador_id: int, origen: OrigenAtencion
) -> BorradorAtencion:
    borrador = sesion.get(BorradorAtencion, borrador_id)
    if borrador is None:
        raise ErrorDeAtencion("El borrador no existe.")
    if borrador.estado != EstadoBorrador.PENDIENTE:
        raise ErrorDeAtencion("El borrador ya no está pendiente.")
    if borrador.canal != origen:
        raise ErrorDeAtencion("El origen de la atención no coincide con el canal del borrador.")
    if atencion_del_borrador(sesion, borrador_id) is not None:
        raise ErrorDeAtencion("Ya existe una atención para este borrador.")
    return borrador


def _documento_disponible(
    sesion: Session, documento_id: int, residente_id: int
) -> DocumentoHistorico:
    documento = sesion.get(DocumentoHistorico, documento_id)
    if documento is None:
        raise ErrorDeAtencion("El documento no existe.")
    if documento.residente_id != residente_id:
        raise ErrorDeAtencion("El documento es de otro residente.")
    if documento.atencion_id is not None:
        raise ErrorDeAtencion("El documento ya se incorporó en otra atención.")
    return documento


def _original_de(sesion: Session, atencion: Atencion) -> dict[str, Any] | None:
    """Contra qué se miden los cambios a mano: lo que extrajo la IA, si vino de un borrador o de
    un documento, o la atención que corrige, si es una adenda."""
    if atencion.borrador_id is not None:
        return sesion.get(BorradorAtencion, atencion.borrador_id).campos
    if atencion.corrige_a_id is not None:
        return sesion.get(Atencion, atencion.corrige_a_id).campos
    documento = sesion.scalar(
        select(DocumentoHistorico).where(DocumentoHistorico.atencion_id == atencion.id)
    )
    return documento.campos if documento else None


def _campos_distintos(antes: dict[str, Any] | None, despues: dict[str, Any]) -> list[str]:
    """Nombres de los campos cuyo contenido cambió. El fragmento de origen no cuenta: el
    formulario puede no conservarlo. Tampoco cuentan el residente ni la especialidad cuando antes
    no estaban: los completa el sistema, no una persona."""
    antes = antes or {}
    return sorted(
        nombre
        for nombre in set(antes) | set(despues)
        if _contenido(antes.get(nombre)) != _contenido(despues.get(nombre))
        and not (nombre in COMPLETADOS_POR_EL_SISTEMA and _contenido(antes.get(nombre)) is None)
    )


def _contenido(dato: Any) -> Any:
    """El dato sin sus fragmentos ni valores vacíos, para comparar dos versiones."""
    if isinstance(dato, list):
        return [c for c in (_contenido(d) for d in dato) if c is not None] or None
    if isinstance(dato, dict):
        limpio = {k: v for k, v in dato.items() if k != "fragmento" and v not in (None, "", [])}
        return limpio or None
    return None if dato in ("", []) else dato


def _tiene_valor(dato: Any) -> bool:
    return isinstance(dato, dict) and bool(dato.get("valor"))
