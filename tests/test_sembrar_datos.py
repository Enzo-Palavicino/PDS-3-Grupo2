from datetime import date

from sqlalchemy import func, select

from app.modelos import EstadoResidente, Nivel, Profesional, Residente, Rol, UsuarioWeb
from app.seguridad import verificar_password
from scripts.sembrar_datos import sembrar

PASSWORD = "clave-de-prueba"


def contar(sesion, modelo) -> int:
    return sesion.scalar(select(func.count()).select_from(modelo))


def usuario(sesion, nombre: str) -> UsuarioWeb:
    return sesion.scalar(select(UsuarioWeb).where(UsuarioWeb.usuario == nombre))


def test_se_puede_correr_dos_veces_sin_duplicar(sesion):
    sembrar(sesion, PASSWORD)
    sesion.commit()
    sembrar(sesion, PASSWORD)
    sesion.commit()

    assert contar(sesion, Residente) == 4
    assert contar(sesion, Profesional) == 3
    assert contar(sesion, UsuarioWeb) == 5


def test_cada_usuario_profesional_queda_asociado_a_su_profesional(sesion):
    sembrar(sesion, PASSWORD)
    sesion.commit()

    pediatra = usuario(sesion, "pediatra")
    directora = usuario(sesion, "directora")

    assert pediatra.rol == Rol.PROFESIONAL
    assert sesion.get(Profesional, pediatra.profesional_id).especialidad == "pediatría"
    assert directora.rol == Rol.DIRECTORA
    assert directora.profesional_id is None


def test_las_passwords_quedan_guardadas_con_hash(sesion):
    sembrar(sesion, PASSWORD)
    sesion.commit()

    for usuario_web in sesion.scalars(select(UsuarioWeb)):
        assert usuario_web.hash_password != PASSWORD
        assert verificar_password(PASSWORD, usuario_web.hash_password)


def residente(sesion, codigo: str) -> Residente:
    return sesion.scalar(select(Residente).where(Residente.codigo == codigo))


def test_los_residentes_y_profesionales_quedan_con_los_datos_de_la_ficha(sesion):
    sembrar(sesion, PASSWORD)
    sesion.commit()

    emilia = residente(sesion, "RES-02")
    assert emilia.fecha_ingreso == date(2026, 1, 20)
    assert emilia.estado == EstadoResidente.ACTIVO
    pediatra = usuario(sesion, "pediatra")
    assert sesion.get(Profesional, pediatra.profesional_id).registro == "SIS-90001"


def test_completa_los_campos_vacios_de_una_base_que_ya_tenia_datos(sesion):
    # Como en el servidor: los datos se sembraron antes de que existieran estas columnas.
    sembrar(sesion, PASSWORD)
    sesion.commit()
    for fila in sesion.scalars(select(Residente)):
        fila.fecha_ingreso = None
    for fila in sesion.scalars(select(Profesional)):
        fila.registro = None
    sesion.commit()

    sembrar(sesion, PASSWORD)
    sesion.commit()

    assert residente(sesion, "RES-01").fecha_ingreso == date(2024, 3, 11)
    assert sesion.scalar(select(func.count()).where(Profesional.registro.is_(None))) == 0


def test_no_cambia_lo_que_alguien_ya_edito(sesion):
    sesion.add(
        Residente(
            codigo="RES-01",
            nombres="Tomás",
            apellidos="Rivas",
            fecha_nacimiento=date(2023, 7, 14),
            nivel=Nivel.HETEROGENEO,
            fecha_ingreso=date(2024, 4, 1),
        )
    )
    sesion.commit()
    sembrar(sesion, PASSWORD)
    sesion.commit()
    pediatra = sesion.get(Profesional, usuario(sesion, "pediatra").profesional_id)
    pediatra.registro = "SIS-12345"
    sesion.commit()

    sembrar(sesion, PASSWORD)
    sesion.commit()

    assert residente(sesion, "RES-01").fecha_ingreso == date(2024, 4, 1)
    assert sesion.get(Profesional, pediatra.id).registro == "SIS-12345"
