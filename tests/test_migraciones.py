from alembic import command


def test_los_modelos_coinciden_con_las_migraciones(url_bd, configurar_alembic):
    # Falla si alguien cambió un modelo sin crear su migración (alembic revision --autogenerate).
    command.check(configurar_alembic(url_bd))


def test_las_migraciones_se_pueden_revertir(url_bd, configurar_alembic):
    configuracion = configurar_alembic(url_bd)

    command.downgrade(configuracion, "base")
    command.upgrade(configuracion, "head")
