"""Tests for PATCH /api/stations/{station_id}/location endpoint."""
import pytest
import uuid
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, MagicMock, patch
from api.main import app
from db.database import get_db


# --- Dependency override helpers ---

async def _override_get_db_none():
    """Session whose execute() returns empty result — simulates station not found."""
    sess = AsyncMock()
    empty_result = MagicMock()
    empty_result.scalar_one_or_none = MagicMock(return_value=None)
    sess.execute = AsyncMock(return_value=empty_result)
    yield sess


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_patch_station_location_not_found():
    """PATCH with valid payload for non-existent station_id returns 404."""
    app.dependency_overrides[get_db] = _override_get_db_none
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.patch(
            f"/api/stations/{uuid.uuid4()}/location",
            json={"lat": 55.75, "lon": 37.61},
        )
    assert r.status_code == 404
    assert r.json()["detail"] == "Station not found"


@pytest.mark.asyncio
async def test_patch_station_location_validation_lat_too_high():
    """PATCH with lat > 90 returns 422 (Pydantic validation)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.patch(
            f"/api/stations/{uuid.uuid4()}/location",
            json={"lat": 999.0, "lon": 37.61},
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_patch_station_location_validation_lon_out_of_range():
    """PATCH with lon > 180 returns 422 (Pydantic validation)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.patch(
            f"/api/stations/{uuid.uuid4()}/location",
            json={"lat": 55.75, "lon": 999.0},
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_patch_station_location_validation_missing_fields():
    """PATCH with missing lat/lon returns 422."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.patch(
            f"/api/stations/{uuid.uuid4()}/location",
            json={},
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_patch_station_location_success():
    """PATCH with valid station returns 200 and StationOut."""
    station_id = uuid.uuid4()

    # Build a mock station object with all required attributes for StationOut.from_orm
    mock_station = MagicMock()
    mock_station.id = station_id
    mock_station.brand = "Лукойл"
    mock_station.aliases = ["Лукойл Центральная"]
    mock_station.city = "Казань"
    mock_station.region = "Татарстан"
    mock_station.last_report_at = None
    mock_station.fuel_states = []
    mock_station.location = None  # after setting it will stay None in mock, but from_orm handles that

    async def _override_get_db_found():
        sess = AsyncMock()
        found_result = MagicMock()
        found_result.scalar_one_or_none = MagicMock(return_value=mock_station)
        found_result.scalar_one = MagicMock(return_value=mock_station)
        sess.execute = AsyncMock(return_value=found_result)
        sess.commit = AsyncMock()
        yield sess

    app.dependency_overrides[get_db] = _override_get_db_found

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.patch(
            f"/api/stations/{station_id}/location",
            json={"lat": 55.75, "lon": 37.61},
        )

    assert r.status_code == 200
    body = r.json()
    assert body["id"] == str(station_id)
    assert body["brand"] == "Лукойл"


@pytest.mark.asyncio
async def test_nearby_stations_lat_validation():
    from api.main import app
    from httpx import AsyncClient, ASGITransport
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(
            "/api/stations/nearby",
            params={"lat": 999.0, "lon": 37.6, "radius_km": 10},
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_nearby_stations_no_results():
    from api.main import app
    from db.database import get_db
    from httpx import AsyncClient, ASGITransport
    from unittest.mock import AsyncMock, MagicMock

    async def _override():
        sess = AsyncMock()
        mock_result = MagicMock()
        mock_result.all = MagicMock(return_value=[])
        sess.execute = AsyncMock(return_value=mock_result)
        yield sess

    app.dependency_overrides[get_db] = _override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get(
                "/api/stations/nearby",
                params={"lat": 44.049, "lon": 42.861, "radius_km": 50},
            )
        assert r.status_code == 200
        assert r.json() == []
    finally:
        app.dependency_overrides.pop(get_db, None)
