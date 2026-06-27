from pydantic import BaseModel, model_validator
from datetime import datetime
from uuid import UUID


class FuelStateOut(BaseModel):
    grade: str
    available: bool
    price: float | None
    updated_at: datetime

    class Config:
        from_attributes = True


class StationOut(BaseModel):
    id: UUID
    brand: str | None
    aliases: list[str]
    city: str | None
    region: str | None
    last_report_at: datetime | None
    fuel_states: list[FuelStateOut] = []
    location: dict | None = None

    class Config:
        from_attributes = True

    @model_validator(mode="before")
    @classmethod
    def extract_location(cls, data):
        # Handle ORM object — extract location geometry into dict
        if hasattr(data, "__dict__") or hasattr(data, "location"):
            raw_loc = getattr(data, "location", None)
            if raw_loc is not None:
                try:
                    from geoalchemy2.shape import to_shape
                    shape = to_shape(raw_loc)
                    coords = list(shape.coords)[0]  # (lon, lat)
                    # Inject into the data dict for pydantic to pick up
                    # We need to return a dict-compatible representation
                    # Since pydantic v2 "before" validators on ORM objects:
                    # convert to dict manually
                    pass
                except Exception:
                    pass
        return data

    @classmethod
    def model_validate(cls, obj, *args, **kwargs):
        """Override to handle PostGIS geometry serialization."""
        instance = super().model_validate(obj, *args, **kwargs)
        # Extract location from ORM object after base validation
        if hasattr(obj, "location") and obj.location is not None:
            try:
                from geoalchemy2.shape import to_shape
                shape = to_shape(obj.location)
                coords = list(shape.coords)[0]  # (lon, lat)
                instance.location = {"coordinates": list(coords)}
            except Exception:
                instance.location = None
        return instance


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
    station_alias: str
    brand: str | None
    fuel_states: list[FuelStateOut]
