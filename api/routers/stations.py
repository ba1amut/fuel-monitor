import logging
import os
from fastapi import APIRouter, Depends, Query, HTTPException, Header
from sqlalchemy import select, update, delete, cast, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from geoalchemy2 import Geography
from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from db.database import get_db
from db.models import Station, StationFuelState, Report
from api.schemas import StationOut, LocationUpdateIn, NearbyStationOut
from api.services.geocoder import reverse_geocode
from uuid import UUID

ADMIN_KEY = os.getenv("ADMIN_KEY", "")

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


@router.get("/nearby", response_model=list[NearbyStationOut])
async def nearby_stations(
    lat: float = Query(..., ge=-90.0, le=90.0),
    lon: float = Query(..., ge=-180.0, le=180.0),
    radius_km: float = Query(50.0, ge=0.1, le=200.0),
    limit: int = Query(10, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
):
    point_geo = cast(
        func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326), Geography
    )
    station_geo = cast(Station.location, Geography)
    distance_expr = func.ST_Distance(station_geo, point_geo).label("distance_m")
    q = (
        select(
            Station,
            distance_expr,
        )
        .options(selectinload(Station.fuel_states))
        .where(Station.location.isnot(None))
        .where(func.ST_DWithin(station_geo, point_geo, radius_km * 1000))  # Geography → metres
        .order_by(distance_expr)
        .limit(limit)
    )
    result = await db.execute(q)
    rows = result.all()
    return [
        NearbyStationOut.from_nearby(station, distance_m / 1000).model_dump()
        for station, distance_m in rows
    ]


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
    # Geocode outside DB transaction — avoids holding a connection during HTTP call
    geocoded_city = None
    try:
        geocoded_city = await reverse_geocode(body.lat, body.lon)
    except Exception:
        logging.warning(
            "reverse_geocode failed for (%s, %s)", body.lat, body.lon, exc_info=True
        )

    result = await db.execute(
        select(Station).options(selectinload(Station.fuel_states)).where(Station.id == station_id)
    )
    station = result.scalar_one_or_none()
    if station is None:
        raise HTTPException(status_code=404, detail="Station not found")
    station.location = from_shape(Point(body.lon, body.lat), srid=4326)
    if station.city is None and geocoded_city is not None:
        station.city = geocoded_city
    await db.commit()
    result = await db.execute(
        select(Station).options(selectinload(Station.fuel_states)).where(Station.id == station_id)
    )
    station = result.scalar_one()
    return StationOut.from_orm(station).model_dump()


@router.post("/{source_id}/merge-into/{target_id}", response_model=StationOut)
async def merge_stations(
    source_id: UUID,
    target_id: UUID,
    x_admin_key: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    if not ADMIN_KEY or x_admin_key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")
    if source_id == target_id:
        raise HTTPException(status_code=400, detail="source and target must differ")

    result = await db.execute(
        select(Station).options(selectinload(Station.fuel_states))
        .where(Station.id.in_([source_id, target_id]))
    )
    stations = {s.id: s for s in result.scalars().all()}
    if source_id not in stations:
        raise HTTPException(status_code=404, detail="Source station not found")
    if target_id not in stations:
        raise HTTPException(status_code=404, detail="Target station not found")

    source = stations[source_id]
    target = stations[target_id]

    # Merge aliases (deduplicated)
    merged_aliases = list(dict.fromkeys((target.aliases or []) + (source.aliases or [])))
    target.aliases = merged_aliases

    # Copy location from source if target has none
    if target.location is None and source.location is not None:
        target.location = source.location

    # Re-assign reports
    await db.execute(
        update(Report).where(Report.station_id == source_id).values(station_id=target_id)
    )

    # Merge fuel_states: upsert source states into target (keep newer by updated_at)
    for src_fs in source.fuel_states:
        existing = next((fs for fs in target.fuel_states if fs.grade == src_fs.grade), None)
        if existing is None:
            src_fs.station_id = target_id
        elif src_fs.updated_at and existing.updated_at and src_fs.updated_at > existing.updated_at:
            existing.available = src_fs.available
            existing.price = src_fs.price
            existing.updated_at = src_fs.updated_at
            await db.execute(delete(StationFuelState).where(StationFuelState.id == src_fs.id))
        else:
            await db.execute(delete(StationFuelState).where(StationFuelState.id == src_fs.id))

    await db.execute(delete(Station).where(Station.id == source_id))
    await db.commit()

    result = await db.execute(
        select(Station).options(selectinload(Station.fuel_states)).where(Station.id == target_id)
    )
    return StationOut.from_orm(result.scalar_one()).model_dump()
