"""Esquema inicial: las tablas de la integración con mensajería y la auditoría solo de inserción.

Revision ID: 0001
Revises:
Create Date: 2026-11-02 15:27:59.396477

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Auditoría solo de inserción (D41, art. 9): la base de datos rechaza modificar o borrar
# eventos, aunque el código lo intente. Por ahora para SQLite; la versión para PostgreSQL se
# agrega junto con el despliegue.
TRIGGERS_AUDITORIA_SQLITE = [
    """
    CREATE TRIGGER eventos_auditoria_sin_update
    BEFORE UPDATE ON eventos_auditoria
    BEGIN
        SELECT RAISE(ABORT, 'eventos_auditoria es solo de inserción');
    END
    """,
    """
    CREATE TRIGGER eventos_auditoria_sin_delete
    BEFORE DELETE ON eventos_auditoria
    BEGIN
        SELECT RAISE(ABORT, 'eventos_auditoria es solo de inserción');
    END
    """,
]


def upgrade() -> None:
    op.create_table('eventos_auditoria',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('ocurrido_en', sa.DateTime(), nullable=False),
    sa.Column('actor_tipo', sa.String(length=20), nullable=False),
    sa.Column('actor_id', sa.String(length=64), nullable=True),
    sa.Column('accion', sa.String(length=60), nullable=False),
    sa.Column('entidad', sa.String(length=40), nullable=True),
    sa.Column('entidad_id', sa.String(length=64), nullable=True),
    sa.Column('detalle', sa.JSON(), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_eventos_auditoria'))
    )
    op.create_table('profesionales',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('nombre', sa.String(length=120), nullable=False),
    sa.Column('especialidad', sa.String(length=60), nullable=False),
    sa.Column('activo', sa.Boolean(), nullable=False),
    sa.Column('creado_en', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_profesionales'))
    )
    op.create_table('residentes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('codigo', sa.String(length=10), nullable=False),
    sa.Column('nombres', sa.String(length=120), nullable=False),
    sa.Column('apellidos', sa.String(length=120), nullable=False),
    sa.Column('apodo', sa.String(length=60), nullable=True),
    sa.Column('fecha_nacimiento', sa.Date(), nullable=False),
    sa.Column('nivel', sa.String(length=20), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_residentes')),
    sa.UniqueConstraint('codigo', name=op.f('uq_residentes_codigo'))
    )
    op.create_table('borradores_atencion',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('profesional_id', sa.Integer(), nullable=False),
    sa.Column('residente_id', sa.Integer(), nullable=True),
    sa.Column('canal', sa.String(length=20), nullable=False),
    sa.Column('campos', sa.JSON(), nullable=False),
    sa.Column('faltantes', sa.JSON(), nullable=False),
    sa.Column('ambiguedades', sa.JSON(), nullable=False),
    sa.Column('estado', sa.String(length=20), nullable=False),
    sa.Column('mensaje_bot_id_externo', sa.String(length=64), nullable=True),
    sa.Column('creado_en', sa.DateTime(), nullable=False),
    sa.Column('actualizado_en', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['profesional_id'], ['profesionales.id'], name=op.f('fk_borradores_atencion_profesional_id_profesionales')),
    sa.ForeignKeyConstraint(['residente_id'], ['residentes.id'], name=op.f('fk_borradores_atencion_residente_id_residentes')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_borradores_atencion'))
    )
    op.create_table('mensajes_entrantes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('canal', sa.String(length=20), nullable=False),
    sa.Column('id_externo', sa.String(length=64), nullable=False),
    sa.Column('remitente_externo', sa.String(length=64), nullable=False),
    sa.Column('destino_respuesta', sa.String(length=64), nullable=False),
    sa.Column('profesional_id', sa.Integer(), nullable=True),
    sa.Column('tipo', sa.String(length=20), nullable=False),
    sa.Column('texto', sa.Text(), nullable=True),
    sa.Column('audio_ref', sa.String(length=255), nullable=True),
    sa.Column('audio_mime', sa.String(length=60), nullable=True),
    sa.Column('audio_tamano_bytes', sa.Integer(), nullable=True),
    sa.Column('audio_duracion_seg', sa.Integer(), nullable=True),
    sa.Column('ruta_audio', sa.String(length=255), nullable=True),
    sa.Column('responde_a', sa.String(length=64), nullable=True),
    sa.Column('recibido_en', sa.DateTime(), nullable=False),
    sa.Column('estado', sa.String(length=20), nullable=False),
    sa.Column('intentos', sa.Integer(), nullable=False),
    sa.Column('proximo_intento_en', sa.DateTime(), nullable=True),
    sa.Column('ultimo_error', sa.String(length=255), nullable=True),
    sa.Column('creado_en', sa.DateTime(), nullable=False),
    sa.Column('actualizado_en', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['profesional_id'], ['profesionales.id'], name=op.f('fk_mensajes_entrantes_profesional_id_profesionales')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_mensajes_entrantes')),
    sa.UniqueConstraint('canal', 'id_externo', name=op.f('uq_mensajes_entrantes_canal_id_externo'))
    )
    with op.batch_alter_table('mensajes_entrantes', schema=None) as batch_op:
        batch_op.create_index('ix_mensajes_entrantes_cola', ['estado', 'proximo_intento_en'], unique=False)

    op.create_table('usuarios_web',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('usuario', sa.String(length=60), nullable=False),
    sa.Column('rol', sa.String(length=20), nullable=False),
    sa.Column('profesional_id', sa.Integer(), nullable=True),
    sa.Column('hash_password', sa.String(length=255), nullable=False),
    sa.Column('activo', sa.Boolean(), nullable=False),
    sa.Column('creado_en', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['profesional_id'], ['profesionales.id'], name=op.f('fk_usuarios_web_profesional_id_profesionales')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_usuarios_web')),
    sa.UniqueConstraint('usuario', name=op.f('uq_usuarios_web_usuario'))
    )
    op.create_table('vinculos_canal',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('profesional_id', sa.Integer(), nullable=False),
    sa.Column('canal', sa.String(length=20), nullable=False),
    sa.Column('id_externo', sa.String(length=64), nullable=False),
    sa.Column('activo', sa.Boolean(), nullable=False),
    sa.Column('creado_en', sa.DateTime(), nullable=False),
    sa.Column('revocado_en', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['profesional_id'], ['profesionales.id'], name=op.f('fk_vinculos_canal_profesional_id_profesionales')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_vinculos_canal'))
    )
    with op.batch_alter_table('vinculos_canal', schema=None) as batch_op:
        batch_op.create_index('uq_vinculos_canal_cuenta_activa', ['canal', 'id_externo'], unique=True, sqlite_where=sa.text('activo'), postgresql_where=sa.text('activo'))

    op.create_table('borrador_mensajes',
    sa.Column('borrador_id', sa.Integer(), nullable=False),
    sa.Column('mensaje_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['borrador_id'], ['borradores_atencion.id'], name=op.f('fk_borrador_mensajes_borrador_id_borradores_atencion')),
    sa.ForeignKeyConstraint(['mensaje_id'], ['mensajes_entrantes.id'], name=op.f('fk_borrador_mensajes_mensaje_id_mensajes_entrantes')),
    sa.PrimaryKeyConstraint('borrador_id', 'mensaje_id', name=op.f('pk_borrador_mensajes')),
    sa.UniqueConstraint('mensaje_id', name=op.f('uq_borrador_mensajes_mensaje_id'))
    )
    op.create_table('codigos_vinculacion',
    sa.Column('codigo', sa.String(length=64), nullable=False),
    sa.Column('profesional_id', sa.Integer(), nullable=False),
    sa.Column('creado_por', sa.Integer(), nullable=True),
    sa.Column('creado_en', sa.DateTime(), nullable=False),
    sa.Column('expira_en', sa.DateTime(), nullable=False),
    sa.Column('usado_en', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['creado_por'], ['usuarios_web.id'], name=op.f('fk_codigos_vinculacion_creado_por_usuarios_web')),
    sa.ForeignKeyConstraint(['profesional_id'], ['profesionales.id'], name=op.f('fk_codigos_vinculacion_profesional_id_profesionales')),
    sa.PrimaryKeyConstraint('codigo', name=op.f('pk_codigos_vinculacion'))
    )
    op.create_table('extracciones',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('borrador_id', sa.Integer(), nullable=False),
    sa.Column('entrada_seudonimizada', sa.Text(), nullable=False),
    sa.Column('salida', sa.JSON(), nullable=False),
    sa.Column('proveedor', sa.String(length=30), nullable=False),
    sa.Column('modelo', sa.String(length=60), nullable=False),
    sa.Column('creado_en', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['borrador_id'], ['borradores_atencion.id'], name=op.f('fk_extracciones_borrador_id_borradores_atencion')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_extracciones'))
    )
    op.create_table('transcripciones',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('mensaje_id', sa.Integer(), nullable=False),
    sa.Column('texto', sa.Text(), nullable=False),
    sa.Column('segmentos', sa.JSON(), nullable=True),
    sa.Column('proveedor', sa.String(length=30), nullable=False),
    sa.Column('modelo', sa.String(length=60), nullable=False),
    sa.Column('duracion_seg', sa.Double(), nullable=True),
    sa.Column('creado_en', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['mensaje_id'], ['mensajes_entrantes.id'], name=op.f('fk_transcripciones_mensaje_id_mensajes_entrantes')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_transcripciones')),
    sa.UniqueConstraint('mensaje_id', name=op.f('uq_transcripciones_mensaje_id'))
    )

    if op.get_context().dialect.name == 'sqlite':
        for sql in TRIGGERS_AUDITORIA_SQLITE:
            op.execute(sql)


def downgrade() -> None:
    # Al borrar cada tabla se borran también sus triggers.
    op.drop_table('transcripciones')
    op.drop_table('extracciones')
    op.drop_table('codigos_vinculacion')
    op.drop_table('borrador_mensajes')
    with op.batch_alter_table('vinculos_canal', schema=None) as batch_op:
        batch_op.drop_index('uq_vinculos_canal_cuenta_activa', sqlite_where=sa.text('activo'), postgresql_where=sa.text('activo'))

    op.drop_table('vinculos_canal')
    op.drop_table('usuarios_web')
    with op.batch_alter_table('mensajes_entrantes', schema=None) as batch_op:
        batch_op.drop_index('ix_mensajes_entrantes_cola')

    op.drop_table('mensajes_entrantes')
    op.drop_table('borradores_atencion')
    op.drop_table('residentes')
    op.drop_table('profesionales')
    op.drop_table('eventos_auditoria')
