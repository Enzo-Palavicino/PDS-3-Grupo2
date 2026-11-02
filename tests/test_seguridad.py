from app.seguridad import hashear_password, verificar_password


def test_el_hash_no_contiene_la_password():
    guardado = hashear_password("clave-de-prueba")

    assert guardado.startswith("scrypt$")
    assert "clave-de-prueba" not in guardado


def test_acepta_la_password_correcta_y_rechaza_otra():
    guardado = hashear_password("clave-de-prueba")

    assert verificar_password("clave-de-prueba", guardado)
    assert not verificar_password("otra-clave", guardado)


def test_la_misma_password_da_hashes_distintos():
    # Por la sal aleatoria: el hash no revela si dos usuarios comparten contraseña.
    assert hashear_password("clave-de-prueba") != hashear_password("clave-de-prueba")


def test_un_hash_mal_formado_se_rechaza():
    assert not verificar_password("clave-de-prueba", "texto-cualquiera")
