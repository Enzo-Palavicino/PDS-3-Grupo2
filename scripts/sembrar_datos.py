"""Carga los datos de demostración: residentes, profesionales y usuarios web.

Uso:  python -m scripts.sembrar_datos

Con SEED_DEMO=true carga además la ficha de la demo de la entrega 2: asignaciones, antecedentes,
mediciones y atenciones firmadas (con hash y timbre), que dejan tratamientos y controles en la
ficha. Emilia Soto (RES-02) queda sin atenciones: es la del audio en vivo.

Todos los datos son inventados. Se puede correr varias veces: lo que ya existe no se duplica,
y en lo que ya existe solo se completan los campos vacíos (por ejemplo, los que agregó una
migración), sin tocar lo que alguien editó.
La contraseña de los usuarios sale de SEED_PASSWORD (en .env), nunca del código.
"""

import sys
from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.config import obtener_config
from app.db import crear_fabrica_de_sesiones, crear_motor
from app.modelos import (
    Antecedente,
    Asignacion,
    Atencion,
    Medicion,
    Nivel,
    OrigenAtencion,
    Profesional,
    Residente,
    Rol,
    TipoAntecedente,
    UsuarioWeb,
)
from app.nucleo.atenciones import PasswordIncorrecta, crear_atencion, firmar_atencion
from app.seguridad import hashear_password

# Edades al 2 de noviembre de 2026. Los dos "Tomás" sirven para probar nombres ambiguos.
RESIDENTES = [
    # código, nombres, apellidos, apodo, fecha de nacimiento, nivel
    ("RES-01", "Tomás", "Rivas", "Tomi", date(2023, 7, 14), Nivel.HETEROGENEO),  # 3 años
    ("RES-02", "Emilia", "Soto", "Emi", date(2025, 12, 28), Nivel.SALA_CUNA_MENOR),  # 10 meses
    ("RES-03", "Martina", "Rojas", "Marti", date(2025, 2, 20), Nivel.SALA_CUNA_MAYOR),  # 20 meses
    ("RES-04", "Tomás", "Díaz", None, date(2022, 9, 3), Nivel.HETEROGENEO),  # 4 años
]

# Fecha en que cada residente ingresó al Hogar.
INGRESOS = {
    "RES-01": date(2024, 3, 11),
    "RES-02": date(2026, 1, 20),
    "RES-03": date(2025, 6, 2),
    "RES-04": date(2023, 5, 15),
}

PROFESIONALES = [
    # nombre, especialidad, usuario web, registro profesional (inventado)
    ("Carolina Fuentes", "pediatría", "pediatra", "SIS-90001"),
    ("Felipe Araya", "nutrición", "nutricionista", "SIS-90002"),
    ("Javiera Muñoz", "kinesiología", "kinesiologo", "SIS-90003"),
]

# Residentes que atiende cada profesional de la demo (usuario web → códigos). Sin asignación, un
# profesional no ve la ficha ni registra atenciones de ese residente, tampoco por mensajería.
ASIGNACIONES = {
    "pediatra": ("RES-01", "RES-02"),
    "nutricionista": ("RES-02", "RES-03"),
    "kinesiologo": ("RES-03", "RES-04"),
}

USUARIOS_SIN_PROFESIONAL = [
    ("directora", Rol.DIRECTORA),
    ("encargada_salud", Rol.ENCARGADA_SALUD),
]

