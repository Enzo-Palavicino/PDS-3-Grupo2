import json

from sqlalchemy import select

from app.modelos import EventoAuditoria


def test_sin_sesion_las_paginas_llevan_al_inicio_de_sesion(cliente):
    respuesta = cliente.get("/borradores/7", follow_redirects=False)

    assert respuesta.status_code == 303
    assert respuesta.headers["location"] == "/login?siguiente=/borradores/7"


def test_cada_rol_entra_a_su_pagina(entrar, acciones):
    assert entrar("directora").headers["location"] == "/vinculos"
    assert entrar("encargada_salud").headers["location"] == "/borradores"
    assert entrar("pediatra").headers["location"] == "/borradores"
    assert acciones() == ["inicio_sesion"] * 3


def test_una_contrasena_incorrecta_no_entra(entrar, acciones):
    respuesta = entrar("pediatra", password="otra-clave")

    assert respuesta.status_code == 401
    assert "Usuario o contraseña incorrectos" in respuesta.text
    assert acciones() == ["inicio_sesion_fallido"]


def test_la_auditoria_no_guarda_la_contrasena_intentada(entrar, sesion):
    entrar("pediatra", password="clave-equivocada")

    sesion.commit()
    evento = sesion.scalar(select(EventoAuditoria))
    assert evento.detalle == {"usuario": "pediatra"}
    assert "clave-equivocada" not in json.dumps(evento.detalle)


def test_despues_de_entrar_vuelve_a_la_pagina_pedida(entrar):
    assert entrar("pediatra", siguiente="/borradores/7").headers["location"] == "/borradores/7"


def test_si_la_pagina_pedida_es_de_otro_rol_va_a_su_pagina_de_inicio(entrar):
    # Por ejemplo, el enlace de un borrador que envió el bot, abierto por la directora: esa
    # página le respondería 403.
    assert entrar("directora", siguiente="/borradores/7").headers["location"] == "/vinculos"
    assert entrar("pediatra", siguiente="/vinculos").headers["location"] == "/borradores"


def test_nunca_redirige_a_otro_sitio(entrar):
    for externo in ["https://sitio-falso.example", "//sitio-falso.example"]:
        assert entrar("pediatra", siguiente=externo).headers["location"] == "/borradores"


def test_un_formulario_sin_token_csrf_se_rechaza(cliente):
    cliente.get("/login")

    respuesta = cliente.post("/login", data={"usuario": "pediatra", "password": "x"})

    assert respuesta.status_code == 403


def test_cerrar_sesion(cliente, entrar, csrf):
    entrar("pediatra")

    cliente.post("/logout", data={"csrf": csrf()})

    assert cliente.get("/borradores", follow_redirects=False).status_code == 303
