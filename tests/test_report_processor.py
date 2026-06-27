import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from api.services.report_processor import process_report
from api.services.parser import ParsedReport, FuelItem


@pytest.mark.asyncio
async def test_process_text_report_success():
    parsed = ParsedReport(
        station_alias="Лукойл на Ленинском",
        brand="Лукойл",
        fuels=[FuelItem(grade="АИ-95", available=True, price=79.0)],
        confidence=0.9,
        parse_failed=False,
    )
    mock_station = MagicMock()
    mock_station.id = "uuid-123"
    mock_station.aliases = ["Лукойл на Ленинском"]
    mock_session = MagicMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.execute = AsyncMock(return_value=MagicMock())
    mock_session.refresh = AsyncMock()

    with patch("api.services.report_processor.parse_text", AsyncMock(return_value=parsed)), \
         patch("api.services.report_processor.find_or_create_station", AsyncMock(return_value=mock_station)), \
         patch("api.services.report_processor._upsert_fuel_states", AsyncMock()):
        result = await process_report(
            session=mock_session,
            telegram_user_id=123456,
            text="Лукойл на Ленинском, АИ-95 есть 79 руб",
        )

    assert result.success is True
    assert result.parse_failed is False
    assert len(result.fuels) == 1


@pytest.mark.asyncio
async def test_process_text_report_parse_failed():
    """When parse fails, station is not created and result reflects failure."""
    parsed = ParsedReport(
        station_alias=None,
        brand=None,
        fuels=[],
        confidence=0.1,
        parse_failed=True,
    )
    mock_session = MagicMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.execute = AsyncMock(return_value=MagicMock())
    mock_session.refresh = AsyncMock()

    with patch("api.services.report_processor.parse_text", AsyncMock(return_value=parsed)), \
         patch("api.services.report_processor.find_or_create_station", AsyncMock()) as mock_find:
        result = await process_report(
            session=mock_session,
            telegram_user_id=999,
            text="непонятный текст",
        )

    assert result.success is True
    assert result.parse_failed is True
    assert result.fuels == []
    assert result.station_name is None
    mock_find.assert_not_called()


@pytest.mark.asyncio
async def test_process_voice_report_transcribes_first():
    """Voice input is transcribed then parsed as text."""
    parsed = ParsedReport(
        station_alias="Газпромнефть",
        brand="Газпромнефть",
        fuels=[FuelItem(grade="АИ-92", available=True, price=55.0)],
        confidence=0.85,
        parse_failed=False,
    )
    mock_station = MagicMock()
    mock_station.id = "uuid-456"
    mock_station.aliases = ["Газпромнефть"]
    mock_session = MagicMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.execute = AsyncMock(return_value=MagicMock())
    mock_session.refresh = AsyncMock()

    mock_transcribe = AsyncMock(return_value="Газпромнефть АИ-92 55 рублей")

    with patch("api.services.report_processor._transcribe", mock_transcribe), \
         patch("api.services.report_processor.parse_text", AsyncMock(return_value=parsed)), \
         patch("api.services.report_processor.find_or_create_station", AsyncMock(return_value=mock_station)), \
         patch("api.services.report_processor._upsert_fuel_states", AsyncMock()):
        result = await process_report(
            session=mock_session,
            telegram_user_id=777,
            voice_bytes=b"fake-ogg-data",
        )

    mock_transcribe.assert_called_once_with(b"fake-ogg-data")
    assert result.success is True
    assert result.fuels[0].grade == "АИ-92"


@pytest.mark.asyncio
async def test_process_photo_report():
    """Photo input goes through parse_photo, not parse_text."""
    parsed = ParsedReport(
        station_alias="Роснефть",
        brand="Роснефть",
        fuels=[FuelItem(grade="ДТ", available=True, price=68.5)],
        confidence=0.8,
        parse_failed=False,
    )
    mock_station = MagicMock()
    mock_station.id = "uuid-789"
    mock_station.aliases = ["Роснефть"]
    mock_session = MagicMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.execute = AsyncMock(return_value=MagicMock())
    mock_session.refresh = AsyncMock()

    mock_parse_photo = AsyncMock(return_value=parsed)

    with patch("api.services.report_processor.parse_photo", mock_parse_photo), \
         patch("api.services.report_processor.find_or_create_station", AsyncMock(return_value=mock_station)), \
         patch("api.services.report_processor._upsert_fuel_states", AsyncMock()):
        result = await process_report(
            session=mock_session,
            telegram_user_id=888,
            image_bytes=b"fake-jpeg-data",
        )

    mock_parse_photo.assert_called_once_with(b"fake-jpeg-data")
    assert result.success is True
    assert result.fuels[0].grade == "ДТ"
