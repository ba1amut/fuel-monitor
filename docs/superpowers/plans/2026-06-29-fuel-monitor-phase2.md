# Fuel Monitor Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` to implement task-by-task. Dependency order: Task 1 → Task 2 → Task 4. Task 3 is independent.

**Goal:** Исправить четыре ключевых пробела: станции не дедуплицируются (нет города), карта пустая (нет GPS), ответы бота неполные, нет фолбека по городу.

**Architecture:** Telegram Bot (aiogram 3.x, port 8080) → FastAPI API (port 8001) → PostgreSQL/PostGIS. Бот вызывает API через httpx по `API_URL`. Всё async.

**Tech Stack:** Python 3.11+, aiogram 3.7.0, FastAPI 0.111.0, SQLAlchemy 2.0.30 async, GeoAlchemy2 0.15.1, httpx 0.27.0, pytest-asyncio 0.23.6.

## Global Constraints

- Никаких новых pip-зависимостей — всё уже установлено
- Все обращения к БД async (asyncpg + SQLAlchemy async session)
- Бот обращается к API через `API_URL = os.getenv("API_URL", "http://api:8000")` и `httpx.AsyncClient`
- Пути импортов: `from db.database import get_db`, `from db.models import Station`, `from api.schemas import StationOut`
- Тесты: pytest-asyncio, AsyncMock для внешних вызовов (YandexGPT, httpx, DB)
- Формат коммита: `feat(phase2): <описание>`

---

### Task 1: Извлечение города из GPT

**Проблема:** `city` никогда не извлекается → `station_matcher` всегда получает `city=None` → дедупликации нет → каждый репорт создаёт новую станцию.

**Files:**
- Modify: `api/services/parser.py` — SYSTEM_PROMPT + ParsedReport
- Modify: `api/services/report_processor.py` — передать `parsed.city`
- Modify: `tests/test_parser.py` — тесты на город

**Interfaces:**
- Produces: `ParsedReport.city: str | None` — используется в Task 2 и Task 4

---

- [ ] **Step 1.1 — Добавить `city` в `ParsedReport` и SYSTEM_PROMPT**

  Файл: `api/services/parser.py`

  Изменение 1 — добавить поле в датакласс (после `brand`):
  ```python
  @dataclass
  class ParsedReport:
      station_alias: str | None
      brand: str | None
      city: str | None          # ← добавить
      fuels: list[FuelItem] = field(default_factory=list)
      confidence: float = 0.0
      parse_failed: bool = False
  ```

  Изменение 2 — обновить `SYSTEM_PROMPT` (добавить строку `"city"`):
  ```python
  SYSTEM_PROMPT = """Ты парсер отчётов об АЗС. Извлеки из сообщения пользователя данные и верни ТОЛЬКО валидный JSON без пояснений:
  {
    "station_alias": "название или ориентир АЗС или null",
    "brand": "сеть АЗС (Лукойл/Роснефть/Газпромнефть/Татнефть/независимая/null)",
    "city": "город из сообщения или null",
    "fuels": [{"grade": "АИ-92|АИ-95|АИ-100|ДТ|ГАЗ", "available": true/false, "price": число или null}],
    "confidence": число от 0 до 1
  }
  Если данных недостаточно — ставь низкий confidence."""
  ```

  Изменение 3 — в `_parse_response` добавить `city` при создании ParsedReport:
  ```python
  return ParsedReport(
      station_alias=data.get("station_alias"),
      brand=data.get("brand"),
      city=data.get("city"),          # ← добавить
      fuels=fuels,
      confidence=confidence,
      parse_failed=confidence < CONFIDENCE_THRESHOLD,
  )
  ```

  И в except-ветке тоже добавить `city=None`:
  ```python
  return ParsedReport(
      station_alias=None, brand=None, city=None, fuels=[], confidence=0.0, parse_failed=True
  )
  ```

