from api.services.city_centroids import get_centroid


def test_known_city_returns_coords():
    result = get_centroid("Москва")
    assert result is not None
    lat, lon = result
    assert 55.0 < lat < 57.0
    assert 36.0 < lon < 39.0


def test_case_insensitive():
    assert get_centroid("москва") == get_centroid("МОСКВА")


def test_unknown_city_returns_none():
    assert get_centroid("Нью-Йорк") is None


def test_none_input_returns_none():
    assert get_centroid(None) is None


def test_essentuki_exists():
    result = get_centroid("Ессентуки")
    assert result is not None
