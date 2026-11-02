"""Auditoría solo de inserción también en PostgreSQL (en SQLite ya la impone la migración 0001).

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-03 09:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0002'
down_revision: str | Sequence[str] | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# La base de datos rechaza modificar, borrar o vaciar (TRUNCATE) los eventos de auditoría,
# aunque el código lo intente (D41, art. 9).
FUNCION = """
CREATE FUNCTION rechazar_cambios_en_auditoria() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'eventos_auditoria es solo de inserción';
END;
$$ LANGUAGE plpgsql
"""
TRIGGERS = [
    """
    CREATE TRIGGER eventos_auditoria_sin_cambios
    BEFORE UPDATE OR DELETE ON eventos_auditoria
    FOR EACH ROW EXECUTE FUNCTION rechazar_cambios_en_auditoria()
    """,
    """
    CREATE TRIGGER eventos_auditoria_sin_truncate
    BEFORE TRUNCATE ON eventos_auditoria
    FOR EACH STATEMENT EXECUTE FUNCTION rechazar_cambios_en_auditoria()
    """,
]


def _es_postgresql() -> bool:
    return op.get_context().dialect.name == 'postgresql'


def upgrade() -> None:
    if _es_postgresql():
        op.execute(FUNCION)
        for sql in TRIGGERS:
            op.execute(sql)


def downgrade() -> None:
    if _es_postgresql():
        op.execute('DROP TRIGGER IF EXISTS eventos_auditoria_sin_truncate ON eventos_auditoria')
        op.execute('DROP TRIGGER IF EXISTS eventos_auditoria_sin_cambios ON eventos_auditoria')
        op.execute('DROP FUNCTION IF EXISTS rechazar_cambios_en_auditoria()')