# Ficha de la demo de la entrega 2 (solo con SEED_DEMO=true). Todo inventado.
ANTECEDENTES_DEMO = [
    # código, tipo, descripción, fecha
    ("RES-01", TipoAntecedente.DIAGNOSTICO_CRONICO, "Asma bronquial", date(2025, 6, 10)),
    ("RES-01", TipoAntecedente.VACUNA, "Vacunas del PNI al día (18 meses)", date(2025, 1, 14)),
    (
        "RES-02",
        TipoAntecedente.ALERGIA,
        "Alergia a la proteína de la leche de vaca",
        date(2026, 2, 3),
    ),
    ("RES-02", TipoAntecedente.PERINATAL, "Recién nacida de término, 3.200 g", date(2025, 12, 28)),
    ("RES-03", TipoAntecedente.PERINATAL, "Prematura de 34 semanas, 1.950 g", date(2025, 2, 20)),
    (
        "RES-04",
        TipoAntecedente.HOSPITALIZACION,
        "Neumonía, Hospital Luis Calvo Mackenna, 5 días",
        date(2025, 8, 12),
    ),
    ("RES-04", TipoAntecedente.ALERGIA, "Alergia a la penicilina", date(2024, 3, 2)),
]
MEDICIONES_DEMO = [
    # código, fecha, peso (kg), talla (cm)
    ("RES-01", date(2026, 10, 20), 14.2, 95.0),
    ("RES-02", date(2026, 10, 30), 8.1, 70.5),
    ("RES-04", date(2026, 9, 22), 16.0, 102.0),
]
# Cada una la firma su profesional con SEED_PASSWORD, así que queda con hash y timbre.
ATENCIONES_DEMO = [
    (
        "pediatra",
        "RES-01",
        {
            "fecha_atencion": {"valor": "2026-10-20", "fragmento": None},
            "lugar": {"valor": "Hogar", "fragmento": None},
            "motivo": {"valor": "Control por crisis de asma leve", "fragmento": None},
            "diagnosticos": [{"valor": "Asma bronquial, crisis leve", "fragmento": None}],
            "evolucion_clinica": {
                "valor": "Sibilancias espiratorias aisladas, sin dificultad respiratoria.",
                "fragmento": None,
            },
            "indicaciones_farmacologicas": [
                {
                    "medicamento": "Salbutamol",
                    "dosis": "2 puff",
                    "frecuencia_horario": "cada 6 horas",
                    "via": "inhalatoria",
                    "duracion": "5 días",
                    "fecha_inicio": "2026-10-20",
                    "fecha_termino": "2026-10-25",
                    "fragmento": None,
                },
                {
                    "medicamento": "Budesonida",
                    "dosis": "200 mcg",
                    "frecuencia_horario": "cada 12 horas",
                    "via": "inhalatoria",
                    "duracion": "3 meses",
                    "fecha_inicio": "2026-10-20",
                    "fecha_termino": "2027-01-20",
                    "fragmento": None,
                },
            ],
            "otras_indicaciones": [{"valor": "Usar aerocámara", "fragmento": None}],
            "proximo_control": {
                "fecha": "2026-11-20",
                "descripcion": "Control de asma",
                "fragmento": None,
            },
            "acompanante": {
                "nombre": "Daniela Núñez",
                "cargo": "educadora de párvulos",
                "fragmento": None,
            },
        },
    ),
    (
        "nutricionista",
        "RES-03",
        {
            "fecha_atencion": {"valor": "2026-11-05", "fragmento": None},
            "lugar": {"valor": "Hogar", "fragmento": None},
            "motivo": {"valor": "Control nutricional", "fragmento": None},
            "diagnosticos": [{"valor": "Riesgo de desnutrición", "fragmento": None}],
            "indicaciones_farmacologicas": [
                {
                    "medicamento": "Sulfato ferroso",
                    "dosis": "1 ml",
                    "frecuencia_horario": "una vez al día",
                    "via": "oral",
                    "duracion": "3 meses",
                    "fragmento": None,
                }
            ],
            "otras_indicaciones": [
                {"valor": "Agregar una colación a media tarde", "fragmento": None}
            ],
            "mediciones": {"peso_kg": 10.3, "talla_cm": 79.0, "fragmento": None},
            "proximo_control": {
                "fecha": "2026-12-05",
                "descripcion": "Control de peso",
                "fragmento": None,
            },
        },
    ),
    (
        "kinesiologo",
        "RES-04",
        {
            "fecha_atencion": {"valor": "2026-09-22", "fragmento": None},
            "lugar": {"valor": "Hogar", "fragmento": None},
            "motivo": {"valor": "Kinesiterapia respiratoria posneumonía", "fragmento": None},
            "diagnosticos": [{"valor": "Neumonía en resolución", "fragmento": None}],
            "otras_indicaciones": [
                {"valor": "Ejercicios respiratorios dos veces al día", "fragmento": None}
            ],
        },
    ),
]


def sembrar(sesion: Session, password: str) -> None:
    for codigo, nombres, apellidos, apodo, nacimiento, nivel in RESIDENTES:
        ingreso = INGRESOS[codigo]
        residente = sesion.scalar(select(Residente).where(Residente.codigo == codigo))
        if residente is None:
            sesion.add(
                Residente(
                    codigo=codigo,
                    nombres=nombres,
                    apellidos=apellidos,
                    apodo=apodo,
                    fecha_nacimiento=nacimiento,
                    nivel=nivel,
                    fecha_ingreso=ingreso,
                )
            )
        elif residente.fecha_ingreso is None:
            residente.fecha_ingreso = ingreso

    for usuario, rol in USUARIOS_SIN_PROFESIONAL:
        if not _existe(sesion, UsuarioWeb.usuario, usuario):
            sesion.add(UsuarioWeb(usuario=usuario, rol=rol, hash_password=hashear_password(password)))

    for nombre, especialidad, usuario, registro in PROFESIONALES:
        existente = sesion.scalar(select(UsuarioWeb).where(UsuarioWeb.usuario == usuario))
        if existente is not None:
            profesional = sesion.get(Profesional, existente.profesional_id)
            if profesional is not None and profesional.registro is None:
                profesional.registro = registro
            continue
        profesional = Profesional(nombre=nombre, especialidad=especialidad, registro=registro)
        sesion.add(profesional)
        sesion.flush()  # asigna profesional.id, que necesita el usuario
        sesion.add(
            UsuarioWeb(
                usuario=usuario,
                rol=Rol.PROFESIONAL,
                profesional_id=profesional.id,
                hash_password=hashear_password(password),
            )
        )
        # Solo al crear este profesional de demo.
        _asignar(sesion, profesional.id, ASIGNACIONES[usuario])


