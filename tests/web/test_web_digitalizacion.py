from datetime import date

import pytest
from sqlalchemy import func, select

from app.modelos import Adjunto, DocumentoHistorico, EventoAuditoria, UsuarioWeb
from app.nucleo.documentos import subir_documento
from tests.web.conftest import csrf_de
from tests.web.test_web_adjuntos import PDF, PNG


def subir(cliente, archivos=None, **datos):
    pagina = cliente.get('/digitalizacion?residente_id=2')
    return cliente.post('/digitalizacion', data={
        'csrf': csrf_de(pagina.text), 'residente_id':'2', 'confirmar_identidad':'true',
        'tipo_documento':'Registro de atención', **datos,
    }, files=archivos or [('archivos', ('foto.png', PNG, 'image/png'))])


def test_carga_multiple_fecha_opcional_auditoria_y_notificacion_post_commit(cliente, entrar, sesion, fabrica_de_sesiones, acciones):
    class WorkerPrueba:
        llamadas = 0
        def despertar(self):
            self.llamadas += 1
            with fabrica_de_sesiones() as otra:
                assert otra.scalar(select(func.count()).select_from(DocumentoHistorico)) == 2
    worker = WorkerPrueba()
    cliente.app.state.worker_documentos = worker
    entrar('encargada_salud')
    respuesta = subir(cliente, [('archivos', ('uno.png', PNG)), ('archivos', ('dos.png', PNG))])
    assert respuesta.status_code == 200
    assert '2 documento(s) guardado(s)' in respuesta.text
    documentos = list(sesion.scalars(select(DocumentoHistorico)))
    assert len(documentos) == 2
    assert all(d.estado == 'subido' and d.intentos == 0 and d.proximo_intento_en is None and d.fecha_original is None for d in documentos)
    assert all(sesion.get(Adjunto, d.adjunto_id).contenido == PNG for d in documentos)
    assert all(d.residente_id == 2 and d.subido_por is not None for d in documentos)
    assert worker.llamadas == 1
    assert acciones().count('documento_subido') == 2
    assert acciones().count('adjunto_subido') == 2


def test_fecha_y_tipo_guardados_sin_worker_sigue_subido(cliente, entrar, sesion):
    entrar('encargada_salud')
    assert subir(cliente, fecha_original='2020-01-12', tipo_documento='Examen').status_code == 200
    documento = sesion.scalar(select(DocumentoHistorico))
    assert documento.fecha_original == date(2020, 1, 12)
    assert documento.tipo_documento == 'Examen' and documento.estado == 'subido'
    adjunto = sesion.get(Adjunto, documento.adjunto_id)
    assert adjunto.fecha_emision == documento.fecha_original
    assert adjunto.tipo == 'documento_historico' and adjunto.atencion_id is None


@pytest.mark.parametrize('rol', ['directora', 'pediatra'])
def test_solo_encargada_puede_ver_subir_y_consultar_estados(cliente, entrar, csrf, rol):
    entrar(rol)
    token = csrf('/cuenta/password')
    assert cliente.get('/digitalizacion').status_code == 403
    assert cliente.get('/digitalizacion/estados?residente_id=2').status_code == 403
    respuesta = cliente.post('/digitalizacion', data={'csrf':token, 'residente_id':2, 'tipo_documento':'Examen', 'confirmar_identidad':'true'}, files={'archivos':('x.png', PNG)})
    assert respuesta.status_code == 403


def test_identidad_y_csrf(cliente, entrar, sesion):
    entrar('encargada_salud')
    assert 'name="archivos"' not in cliente.get('/digitalizacion').text
    assert subir(cliente, confirmar_identidad='false').status_code == 400
    assert subir(cliente, residente_id='3').status_code == 400  # se mostró al residente 2
    assert subir(cliente, csrf='incorrecto').status_code == 403
    assert sesion.scalar(select(func.count()).select_from(DocumentoHistorico)) == 0
    sesion.commit()
    assert cliente.get('/digitalizacion?residente_id=999').status_code == 404


@pytest.mark.parametrize('contenido', [PDF, b'no es imagen', b'', b'x' * (10 * 1024 * 1024 + 1)])
def test_lote_invalido_se_revierte_completo(cliente, entrar, sesion, contenido):
    entrar('encargada_salud')
    respuesta = subir(cliente, [('archivos', ('correcta.png', PNG)), ('archivos', ('falsa.png', contenido))])
    assert respuesta.status_code == 400
    assert sesion.scalar(select(func.count()).select_from(Adjunto)) == 0
    assert sesion.scalar(select(func.count()).select_from(DocumentoHistorico)) == 0
    assert sesion.scalar(select(EventoAuditoria).where(EventoAuditoria.accion == 'documento_subido')) is None


def test_limites_y_metadatos(cliente, entrar, sesion, monkeypatch):
    entrar('encargada_salud')
    assert subir(cliente, [('archivos', ('foto.png', PNG))] * 11).status_code == 400
    assert subir(cliente, tipo_documento=' ').status_code == 400
    assert subir(cliente, fecha_original='incorrecta').status_code == 400
    monkeypatch.setattr('app.web.digitalizacion.MAXIMO_LOTE_BYTES', len(PNG))
    assert subir(cliente, [('archivos', ('foto.png', PNG))] * 2).status_code == 400
    assert sesion.scalar(select(func.count()).select_from(DocumentoHistorico)) == 0


def test_estados_reflejan_base_sin_filtrar_contenido_clinico(cliente, entrar, sesion):
    entrar('encargada_salud')
    subir(cliente)
    documento = sesion.scalar(select(DocumentoHistorico))
    documento.texto_leido = 'contenido clinico reservado'
    documento.ultimo_error = 'error con datos privados'
    for estado, etiqueta in [('subido', 'Subido'), ('leido', 'Procesando'), ('por_revisar', 'Por revisar'), ('incorporado', 'Incorporado'), ('error', 'Error'), ('descartado', 'Descartado')]:
        documento.estado = estado
        sesion.commit()
        respuesta = cliente.get('/digitalizacion/estados?residente_id=2')
        assert respuesta.json()['documentos'][0]['estado'] == etiqueta
        assert 'contenido clinico reservado' not in respuesta.text
        assert 'datos privados' not in respuesta.text
        assert respuesta.headers['cache-control'] == 'no-store, private'
    assert cliente.get('/digitalizacion/estados?residente_id=3').json()['documentos'] == []
    assert 'setTimeout(actualizar, 5000)' in cliente.get('/digitalizacion?residente_id=2').text
    cliente.cookies.clear()
    assert cliente.get('/digitalizacion/estados?residente_id=2', follow_redirects=False).status_code == 303


def test_worker_caido_no_pierde_documento(cliente, entrar, sesion):
    class WorkerCaido:
        def despertar(self):
            raise RuntimeError('fallo ficticio')
    cliente.app.state.worker_documentos = WorkerCaido()
    entrar('encargada_salud')
    assert subir(cliente).status_code == 200
    assert sesion.scalar(select(DocumentoHistorico)).estado == 'subido'


def test_servicio_no_autoriza_directora(sesion, datos_demo):
    directora = sesion.scalar(select(UsuarioWeb).where(UsuarioWeb.usuario == 'directora'))
    with pytest.raises(PermissionError):
        subir_documento(sesion, 2, PNG, 'foto.png', 'Registro', directora)
