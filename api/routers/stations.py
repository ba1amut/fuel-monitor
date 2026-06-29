from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from db.database import get_db
from db.models import Station, StationFuelState
from api.schemas import StationOut, LocationUpdateIn
from uuid import UUID

router = APIRouter(prefix="/api/stations", tags=["stations"])


@router.get("", response_model=list[StationOut])
async def list_stations(
    brand: str | None = Query(None),
    grade: str | None = Query(None),
    city: str | None = Query(None),
    region: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    q = select(Station).options(selectinload(Station.fuel_states))
    if brand:
        q = q.where(Station.brand == brand)
    if city:
        q = q.where(Station.city == city)
    if region:
        q = q.where(Station.region == region)
    if grade:
        q = q.join(StationFuelState).where(StationFuelState.grade == grade)
    result = await db.execute(q)
    stations = result.scalars().unique().all()

    # Filter fuel_states in-memory when grade filter provided to avoid leaking other grades
    if grade:
        for s in stations:
            s.fuel_states = [fs for fs in s.fuel_states if fs.grade == grade]

    return [StationOut.from_orm(s).model_dump() for s in stations]


@router.get("/{station_id}", response_model=StationOut)
async def get_station(station_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Station).options(selectinload(Station.fuel_states)).where(Station.id == station_id)
    )
    station = result.scalar_one_or_none()
    if station is None:
        raise HTTPException(status_code=404, detail="Station not found")
    return StationOut.from_orm(station).model_dump()


@router.patch("/{station_id}/location", response_model=StationOut)
async def update_station_location(
    station_id: UUID,
    body: LocationUpdateIn,
    db: AsyncSession = Depends(get_db),
):
    station = await db.get(Station, station_id)
    if station is None:
        raise HTTPException(status_code=404, detail="Station not found")
    station.location = from_shape(Point(body.lon, body.lat), srid=4326)
    await db.commit()
    await db.refresh(station)
    return StationOut.from_orm(station)