def sembrar_demo(sesion: Session, password: str) -> list[str]:
    """Carga la ficha de la demo de la entrega 2 sobre los datos de sembrar(). Se puede correr
    varias veces: no duplica nada. Devuelve los avisos de lo que no se pudo cargar."""
    avisos = []
    residentes = {r.codigo: r for r in sesion.scalars(select(Residente))}
    usuarios = {u.usuario: u for u in sesion.scalars(select(UsuarioWeb))}

    # En una base donde los profesionales ya existían (como la del servidor), no tienen
    # asignaciones. Solo se agregan a quien no tiene ninguna: las demás las eligió alguien.
    for usuario, codigos in ASIGNACIONES.items():
        profesional_id = usuarios[usuario].profesional_id
        if not _existe(sesion, Asignacion.profesional_id, profesional_id):
            _asignar(sesion, profesional_id, codigos)

    encargada = usuarios["encargada_salud"]
    for codigo, tipo, descripcion, fecha in ANTECEDENTES_DEMO:
        residente_id = residentes[codigo].id
        ya_esta = sesion.scalar(
            select(Antecedente.id).where(
                Antecedente.residente_id == residente_id,
                Antecedente.descripcion == descripcion,
            )
        )
        if ya_esta is None:
            sesion.add(
                Antecedente(
                    residente_id=residente_id,
                    tipo=tipo,
                    descripcion=descripcion,
                    fecha=fecha,
                    registrado_por=encargada.id,
                )
            )

    for codigo, fecha, peso, talla in MEDICIONES_DEMO:
        residente_id = residentes[codigo].id
        ya_esta = sesion.scalar(
            select(Medicion.id).where(
                Medicion.residente_id == residente_id, Medicion.fecha == fecha
            )
        )
        if ya_esta is None:
            sesion.add(
                Medicion(residente_id=residente_id, fecha=fecha, peso_kg=peso, talla_cm=talla)
            )

    for usuario, codigo, campos in ATENCIONES_DEMO:
        autor = usuarios[usuario]
        fecha = date.fromisoformat(campos["fecha_atencion"]["valor"])
        ya_esta = sesion.scalar(
            select(Atencion.id).where(
                Atencion.residente_id == residentes[codigo].id,
                Atencion.profesional_id == autor.profesional_id,
                Atencion.fecha_atencion == fecha,
            )
        )
        if ya_esta is not None:
            continue
        try:
            # Si no se puede firmar, no queda ni el borrador.
            with sesion.begin_nested():
                atencion = crear_atencion(
                    sesion, residentes[codigo].id, autor, campos, OrigenAtencion.WEB
                )
                firmar_atencion(sesion, atencion, autor, password)
        except PasswordIncorrecta:
            avisos.append(
                f"No se cargó la atención de {codigo}: {usuario} ya no usa SEED_PASSWORD."
            )
    return avisos


def _asignar(sesion: Session, profesional_id: int, codigos: tuple[str, ...]) -> None:
    for residente in sesion.scalars(select(Residente).where(Residente.codigo.in_(codigos))):
        sesion.add(Asignacion(residente_id=residente.id, profesional_id=profesional_id))


def _existe(sesion: Session, columna, valor) -> bool:
    return sesion.scalar(select(columna).where(columna == valor)) is not None


def main() -> int:
    config = obtener_config()
    if not config.seed_password:
        print("Falta SEED_PASSWORD en .env: es la contraseña de los usuarios de demostración.")
        return 1
    motor = crear_motor(config.database_url)
    try:
        with crear_fabrica_de_sesiones(motor).begin() as sesion:
            password = config.seed_password.get_secret_value()
            sembrar(sesion, password)
            avisos = sembrar_demo(sesion, password) if config.seed_demo else None
    except OperationalError:
        print("No se pudo cargar los datos. ¿Creaste las tablas con: alembic upgrade head?")
        return 1
    finally:
        motor.dispose()
    usuarios = [usuario for usuario, _ in USUARIOS_SIN_PROFESIONAL]
    usuarios += [usuario for _, _, usuario, _ in PROFESIONALES]
    print("Datos de demostración cargados. Usuarios web:", ", ".join(usuarios))
    print("Todos usan la contraseña de SEED_PASSWORD.")
    if avisos is not None:
        print("Ficha de la demo de la entrega 2 cargada (SEED_DEMO=true).")
        for aviso in avisos:
            print("Aviso:", aviso)
    return 0


if __name__ == "__main__":
    sys.exit(main())
