"""empty message

Revision ID: 47caa8c69f2c
Revises: 7d120134b41
Create Date: 2015-05-04 16:30:55.218865

"""

# revision identifiers, used by Alembic.
revision = '47caa8c69f2c'
down_revision = '7d120134b41'

from alembic import op
import sqlalchemy as sa


def upgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.create_table('groupmember_association',
    sa.Column('group_id', sa.String(length=32), nullable=False),
    sa.Column('persona_id', sa.String(length=32), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=True),
    sa.Column('created', sa.DateTime(), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('active', sa.Boolean(), nullable=True),
    sa.Column('last_seen', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['group_id'], ['group.id'], ),
    sa.ForeignKeyConstraint(['persona_id'], ['persona.id'], ),
    sa.PrimaryKeyConstraint('group_id', 'persona_id')
    )
    op.create_foreign_key('fk_author_id', 'starmap', 'persona', ['author_id'], ['id'])
    op.create_foreign_key('fk_author_id', 'vesicle', 'persona', ['author_id'], ['id'])
    ### end Alembic commands ###


def downgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint('fk_author_id', 'vesicle', type_='foreignkey')
    op.drop_constraint('fk_author_id', 'starmap', type_='foreignkey')
    op.drop_table('groupmember_association')
    ### end Alembic commands ###
