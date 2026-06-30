from pydantic import BaseModel, ConfigDict, Field
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
    is_approximate: bool = False

    @classmethod
    def from_orm(cls, station) -> "StationOut":
        from api.services.city_centroids import get_centroid

        is_approximate = False
        loc = None
        if station.location is not None:
            try:
                shape = to_shape(station.location)
                loc = {"coordinates": list(shape.coords[0])}
            except Exception:
                loc = None
        if loc is None:
            centroid = get_centroid(station.city)
            if centroid:
                lat, lon = centroid
                loc = {"coordinates": [lon, lat]}
                is_approximate = True
        return cls(
            id=station.id,
            brand=station.brand,
            aliases=station.aliases or [],
            city=station.city,
            region=station.region,
            last_report_at=station.last_report_at,
            fuel_states=[FuelStateOut.model_validate(fs) for fs in station.fuel_states],
            location=loc,
            is_approximate=is_approximate,
        )


class NearbyStationOut(StationOut):
    distance_km: float

    @classmethod
    def from_nearby(cls, station, distance_km: float) -> "NearbyStationOut":
        base_dict = StationOut.from_orm(station).model_dump()
        return cls(**base_dict, distance_km=round(distance_km, 1))


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
    station_id: str | None = None


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


class LocationUpdateIn(BaseModel):
    lat: float = Field(..., ge=-90.0, le=90.0)
    lon: float = Field(..., ge=-180.0, le=180.0)
