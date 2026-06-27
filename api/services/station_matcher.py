from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import Station

FUZZY_THRESHOLD = 75  # минимальный score для совпадения


async def find_or_create_station(
    session: AsyncSession,
    brand: str | None,
    alias: str | None,
    city: str | None,
    region: str | None,
    location,  # WKT string or None
) -> Station:
    if alias and city:
        result = await session.execute(
            select(Station).where(Station.city == city)
        )
        candidates = result.scalars().all()
        best_match = _find_best_match(alias, candidates)
        if best_match:
            if alias not in best_match.aliases:
                best_match.aliases = best_match.aliases + [alias]
            await session.commit()
            return best_match

    station = Station(
        brand=brand or "независимая",
        aliases=[alias] if alias else [],
        city=city,
        region=region,
        location=location,
    )
    session.add(station)
    await session.commit()
    await session.refresh(station)
    return station


def _find_best_match(alias: str, candidates: list[Station]) -> Station | None:
    best_score = 0
    best = None
    for station in candidates:
        for existing_alias in (station.aliases or []):
            score = fuzz.token_sort_ratio(alias.lower(), existing_alias.lower())
            if score > best_score:
                best_score = score
                best = station
    return best if best_score >= FUZZY_THRESHOLD else None
