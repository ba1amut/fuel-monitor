# Fuel Monitor: /near Command Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `/near` Telegram bot command that asks the user to share their geolocation and returns a list of nearby fuel stations sorted by distance.

**Architecture:** Task 1 adds `GET /api/stations/nearby?lat&lon&radius_km&limit` using PostGIS `ST_DWithin`/`ST_Distance` with geography cast for accurate metric distances. Task 2 wires up the `/near` command in the bot: adds a `_pending_query` dict (separate from the existing `_pending_location` for report-mode), a `/near` command handler, `_handle_nearby_query()`, and updates `handle_location` to dispatch to the right handler. Task 2 also registers bot commands via `set_my_commands` (currently not called anywhere).

**Tech Stack:** Python 3.11+, FastAPI 0.111.0, aiogram 3.7.0, SQLAlchemy 2.0.30 async, GeoAlchemy2 0.15.1, PostGIS (geography type for ST_DWithin/ST_Distance), httpx 0.27.0, pytest-asyncio 0.23.6.

## Global Constraints

- No new pip dependencies — all packages already installed
- All DB access async (asyncpg + SQLAlchemy async session)
- Bot calls API via `API_URL = os.getenv("API_URL", "http://api:8000")` and `httpx.AsyncClient`
- Import paths: `from db.database import get_db`, `from db.models import Station`, `from api.schemas import StationOut`
- Tests: pytest-asyncio, `AsyncMock` for external calls (DB, httpx)
- Commit format: `feat(near): <description>`
- Secrets only via `.env`, never in code

---

### Task 1: `GET /api/stations/nearby` API endpoint

**Problem:** No proximity query exists. The bot needs to call an endpoint with `lat/lon` and get back stations within a radius, sorted by distance, with distance included in the response.

**Files:**
- Modify: `api/schemas.py` — add `NearbyStationOut(StationOut)` with `distance_km: float`
- Modify: `api/routers/stations.py` — add `/nearby` endpoint **before** `/{station_id}` to avoid path conflict
- Modify: `tests/test_stations_api.py` — add validation + empty-result tests

**Interfaces:**
- Consumes: `Station` ORM model, `StationOut.from_orm()` (already in `api/schemas.py`)
- Produces:
  - `GET /api/stations/nearby?lat=float&lon=float&radius_km=float&limit=int` → `list[NearbyStationOut]`
  - `class NearbyStationOut(StationOut)` with extra field `distance_km: float`
  - `NearbyStationOut.from_nearby(station: Station, distance_km: float) -> NearbyStationOut`

---

- [ ] **Step 1.1 — Write failing tests**

  File: `tests/test_stations_api.py`

  Add at end of file:
  ```python
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
      from api.routers.stations import router as stations_router
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
  ```

- [ ] **Step 1.2 — Run tests to confirm they fail**

  ```bash
  pytest tests/test_stations_api.py::test_nearby_stations_lat_validation tests/test_stations_api.py::test_nearby_stations_no_results -v
  ```
  Expected: FAIL — `404 Not Found` or `ImportError` (endpoint not yet defined)

- [ ] **Step 1.3 — Add `NearbyStationOut` to `api/schemas.py`**

  Add after `class StationOut` (before `class ReportIn`):
  ```python
  class NearbyStationOut(StationOut):
      distance_km: float

      @classmethod
      def from_nearby(cls, station, distance_km: float) -> "NearbyStationOut":
          base_dict = StationOut.from_orm(station).model_dump()
          return cls(**base_dict, distance_km=round(distance_km, 1))
  ```

- [ ] **Step 1.4 — Add `/nearby` endpoint to `api/routers/stations.py`**

  **CRITICAL:** The new route must be inserted **before** `@router.get("/{station_id}", ...)` in the file. If it is placed after, FastAPI will attempt to parse the literal string "nearby" as a UUID and return 422 instead of routing correctly.

  Add new imports at the top of the file (after the existing import block):
  ```python
  from sqlalchemy import cast, func, literal_column
  from geoalchemy2 import Geography
  ```

  Update the existing import from `api.schemas`:
  ```python
  from api.schemas import StationOut, LocationUpdateIn, NearbyStationOut
  ```

  Insert the following endpoint **before** `@router.get("/{station_id}", response_model=StationOut)`:
  ```python
  @router.get("/nearby", response_model=list[NearbyStationOut])
  async def nearby_stations(
      lat: float = Query(..., ge=-90.0, le=90.0),
      lon: float = Query(..., ge=-180.0, le=180.0),
      radius_km: float = Query(50.0, ge=0.1, le=200.0),
      limit: int = Query(10, ge=1, le=20),
      db: AsyncSession = Depends(get_db),
  ):
      point_geo = cast(
          func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326), Geography
      )
      station_geo = cast(Station.location, Geography)
      q = (
          select(
              Station,
              func.ST_Distance(station_geo, point_geo).label("distance_m"),
          )
          .options(selectinload(Station.fuel_states))
          .where(Station.location.isnot(None))
          .where(func.ST_DWithin(station_geo, point_geo, radius_km * 1000))
          .order_by(literal_column("distance_m"))
          .limit(limit)
      )
      result = await db.execute(q)
      rows = result.all()
      return [
          NearbyStationOut.from_nearby(station, distance_m / 1000).model_dump()
          for station, distance_m in rows
      ]
  ```

