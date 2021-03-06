"""Add notifications

Revision ID: 56d3b97959b7
Revises: 53c66ed4223b
Create Date: 2015-06-15 22:20:38.330109

"""

# revision identifiers, used by Alembic.
revision = '56d3b97959b7'
down_revision = '53c66ed4223b'

from alembic import op
import sqlalchemy as sa


def upgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.create_table('notification',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('text', sa.Text(), nullable=True),
    sa.Column('url', sa.Text(), nullable=True),
    sa.Column('source', sa.String(length=128), nullable=True),
    sa.Column('domain', sa.String(length=128), nullable=True),
    sa.Column('unread', sa.Boolean(), nullable=True),
    sa.Column('created', sa.DateTime(), nullable=True),
    sa.Column('modified', sa.DateTime(), nullable=True),
    sa.Column('recipient_id', sa.String(length=32), nullable=True),
    sa.ForeignKeyConstraint(['recipient_id'], ['identity.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    ### end Alembic commands ###


def downgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('notification')
    ### end Alembic commands ###
