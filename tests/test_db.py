import pytest

from app.db import normalizar_url


@pytest.mark.parametrize(
    ("entregada", "esperada"),
    [
        # Las formas en que Render (y otros servicios) entregan la URL de PostgreSQL.
        ("postgres://u:c@servidor:5432/bd", "postgresql+psycopg://u:c@servidor:5432/bd"),
        ("postgresql://u:c@servidor:5432/bd", "postgresql+psycopg://u:c@servidor:5432/bd"),
        # Las que ya indican el driver, o son de SQLite, no cambian.
        ("postgresql+psycopg://u:c@servidor/bd", "postgresql+psycopg://u:c@servidor/bd"),
        ("sqlite:///./data/app.db", "sqlite:///./data/app.db"),
    ],
)
def test_la_url_de_postgresql_indica_el_driver(entregada, esperada):
    assert normalizar_url(entregada) == esperada
