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
async def test_parse_photo_two_step_pipeline():
    """parse_photo must call OCR first, then GPT with the extracted text."""
    ocr_text = "АИ-92  56.90\nАИ-95  61.50\nДТ     65.00"
    gpt_response = (
        '{"station_alias": null, "brand": null, '
        '"fuels": ['
        '{"grade": "АИ-92", "available": true, "price": 56.90},'
        '{"grade": "АИ-95", "available": true, "price": 61.50},'
        '{"grade": "ДТ", "available": true, "price": 65.00}'
        '], "confidence": 0.9}'
    )
    fake_image = b"\xff\xd8\xff"  # minimal JPEG magic bytes

    with (
        patch("api.services.parser._call_ocr", new_callable=AsyncMock) as mock_ocr,
        patch("api.services.parser._call_yandex_gpt", new_callable=AsyncMock) as mock_gpt,
    ):
        mock_ocr.return_value = ocr_text
        mock_gpt.return_value = gpt_response

        result = await parse_photo(fake_image)

        # OCR must be called exactly once with the raw image bytes
        mock_ocr.assert_awaited_once_with(fake_image)
        # GPT must be called exactly once (with OCR text embedded in messages)
        mock_gpt.assert_awaited_once()
        gpt_call_messages = mock_gpt.call_args[0][0]
        user_message = next(m for m in gpt_call_messages if m["role"] == "user")
        assert ocr_text in user_message["text"]

    assert isinstance(result, ParsedReport)
    assert result.parse_failed is False
    assert result.confidence == 0.9
    assert len(result.fuels) == 3
    grades = [f.grade for f in result.fuels]
    assert "АИ-92" in grades
    assert "АИ-95" in grades
    assert "ДТ" in grades
    assert all(f.available for f in result.fuels)


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
