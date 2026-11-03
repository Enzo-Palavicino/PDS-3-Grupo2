from sqlalchemy import select

from app.modelos import CodigoVinculacion, UsuarioWeb, VinculoCanal


def test_la_directora_ve_a_los_profesionales(cliente, entrar):
    entrar("directora")

    html = cliente.get("/vinculos").text

    assert "Carolina Fuentes" in html
    assert "Generar enlace" in html


def test_un_profesional_no_puede_ver_los_vinculos(cliente, entrar):
    entrar("pediatra")

    assert cliente.get("/vinculos").status_code == 403


def test_sin_bot_conectado_el_enlace_es_el_comando_start(
    cliente, entrar, csrf, id_profesional, sesion
):
    entrar("directora")

    html = cliente.post(
        "/vinculos/codigo",
        data={"csrf": csrf("/vinculos"), "profesional_id": id_profesional("pediatra")},
    ).text

    sesion.commit()
    codigo = sesion.scalar(select(CodigoVinculacion))
    directora = sesion.scalar(
        select(UsuarioWeb).where(UsuarioWeb.usuario == "directora")
    )
    assert f"/start {codigo.codigo}" in html
    assert codigo.creado_por == directora.id


def test_con_el_bot_conectado_muestra_el_enlace_y_su_qr(
    cliente, entrar, csrf, id_profesional
):
    class TelegramFalso:
        def obtener_bot(self):
            return {"username": "bot_de_prueba_bot"}

    cliente.app.state.cliente_telegram = TelegramFalso()
    entrar("directora")

    html = cliente.post(
        "/vinculos/codigo",
        data={"csrf": csrf("/vinculos"), "profesional_id": id_profesional("pediatra")},
    ).text

    assert "https://t.me/bot_de_prueba_bot?start=" in html
    assert "<svg" in html


def test_revocar_un_vinculo(cliente, entrar, csrf, id_profesional, sesion, acciones):
    vinculo = VinculoCanal(
        profesional_id=id_profesional("pediatra"),
        canal="telegram",
        id_externo="55667788",
    )
    sesion.add(vinculo)
    sesion.commit()
    entrar("directora")

    cliente.post(f"/vinculos/{vinculo.id}/revocar", data={"csrf": csrf("/vinculos")})

    sesion.refresh(vinculo)
    assert vinculo.activo is False
    assert acciones()[-1] == "vinculo_revocado"


def test_enlace_whatsapp_y_qr(cliente, entrar, csrf, id_profesional):
    cliente.app.state.config.whatsapp_enabled = True
    cliente.app.state.config.whatsapp_phone_number = "56987654321"
    entrar("directora")
    respuesta = cliente.post(
        "/vinculos/codigo",
        data={
            "csrf": csrf("/vinculos"),
            "profesional_id": id_profesional("pediatra"),
            "canal": "whatsapp",
        },
    )
    assert respuesta.status_code == 200
    assert "https://wa.me/56987654321?text=%2Fstart%20" in respuesta.text
    assert "<svg" in respuesta.text
    assert "envíe el mensaje" in respuesta.text


def test_no_genera_codigo_whatsapp_si_esta_apagado(
    cliente, entrar, csrf, id_profesional, sesion
):
    entrar("directora")
    respuesta = cliente.post(
        "/vinculos/codigo",
        data={
            "csrf": csrf("/vinculos"),
            "profesional_id": id_profesional("pediatra"),
            "canal": "whatsapp",
        },
    )
    assert respuesta.status_code == 400
    assert sesion.scalar(select(CodigoVinculacion)) is None
