import pytest
from sqlalchemy import delete, func, select

from app.modelos import Asignacion, BorradorAtencion, EstadoMensaje
from app.nucleo.procesamiento import procesar
from app.proveedores.llm.fake import ProveedorLLMFake


@pytest.mark.parametrize('canal', ['telegram', 'whatsapp'])
@pytest.mark.parametrize('texto', ['Atendí a Emilia Soto por tos.', 'Atendí a RES-02 por tos.'])
def test_rechaza_no_asignado_antes_del_llm(sesion, residentes_guardados, profesional, guardar_mensaje, contexto, canal_falso, canal, texto):
    sesion.execute(delete(Asignacion).where(Asignacion.residente_id == 2))
    sesion.commit()
    contexto.adaptadores[canal] = canal_falso
    mensaje = guardar_mensaje(canal=canal, texto=texto)
    procesar(sesion, mensaje, contexto)
    assert mensaje.estado == EstadoMensaje.RECHAZADO
    assert contexto.llm.entradas == []
    assert sesion.scalar(select(func.count()).select_from(BorradorAtencion)) == 0
    assert 'No tienes autorización' in canal_falso.enviados[-1][1]
    procesar(sesion, mensaje, contexto)
    assert len(canal_falso.enviados) == 1


def test_revisa_asignacion_despues_del_llm(sesion, fabrica_de_sesiones, residentes_guardados, guardar_mensaje, contexto):
    class RetiraDuranteLlamada(ProveedorLLMFake):
        def generar_json(self, instrucciones, entrada, esquema):
            with fabrica_de_sesiones.begin() as otra:
                otra.execute(delete(Asignacion).where(Asignacion.residente_id == 2))
            return super().generar_json(instrucciones, entrada, esquema)
    contexto.llm = RetiraDuranteLlamada()
    mensaje = guardar_mensaje(texto='Atendí a Emilia Soto por tos.')
    procesar(sesion, mensaje, contexto)
    assert mensaje.estado == EstadoMensaje.RECHAZADO
    assert sesion.scalar(select(func.count()).select_from(BorradorAtencion)) == 0


def test_asignado_si_crea_borrador(sesion, residentes_guardados, guardar_mensaje, contexto):
    mensaje = guardar_mensaje(texto='Atendí a Emilia Soto por tos.')
    procesar(sesion, mensaje, contexto)
    assert mensaje.estado == EstadoMensaje.LISTO
    assert sesion.scalar(select(BorradorAtencion)).residente_id == 2
