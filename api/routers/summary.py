from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from db.database import get_db
from db.models import Station
from api.schemas import SummaryItem, FuelStateOut

router = APIRouter(prefix="/api/summary", tags=["summary"])


@router.get("", response_model=list[SummaryItem])
async def get_summary(
    city: str | None = Query(None),
    brand: str | None = Query(None),
    grade: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    q = select(Station).options(selectinload(Station.fuel_states))
    if city:
        q = q.where(Station.city == city)
    if brand:
        q = q.where(Station.brand == brand)
    result = await db.execute(q)
    stations = result.scalars().unique().all()

    items = []
    for s in stations:
        fuel_states = s.fuel_states
        if grade:
            fuel_states = [fs for fs in fuel_states if fs.grade == grade]
        if not fuel_states:
            continue
        items.append(SummaryItem(
            station_alias=s.aliases[0] if s.aliases else "АЗС",
            brand=s.brand,
            fuel_states=[FuelStateOut.model_validate(fs) for fs in fuel_states],
        ))
    return items