- [ ] **Step 1.5 — Run all tests**

  ```bash
  pytest tests/ -v
  ```
  Expected: all existing tests PASS + 2 new tests PASS (37+ total)

- [ ] **Step 1.6 — Commit**

  ```bash
  git add api/schemas.py api/routers/stations.py tests/test_stations_api.py
  git commit -m "feat(near): add GET /api/stations/nearby PostGIS proximity endpoint"
  ```

---

### Task 2: Bot `/near` command

**Problem:** Users driving on a highway have no way to query nearby stations. The bot needs a `/near` command that requests their geolocation and returns the nearest stations.

**Disambiguation:** The existing `_pending_location` dict in `bot/handlers/report.py` stores station_id for the report flow (after submitting a fuel report). A new `_pending_query` dict signals query mode. In `handle_location`, query mode is checked first.

**Files:**
- Modify: `bot/handlers/report.py` — add `_pending_query`, `_format_nearby_stations`, `_handle_nearby_query`, `/near` command handler, update `handle_location`
- Modify: `bot/main.py` — add `set_my_commands` to `on_startup`
- Modify: `tests/test_bot_handlers.py` — add format function tests

**Interfaces:**
- Consumes: `GET /api/stations/nearby?lat&lon&radius_km&limit` → `list[NearbyStationOut]` (Task 1)
- Produces:
  - `_format_nearby_stations(stations: list[dict]) -> str` — pure formatting function, testable without bot
  - `_pending_query: dict[int, bool]` — user_id → True when awaiting query-mode location

---

- [ ] **Step 2.1 — Write failing format tests**

  File: `tests/test_bot_handlers.py`

  Add at end of file:
  ```python
  def test_format_nearby_stations_with_results():
      from bot.handlers.report import _format_nearby_stations
      stations = [
          {
              "aliases": ["Октан"],
              "brand": "независимая",
              "city": "Ессентуки",
              "distance_km": 1.2,
              "fuel_states": [
                  {"grade": "АИ-95", "available": True, "price": 79.5},
                  {"grade": "АИ-92", "available": False, "price": None},
              ],
          }
      ]
      result = _format_nearby_stations(stations)
      assert "Октан" in result
      assert "1.2 км" in result
      assert "✅ АИ-95" in result
      assert "❌ АИ-92" in result


  def test_format_nearby_stations_empty():
      from bot.handlers.report import _format_nearby_stations
      result = _format_nearby_stations([])
      assert "не найдено" in result.lower()
  ```

- [ ] **Step 2.2 — Run tests to confirm they fail**

  ```bash
  pytest tests/test_bot_handlers.py::test_format_nearby_stations_with_results tests/test_bot_handlers.py::test_format_nearby_stations_empty -v
  ```
  Expected: FAIL with `ImportError` (`_format_nearby_stations` not defined)

- [ ] **Step 2.3 — Add `_pending_query`, format helper, and query handler to `bot/handlers/report.py`**

  **2.3a** — Add import at the top of the file (after existing imports):
  ```python
  from aiogram.filters import Command
  ```

  **2.3b** — Add `_pending_query` after the existing `_pending_location` line:
  ```python
  # user_id -> True — ожидание геолокации от /near команды
  _pending_query: dict[int, bool] = {}
  ```

  **2.3c** — Add `_format_nearby_stations` and `_handle_nearby_query` after `_format_fuels_fallback`:
  ```python
  def _format_nearby_stations(stations: list[dict]) -> str:
      if not stations:
          return "Станций в радиусе 50 км не найдено."
      lines = ["<b>АЗС рядом с тобой:</b>"]
      for s in stations:
          name = (s.get("aliases") or [None])[0] or s.get("brand") or "АЗС"
          dist = s.get("distance_km", 0)
          city = s.get("city") or ""
          city_str = f" · {city}" if city else ""
          fuels = s.get("fuel_states") or []
          avail = [f["grade"] for f in fuels if f.get("available")]
          unavail = [f["grade"] for f in fuels if not f.get("available")]
          parts = []
          if avail:
              parts.append("✅ " + ", ".join(avail))
          if unavail:
              parts.append("❌ " + ", ".join(unavail))
          fuel_str = "  ".join(parts) if parts else "нет данных"
          lines.append(f"📍 <b>{name}</b>{city_str} — {dist} км\n{fuel_str}")
      return "\n\n".join(lines)


  async def _handle_nearby_query(message: types.Message, lat: float, lon: float):
      try:
          async with httpx.AsyncClient(timeout=10) as client:
              r = await client.get(
                  f"{API_URL}/api/stations/nearby",
                  params={"lat": lat, "lon": lon, "radius_km": 50, "limit": 10},
              )
          if not r.is_success:
              logging.error("Nearby query failed: %s %s", r.status_code, r.text)
              await message.answer(
                  "Ошибка при поиске станций.", reply_markup=ReplyKeyboardRemove()
              )
              return
          await message.answer(
              _format_nearby_stations(r.json()),
              reply_markup=ReplyKeyboardRemove(),
              parse_mode="HTML",
          )
      except httpx.HTTPError as exc:
          logging.error("Nearby query network error: %s", exc)
          await message.answer(
              "Не удалось получить данные, попробуй позже.",
              reply_markup=ReplyKeyboardRemove(),
          )
  ```

  **2.3d** — Add `/near` command handler after `_handle_nearby_query`:
  ```python
  @router.message(Command("near"))
  async def handle_near_command(message: types.Message):
      _pending_query[message.from_user.id] = True
      await message.answer(
          "Поделись геолокацией — покажу АЗС рядом с тобой.",
          reply_markup=_location_keyboard(),
      )
  ```

