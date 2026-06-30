import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.geocoder import reverse_geocode
from api.services.parser import FuelItem, ParsedReport, parse_photo, parse_text
from api.services.speechkit import transcribe_voice as _transcribe
from api.services.station_matcher import find_or_create_station
from db.models import Report, Station, StationFuelState, User


@dataclass
class ProcessResult:
    success: bool
    station_name: str | None
    fuels: list[FuelItem] = field(default_factory=list)
    parse_failed: bool = False
    message: str = ""
    station_id: str | None = None


async def process_report(
    session: AsyncSession,
    telegram_user_id: int,
    text: str | None = None,
    image_bytes: bytes | None = None,
    voice_bytes: bytes | None = None,
    user_lat: float | None = None,
    user_lon: float | None = None,
) -> ProcessResult:
    # --- Phase 1: HTTP only — no DB connection held ---

    source = "telegram_text"
    raw_text = text or ""

    if voice_bytes:
        source = "telegram_voice"
        raw_text = await _transcribe(voice_bytes)
        parsed = await parse_text(raw_text)
    elif image_bytes:
        source = "telegram_photo"
        parsed = await parse_photo(image_bytes)
        raw_text = "[фото]"
    else:
        parsed = await parse_text(raw_text)

    location = None
    city = parsed.city
    if user_lat is not None and user_lon is not None:
        location = f"SRID=4326;POINT({user_lon} {user_lat})"
        if not city:
            try:
                city = await reverse_geocode(user_lat, user_lon)
            except Exception:
                logging.warning(
                    "reverse_geocode failed for (%s, %s)", user_lat, user_lon,
                    exc_info=True,
                )

    # --- Phase 2: single DB transaction ---

    await _upsert_user(session, telegram_user_id)

    station = None
    if not parsed.parse_failed:
        station = await find_or_create_station(
            session,
            brand=parsed.brand,
            alias=parsed.station_alias,
            city=city,
            region=None,
            location=location,
        )

    report = Report(
        station_id=station.id if station else None,
        telegram_user_id=telegram_user_id,
        raw_text=raw_text,
        has_photo=image_bytes is not None,
        fuels=[{"grade": f.grade, "available": f.available, "price": f.price} for f in parsed.fuels],
        user_location=location,
        confidence=parsed.confidence,
        parse_failed=parsed.parse_failed,
        source=source,
    )
    session.add(report)
    await session.flush()
    await session.refresh(report)

    if station and not parsed.parse_failed:
        await _upsert_fuel_states(session, station.id, parsed.fuels, report.id)
        await _update_station_stats(session, station)

    await session.commit()

    station_name = (station.aliases[0] if station and station.aliases else None)
    return ProcessResult(
        success=True,
        station_name=station_name,
        fuels=parsed.fuels,
        parse_failed=parsed.parse_failed,
        station_id=str(station.id) if station else None,
    )


async def _upsert_user(session: AsyncSession, telegram_user_id: int):
    stmt = pg_insert(User).values(
        telegram_user_id=telegram_user_id,
        report_count=1,
        first_seen_at=datetime.now(timezone.utc),
        last_seen_at=datetime.now(timezone.utc),
    ).on_conflict_do_update(
        index_elements=["telegram_user_id"],
        set_={
            "report_count": User.report_count + 1,
            "last_seen_at": datetime.now(timezone.utc),
        },
    )
    await session.execute(stmt)


async def _upsert_fuel_states(session: AsyncSession, station_id, fuels: list[FuelItem], report_id):
    now = datetime.now(timezone.utc)
    for fuel in fuels:
        stmt = pg_insert(StationFuelState).values(
            id=uuid.uuid4(),
            station_id=station_id,
            grade=fuel.grade,
            available=fuel.available,
            price=fuel.price,
            last_report_id=report_id,
            updated_at=now,
        ).on_conflict_do_update(
            index_elements=["station_id", "grade"],
            set_={"available": fuel.available, "price": fuel.price,
                  "last_report_id": report_id, "updated_at": now},
        )
        await session.execute(stmt)


async def _update_station_stats(session: AsyncSession, station: Station):
    station.last_report_at = datetime.now(timezone.utc)
    station.report_count = (station.report_count or 0) + 1
