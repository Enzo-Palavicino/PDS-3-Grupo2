from datetime import timedelta

from app.db import ahora
from app.modelos import EstadoBorrador

# Quién ve qué


def test_la_encargada_de_salud_ve_todos_los_borradores(cliente, entrar, crear_borrador):
    del_pediatra = crear_borrador("pediatra")
    del_nutricionista = crear_borrador("nutricionista")
    entrar("encargada_salud")

    html = cliente.get("/borradores").text

    assert f"/borradores/{del_pediatra.id}" in html
    assert f"/borradores/{del_nutricionista.id}" in html


def test_un_profesional_ve_solo_sus_borradores(cliente, entrar, crear_borrador):
    propio = crear_borrador("pediatra")
    ajeno = crear_borrador("nutricionista")
    entrar("pediatra")

    html = cliente.get("/borradores").text

    assert f"/borradores/{propio.id}" in html
    assert f"/borradores/{ajeno.id}" not in html


def test_la_directora_no_ve_borradores(cliente, entrar):
    entrar("directora")

    assert cliente.get("/borradores").status_code == 403


# Detalle


def test_el_detalle_muestra_cada_dato_con_su_fragmento_y_el_nombre_del_residente(
    cliente, entrar, crear_borrador
):
    borrador = crear_borrador("pediatra")
    entrar("pediatra")

    html = cliente.get(f"/borradores/{borrador.id}").text

    assert "bronquiolitis leve" in html
    assert "cuadro de bronquiolitis leve" in html
    # Los fragmentos se guardan seudonimizados; la web los muestra con el nombre.
    assert "atendí a Emilia Soto (RES-02)" in html
    assert "acompañante (nombre y cargo)" in html


def test_abrir_un_borrador_queda_en_la_auditoria(cliente, entrar, crear_borrador, acciones):
    borrador = crear_borrador("pediatra")
    entrar("pediatra")

    cliente.get(f"/borradores/{borrador.id}")

    assert acciones()[-1] == "borrador_leido"


def test_un_profesional_no_puede_abrir_un_borrador_ajeno(cliente, entrar, crear_borrador):
    ajeno = crear_borrador("nutricionista")
    entrar("pediatra")

    assert cliente.get(f"/borradores/{ajeno.id}").status_code == 403


def test_un_borrador_que_no_existe(cliente, entrar):
    entrar("encargada_salud")

    respuesta = cliente.get("/borradores/999")

    assert respuesta.status_code == 404
    assert "Ese borrador no existe" in respuesta.text


# Descartar


def test_el_profesional_puede_descartar_su_borrador(
    cliente, entrar, csrf, crear_borrador, sesion, acciones
):
    borrador = crear_borrador("pediatra")
    entrar("pediatra")

    respuesta = cliente.post(
        f"/borradores/{borrador.id}/descartar", data={"csrf": csrf()}, follow_redirects=False
    )

    assert respuesta.status_code == 303
    sesion.refresh(borrador)
    assert borrador.estado == EstadoBorrador.DESCARTADO
    assert acciones()[-1] == "borrador_descartado"


def test_la_encargada_de_salud_puede_descartar_cualquier_borrador(
    cliente, entrar, csrf, crear_borrador, sesion
):
    borrador = crear_borrador("nutricionista")
    entrar("encargada_salud")

    cliente.post(f"/borradores/{borrador.id}/descartar", data={"csrf": csrf()})

    sesion.refresh(borrador)
    assert borrador.estado == EstadoBorrador.DESCARTADO


def test_no_se_puede_descartar_un_borrador_ajeno(cliente, entrar, csrf, crear_borrador, sesion):
    ajeno = crear_borrador("nutricionista")
    entrar("pediatra")

    respuesta = cliente.post(f"/borradores/{ajeno.id}/descartar", data={"csrf": csrf()})

    assert respuesta.status_code == 403
    sesion.refresh(ajeno)
    assert ajeno.estado == EstadoBorrador.PENDIENTE


def test_descartar_sin_token_csrf_se_rechaza(cliente, entrar, crear_borrador):
    borrador = crear_borrador("pediatra")
    entrar("pediatra")

    respuesta = cliente.post(f"/borradores/{borrador.id}/descartar", data={})

    assert respuesta.status_code == 403


# Borradores sin actividad (regla 9)


def dejar_sin_cambios(sesion, borrador, dias: int) -> None:
    """Simula que el borrador no cambia hace `dias` días."""
    borrador.actualizado_en = ahora() - timedelta(days=dias)
    sesion.commit()


def test_un_borrador_sin_cambios_hace_mas_de_30_dias_aparece_marcado(
    cliente, entrar, crear_borrador, sesion
):
    antiguo = crear_borrador("pediatra")
    dejar_sin_cambios(sesion, antiguo, dias=31)
    entrar("pediatra")

    assert "etiqueta sin-actividad" in cliente.get("/borradores").text
    detalle = cliente.get(f"/borradores/{antiguo.id}").text
    assert "etiqueta sin-actividad" in detalle
    assert "revísalo y complétalo o descártalo" in detalle


def test_un_borrador_con_cambios_recientes_no_aparece_marcado(
    cliente, entrar, crear_borrador, sesion
):
    reciente = crear_borrador("pediatra")
    dejar_sin_cambios(sesion, reciente, dias=29)
    entrar("pediatra")

    assert "etiqueta sin-actividad" not in cliente.get("/borradores").text
    assert "etiqueta sin-actividad" not in cliente.get(f"/borradores/{reciente.id}").text