- [ ] **Step 2.4 — Update `handle_location` in `bot/handlers/report.py`**

  Replace the existing `handle_location` function (from `@router.message(F.location)` to the end) with:
  ```python
  @router.message(F.location)
  async def handle_location(message: types.Message):
      user_id = message.from_user.id
      lat = message.location.latitude
      lon = message.location.longitude

      # Query mode: /near command is awaiting location
      if _pending_query.pop(user_id, False):
          await _handle_nearby_query(message, lat, lon)
          return

      # Report mode: station location confirmation after submitting a fuel report
      station_id = _pending_location.pop(user_id, None)
      if not station_id:
          await message.answer("Спасибо!", reply_markup=ReplyKeyboardRemove())
          return
      try:
          async with httpx.AsyncClient(timeout=10) as client:
              r = await client.patch(
                  f"{API_URL}/api/stations/{station_id}/location",
                  json={"lat": lat, "lon": lon},
              )
          if r.is_success:
              await message.answer(
                  "Местоположение АЗС сохранено.", reply_markup=ReplyKeyboardRemove()
              )
          else:
              logging.error("PATCH location failed: %s %s", r.status_code, r.text)
              await message.answer(
                  "Не удалось сохранить, попробуй на карте.",
                  reply_markup=ReplyKeyboardRemove(),
              )
      except httpx.HTTPError as exc:
          logging.error("PATCH location network error: %s", exc)
          await message.answer(
              "Не удалось сохранить, попробуй на карте.",
              reply_markup=ReplyKeyboardRemove(),
          )
  ```

- [ ] **Step 2.5 — Add `set_my_commands` to `on_startup` in `bot/main.py`**

  The current `on_startup` only calls `bot.set_webhook`. Extend it to also register commands:

  Replace:
  ```python
  async def on_startup(bot: Bot):
      await bot.set_webhook(WEBHOOK_URL)
      logging.info(f"Webhook set to {WEBHOOK_URL}")
  ```

  With:
  ```python
  async def on_startup(bot: Bot):
      await bot.set_webhook(WEBHOOK_URL)
      from aiogram.types import BotCommand
      await bot.set_my_commands([
          BotCommand(command="near", description="АЗС рядом со мной"),
          BotCommand(command="city", description="АЗС в городе — /city Ессентуки"),
          BotCommand(command="map", description="Открыть карту"),
          BotCommand(command="help", description="Как пользоваться ботом"),
      ])
      logging.info(f"Webhook set to {WEBHOOK_URL}")
  ```

- [ ] **Step 2.6 — Run all tests**

  ```bash
  pytest tests/ -v
  ```
  Expected: all tests PASS including the 2 new format tests (39+ total)

- [ ] **Step 2.7 — Commit**

  ```bash
  git add bot/handlers/report.py bot/main.py tests/test_bot_handlers.py
  git commit -m "feat(near): add /near command — show nearby stations by geolocation"
  ```

---

## Deploy

```bash
cd /opt/fuel-monitor && git pull && docker compose build api bot && docker compose up -d api bot
```

## Verify

1. `/near` в боте → нажать кнопку "📍 Поделиться геолокацией" → получить список АЗС с расстоянием
2. `/city Ессентуки` → получить сводку по городу (существующий функционал, регрессия)
3. Отправить текстовый репорт → бот по-прежнему предлагает указать место АЗС (регрессия)
4. Поделиться геолокацией в ответ на репорт → сохраняется как местоположение АЗС (не как `/near` запрос)
