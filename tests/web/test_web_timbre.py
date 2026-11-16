from app.modelos import Profesional
from tests.web.conftest import csrf_de

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def subir(cliente, contenido: bytes, nombre: str = "timbre.png"):
    csrf = csrf_de(cliente.get("/cuenta/timbre").text)
    return cliente.post(
        "/cuenta/timbre",
        data={"csrf": csrf},
        files={"archivo": (nombre, contenido, "image/png")},
        follow_redirects=False,
    )


def test_la_profesional_sube_su_timbre_y_se_muestra(cliente, entrar, id_profesional):
    entrar("pediatra")

    respuesta = subir(cliente, PNG)

    assert respuesta.status_code == 303
    profesional_id = id_profesional("pediatra")
    imagen = cliente.get(f"/profesionales/{profesional_id}/timbre")
    assert (imagen.content, imagen.headers["content-type"]) == (PNG, "image/png")
    assert imagen.headers["x-content-type-options"] == "nosniff"
    assert "Timbre guardado" in cliente.get("/cuenta/timbre?guardado=1").text


def test_un_archivo_que_no_es_imagen_se_rechaza_aunque_diga_png(
    cliente, entrar, sesion, id_profesional
):
    entrar("pediatra")

    respuesta = subir(cliente, b"no soy una imagen", nombre="timbre.png")

    assert respuesta.status_code == 400
    assert "PNG o JPG" in respuesta.text
    sesion.expire_all()
    profesional = sesion.get(Profesional, id_profesional("pediatra"))
    assert profesional.timbre_imagen is None
    sesion.commit()


def test_sin_imagen_se_entrega_el_timbre_generado(cliente, entrar, id_profesional):
    entrar("encargada_salud")

    imagen = cliente.get(f"/profesionales/{id_profesional('pediatra')}/timbre")

    assert imagen.headers["content-type"].startswith("image/svg+xml")
    assert "Carolina Fuentes" in imagen.text


def test_el_timbre_exige_iniciar_sesion(cliente, id_profesional):
    respuesta = cliente.get(
        f"/profesionales/{id_profesional('pediatra')}/timbre", follow_redirects=False
    )

    assert respuesta.status_code == 303
    assert respuesta.headers["location"].startswith("/login")


def test_solo_un_profesional_sube_su_timbre(cliente, entrar):
    entrar("encargada_salud")

    assert cliente.get("/cuenta/timbre").status_code == 403


def test_un_profesional_que_no_existe_da_404(cliente, entrar):
    entrar("pediatra")

    assert cliente.get("/profesionales/999/timbre").status_code == 404


def test_el_menu_de_la_profesional_lleva_a_su_timbre(cliente, entrar):
    entrar("pediatra")

    assert 'href="/cuenta/timbre"' in cliente.get("/borradores").text
