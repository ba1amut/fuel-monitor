from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, case, and_
from sqlalchemy.ext.asyncio import AsyncSession
from db.database import get_db
from db.models import Station, StationFuelState
from api.schemas import HeatmapRegion

router = APIRouter(prefix="/api/heatmap", tags=["heatmap"])


@router.get("", response_model=list[HeatmapRegion])
async def get_heatmap(
    brand: str | None = Query(None),
    grade: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    # Build join condition — move grade filter into JOIN to keep outer join semantics
    join_cond = StationFuelState.station_id == Station.id
    if grade:
        join_cond = and_(join_cond, StationFuelState.grade == grade)

    q = (
        select(
            Station.region,
            func.count(func.distinct(Station.id)).label("total"),
            func.sum(case((StationFuelState.available == False, 1), else_=0)).label("deficit"),
        )
        .join(StationFuelState, join_cond, isouter=True)
        .group_by(Station.region)
    )
    if brand:
        q = q.where(Station.brand == brand)

    result = await db.execute(q)
    rows = result.all()
    return [
        HeatmapRegion(
            region=r.region or "Неизвестно",
            total=r.total,
            deficit=r.deficit or 0,
            deficit_ratio=round((r.deficit or 0) / r.total, 2) if r.total else 0,
        )
        for r in rows
    ]
