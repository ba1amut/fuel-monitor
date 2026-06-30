"""performance indexes — city, brand, region, location (gist), reports.station_id

Revision ID: 003
Revises: 002
Create Date: 2026-07-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_stations_city", "stations", ["city"])
    op.create_index("ix_stations_brand", "stations", ["brand"])
    op.create_index("ix_stations_region", "stations", ["region"])
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_stations_location_gist "
        "ON stations USING gist (location)"
    )
    op.create_index("ix_reports_station_id", "reports", ["station_id"])


def downgrade() -> None:
    op.drop_index("ix_reports_station_id", table_name="reports")
    op.execute("DROP INDEX IF EXISTS ix_stations_location_gist")
    op.drop_index("ix_stations_region", table_name="stations")
    op.drop_index("ix_stations_brand", table_name="stations")
    op.drop_index("ix_stations_city", table_name="stations")
