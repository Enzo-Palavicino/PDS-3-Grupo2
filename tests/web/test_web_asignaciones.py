import pytest
from sqlalchemy import func, select

from app.modelos import Asignacion, BorradorAtencion, Profesional
from app.nucleo.permisos import profesional_asignado


@pytest.mark.parametrize('rol', ['directora', 'encargada_salud'])
def test_asignar_quitar_idempotente_y_auditado(cliente, entrar, csrf, sesion, id_profesional, acciones, rol):
    pid = id_profesional('pediatra')
    entrar(rol)
    ruta = '/residentes/3/asignaciones'
    assert cliente.get(ruta).status_code == 200
    token = csrf(ruta)
    for _ in range(2):
        assert cliente.post(ruta, data={'csrf': token, 'accion': 'asignar', 'profesional_id': pid}).status_code == 200
    assert profesional_asignado(sesion, pid, 3)
    sesion.commit()
    assert acciones().count('asignacion_creada') == 1
    for _ in range(2):
        assert cliente.post(ruta, data={'csrf': token, 'accion': 'quitar', 'profesional_id': pid}).status_code == 200
    assert not profesional_asignado(sesion, pid, 3)
    sesion.commit()
    assert acciones().count('asignacion_retirada') == 1


def test_profesional_no_asigna_y_csrf_es_obligatorio(cliente, entrar, csrf, id_profesional):
    pid = id_profesional('pediatra')
    entrar('pediatra')
    assert cliente.get('/residentes/1/asignaciones').status_code == 403
    assert cliente.post('/residentes/1/asignaciones', data={'csrf': csrf(), 'accion':'asignar', 'profesional_id':pid}).status_code == 403
    entrar('directora')
    assert cliente.post('/residentes/1/asignaciones', data={'accion':'asignar', 'profesional_id':pid}).status_code == 403


def test_retiro_corta_borrador_y_ruta_de_ficha_sin_borrar(cliente, entrar, csrf, crear_borrador, id_profesional, sesion):
    borrador = crear_borrador()
    pid = id_profesional('pediatra')
    entrar('pediatra')
    assert cliente.get(f'/borradores/{borrador.id}').status_code == 200
    assert cliente.get('/residentes/2').status_code == 200
    assert cliente.get('/residentes/3').status_code == 403
    entrar('directora')
    assert cliente.get('/residentes/2').status_code == 403
    cliente.post('/residentes/2/asignaciones', data={'csrf':csrf('/residentes/2/asignaciones'), 'accion':'quitar', 'profesional_id':pid})
    entrar('pediatra')
    assert cliente.get('/residentes/2').status_code == 403
    assert cliente.get(f'/borradores/{borrador.id}').status_code == 403
    assert cliente.post(f'/borradores/{borrador.id}/descartar', data={'csrf':csrf()}).status_code == 403
    assert f'/borradores/{borrador.id}"' not in cliente.get('/borradores').text
    entrar('encargada_salud')
    assert cliente.get(f'/borradores/{borrador.id}').status_code == 200
    assert sesion.get(BorradorAtencion, borrador.id) is not None


def test_profesional_inactivo_y_ids_invalidos(cliente, entrar, csrf, sesion, id_profesional):
    pid = id_profesional('pediatra')
    sesion.get(Profesional, pid).activo = False
    sesion.commit()
    entrar('directora')
    token = csrf('/residentes/3/asignaciones')
    assert cliente.post('/residentes/3/asignaciones', data={'csrf':token, 'accion':'asignar', 'profesional_id':pid}).status_code == 400
    assert cliente.get('/residentes/999/asignaciones').status_code == 404
    assert cliente.post('/residentes/3/asignaciones', data={'csrf':token, 'accion':'asignar', 'profesional_id':999}).status_code == 404


def test_semilla_no_restaura_asignaciones_retiradas(sesion, datos_demo):
    from scripts.sembrar_datos import sembrar
    assert sesion.scalar(select(func.count()).select_from(Asignacion)) == 6
    sesion.delete(sesion.scalar(select(Asignacion)))
    sesion.commit()
    sembrar(sesion, 'clave-de-prueba')
    sesion.commit()
    assert sesion.scalar(select(func.count()).select_from(Asignacion)) == 5


@pytest.mark.parametrize('rol', ['directora', 'encargada_salud'])
def test_crear_residente_con_varios_profesionales(cliente, entrar, csrf, sesion, id_profesional, acciones, rol):
    from app.modelos import Residente
    from tests.web.test_web_residentes import DATOS
    ids = [id_profesional('pediatra'), id_profesional('nutricionista')]
    entrar(rol)
    respuesta = cliente.post('/residentes/nuevo', data={**DATOS, 'csrf': csrf('/residentes/nuevo'), 'profesionales_ids': [*ids, ids[0]]})
    assert respuesta.status_code == 200
    nuevo = sesion.scalar(select(Residente).where(Residente.codigo == 'RES-05'))
    asignaciones = list(sesion.scalars(select(Asignacion).where(Asignacion.residente_id == nuevo.id)))
    assert {a.profesional_id for a in asignaciones} == set(ids)
    assert all(a.asignado_por is not None for a in asignaciones)
    assert acciones().count('asignacion_creada') == 2


def test_seleccion_invalida_no_crea_residente(cliente, entrar, csrf, sesion, id_profesional):
    from app.modelos import Residente
    from tests.web.test_web_residentes import DATOS
    pid = id_profesional('pediatra')
    sesion.get(Profesional, pid).activo = False
    sesion.commit()
    entrar('directora')
    for seleccionado in (pid, 999):
        respuesta = cliente.post('/residentes/nuevo', data={**DATOS, 'csrf': csrf('/residentes/nuevo'), 'profesionales_ids': [seleccionado]})
        assert respuesta.status_code == 400
        assert sesion.scalar(select(func.count()).select_from(Residente)) == 4
        sesion.commit()


def test_confirmacion_de_duplicado_conserva_seleccion(cliente, entrar, csrf, id_profesional):
    from tests.web.test_web_residentes import DATOS
    pid = id_profesional('pediatra')
    entrar('directora')
    cliente.post('/residentes/nuevo', data={**DATOS, 'csrf': csrf('/residentes/nuevo')})
    datos = {**DATOS, 'csrf': csrf('/residentes/nuevo'), 'profesionales_ids': [pid]}
    respuesta = cliente.post('/residentes/nuevo', data=datos)
    assert respuesta.status_code == 409
    assert f'<option value="{pid}" selected>' in respuesta.text
    assert cliente.post('/residentes/nuevo', data={**datos, 'confirmar_duplicado':'true'}).status_code == 200
