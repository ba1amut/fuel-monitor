import pytest
from unittest.mock import AsyncMock, patch

from api.services.parser import parse_text, parse_photo, ParsedReport, FuelItem, _parse_response


@pytest.mark.asyncio
async def test_parse_text_happy_path():
    mock_response = (
        '{"station_alias": "Лукойл на Ленинском", "brand": "Лукойл", '
        '"fuels": [{"grade": "АИ-95", "available": true, "price": 79.0}], '
        '"confidence": 0.95}'
    )
    with patch("api.services.parser._call_yandex_gpt", new_callable=AsyncMock) as mock_gpt:
        mock_gpt.return_value = mock_response
        result = await parse_text("Лукойл на Ленинском, АИ-95 есть, 79 руб")

    assert isinstance(result, ParsedReport)
    assert result.brand == "Лукойл"
    assert result.station_alias == "Лукойл на Ленинском"
    assert len(result.fuels) == 1
    assert result.fuels[0].grade == "АИ-95"
    assert result.fuels[0].available is True
    assert result.fuels[0].price == 79.0
    assert result.confidence == 0.95
    assert result.parse_failed is False


@pytest.mark.asyncio
async def test_parse_text_low_confidence():
    mock_response = '{"station_alias": null, "brand": null, "fuels": [], "confidence": 0.2}'
    with patch("api.services.parser._call_yandex_gpt", new_callable=AsyncMock) as mock_gpt:
        mock_gpt.return_value = mock_response
        result = await parse_text("непонятное сообщение")

    assert result.parse_failed is True
    assert result.confidence == 0.2


@pytest.mark.asyncio
async def test_parse_photo_deepseek_success():
    mock_response = (
        '{"station_alias": "Октан у озера", "brand": "независимая", "city": "Ессентуки", '
        '"fuels": [{"grade": "АИ-95", "available": true, "price": 79.5}], '
        '"confidence": 0.9}'
    )
    with patch("api.services.parser._call_deepseek_vision", new_callable=AsyncMock) as mock_ds:
        mock_ds.return_value = mock_response
        result = await parse_photo(b"fake_image_bytes")
    assert result.city == "Ессентуки"
    assert not result.parse_failed
    assert result.fuels[0].grade == "АИ-95"
    assert result.fuels[0].price == 79.5


@pytest.mark.asyncio
async def test_parse_photo_deepseek_low_confidence():
    mock_response = (
        '{"station_alias": null, "brand": null, "city": null, "fuels": [], "confidence": 0.2}'
    )
    with patch("api.services.parser._call_deepseek_vision", new_callable=AsyncMock) as mock_ds:
        mock_ds.return_value = mock_response
        result = await parse_photo(b"fake_image_bytes")
    assert result.parse_failed


def test_parse_response_strips_code_fences():
    raw = '```json\n{"station_alias": "test", "brand": null, "fuels": [], "confidence": 0.9}\n```'
    result = _parse_response(raw)
    assert not result.parse_failed
    assert result.confidence == 0.9


def test_parse_response_strips_plain_fences():
    raw = '```\n{"station_alias": null, "brand": null, "fuels": [], "confidence": 0.8}\n```'
    result = _parse_response(raw)
    assert not result.parse_failed
    assert result.confidence == 0.8


@pytest.mark.asyncio
async def test_parse_text_extracts_city():
    mock_response = (
        '{"station_alias": "Октан около озера", "brand": "независимая", '
        '"city": "Ессентуки", '
        '"fuels": [{"grade": "АИ-95", "available": true, "price": 79.5}], '
        '"confidence": 0.9}'
    )
    with patch("api.services.parser._call_yandex_gpt", new_callable=AsyncMock) as mock_gpt:
        mock_gpt.return_value = mock_response
        result = await parse_text("Ессентуки АЗС октан около озера: 95 - 79.5 руб")
    assert result.city == "Ессентуки"
    assert not result.parse_failed


def test_parse_response_city_none_when_missing():
    raw = '{"station_alias": "Лукойл", "brand": "Лукойл", "fuels": [], "confidence": 0.8}'
    result = _parse_response(raw)
    assert result.city is None
    assert not result.parse_failed
