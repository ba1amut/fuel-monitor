from db.models import User, Station, Report, StationFuelState


def test_models_importable():
    assert User.__tablename__ == "users"
    assert Station.__tablename__ == "stations"
    assert Report.__tablename__ == "reports"
    assert StationFuelState.__tablename__ == "station_fuel_states"
