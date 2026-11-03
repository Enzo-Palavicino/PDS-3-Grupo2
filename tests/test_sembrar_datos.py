from sqlalchemy import func, select

from app.modelos import Profesional, Residente, Rol, UsuarioWeb
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
