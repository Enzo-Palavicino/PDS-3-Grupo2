import base64
import hashlib
from datetime import date

import pytest
from sqlalchemy import delete, func, select

from app.modelos import Adjunto, Asignacion, Atencion, EventoAuditoria, UsuarioWeb
from app.nucleo.adjuntos import (
    TAMANO_MAXIMO_BYTES,
    ArchivoNoPermitido,
    detectar_mime,
    guardar_adjunto,
    leer_adjunto,
)
from app.nucleo.atenciones import crear_atencion, firmar_atencion, verificar_integridad
from tests.web.conftest import PASSWORD

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a3ioAAAAASUVORK5CYII=')
PDF = b'%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [] /Count 0 >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n'


def subir(cliente, csrf, contenido=PNG, nombre='examen.png', **cambios):
    datos = {'csrf': csrf('/adjuntos'), 'residente_id': '2', 'tipo':'examen',
             'emisor':'CESFAM ficticio', 'fecha_emision':'2026-11-10', **cambios}
    return cliente.post('/adjuntos', data=datos, files={'archivo': (nombre, contenido, 'application/octet-stream')})


@pytest.mark.parametrize('cuenta', ['pediatra', 'encargada_salud'])
def test_subida_externa_y_descarga_privada(cliente, entrar, csrf, sesion, acciones, cuenta):
    entrar(cuenta)
    respuesta = subir(cliente, csrf)
    assert respuesta.status_code == 200 and 'Documento adjuntado exitosamente' in respuesta.text
    fila = sesion.scalar(select(Adjunto))
    assert fila.atencion_id is None
    assert fila.mime == 'image/png' and fila.contenido == PNG
    assert fila.sha256 == hashlib.sha256(PNG).hexdigest()
    assert fila.tamano_bytes == len(PNG)
    assert fila.fecha_emision == date(2026, 11, 10)
    assert sesion.scalar(select(func.count()).select_from(Atencion)) == 0
    aid = fila.id
    sesion.commit()
    descarga = cliente.get(f'/adjuntos/{aid}/descargar')
    assert descarga.content == PNG
    assert descarga.headers['content-type'] == 'image/png'
    assert descarga.headers['content-disposition'].startswith('attachment;')
    assert descarga.headers['cache-control'] == 'no-store, private'
    assert descarga.headers['x-content-type-options'] == 'nosniff'
    assert acciones().count('adjunto_descargado') == 1
    cliente.get(f'/adjuntos/{aid}/descargar')
    assert acciones().count('adjunto_descargado') == 2


def test_no_confia_en_extension_o_mime(cliente, entrar, csrf, sesion):
    entrar('pediatra')
    assert subir(cliente, csrf, nombre='falso.pdf').status_code == 200
    fila = sesion.scalar(select(Adjunto))
    assert fila.mime == 'image/png' and fila.nombre_archivo == 'falso.png'


@pytest.mark.parametrize('contenido', [b'', b'<script>alert(1)</script>', b'%PDF-1.4\nincompleto', b'\x89PNG\r\n\x1a\n', b'x' * (TAMANO_MAXIMO_BYTES + 1)])
def test_rechaza_archivo_invalido_sin_guardar(cliente, entrar, csrf, sesion, contenido):
    entrar('pediatra')
    assert subir(cliente, csrf, contenido=contenido, nombre='parece.pdf').status_code == 400
    assert sesion.scalar(select(func.count()).select_from(Adjunto)) == 0
    assert sesion.scalar(select(EventoAuditoria).where(EventoAuditoria.accion == 'adjunto_subido')) is None


def test_limite_exacto_y_pdf():
    assert detectar_mime(PDF) == 'application/pdf'
    grande = PDF[:-6] + b' ' * (TAMANO_MAXIMO_BYTES - len(PDF)) + PDF[-6:]
    assert len(grande) == TAMANO_MAXIMO_BYTES
    assert detectar_mime(grande) == 'application/pdf'
    with pytest.raises(ArchivoNoPermitido):
        detectar_mime(grande + b' ')


def test_sin_sesion_sin_asignacion_y_directora_no_descargan(cliente, entrar, csrf, sesion, acciones):
    entrar('pediatra')
    subir(cliente, csrf)
    aid = sesion.scalar(select(Adjunto.id))
    sesion.commit()
    cliente.cookies.clear()
    assert cliente.get(f'/adjuntos/{aid}/descargar').status_code == 403
    for cuenta in ('directora', 'kinesiologo'):
        entrar(cuenta)
        assert cliente.get(f'/adjuntos/{aid}/descargar').status_code == 403
        assert cliente.get('/adjuntos?residente_id=2').status_code == 403
    assert acciones().count('adjunto_descargado') == 0
    entrar('pediatra')
    autor = sesion.scalar(select(UsuarioWeb).where(UsuarioWeb.usuario == 'pediatra'))
    sesion.execute(delete(Asignacion).where(Asignacion.profesional_id == autor.profesional_id, Asignacion.residente_id == 2))
    sesion.commit()
    assert cliente.get(f'/adjuntos/{aid}/descargar').status_code == 403
    assert subir(cliente, csrf).status_code == 403