- [ ] **Step 1.2 — Передать `parsed.city` в `find_or_create_station`**

  Файл: `api/services/report_processor.py`

  Найти вызов `find_or_create_station` (там сейчас `city=None`) и заменить:
  ```python
  station = await find_or_create_station(
      session=session,
      brand=parsed.brand,
      alias=parsed.station_alias,
      city=parsed.city,          # ← было city=None
      region=None,
      location=user_location,
  )
  ```

- [ ] **Step 1.3 — Написать тесты**

  Файл: `tests/test_parser.py`

  Добавить в конец файла:
  ```python
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
  ```

- [ ] **Step 1.4 — Запустить тесты**

  ```bash
  pytest tests/test_parser.py -v
  ```
  Ожидается: все тесты PASS.

- [ ] **Step 1.5 — Коммит**

  ```bash
  git add api/services/parser.py api/services/report_processor.py tests/test_parser.py
  git commit -m "feat(phase2): extract city from GPT response and pass to station_matcher"
  ```

---

### Task 2: Бот запрашивает геолокацию + PATCH endpoint

**Проблема:** Станции без GPS → маркеров нет. Пользователь не знает что нужно поделиться геолокацией.

**Files:**
- Modify: `bot/handlers/report.py` — добавить `_pending_location`, keyboard, `handle_location`
- Modify: `api/routers/stations.py` — добавить `PATCH /api/stations/{id}/location`
- Modify: `api/schemas.py` — добавить `LocationUpdateIn`
- Modify: `tests/test_stations_api.py` — тест PATCH endpoint

**Interfaces:**
- Consumes: `ParsedReport.city` (Task 1)
- Produces: `PATCH /api/stations/{station_id}/location` — принимает `{lat, lon}`, обновляет `station.location`

---

- [ ] **Step 2.1 — Добавить `LocationUpdateIn` в `api/schemas.py`**

  ```python
  # Добавить в конец файла api/schemas.py
  from pydantic import Field

  class LocationUpdateIn(BaseModel):
      lat: float = Field(..., ge=-90.0, le=90.0)
      lon: float = Field(..., ge=-180.0, le=180.0)
  ```

- [ ] **Step 2.2 — Добавить PATCH endpoint в `api/routers/stations.py`**

  ```python
  # Добавить в конец файла api/routers/stations.py
  from geoalchemy2.shape import from_shape
  from shapely.geometry import Point
  from api.schemas import LocationUpdateIn

  @router.patch("/{station_id}/location", response_model=StationOut)
  async def update_station_location(
      station_id: UUID,
      body: LocationUpdateIn,
      db: AsyncSession = Depends(get_db),
  ):
      station = await db.get(Station, station_id)
      if station is None:
          raise HTTPException(status_code=404, detail="Station not found")
      station.location = from_shape(Point(body.lon, body.lat), srid=4326)
      await db.commit()
      await db.refresh(station)
      return StationOut.from_orm(station)
  ```

- [ ] **Step 2.3 — Обновить `bot/handlers/report.py`**

  Добавить в начало файла (после существующих импортов):
  ```python
  from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove

  # user_id -> station_id (str UUID) — хранит ожидание геолокации между webhook-вызовами
  _pending_location: dict[int, str] = {}

  def _location_keyboard() -> ReplyKeyboardMarkup:
      return ReplyKeyboardMarkup(
          keyboard=[[KeyboardButton(text="Поделиться геолокацией", request_location=True)]],
          resize_keyboard=True,
          one_time_keyboard=True,
      )
  ```

  В каждый из трёх обработчиков (`handle_text_report`, `handle_photo_report`, `handle_voice_report`) добавить ПОСЛЕ успешного ответа бота:
  ```python
  # После строки await message.answer(reply_text, ...)
  if r_data.get("station_id"):
      _pending_location[message.from_user.id] = r_data["station_id"]
      await message.answer(
          "Укажи местоположение АЗС — это поможет отобразить её на карте.",
          reply_markup=_location_keyboard(),
      )
  ```

  Добавить новый handler в конец файла:
  ```python
  @router.message(F.location)
  async def handle_location(message: types.Message, bot: Bot):
      station_id = _pending_location.pop(message.from_user.id, None)
      if not station_id:
          await message.answer("Спасибо, но сейчас геолокация не ожидалась.",
                               reply_markup=ReplyKeyboardRemove())
          return
      lat = message.location.latitude
      lon = message.location.longitude
      async with httpx.AsyncClient(timeout=10) as client:
          r = await client.patch(
              f"{API_URL}/api/stations/{station_id}/location",
              json={"lat": lat, "lon": lon},
          )
      if r.is_success:
          await message.answer("Местоположение АЗС сохранено на карте.",
                               reply_markup=ReplyKeyboardRemove())
      else:
          await message.answer("Не удалось сохранить геолокацию, попробуй позже.",
                               reply_markup=ReplyKeyboardRemove())
  ```

  **Важно:** Для этого нужно чтобы API возвращал `station_id` в ответе. Проверь `/api/reports` response — если `station_id` не возвращается, добавить в `ReportResult` схему и в роутер репортов.

