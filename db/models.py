from sqlalchemy import (
    BigInteger, Boolean, Column, Float, ForeignKey,
    Integer, Numeric, String, Text, DateTime, func,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from geoalchemy2 import Geometry
import uuid

from db.database import Base


class User(Base):
    __tablename__ = "users"

    telegram_user_id = Column(BigInteger, primary_key=True)
    report_count = Column(Integer, default=0, nullable=False)
    first_seen_at = Column(DateTime(timezone=True), server_default=func.now())
    last_seen_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    is_banned = Column(Boolean, default=False, nullable=False)

    reports = relationship("Report", back_populates="user")


class Station(Base):
    __tablename__ = "stations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    brand = Column(String(100))
    aliases = Column(JSONB, default=list)
    address = Column(Text)
    location = Column(Geometry("POINT", srid=4326))
    city = Column(String(100))
    region = Column(String(100))
    last_report_at = Column(DateTime(timezone=True))
    report_count = Column(Integer, default=0)

    reports = relationship("Report", back_populates="station")
    fuel_states = relationship("StationFuelState", back_populates="station")


class Report(Base):
    __tablename__ = "reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    station_id = Column(UUID(as_uuid=True), ForeignKey("stations.id"), nullable=True)
    telegram_user_id = Column(
        BigInteger, ForeignKey("users.telegram_user_id"), nullable=False
    )
    raw_text = Column(Text)
    has_photo = Column(Boolean, default=False)
    fuels = Column(JSONB, default=list)
    user_location = Column(Geometry("POINT", srid=4326), nullable=True)
    queue_minutes = Column(Integer, nullable=True)
    confidence = Column(Float, nullable=True)
    parse_failed = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    source = Column(String(30))  # telegram_text | telegram_photo | telegram_voice

    station = relationship("Station", back_populates="reports")
    user = relationship("User", back_populates="reports")


class StationFuelState(Base):
    __tablename__ = "station_fuel_states"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    station_id = Column(
        UUID(as_uuid=True), ForeignKey("stations.id"), nullable=False
    )
    grade = Column(String(20), nullable=False)  # АИ-92, АИ-95, АИ-100, ДТ, ГАЗ
    available = Column(Boolean, nullable=False)
    price = Column(Numeric(8, 2), nullable=True)
    last_report_id = Column(UUID(as_uuid=True), ForeignKey("reports.id"))
    updated_at = Column(DateTime(timezone=True), server_default=func.now())

    station = relationship("Station", back_populates="fuel_states")
