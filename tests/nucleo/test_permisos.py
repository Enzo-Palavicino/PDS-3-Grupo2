import pytest
from sqlalchemy import select

from app.modelos import Asignacion, Atencion, EstadoAtencion, Profesional, UsuarioWeb
from app.nucleo.permisos import (
    puede_editar_atencion,
    puede_firmar,
    puede_registrar_atencion,
    puede_ver_ficha,
)
from scripts.sembrar_datos import sembrar


@pytest.fixture
def datos(sesion):
    sembrar(sesion, 'clave-de-prueba')
    sesion.commit()
    return {u.usuario: u for u in sesion.scalars(select(UsuarioWeb))}


@pytest.mark.parametrize('nombre,residente,permiso', [
    ('pediatra', 1, True), ('pediatra', 3, False), ('nutricionista', 2, True),
    ('nutricionista', 1, False), ('encargada_salud', 4, True), ('directora', 1, False),
])
def test_lectura_y_registro(sesion, datos, nombre, residente, permiso):
    assert puede_ver_ficha(sesion, datos[nombre], residente) is permiso
    assert puede_registrar_atencion(sesion, datos[nombre], residente) is permiso


def test_edicion_firma_retiro_e_inactividad(sesion, datos):
    autor = datos['pediatra']
    atencion = Atencion(residente_id=1, profesional_id=autor.profesional_id, origen='web', estado='borrador')
    assert puede_editar_atencion(autor, atencion)
    assert puede_firmar(autor, atencion)
    assert puede_editar_atencion(datos['encargada_salud'], atencion)
    assert not puede_firmar(datos['encargada_salud'], atencion)
    assert not puede_editar_atencion(datos['directora'], atencion)
    assert not puede_firmar(datos['nutricionista'], atencion)
    atencion.estado = EstadoAtencion.FIRMADA
    assert not puede_firmar(autor, atencion)
    assert not puede_editar_atencion(datos['encargada_salud'], atencion)
    atencion.estado = EstadoAtencion.BORRADOR
    asignacion = sesion.scalar(select(Asignacion).where(Asignacion.residente_id == 1, Asignacion.profesional_id == autor.profesional_id))
    sesion.delete(asignacion)
    sesion.flush()
    assert not puede_firmar(autor, atencion)
    assert not puede_editar_atencion(autor, atencion)
    assert not puede_ver_ficha(sesion, autor, 1)
    assert puede_ver_ficha(sesion, autor, 2)
    sesion.get(Profesional, autor.profesional_id).activo = False
    sesion.flush()
    assert not puede_ver_ficha(sesion, autor, 2)


def test_usuario_inactivo_o_objeto_desconectado_no_autoriza(sesion, datos):
    autor = datos['pediatra']
    autor.activo = False
    assert not puede_ver_ficha(sesion, autor, 1)
    autor.activo = True
    atencion = Atencion(residente_id=1, profesional_id=autor.profesional_id, estado='borrador')
    sesion.expunge(autor)
    assert not puede_firmar(autor, atencion)
    assert not puede_editar_atencion(autor, atencion)
