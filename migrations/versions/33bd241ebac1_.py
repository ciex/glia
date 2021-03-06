"""empty message

Revision ID: 33bd241ebac1
Revises: 11cea14fbfa3
Create Date: 2015-06-17 12:50:56.234860

"""

# revision identifiers, used by Alembic.
revision = '33bd241ebac1'
down_revision = '11cea14fbfa3'

from alembic import op
import sqlalchemy as sa


def upgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint(u'percept_association_author_id_fkey', 'percept_association', type_='foreignkey')
    op.create_foreign_key("percept_association_author_id_fkey", 'percept_association', 'identity', ['author_id'], ['id'])
    ### end Alembic commands ###


def downgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint("percept_association_author_id_fkey", 'percept_association', type_='foreignkey')
    op.create_foreign_key(u'percept_association_author_id_fkey', 'percept_association', 'persona', ['author_id'], ['id'])
    ### end Alembic commands ###
