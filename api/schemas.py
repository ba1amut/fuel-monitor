from pydantic import BaseModel, ConfigDict
from datetime import datetime
from uuid import UUID
from geoalchemy2.shape import to_shape


class FuelStateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    grade: str
    available: bool
    price: float | None
    updated_at: datetime


class StationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    brand: str | None
    aliases: list[str]
    city: str | None
    region: str | None
    last_report_at: datetime | None
    fuel_states: list[FuelStateOut] = []
    location: dict | None = None

    @classmethod
    def from_orm(cls, station) -> "StationOut":
        loc = None
        if station.location is not None:
            try:
                shape = to_shape(station.location)
                loc = {"coordinates": list(shape.coords[0])}
            except Exception:
                loc = None
        return cls(
            id=station.id,
            brand=station.brand,
            aliases=station.aliases or [],
            city=station.city,
            region=station.region,
            last_report_at=station.last_report_at,
            fuel_states=[FuelStateOut.model_validate(fs) for fs in station.fuel_states],
            location=loc,
        )


class ReportIn(BaseModel):
    telegram_user_id: int
    text: str | None = None
    user_lat: float | None = None
    user_lon: float | None = None


class ReportResult(BaseModel):
    success: bool
    station_name: str | None
    parse_failed: bool
    fuels: list[dict] = []


class HeatmapRegion(BaseModel):
    region: str
    total: int
    deficit: int
    deficit_ratio: float


class SummaryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    station_alias: str
    brand: str | None
    fuel_states: list[FuelStateOut]
