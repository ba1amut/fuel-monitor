import pytest
from bot.handlers.report import _format_full_station


def test_format_full_station_with_fuels():
    station = {
        "aliases": ["Октан около озера"],
        "brand": "независимая",
        "city": "Ессентуки",
        "fuel_states": [
            {"grade": "АИ-95", "available": True, "price": 79.5},
            {"grade": "АИ-92", "available": False, "price": None},
        ],
    }
    result = _format_full_station(station)
    assert "Октан около озера" in result
    assert "✅ АИ-95 — 79.5 руб" in result
    assert "❌ АИ-92 — нет" in result
    assert "Ессентуки" in result


def test_format_full_station_no_fuels():
    station = {"aliases": ["Тест"], "brand": None, "city": None, "fuel_states": []}
    result = _format_full_station(station)
    assert "Данных о топливе нет" in result


def test_format_full_station_no_aliases_uses_brand():
    station = {
        "aliases": [],
        "brand": "Лукойл",
        "city": "Москва",
        "fuel_states": [{"grade": "АИ-95", "available": True, "price": None}],
    }
    result = _format_full_station(station)
    assert "Лукойл" in result
    assert "Москва" in result
    assert "✅ АИ-95" in result


def test_format_full_station_no_city():
    station = {
        "aliases": ["АЗС у дороги"],
        "brand": None,
        "city": None,
        "fuel_states": [{"grade": "ДТ", "available": True, "price": 70.0}],
    }
    result = _format_full_station(station)
    assert "АЗС у дороги" in result
    assert " · " not in result  # no city separator when city is absent
    assert "✅ ДТ — 70.0 руб" in result


def test_format_full_station_available_no_price():
    station = {
        "aliases": ["Тест"],
        "brand": None,
        "city": None,
        "fuel_states": [{"grade": "АИ-98", "available": True, "price": None}],
    }
    result = _format_full_station(station)
    assert "✅ АИ-98" in result
    # No price string when price is None
    assert "руб" not in result
