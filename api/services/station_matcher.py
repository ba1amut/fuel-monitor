import logging
import re

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.geocoder import reverse_geocode
from db.models import Station

FUZZY_THRESHOLD = 75  # минимальный score для совпадения


def _parse_wkt_point(wkt: str) -> tuple[float, float] | None:
    """'SRID=4326;POINT(lon lat)' → (lat, lon)"""
    m = re.search(r'POINT\(([0-9.\-]+)\s+([0-9.\-]+)\)', wkt or "")
    if not m:
        return None
    return float(m.group(2)), float(m.group(1))


async def find_or_create_station(
    session: AsyncSession,
    brand: str | None,
    alias: str | None,
    city: str | None,
    region: str | None,
    location,  # WKT string or None
) -> Station:
    if alias:
        # Step 1: search among stations with the same city
        if city:
            result = await session.execute(
                select(Station).where(Station.city == city)
            )
            best_match = _find_best_match(alias, result.scalars().all())
            if best_match:
                if alias not in best_match.aliases:
                    best_match.aliases = best_match.aliases + [alias]
                await session.commit()
                return best_match

        # Step 2: fallback — search stations without city; backfill city on match
        result = await session.execute(
            select(Station).where(Station.city.is_(None))
        )
        best_match = _find_best_match(alias, result.scalars().all())
        if best_match:
            if alias not in best_match.aliases:
                best_match.aliases = best_match.aliases + [alias]
            if city:
                best_match.city = city
            await session.commit()
            return best_match

    if not city and location:
        coords = _parse_wkt_point(location)
        if coords:
            try:
                city = await reverse_geocode(*coords)
            except Exception:
                logging.warning("reverse_geocode failed for location %s", location)

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
