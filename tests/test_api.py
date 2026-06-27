import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock, MagicMock
from api.main import app
from api.services.report_processor import ProcessResult
from api.services.parser import FuelItem
from db.database import get_db


# --- Dependency override helpers ---

async def _override_get_db():
    """Dummy DB session — never touches a real database."""
    yield MagicMock()


@pytest.fixture(autouse=True)
def override_db():
    app.dependency_overrides[get_db] = _override_get_db
    yield
    app.dependency_overrides.clear()


def _make_db_session(execute_return_value):
    """Build an async DB session mock where execute() returns the given value."""
    async def _db():
        sess = MagicMock()
        sess.execute = AsyncMock(return_value=execute_return_value)
        yield sess
    return _db


# --- /api/reports ---

@pytest.mark.asyncio
async def test_post_report_text_success():
    mock_result = ProcessResult(
        success=True,
        station_name="Лукойл",
        fuels=[FuelItem(grade="АИ-95", available=True, price=79.0)],
        parse_failed=False,
    )
    with patch("api.routers.reports.process_report", AsyncMock(return_value=mock_result)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(
                "/api/reports",
                data={"telegram_user_id": "123", "text": "Лукойл АИ-95 79р"},
            )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["station_name"] == "Лукойл"
    assert body["parse_failed"] is False
    assert len(body["fuels"]) == 1
    assert body["fuels"][0]["grade"] == "АИ-95"


@pytest.mark.asyncio
async def test_post_report_parse_failed():
    mock_result = ProcessResult(
        success=True,
        station_name=None,
        fuels=[],
        parse_failed=True,
    )
    with patch("api.routers.reports.process_report", AsyncMock(return_value=mock_result)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(
                "/api/reports",
                data={"telegram_user_id": "999", "text": "непонятный текст"},
            )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["parse_failed"] is True
    assert body["station_name"] is None
    assert body["fuels"] == []


@pytest.mark.asyncio
async def test_post_report_missing_telegram_user_id():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/reports", data={"text": "тест"})
    assert r.status_code == 422


# --- /api/stations ---

@pytest.mark.asyncio
async def test_list_stations_empty():
    # result.scalars().unique().all() == []
    execute_result = MagicMock()
    execute_result.scalars.return_value.unique.return_value.all.return_value = []

    app.dependency_overrides[get_db] = _make_db_session(execute_result)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/stations")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_get_station_not_found():
    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = None

    app.dependency_overrides[get_db] = _make_db_session(execute_result)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/stations/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404


# --- /api/heatmap ---

@pytest.mark.asyncio
async def test_get_heatmap_empty():
    execute_result = MagicMock()
    execute_result.all.return_value = []

    app.dependency_overrides[get_db] = _make_db_session(execute_result)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/heatmap")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_get_heatmap_with_data():
    row = MagicMock()
    row.region = "Татарстан"
    row.total = 10
    row.deficit = 3

    execute_result = MagicMock()
    execute_result.all.return_value = [row]

    app.dependency_overrides[get_db] = _make_db_session(execute_result)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/heatmap")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["region"] == "Татарстан"
    assert data[0]["total"] == 10
    assert data[0]["deficit"] == 3
    assert data[0]["deficit_ratio"] == 0.3


# --- /api/summary ---

@pytest.mark.asyncio
async def test_get_summary_empty():
    execute_result = MagicMock()
    execute_result.scalars.return_value.unique.return_value.all.return_value = []

    app.dependency_overrides[get_db] = _make_db_session(execute_result)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/summary")
    assert r.status_code == 200
    assert r.json() == []