def test_selector_no_expone_no_asignados_y_csrf(cliente, entrar):
    entrar('pediatra')
    respuesta = cliente.get('/adjuntos')
    assert 'RES-02' in respuesta.text and 'RES-03' not in respuesta.text
    assert cliente.post('/adjuntos', data={'residente_id':2, 'tipo':'examen'}, files={'archivo':('x.png', PNG)}).status_code == 403


@pytest.fixture
def atencion(sesion, datos_demo):
    usuario = sesion.scalar(select(UsuarioWeb).where(UsuarioWeb.usuario == 'pediatra'))
    fila = crear_atencion(sesion, 2, usuario, {'motivo': {'valor':'Control ficticio'}}, 'web', fecha_atencion=date(2026, 11, 10))
    sesion.commit()
    return fila


def test_adjuntar_a_borrador_y_firmada_sin_alterar_firma(cliente, entrar, csrf, sesion, atencion):
    entrar('pediatra')
    assert subir(cliente, csrf, atencion_id=str(atencion.id)).status_code == 200
    autor = sesion.scalar(select(UsuarioWeb).where(UsuarioWeb.usuario == 'pediatra'))
    firmar_atencion(sesion, atencion, autor, PASSWORD)
    sesion.commit()
    firma = atencion.hash_firma
    assert subir(cliente, csrf, contenido=PDF, nombre='nuevo.pdf', atencion_id=str(atencion.id)).status_code == 200
    sesion.expire_all()
    assert atencion.hash_firma == firma and verificar_integridad(atencion)
    assert sesion.scalar(select(func.count()).select_from(Adjunto)) == 2
    aid = sesion.scalar(select(Adjunto.id))
    sesion.commit()
    assert cliente.delete(f'/adjuntos/{aid}/descargar').status_code == 405
    assert cliente.post(f'/adjuntos/{aid}/eliminar').status_code == 404


def test_destinos_manipulados_y_autor_ajeno(cliente, entrar, csrf, sesion, atencion):
    entrar('pediatra')
    assert subir(cliente, csrf, residente_id='1', atencion_id=str(atencion.id)).status_code == 400
    assert subir(cliente, csrf, atencion_id='999').status_code == 400
    assert subir(cliente, csrf, atencion_id='texto').status_code == 400
    entrar('nutricionista')  # asignado a Emilia, pero no es autor de su atención
    assert subir(cliente, csrf, atencion_id=str(atencion.id)).status_code == 403
    assert sesion.scalar(select(func.count()).select_from(Adjunto)) == 0


def test_servicios_tambien_validan_permisos_y_nombre(sesion, datos_demo):
    autor = sesion.scalar(select(UsuarioWeb).where(UsuarioWeb.usuario == 'pediatra'))
    directora = sesion.scalar(select(UsuarioWeb).where(UsuarioWeb.usuario == 'directora'))
    with pytest.raises(PermissionError):
        guardar_adjunto(sesion, 2, PNG, 'x.png', 'examen', directora)
    fila = guardar_adjunto(sesion, 2, PNG, '../../informe\r\n.exe', 'informe', autor)
    assert fila.nombre_archivo == 'informe.png'
    with pytest.raises(PermissionError):
        leer_adjunto(sesion, fila.id, directora)
    assert leer_adjunto(sesion, fila.id, autor).contenido == PNG


def test_integridad_y_metadatos(cliente, entrar, csrf, sesion):
    entrar('pediatra')
    for cambios in ({'tipo':'inventado'}, {'fecha_emision':'incorrecta'}, {'emisor':''}):
        assert subir(cliente, csrf, **cambios).status_code == 400
    assert subir(cliente, csrf).status_code == 200
    fila = sesion.scalar(select(Adjunto))
    aid = fila.id
    fila.contenido = b'alterado'
    sesion.commit()
    assert cliente.get(f'/adjuntos/{aid}/descargar').status_code == 409


def test_error_conserva_destino(cliente, entrar, csrf, atencion):
    entrar('pediatra')
    respuesta = subir(cliente, csrf, contenido=b'invalido', atencion_id=str(atencion.id))
    assert respuesta.status_code == 400
    assert f'<option value="{atencion.id}" selected>' in respuesta.text


def test_jpeg_identificado_por_contenido():
    # Cabecera JFIF y marcador de fin: no depende del nombre o del MIME del navegador.
    jpeg = b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9'
    assert detectar_mime(jpeg) == 'image/jpeg'
    with pytest.raises(ArchivoNoPermitido):
        detectar_mime(jpeg[:-2])
