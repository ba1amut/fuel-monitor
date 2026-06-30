import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from api.services.station_matcher import find_or_create_station
from db.models import Station


@pytest.mark.asyncio
async def test_find_existing_station_by_alias():
    existing = Station(
        brand="Лукойл",
        aliases=["Лукойл на Ленинском", "АЗС у метро"],
        city="Москва",
    )
    mock_session = MagicMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [existing]
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()

    result = await find_or_create_station(
        mock_session, brand="Лукойл", alias="Лукойл на ленинском",
        city="Москва", region=None, location=None
    )
    assert result is existing


@pytest.mark.asyncio
async def test_create_new_station_when_no_match():
    mock_session = MagicMock()
    empty_result = MagicMock()
    empty_result.scalars.return_value.all.return_value = []
    # execute called twice: city-filtered, then cityless
    mock_session.execute = AsyncMock(return_value=empty_result)
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock()

    result = await find_or_create_station(
        mock_session, brand="Роснефть", alias="новая АЗС",
        city="Казань", region="Татарстан", location=None
    )
    assert result.brand == "Роснефть"
    assert "новая АЗС" in result.aliases
    mock_session.add.assert_called_once()


@pytest.mark.asyncio
async def test_find_cityless_station_and_backfill_city():
    """Station created without city must be found and updated when city is known."""
    existing = Station(brand="Октан", aliases=["Октан маркет №15"], city=None)
    empty_result = MagicMock()
    empty_result.scalars.return_value.all.return_value = []
    cityless_result = MagicMock()
    cityless_result.scalars.return_value.all.return_value = [existing]

    mock_session = MagicMock()
    mock_session.execute = AsyncMock(side_effect=[empty_result, cityless_result])
    mock_session.commit = AsyncMock()

    result = await find_or_create_station(
        mock_session, brand="Октан", alias="Октан маркет",
        city="Ессентуки", region=None, location=None
    )
    assert result is existing
    assert result.city == "Ессентуки"


@pytest.mark.asyncio
async def test_create_station_geocodes_city_from_gps():
    """When location provided but city is None, city is resolved via reverse_geocode."""
    mock_session = MagicMock()
    empty_result = MagicMock()
    empty_result.scalars.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=empty_result)
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock()

    with patch(
        "api.services.station_matcher.reverse_geocode", new_callable=AsyncMock
    ) as mock_geo:
        mock_geo.return_value = "Ессентуки"
        result = await find_or_create_station(
            mock_session, brand="независимая", alias="АЗС у дороги",
            city=None, region=None, location="SRID=4326;POINT(44.0413 43.8573)"
        )

    assert result.city == "Ессентуки"
    mock_geo.assert_awaited_once_with(43.8573, 44.0413)
