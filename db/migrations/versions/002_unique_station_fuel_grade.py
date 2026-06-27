"""unique index station_fuel_states

Revision ID: 002
Revises: 001
Create Date: 2026-06-27 00:01:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_station_fuel_grade",
        "station_fuel_states",
        ["station_id", "grade"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_station_fuel_grade", "station_fuel_states")
