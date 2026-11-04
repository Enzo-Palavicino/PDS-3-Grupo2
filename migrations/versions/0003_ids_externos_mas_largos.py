"""Ids externos de mensajes de hasta 255 caracteres: los de WhatsApp (wamid) miden más de 64.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-04 01:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0003'
down_revision: str | Sequence[str] | None = '0002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _cambiar_largo(antes: int, despues: int) -> None:
    with op.batch_alter_table('mensajes_entrantes', schema=None) as batch_op:
        batch_op.alter_column('id_externo',
               existing_type=sa.String(length=antes),
               type_=sa.String(length=despues),
               existing_nullable=False)
        batch_op.alter_column('responde_a',
               existing_type=sa.String(length=antes),
               type_=sa.String(length=despues),
               existing_nullable=True)

    with op.batch_alter_table('borradores_atencion', schema=None) as batch_op:
        batch_op.alter_column('mensaje_bot_id_externo',
               existing_type=sa.String(length=antes),
               type_=sa.String(length=despues),
               existing_nullable=True)


def upgrade() -> None:
    _cambiar_largo(64, 255)


def downgrade() -> None:
    # En PostgreSQL falla si ya hay ids de más de 64 caracteres guardados.
    _cambiar_largo(255, 64)
