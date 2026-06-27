from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from db.database import get_db
from db.models import Station, StationFuelState
from api.schemas import StationOut
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
    return [StationOut.model_validate(s) for s in stations]


@router.get("/{station_id}", response_model=StationOut)
async def get_station(station_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Station).options(selectinload(Station.fuel_states)).where(Station.id == station_id)
    )
    station = result.scalar_one_or_none()
    if station is None:
        raise HTTPException(status_code=404, detail="Station not found")
    return StationOut.model_validate(station)
