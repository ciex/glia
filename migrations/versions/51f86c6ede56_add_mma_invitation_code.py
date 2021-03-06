"""Add mma.invitation_code

Revision ID: 51f86c6ede56
Revises: 3c3bc3d8d8bf
Create Date: 2015-06-28 15:33:21.326354

"""

# revision identifiers, used by Alembic.
revision = '51f86c6ede56'
down_revision = '3c3bc3d8d8bf'

from alembic import op
import sqlalchemy as sa


def upgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.add_column('movementmember_association', sa.Column('invitation_code', sa.String(length=32), nullable=True))
    ### end Alembic commands ###


def downgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('movementmember_association', 'invitation_code')
    ### end Alembic commands ###
