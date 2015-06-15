"""Add Mention

Revision ID: 217b54d2d8e1
Revises: 79c14eaf5c9
Create Date: 2015-05-21 11:00:26.589664

"""

# revision identifiers, used by Alembic.
revision = '217b54d2d8e1'
down_revision = '79c14eaf5c9'

from alembic import op
import sqlalchemy as sa


def upgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.create_table('mention',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('identity_id', sa.String(length=32), nullable=True),
    sa.Column('text', sa.String(length=80), nullable=True),
    sa.ForeignKeyConstraint(['id'], ['planet.id'], ),
    sa.ForeignKeyConstraint(['identity_id'], ['identity.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_foreign_key("fk_id_blog", 'identity', 'starmap', ['blog_id'], ['id'])
    ### end Alembic commands ###


def downgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint("fk_id_blog", 'identity', type_='foreignkey')
    op.drop_table('mention')
    ### end Alembic commands ###