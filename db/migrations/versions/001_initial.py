"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-06-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import geoalchemy2

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### Create PostGIS extension (required for Geometry columns) ###
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    # ### users ###
    op.create_table(
        "users",
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("report_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("is_banned", sa.Boolean(), nullable=False, server_default="false"),
        sa.PrimaryKeyConstraint("telegram_user_id"),
    )

    # ### stations ###
    op.create_table(
        "stations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("brand", sa.String(length=100), nullable=True),
        sa.Column("aliases", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column(
            "location",
            geoalchemy2.types.Geometry(geometry_type="POINT", srid=4326),
            nullable=True,
        ),
        sa.Column("city", sa.String(length=100), nullable=True),
        sa.Column("region", sa.String(length=100), nullable=True),
        sa.Column("last_report_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("report_count", sa.Integer(), nullable=True, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
    )

    # ### reports ###
    op.create_table(
        "reports",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("station_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("has_photo", sa.Boolean(), nullable=True, server_default="false"),
        sa.Column("fuels", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "user_location",
            geoalchemy2.types.Geometry(geometry_type="POINT", srid=4326),
            nullable=True,
        ),
        sa.Column("queue_minutes", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("parse_failed", sa.Boolean(), nullable=True, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("source", sa.String(length=30), nullable=True),
        sa.ForeignKeyConstraint(["station_id"], ["stations.id"]),
        sa.ForeignKeyConstraint(["telegram_user_id"], ["users.telegram_user_id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # ### station_fuel_states ###
    op.create_table(
        "station_fuel_states",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("station_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("grade", sa.String(length=20), nullable=False),
        sa.Column("available", sa.Boolean(), nullable=False),
        sa.Column("price", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("last_report_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["last_report_id"], ["reports.id"]),
        sa.ForeignKeyConstraint(["station_id"], ["stations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("station_fuel_states")
    op.drop_table("reports")
    op.drop_table("stations")
    op.drop_table("users")
    op.execute("DROP EXTENSION IF EXISTS postgis")
