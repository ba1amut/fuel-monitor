import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from api.services.geocoder import reverse_geocode


def _mock_client(json_data: dict):
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = json_data

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)

    mock_cls = MagicMock()
    mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)
    return mock_cls


@pytest.mark.asyncio
async def test_reverse_geocode_returns_city():
    with patch("api.services.geocoder.httpx.AsyncClient", _mock_client({"address": {"city": "Ессентуки"}})):
        assert await reverse_geocode(43.857, 44.041) == "Ессентуки"


@pytest.mark.asyncio
async def test_reverse_geocode_falls_back_to_town():
    with patch("api.services.geocoder.httpx.AsyncClient", _mock_client({"address": {"town": "Лермонтов"}})):
        assert await reverse_geocode(44.1, 42.9) == "Лермонтов"


@pytest.mark.asyncio
async def test_reverse_geocode_returns_none_when_no_locality():
    with patch("api.services.geocoder.httpx.AsyncClient", _mock_client({"address": {"country": "Россия"}})):
        assert await reverse_geocode(0.0, 0.0) is None