- [ ] **Step 2.4 — Написать тест PATCH endpoint**

  Файл: `tests/test_stations_api.py` (создать если нет):
  ```python
  import pytest
  from httpx import AsyncClient, ASGITransport
  from unittest.mock import AsyncMock, patch, MagicMock
  import uuid

  @pytest.mark.asyncio
  async def test_patch_station_location_not_found():
      from api.main import app
      async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
          with patch("api.routers.stations.get_db") as mock_db:
              mock_session = AsyncMock()
              mock_session.get.return_value = None
              mock_db.return_value.__aiter__ = lambda s: iter([mock_session])
              mock_db.return_value.__anext__ = AsyncMock(return_value=mock_session)
              r = await client.patch(
                  f"/api/stations/{uuid.uuid4()}/location",
                  json={"lat": 55.75, "lon": 37.61},
              )
      assert r.status_code == 404

  @pytest.mark.asyncio
  async def test_patch_station_location_validation():
      from api.main import app
      async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
          r = await client.patch(
              f"/api/stations/{uuid.uuid4()}/location",
              json={"lat": 999.0, "lon": 37.61},   # lat out of range
          )
      assert r.status_code == 422
  ```

- [ ] **Step 2.5 — Запустить тесты**

  ```bash
  pytest tests/ -v
  ```
  Ожидается: все тесты PASS.

- [ ] **Step 2.6 — Коммит**

  ```bash
  git add api/schemas.py api/routers/stations.py bot/handlers/report.py tests/test_stations_api.py
  git commit -m "feat(phase2): bot requests location after report, PATCH station location endpoint"
  ```

---

### Task 3: Фолбек по городским центроидам на карте (независимая задача)

**Проблема:** Станции без GPS вообще не видны на карте. Можно показать их приблизительно — по центру города.

**Files:**
- Create: `api/services/city_centroids.py` — словарь город→(lat,lon)
- Modify: `api/schemas.py` — добавить `is_approximate: bool` в `StationOut`
- Modify: `web/app.js` — синий маркер для приблизительных станций
- Modify: `tests/test_city_centroids.py` — тесты

---

