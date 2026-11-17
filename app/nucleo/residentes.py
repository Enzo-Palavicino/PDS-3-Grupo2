import re
import unicodedata
from datetime import date

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db import ahora
from app.modelos import EstadoResidente, EventoAuditoria, Nivel, Residente, TipoActor
from app.nucleo.auditoria import Accion, registrar_evento
from app.nucleo.extraccion import ZONA_HORARIA


def normalizar(valor: str) -> str:
    return " ".join(
        "".join(
            c
            for c in unicodedata.normalize("NFD", valor.casefold())
            if unicodedata.category(c) != "Mn"
        ).split()
    )


def hoy() -> date:
    return ahora().astimezone(ZONA_HORARIA).date()


def datos_validos(valores: dict) -> dict:
    datos = {}
    for campo, maximo in (("nombres", 120), ("apellidos", 120), ("apodo", 60)):
        valor = " ".join(valores.get(campo, "").split())
        if len(valor) > maximo or (campo != "apodo" and not valor):
            raise ValueError(
                f"{campo.capitalize()}: obligatorio y hasta {maximo} caracteres."
                if campo != "apodo"
                else "El apodo admite hasta 60 caracteres."
            )
        datos[campo] = valor or None
    if valores.get("nivel") not in set(Nivel):
        raise ValueError("Selecciona un nivel válido.")
    datos["nivel"] = valores["nivel"]
    for campo in ("fecha_nacimiento", "fecha_ingreso"):
        try:
            datos[campo] = date.fromisoformat(valores.get(campo, ""))
        except ValueError:
            raise ValueError("Indica fechas de nacimiento e ingreso válidas.") from None
        if datos[campo] > hoy():
            raise ValueError("Las fechas no pueden ser futuras.")
    if datos["fecha_ingreso"] < datos["fecha_nacimiento"]:
        raise ValueError("El ingreso no puede ser anterior al nacimiento.")
    return datos


def duplicados(
    sesion: Session, datos: dict, excluir: int | None = None
) -> list[Residente]:
    nombre = normalizar(datos["nombres"] + " " + datos["apellidos"])
    return [
        r
        for r in sesion.scalars(
            select(Residente).where(
                Residente.fecha_nacimiento == datos["fecha_nacimiento"]
            )
        )
        if r.id != excluir and normalizar(r.nombres + " " + r.apellidos) == nombre
    ]


def guardar(
    sesion: Session, datos: dict, actor_id: int, residente: Residente | None = None
) -> Residente:
    nuevo = residente is None
    if nuevo:
        # SQLite serializa las escrituras con BEGIN IMMEDIATE. PostgreSQL necesita un
        # bloqueo transaccional común a todas las altas para asignar códigos sin colisiones.
        if sesion.get_bind().dialect.name == "postgresql":
            sesion.execute(text("SELECT pg_advisory_xact_lock(4201201)"))
        numeros = [
            int(c[4:])
            for c in sesion.scalars(select(Residente.codigo))
            if re.fullmatch(r"RES-\d+", c)
        ]
        codigo = f"RES-{max(numeros, default=0) + 1:02d}"
        if len(codigo) > 10:
            raise ValueError("Se alcanzó el límite de códigos de residentes.")
        residente = Residente(codigo=codigo)
        sesion.add(residente)
    if residente.fecha_egreso and datos["fecha_ingreso"] > residente.fecha_egreso:
        raise ValueError("El ingreso no puede ser posterior al egreso registrado.")
    for campo, valor in datos.items():
        setattr(residente, campo, valor)
    sesion.flush()
    registrar_evento(
        sesion,
        Accion.RESIDENTE_CREADO if nuevo else Accion.RESIDENTE_EDITADO,
        TipoActor.USUARIO,
        actor_id=actor_id,
        entidad="residente",
        entidad_id=residente.id,
    )
    return residente


def cambiar_estado(
    sesion: Session, residente: Residente, accion: str, fecha: str, actor_id: int
):
    try:
        momento = date.fromisoformat(fecha)
    except ValueError:
        raise ValueError("Indica una fecha válida.") from None
    if momento > hoy() or momento < (
        residente.fecha_ingreso or residente.fecha_nacimiento
    ):
        raise ValueError("La fecha debe estar entre el ingreso y hoy.")
    anterior = residente.fecha_egreso
    if accion == "egresar":
        if residente.estado != EstadoResidente.ACTIVO:
            raise ValueError("El residente ya está egresado.")
        ultimo_reingreso = next(
            (
                e.detalle["fecha"]
                for e in sesion.scalars(
                    select(EventoAuditoria)
                    .where(
                        EventoAuditoria.entidad == "residente",
                        EventoAuditoria.entidad_id == str(residente.id),
                        EventoAuditoria.accion == Accion.RESIDENTE_EDITADO,
                    )
                    .order_by(EventoAuditoria.id.desc())
                )
                if e.detalle and e.detalle.get("operacion") == "reingresar"
            ),
            None,
        )
        if ultimo_reingreso and momento < date.fromisoformat(ultimo_reingreso):
            raise ValueError("El egreso no puede ser anterior al último reingreso.")
        residente.estado = EstadoResidente.EGRESADO
        residente.fecha_egreso = momento
        evento = Accion.RESIDENTE_EGRESADO
    elif accion == "reingresar":
        if residente.estado != EstadoResidente.EGRESADO:
            raise ValueError("El residente ya está activo.")
        if anterior and momento < anterior:
            raise ValueError("El reingreso no puede ser anterior al último egreso.")
        residente.estado = EstadoResidente.ACTIVO
        residente.fecha_egreso = None
        # Conserva el primer ingreso; registra cada reingreso y el egreso anterior en auditoría.
        evento = Accion.RESIDENTE_EDITADO
    else:
        raise ValueError("Acción no válida.")
    registrar_evento(
        sesion,
        evento,
        TipoActor.USUARIO,
        actor_id=actor_id,
        entidad="residente",
        entidad_id=residente.id,
        detalle={
            "operacion": accion,
            "fecha": momento.isoformat(),
            "egreso_anterior": anterior.isoformat() if anterior else None,
        },
    )