- [ ] **Step 3.1 — Создать `api/services/city_centroids.py`**

  ```python
  # api/services/city_centroids.py
  from __future__ import annotations

  CITY_CENTROIDS: dict[str, tuple[float, float]] = {
      "москва": (55.7558, 37.6173),
      "санкт-петербург": (59.9343, 30.3351),
      "новосибирск": (54.9833, 82.8964),
      "екатеринбург": (56.8389, 60.6057),
      "казань": (55.8304, 49.0661),
      "нижний новгород": (56.2965, 43.9361),
      "краснодар": (45.0360, 38.9760),
      "самара": (53.2038, 50.1606),
      "омск": (54.9885, 73.3242),
      "ростов-на-дону": (47.2357, 39.7015),
      "уфа": (54.7388, 55.9721),
      "красноярск": (56.0097, 92.8519),
      "пермь": (58.0105, 56.2502),
      "воронеж": (51.6720, 39.1843),
      "волгоград": (48.7080, 44.5133),
      "челябинск": (55.1644, 61.4368),
      "саратов": (51.5924, 46.0340),
      "тюмень": (57.1522, 65.5272),
      "тольятти": (53.5303, 49.3461),
      "ижевск": (56.8527, 53.2114),
      "барнаул": (53.3547, 83.7697),
      "ульяновск": (54.3282, 48.3866),
      "иркутск": (52.2855, 104.2890),
      "хабаровск": (48.4814, 135.0721),
      "владивосток": (43.1155, 131.8855),
      "ярославль": (57.6261, 39.8845),
      "махачкала": (42.9849, 47.5047),
      "томск": (56.4977, 84.9744),
      "оренбург": (51.7727, 55.0988),
      "кемерово": (55.3333, 86.0833),
      "новокузнецк": (53.7557, 87.1099),
      "рязань": (54.6269, 39.6916),
      "астрахань": (46.3497, 48.0408),
      "набережные челны": (55.7435, 52.4051),
      "пенза": (53.1959, 45.0183),
      "липецк": (52.6031, 39.5708),
      "тула": (54.1961, 37.6182),
      "киров": (58.6036, 49.6680),
      "чебоксары": (56.1439, 47.2489),
      "калининград": (54.7065, 20.5110),
      "брянск": (53.2434, 34.3636),
      "курск": (51.7304, 36.1927),
      "иваново": (57.0000, 40.9739),
      "магнитогорск": (53.4143, 59.0611),
      "тверь": (56.8587, 35.9176),
      "ставрополь": (45.0428, 41.9734),
      "белгород": (50.5957, 36.5873),
      "сочи": (43.5855, 39.7231),
      "ессентуки": (44.0490, 42.8610),
      "пятигорск": (44.0490, 43.0596),
  }


  def get_centroid(city: str | None) -> tuple[float, float] | None:
      """Return (lat, lon) for a Russian city name, case-insensitive. None if unknown."""
      if not city:
          return None
      return CITY_CENTROIDS.get(city.lower())
  ```

- [ ] **Step 3.2 — Добавить `is_approximate` в `StationOut` и использовать центроид**

  Файл: `api/schemas.py`

  Добавить поле в `StationOut`:
  ```python
  is_approximate: bool = False
  ```

  В методе `from_orm()` заменить блок с `loc = None` на:
  ```python
  from api.services.city_centroids import get_centroid

  is_approximate = False
  loc = None
  if station.location is not None:
      try:
          shape = to_shape(station.location)
          loc = {"coordinates": list(shape.coords[0])}
      except Exception:
          loc = None
  if loc is None:
      centroid = get_centroid(station.city)
      if centroid:
          lat, lon = centroid
          loc = {"coordinates": [lon, lat]}
          is_approximate = True
  ```

  И в return добавить `is_approximate=is_approximate`.

- [ ] **Step 3.3 — Обновить `web/app.js`**

  Добавить синий маркер (после определения `greyIcon`):
  ```javascript
  const blueIcon = L.divIcon({
      className: "",
      html: '<div style="width:12px;height:12px;border-radius:50%;background:#3388ff;opacity:0.6;border:2px solid #fff"></div>',
      iconSize: [12, 12],
      iconAnchor: [6, 6],
  });

  function pickIcon(station) {
      if (station.is_approximate) return blueIcon;
      const states = station.fuel_states || [];
      if (states.length === 0) return greyIcon;
      const hasAny = states.some(f => f.available);
      return hasAny ? greenIcon : redIcon;
  }
  ```

  Заменить `greyIcon` / `greenIcon` / `redIcon` выбор на `pickIcon(station)` при создании маркеров.

  В popup добавить строку если приблизительно:
  ```javascript
  const approxNote = station.is_approximate ? '<br><em style="color:#888">⚠ позиция по городу</em>' : '';
  ```

- [ ] **Step 3.4 — Написать тесты**

  Создать `tests/test_city_centroids.py`:
  ```python
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
  ```

- [ ] **Step 3.5 — Запустить тесты**

  ```bash
  pytest tests/test_city_centroids.py -v
  ```

- [ ] **Step 3.6 — Коммит**

  ```bash
  git add api/services/city_centroids.py api/schemas.py web/app.js tests/test_city_centroids.py
  git commit -m "feat(phase2): city centroid fallback for map markers, approximate location indicator"
  ```

---

### Task 4: Полный отчёт по станции в ответе бота

**Проблема:** После репорта бот показывает только то что пришло в ЭТОМ репорте. Если другие пользователи уже сообщали о других марках топлива на той же станции — пользователь не видит.

**Files:**
- Modify: `bot/handlers/report.py` — запросить полную станцию из API и отобразить
- Modify: `tests/test_bot_report.py` — тест полного ответа

**Interfaces:**
- Consumes: `GET /api/stations/{station_id}` (уже существует) + `ParsedReport.city` (Task 1)

---

- [ ] **Step 4.1 — Добавить `_fetch_full_station` и `_format_full_station` в `bot/handlers/report.py`**

  ```python
  async def _fetch_full_station(station_id: str) -> dict | None:
      """Fetch complete station data including all fuel_states. Returns None on error."""
      try:
          async with httpx.AsyncClient(timeout=5) as client:
              r = await client.get(f"{API_URL}/api/stations/{station_id}")
              if r.is_success:
                  return r.json()
      except Exception:
          pass
      return None


  def _format_full_station(station: dict) -> str:
      name = (station.get("aliases") or [None])[0] or station.get("brand") or "АЗС"
      city = station.get("city") or ""
      header = f"📍 {name}" + (f" · {city}" if city else "")
      fuel_states = station.get("fuel_states") or []
      if not fuel_states:
          return header + "\nДанных о топливе нет"
      lines = [header]
      for fs in fuel_states:
          grade = fs.get("grade", "?")
          if fs.get("available"):
              price = fs.get("price")
              price_str = f" — {price} руб" if price else ""
              lines.append(f"✅ {grade}{price_str}")
          else:
              lines.append(f"❌ {grade} — нет")
      return "\n".join(lines)
  ```

- [ ] **Step 4.2 — Использовать `_fetch_full_station` в обработчиках**

  В каждом из трёх обработчиков, после получения `r_data`, заменить формирование ответа:
  ```python
  station_id = r_data.get("station_id")
  if station_id:
      full = await _fetch_full_station(station_id)
      if full:
          reply_text = _format_full_station(full)
      # else — fallback на исходный reply_text из _format_fuels
  ```

- [ ] **Step 4.3 — Написать тест**

  Файл: `tests/test_bot_handlers.py` (создать если нет):
  ```python
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
  ```

- [ ] **Step 4.4 — Запустить тесты**

  ```bash
  pytest tests/ -v
  ```

- [ ] **Step 4.5 — Коммит**

  ```bash
  git add bot/handlers/report.py tests/test_bot_handlers.py
  git commit -m "feat(phase2): show complete station fuel status after report"
  ```

---

## Деплой на сервер после всех задач

```bash
cd /opt/fuel-monitor
git pull
docker compose build api bot
docker compose up -d api bot
```

## Проверка

1. Отправить боту: `Ессентуки АЗС октан около озера: 95 - 79.5 руб`
   - Ожидается: бот отвечает полным статусом станции + предлагает поделиться геолокацией
2. Поделиться геолокацией
   - Ожидается: бот подтверждает сохранение
3. Открыть https://fuel.weatherpath.ru
   - Ожидается: зелёный маркер на точных координатах (или синий — по городу)
4. `/city Ессентуки` в боте
   - Ожидается: список станций с топливом
