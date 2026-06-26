# Fuel Monitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Краудсорсинговый Telegram-бот + веб-карта для мониторинга наличия топлива на АЗС России.

**Architecture:** Python-монолит: aiogram 3 (бот) + FastAPI (API + статика) + PostgreSQL/PostGIS (хранилище). YandexGPT парсит текст и фото, Yandex SpeechKit транскрибирует голос. Веб-карта на Leaflet.js с маркерами и тепловым слоем.

**Tech Stack:** Python 3.11, FastAPI, aiogram 3, SQLAlchemy 2 (async), Alembic, PostgreSQL 15 + PostGIS, asyncpg, httpx, pytest, Leaflet.js 1.9, Leaflet.markercluster, Leaflet.heat, Docker Compose, Nginx.

## Global Constraints

- Python 3.11+, async везде (asyncio)
- SQLAlchemy 2.x с async сессиями
- aiogram 3.x (не 2.x — API несовместимо)
- Все Yandex Cloud запросы через один `YANDEX_API_KEY` + `YANDEX_FOLDER_ID`
- Координаты: EPSG:4326 (WGS 84)
- Язык интерфейса бота: русский
- Все секреты только через `.env`, никогда не в коде

---

## File Map

```
20260626 Fuel-Monitor/
├── docker-compose.yml
├── .env.example
├── requirements.txt
├── nginx/
│   └── nginx.conf
├── bot/
│   ├── main.py               — запуск aiogram, webhook регистрация
│   └── handlers/
│       ├── report.py         — приём текст/фото/голос → вызов API
│       └── query.py          — /start /help /city /map + текстовые запросы
├── api/
│   ├── main.py               — FastAPI app, монтирование статики
│   ├── schemas.py            — Pydantic модели запросов/ответов
│   ├── routers/
│   │   ├── reports.py        — POST /api/reports
│   │   ├── stations.py       — GET /api/stations, GET /api/stations/{id}
│   │   ├── heatmap.py        — GET /api/heatmap
│   │   └── summary.py        — GET /api/summary
│   └── services/
│       ├── parser.py         — YandexGPT text + vision парсинг
│       ├── speechkit.py      — Yandex SpeechKit аудио → текст
│       ├── station_matcher.py — нечёткий поиск + upsert станций
│       └── report_processor.py — оркестрация: парсинг → матчинг → сохранение
├── db/
│   ├── models.py             — SQLAlchemy ORM модели
│   ├── database.py           — engine, async session factory
│   └── migrations/           — Alembic
│       ├── env.py
│       └── versions/
├── web/
│   ├── index.html
│   ├── app.js
│   └── style.css
└── tests/
    ├── conftest.py
    ├── test_parser.py
    ├── test_station_matcher.py
    ├── test_report_processor.py
    └── test_api.py
```

---

## Task 0: Технический спайк — валидация пайплайна

**Цель:** убедиться что Telegram → YandexGPT → Telegram работает до начала основной разработки. Это throwaway-код, не входит в основной проект.

**Files:**
- Create: `spike/bot_spike.py`

**Interfaces:**
- Produces: подтверждение что все три типа сообщений (текст/фото/голос) проходят через Yandex Cloud и возвращаются в бот

- [ ] **Step 1: Создай папку spike и файл**

```python
# spike/bot_spike.py
import asyncio, base64, os, httpx
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
YANDEX_API_KEY = os.getenv("YANDEX_API_KEY")
YANDEX_FOLDER_ID = os.getenv("YANDEX_FOLDER_ID")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

async def call_yandex_gpt(messages: list[dict]) -> str:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
            headers={"Authorization": f"Api-Key {YANDEX_API_KEY}"},
            json={
                "modelUri": f"gpt://{YANDEX_FOLDER_ID}/yandexgpt/latest",
                "completionOptions": {"temperature": 0.1, "maxTokens": 500},
                "messages": messages,
            },
            timeout=30,
        )
        r.raise_for_status()
        return r.json()["result"]["alternatives"][0]["message"]["text"]

async def transcribe_voice(ogg_bytes: bytes) -> str:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize",
            headers={"Authorization": f"Api-Key {YANDEX_API_KEY}"},
            params={"folderId": YANDEX_FOLDER_ID, "lang": "ru-RU", "format": "oggopus"},
            content=ogg_bytes,
            timeout=30,
        )
        r.raise_for_status()
        return r.json().get("result", "")

@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer("Спайк активен. Пришли текст, фото или голос.")

@dp.message(F.text)
async def handle_text(message: types.Message):
    result = await call_yandex_gpt([
        {"role": "system", "text": "Извлеки из текста: название АЗС, марки топлива, наличие (есть/нет), цену. Ответь в формате JSON."},
        {"role": "user", "text": message.text},
    ])
    await message.answer(f"✅ Текст распознан:\n{result}")

@dp.message(F.photo)
async def handle_photo(message: types.Message):
    file = await bot.get_file(message.photo[-1].file_id)
    raw = await bot.download_file(file.file_path)
    b64 = base64.b64encode(raw.read()).decode()
    result = await call_yandex_gpt([
        {"role": "system", "text": "Извлеки с фото: название АЗС, марки топлива, цены. Ответь в формате JSON."},
        {"role": "user", "text": "", "image": {"type": "base64", "data": b64}},
    ])
    await message.answer(f"✅ Фото распознано:\n{result}")

@dp.message(F.voice)
async def handle_voice(message: types.Message):
    file = await bot.get_file(message.voice.file_id)
    raw = await bot.download_file(file.file_path)
    transcript = await transcribe_voice(raw.read())
    result = await call_yandex_gpt([
        {"role": "system", "text": "Извлеки из текста: название АЗС, марки топлива, наличие, цену. Ответь в формате JSON."},
        {"role": "user", "text": transcript},
    ])
    await message.answer(f"✅ Голос → текст: {transcript}\n\nРаспознано:\n{result}")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Создай `.env` для спайка**

```bash
TELEGRAM_TOKEN=your_token_here
YANDEX_API_KEY=your_key_here
YANDEX_FOLDER_ID=your_folder_id_here
```

- [ ] **Step 3: Установи зависимости и запусти**

```bash
pip install aiogram httpx python-dotenv
cd spike
python -c "from dotenv import load_dotenv; load_dotenv('../.env')"
python bot_spike.py
```

- [ ] **Step 4: Протестируй все три сценария вручную**
  - Отправь текст: «Лукойл на Ленинском, АИ-95 есть по 79 руб»
  - Отправь фото табло цен
  - Отправь голосовое сообщение

Ожидаемый результат: бот отвечает JSON с распознанными данными для всех трёх типов.

- [ ] **Step 5: Зафиксируй результат (работает / не работает / частично)**

Если что-то не работает — разбирайся с конкретным сервисом до перехода к Task 1. Спайк можно удалить после успешного прохождения.

---

## Task 1: Инфраструктура проекта

**Files:**
- Create: `requirements.txt`
- Create: `docker-compose.yml`
- Create: `.env.example`
- Create: `nginx/nginx.conf`
- Create: `db/database.py`

**Interfaces:**
- Produces: `get_db()` — async генератор сессии SQLAlchemy; `engine` — AsyncEngine

- [ ] **Step 1: Создай `requirements.txt`**

```
fastapi==0.111.0
uvicorn[standard]==0.29.0
aiogram==3.7.0
sqlalchemy[asyncio]==2.0.30
asyncpg==0.29.0
alembic==1.13.1
httpx==0.27.0
pydantic-settings==2.2.1
python-multipart==0.0.9
geoalchemy2==0.15.1
rapidfuzz==3.9.3
pytest==8.2.0
pytest-asyncio==0.23.6
pytest-httpx==0.30.0
httpx==0.27.0
```

- [ ] **Step 2: Создай `docker-compose.yml`**

```yaml
services:
  db:
    image: postgis/postgis:15-3.4
    environment:
      POSTGRES_DB: fuelmonitor
      POSTGRES_USER: fm
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U fm -d fuelmonitor"]
      interval: 5s
      retries: 10

  api:
    build: .
    command: uvicorn api.main:app --host 0.0.0.0 --port 8000
    env_file: .env
    depends_on:
      db:
        condition: service_healthy
    volumes:
      - ./web:/app/web

  bot:
    build: .
    command: python -m bot.main
    env_file: .env
    depends_on:
      - api

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/conf.d/default.conf
      - certbot_www:/var/www/certbot
      - certbot_conf:/etc/letsencrypt
    depends_on:
      - api

volumes:
  pgdata:
  certbot_www:
  certbot_conf:
```

- [ ] **Step 3: Создай `.env.example`**

```
TELEGRAM_TOKEN=
YANDEX_API_KEY=
YANDEX_FOLDER_ID=
DB_PASSWORD=changeme
DATABASE_URL=postgresql+asyncpg://fm:changeme@db/fuelmonitor
WEBHOOK_HOST=https://yourdomain.ru
```

- [ ] **Step 4: Создай `nginx/nginx.conf`**

```nginx
server {
    listen 80;
    server_name yourdomain.ru;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl;
    server_name yourdomain.ru;

    ssl_certificate /etc/letsencrypt/live/yourdomain.ru/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yourdomain.ru/privkey.pem;

    location /api/ {
        proxy_pass http://api:8000/api/;
        proxy_set_header Host $host;
    }

    location /bot {
        proxy_pass http://api:8000/bot;
        proxy_set_header Host $host;
    }

    location / {
        proxy_pass http://api:8000/;
    }
}
```

- [ ] **Step 5: Создай `db/database.py`**

```python
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
import os

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_async_engine(DATABASE_URL, echo=False)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

async def get_db() -> AsyncSession:
    async with async_session_factory() as session:
        yield session
```

- [ ] **Step 6: Создай `Dockerfile`**

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
```

- [ ] **Step 7: Коммит**

```bash
git init
git add .
git commit -m "feat: project scaffold and infrastructure"
```

---

## Task 2: Модели БД и миграции

**Files:**
- Create: `db/models.py`
- Create: `db/migrations/env.py` (через alembic init)
- Create: `db/migrations/versions/001_initial.py`

**Interfaces:**
- Produces: классы `User`, `Station`, `Report`, `StationFuelState` — SQLAlchemy ORM модели

- [ ] **Step 1: Напиши тест для импорта моделей**

```python
# tests/test_models.py
from db.models import User, Station, Report, StationFuelState

def test_models_importable():
    assert User.__tablename__ == "users"
    assert Station.__tablename__ == "stations"
    assert Report.__tablename__ == "reports"
    assert StationFuelState.__tablename__ == "station_fuel_states"
```

- [ ] **Step 2: Запусти тест — убедись что падает**

```bash
pytest tests/test_models.py -v
```

Ожидаемый результат: `ModuleNotFoundError`

- [ ] **Step 3: Создай `db/models.py`**

```python
from sqlalchemy import (
    BigInteger, Boolean, Column, Float, ForeignKey,
    Integer, Numeric, String, Text, DateTime, func
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from geoalchemy2 import Geometry
import uuid
from db.database import Base

class User(Base):
    __tablename__ = "users"
    telegram_user_id = Column(BigInteger, primary_key=True)
    report_count = Column(Integer, default=0, nullable=False)
    first_seen_at = Column(DateTime(timezone=True), server_default=func.now())
    last_seen_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    is_banned = Column(Boolean, default=False, nullable=False)
    reports = relationship("Report", back_populates="user")

class Station(Base):
    __tablename__ = "stations"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    brand = Column(String(100))
    aliases = Column(JSONB, default=list)
    address = Column(Text)
    location = Column(Geometry("POINT", srid=4326))
    city = Column(String(100))
    region = Column(String(100))
    last_report_at = Column(DateTime(timezone=True))
    report_count = Column(Integer, default=0)
    reports = relationship("Report", back_populates="station")
    fuel_states = relationship("StationFuelState", back_populates="station")

class Report(Base):
    __tablename__ = "reports"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    station_id = Column(UUID(as_uuid=True), ForeignKey("stations.id"), nullable=True)
    telegram_user_id = Column(BigInteger, ForeignKey("users.telegram_user_id"), nullable=False)
    raw_text = Column(Text)
    has_photo = Column(Boolean, default=False)
    fuels = Column(JSONB, default=list)
    user_location = Column(Geometry("POINT", srid=4326), nullable=True)
    queue_minutes = Column(Integer, nullable=True)
    confidence = Column(Float, nullable=True)
    parse_failed = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    source = Column(String(30))  # telegram_text | telegram_photo | telegram_voice
    station = relationship("Station", back_populates="reports")
    user = relationship("User", back_populates="reports")

class StationFuelState(Base):
    __tablename__ = "station_fuel_states"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    station_id = Column(UUID(as_uuid=True), ForeignKey("stations.id"), nullable=False)
    grade = Column(String(20), nullable=False)  # АИ-92, АИ-95, АИ-100, ДТ, ГАЗ
    available = Column(Boolean, nullable=False)
    price = Column(Numeric(8, 2), nullable=True)
    last_report_id = Column(UUID(as_uuid=True), ForeignKey("reports.id"))
    updated_at = Column(DateTime(timezone=True), server_default=func.now())
    station = relationship("Station", back_populates="fuel_states")
```

- [ ] **Step 4: Запусти тест — убедись что проходит**

```bash
pytest tests/test_models.py -v
```

- [ ] **Step 5: Инициализируй Alembic**

```bash
alembic init db/migrations
```

Отредактируй `db/migrations/env.py` — замени строку `target_metadata = None` на:

```python
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from db.database import Base
from db import models  # noqa: F401 — импорт нужен чтобы модели зарегистрировались
target_metadata = Base.metadata
```

И замени `connectable = engine_from_config(...)` блок на async вариант:

```python
from sqlalchemy.ext.asyncio import async_engine_from_config
connectable = async_engine_from_config(
    config.get_section(config.config_ini_section, {}),
    prefix="sqlalchemy.",
)
async with connectable.connect() as connection:
    await connection.run_sync(do_run_migrations)
await connectable.dispose()
```

В `alembic.ini` установи `sqlalchemy.url = %(DATABASE_URL)s` и добавь в `env.py`:
```python
config.set_main_option("sqlalchemy.url", os.getenv("DATABASE_URL"))
```

- [ ] **Step 6: Создай первую миграцию и примени**

```bash
alembic revision --autogenerate -m "initial schema"
alembic upgrade head
```

- [ ] **Step 7: Коммит**

```bash
git add db/
git commit -m "feat: database models and initial migration"
```

---

## Task 3: Yandex Cloud сервисы (парсер + SpeechKit)

**Files:**
- Create: `api/services/parser.py`
- Create: `api/services/speechkit.py`
- Create: `tests/test_parser.py`

**Interfaces:**
- Produces:
  - `parse_text(text: str) -> ParsedReport` — парсинг текстового отчёта
  - `parse_photo(image_bytes: bytes) -> ParsedReport` — парсинг фото
  - `transcribe_voice(ogg_bytes: bytes) -> str` — голос → текст
  - `ParsedReport` — dataclass: `station_alias: str | None`, `brand: str | None`, `fuels: list[FuelItem]`, `confidence: float`, `parse_failed: bool`
  - `FuelItem` — dataclass: `grade: str`, `available: bool`, `price: float | None`

- [ ] **Step 1: Напиши тесты с моками**

```python
# tests/test_parser.py
import pytest
from unittest.mock import AsyncMock, patch
from api.services.parser import parse_text, ParsedReport, FuelItem

@pytest.mark.asyncio
async def test_parse_text_happy_path():
    mock_response = '{"station_alias": "Лукойл на Ленинском", "brand": "Лукойл", "fuels": [{"grade": "АИ-95", "available": true, "price": 79.0}], "confidence": 0.95}'
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
```

- [ ] **Step 2: Запусти тесты — убедись что падают**

```bash
pytest tests/test_parser.py -v
```

- [ ] **Step 3: Создай `api/services/parser.py`**

```python
import json, base64, os
from dataclasses import dataclass, field
import httpx

YANDEX_API_KEY = os.getenv("YANDEX_API_KEY")
YANDEX_FOLDER_ID = os.getenv("YANDEX_FOLDER_ID")
GPT_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
CONFIDENCE_THRESHOLD = 0.5

SYSTEM_PROMPT = """Ты парсер отчётов об АЗС. Извлеки из сообщения пользователя данные и верни ТОЛЬКО валидный JSON без пояснений:
{
  "station_alias": "название или ориентир АЗС или null",
  "brand": "сеть АЗС (Лукойл/Роснефть/Газпромнефть/Татнефть/независимая/null)",
  "fuels": [{"grade": "АИ-92|АИ-95|АИ-100|ДТ|ГАЗ", "available": true/false, "price": число или null}],
  "confidence": число от 0 до 1
}
Если данных недостаточно — ставь низкий confidence."""

@dataclass
class FuelItem:
    grade: str
    available: bool
    price: float | None = None

@dataclass
class ParsedReport:
    station_alias: str | None
    brand: str | None
    fuels: list[FuelItem] = field(default_factory=list)
    confidence: float = 0.0
    parse_failed: bool = False

async def _call_yandex_gpt(messages: list[dict]) -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            GPT_URL,
            headers={"Authorization": f"Api-Key {YANDEX_API_KEY}"},
            json={
                "modelUri": f"gpt://{YANDEX_FOLDER_ID}/yandexgpt/latest",
                "completionOptions": {"temperature": 0.1, "maxTokens": 500},
                "messages": messages,
            },
        )
        r.raise_for_status()
        return r.json()["result"]["alternatives"][0]["message"]["text"]

def _parse_response(raw: str) -> ParsedReport:
    try:
        data = json.loads(raw)
        fuels = [FuelItem(**f) for f in data.get("fuels", [])]
        confidence = float(data.get("confidence", 0))
        return ParsedReport(
            station_alias=data.get("station_alias"),
            brand=data.get("brand"),
            fuels=fuels,
            confidence=confidence,
            parse_failed=confidence < CONFIDENCE_THRESHOLD,
        )
    except Exception:
        return ParsedReport(station_alias=None, brand=None, fuels=[], confidence=0.0, parse_failed=True)

async def parse_text(text: str) -> ParsedReport:
    raw = await _call_yandex_gpt([
        {"role": "system", "text": SYSTEM_PROMPT},
        {"role": "user", "text": text},
    ])
    return _parse_response(raw)

async def parse_photo(image_bytes: bytes) -> ParsedReport:
    b64 = base64.b64encode(image_bytes).decode()
    raw = await _call_yandex_gpt([
        {"role": "system", "text": SYSTEM_PROMPT},
        {"role": "user", "text": "Извлеки данные с фотографии табло АЗС.", "image": {"type": "base64", "data": b64}},
    ])
    return _parse_response(raw)
```

- [ ] **Step 4: Создай `api/services/speechkit.py`**

```python
import os
import httpx

YANDEX_API_KEY = os.getenv("YANDEX_API_KEY")
YANDEX_FOLDER_ID = os.getenv("YANDEX_FOLDER_ID")
STT_URL = "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize"

async def transcribe_voice(ogg_bytes: bytes) -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            STT_URL,
            headers={"Authorization": f"Api-Key {YANDEX_API_KEY}"},
            params={"folderId": YANDEX_FOLDER_ID, "lang": "ru-RU", "format": "oggopus"},
            content=ogg_bytes,
        )
        r.raise_for_status()
        return r.json().get("result", "")
```

- [ ] **Step 5: Запусти тесты — убедись что проходят**

```bash
pytest tests/test_parser.py -v
```

- [ ] **Step 6: Коммит**

```bash
git add api/services/parser.py api/services/speechkit.py tests/test_parser.py
git commit -m "feat: YandexGPT parser and SpeechKit transcription"
```

---

## Task 4: Station Matcher — нечёткий поиск АЗС

**Files:**
- Create: `api/services/station_matcher.py`
- Create: `tests/test_station_matcher.py`

**Interfaces:**
- Consumes: `Station` модель (из Task 2), `ParsedReport` (из Task 3), `AsyncSession`
- Produces: `find_or_create_station(session, brand, alias, city, region, location) -> Station`

- [ ] **Step 1: Напиши тест**

```python
# tests/test_station_matcher.py
import pytest
from unittest.mock import AsyncMock, MagicMock
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
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)
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
```

- [ ] **Step 2: Запусти тест — убедись что падает**

```bash
pytest tests/test_station_matcher.py -v
```

- [ ] **Step 3: Создай `api/services/station_matcher.py`**

```python
from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import Station

FUZZY_THRESHOLD = 75  # минимальный score для совпадения

async def find_or_create_station(
    session: AsyncSession,
    brand: str | None,
    alias: str | None,
    city: str | None,
    region: str | None,
    location,
) -> Station:
    if alias and city:
        result = await session.execute(
            select(Station).where(Station.city == city)
        )
        candidates = result.scalars().all()
        best_match = _find_best_match(alias, candidates)
        if best_match:
            if alias not in best_match.aliases:
                best_match.aliases = best_match.aliases + [alias]
            await session.commit()
            return best_match

    station = Station(
        brand=brand or "независимая",
        aliases=[alias] if alias else [],
        city=city,
        region=region,
        location=location,
    )
    session.add(station)
    await session.commit()
    await session.refresh(station)
    return station

def _find_best_match(alias: str, candidates: list[Station]) -> Station | None:
    best_score = 0
    best = None
    for station in candidates:
        for existing_alias in station.aliases:
            score = fuzz.token_sort_ratio(alias.lower(), existing_alias.lower())
            if score > best_score:
                best_score = score
                best = station
    return best if best_score >= FUZZY_THRESHOLD else None
```

- [ ] **Step 4: Запусти тесты — убедись что проходят**

```bash
pytest tests/test_station_matcher.py -v
```

- [ ] **Step 5: Коммит**

```bash
git add api/services/station_matcher.py tests/test_station_matcher.py
git commit -m "feat: fuzzy station matching and creation"
```

---

## Task 5: Report Processor — оркестрация

**Files:**
- Create: `api/services/report_processor.py`
- Create: `tests/test_report_processor.py`

**Interfaces:**
- Consumes: `parse_text`, `parse_photo` (Task 3), `transcribe_voice` (Task 3), `find_or_create_station` (Task 4), `Report`, `StationFuelState`, `User` (Task 2)
- Produces: `process_report(session, telegram_user_id, text, image_bytes, voice_bytes, user_lat, user_lon) -> ProcessResult`
- `ProcessResult` — dataclass: `success: bool`, `station_name: str | None`, `fuels: list[FuelItem]`, `parse_failed: bool`, `message: str`

- [ ] **Step 1: Напиши тест**

```python
# tests/test_report_processor.py
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
```

- [ ] **Step 2: Запусти тест — убедись что падает**

```bash
pytest tests/test_report_processor.py -v
```

- [ ] **Step 3: Создай `api/services/report_processor.py`**

```python
from dataclasses import dataclass, field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy import select
from db.models import Report, Station, StationFuelState, User
from api.services.parser import parse_text, parse_photo, FuelItem, ParsedReport
from api.services.speechkit import transcribe_voice as _transcribe
from api.services.station_matcher import find_or_create_station
from datetime import datetime, timezone
import uuid

@dataclass
class ProcessResult:
    success: bool
    station_name: str | None
    fuels: list[FuelItem] = field(default_factory=list)
    parse_failed: bool = False
    message: str = ""

async def process_report(
    session: AsyncSession,
    telegram_user_id: int,
    text: str | None = None,
    image_bytes: bytes | None = None,
    voice_bytes: bytes | None = None,
    user_lat: float | None = None,
    user_lon: float | None = None,
) -> ProcessResult:
    await _upsert_user(session, telegram_user_id)

    source = "telegram_text"
    raw_text = text or ""

    if voice_bytes:
        source = "telegram_voice"
        raw_text = await _transcribe(voice_bytes)
        parsed = await parse_text(raw_text)
    elif image_bytes:
        source = "telegram_photo"
        parsed = await parse_photo(image_bytes)
        raw_text = "[фото]"
    else:
        parsed = await parse_text(raw_text)

    location = None
    if user_lat and user_lon:
        location = f"SRID=4326;POINT({user_lon} {user_lat})"

    station = None
    if not parsed.parse_failed:
        station = await find_or_create_station(
            session,
            brand=parsed.brand,
            alias=parsed.station_alias,
            city=None,
            region=None,
            location=location,
        )

    report = Report(
        station_id=station.id if station else None,
        telegram_user_id=telegram_user_id,
        raw_text=raw_text,
        has_photo=image_bytes is not None,
        fuels=[{"grade": f.grade, "available": f.available, "price": f.price} for f in parsed.fuels],
        user_location=location,
        confidence=parsed.confidence,
        parse_failed=parsed.parse_failed,
        source=source,
    )
    session.add(report)
    await session.commit()
    await session.refresh(report)

    if station and not parsed.parse_failed:
        await _upsert_fuel_states(session, station.id, parsed.fuels, report.id)
        await _update_station_stats(session, station)

    station_name = (station.aliases[0] if station and station.aliases else None)
    return ProcessResult(
        success=True,
        station_name=station_name,
        fuels=parsed.fuels,
        parse_failed=parsed.parse_failed,
    )

async def _upsert_user(session: AsyncSession, telegram_user_id: int):
    result = await session.execute(select(User).where(User.telegram_user_id == telegram_user_id))
    user = result.scalar_one_or_none()
    if user:
        user.report_count += 1
        user.last_seen_at = datetime.now(timezone.utc)
    else:
        session.add(User(telegram_user_id=telegram_user_id, report_count=1))
    await session.commit()

async def _upsert_fuel_states(session: AsyncSession, station_id, fuels: list[FuelItem], report_id):
    now = datetime.now(timezone.utc)
    for fuel in fuels:
        stmt = pg_insert(StationFuelState).values(
            id=uuid.uuid4(),
            station_id=station_id,
            grade=fuel.grade,
            available=fuel.available,
            price=fuel.price,
            last_report_id=report_id,
            updated_at=now,
        ).on_conflict_do_update(
            index_elements=["station_id", "grade"],
            set_={"available": fuel.available, "price": fuel.price,
                  "last_report_id": report_id, "updated_at": now},
        )
        await session.execute(stmt)
    await session.commit()

async def _update_station_stats(session: AsyncSession, station: Station):
    station.last_report_at = datetime.now(timezone.utc)
    station.report_count = (station.report_count or 0) + 1
    await session.commit()
```

Добавь уникальный индекс в миграцию для `station_fuel_states(station_id, grade)`:

```bash
alembic revision -m "unique index station_fuel_states"
```

В новой миграции:
```python
from alembic import op
def upgrade():
    op.create_unique_constraint("uq_station_fuel_grade", "station_fuel_states", ["station_id", "grade"])
def downgrade():
    op.drop_constraint("uq_station_fuel_grade", "station_fuel_states")
```

```bash
alembic upgrade head
```

- [ ] **Step 4: Запусти тесты**

```bash
pytest tests/test_report_processor.py -v
```

- [ ] **Step 5: Коммит**

```bash
git add api/services/report_processor.py tests/test_report_processor.py db/migrations/
git commit -m "feat: report processor orchestration"
```

---

## Task 6: FastAPI роуты

**Files:**
- Create: `api/schemas.py`
- Create: `api/routers/reports.py`
- Create: `api/routers/stations.py`
- Create: `api/routers/heatmap.py`
- Create: `api/routers/summary.py`
- Create: `api/main.py`
- Create: `tests/test_api.py`

**Interfaces:**
- Consumes: `process_report` (Task 5), `Station`, `StationFuelState` (Task 2), `get_db` (Task 1)
- Produces: REST API эндпоинты (см. спек)

- [ ] **Step 1: Создай `api/schemas.py`**

```python
from pydantic import BaseModel
from datetime import datetime
from uuid import UUID

class FuelStateOut(BaseModel):
    grade: str
    available: bool
    price: float | None
    updated_at: datetime
    class Config: from_attributes = True

class StationOut(BaseModel):
    id: UUID
    brand: str | None
    aliases: list[str]
    city: str | None
    region: str | None
    last_report_at: datetime | None
    fuel_states: list[FuelStateOut] = []
    class Config: from_attributes = True

class ReportIn(BaseModel):
    telegram_user_id: int
    text: str | None = None
    user_lat: float | None = None
    user_lon: float | None = None

class ReportResult(BaseModel):
    success: bool
    station_name: str | None
    parse_failed: bool
    fuels: list[dict] = []

class HeatmapRegion(BaseModel):
    region: str
    total: int
    deficit: int
    deficit_ratio: float

class SummaryItem(BaseModel):
    station_alias: str
    brand: str | None
    fuel_states: list[FuelStateOut]
```

- [ ] **Step 2: Создай `api/routers/reports.py`**

```python
from fastapi import APIRouter, Depends, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from db.database import get_db
from api.services.report_processor import process_report
from api.schemas import ReportResult

router = APIRouter(prefix="/api/reports", tags=["reports"])

@router.post("", response_model=ReportResult)
async def create_report(
    telegram_user_id: int = Form(...),
    text: str | None = Form(None),
    user_lat: float | None = Form(None),
    user_lon: float | None = Form(None),
    photo: UploadFile | None = File(None),
    voice: UploadFile | None = File(None),
    db: AsyncSession = Depends(get_db),
):
    image_bytes = await photo.read() if photo else None
    voice_bytes = await voice.read() if voice else None
    result = await process_report(
        db, telegram_user_id=telegram_user_id,
        text=text, image_bytes=image_bytes, voice_bytes=voice_bytes,
        user_lat=user_lat, user_lon=user_lon,
    )
    return ReportResult(
        success=result.success,
        station_name=result.station_name,
        parse_failed=result.parse_failed,
        fuels=[{"grade": f.grade, "available": f.available, "price": f.price} for f in result.fuels],
    )
```

- [ ] **Step 3: Создай `api/routers/stations.py`**

```python
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from db.database import get_db
from db.models import Station, StationFuelState
from api.schemas import StationOut
from uuid import UUID

router = APIRouter(prefix="/api/stations", tags=["stations"])

@router.get("", response_model=list[StationOut])
async def list_stations(
    brand: str | None = Query(None),
    grade: str | None = Query(None),
    city: str | None = Query(None),
    region: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    q = select(Station).options(selectinload(Station.fuel_states))
    if brand:
        q = q.where(Station.brand == brand)
    if city:
        q = q.where(Station.city == city)
    if region:
        q = q.where(Station.region == region)
    if grade:
        q = q.join(StationFuelState).where(StationFuelState.grade == grade)
    result = await db.execute(q)
    return result.scalars().unique().all()

@router.get("/{station_id}", response_model=StationOut)
async def get_station(station_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Station).options(selectinload(Station.fuel_states)).where(Station.id == station_id)
    )
    return result.scalar_one()
```

- [ ] **Step 4: Создай `api/routers/heatmap.py`**

```python
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession
from db.database import get_db
from db.models import Station, StationFuelState
from api.schemas import HeatmapRegion

router = APIRouter(prefix="/api/heatmap", tags=["heatmap"])

@router.get("", response_model=list[HeatmapRegion])
async def get_heatmap(
    brand: str | None = Query(None),
    grade: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    q = (
        select(
            Station.region,
            func.count(Station.id).label("total"),
            func.sum(case((StationFuelState.available == False, 1), else_=0)).label("deficit"),
        )
        .join(StationFuelState, isouter=True)
        .group_by(Station.region)
    )
    if brand:
        q = q.where(Station.brand == brand)
    if grade:
        q = q.where(StationFuelState.grade == grade)
    result = await db.execute(q)
    rows = result.all()
    return [
        HeatmapRegion(
            region=r.region or "Неизвестно",
            total=r.total,
            deficit=r.deficit or 0,
            deficit_ratio=round((r.deficit or 0) / r.total, 2) if r.total else 0,
        )
        for r in rows
    ]
```

- [ ] **Step 5: Создай `api/routers/summary.py`**

```python
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from db.database import get_db
from db.models import Station, StationFuelState
from api.schemas import SummaryItem, FuelStateOut

router = APIRouter(prefix="/api/summary", tags=["summary"])

@router.get("", response_model=list[SummaryItem])
async def get_summary(
    city: str | None = Query(None),
    brand: str | None = Query(None),
    grade: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    q = select(Station).options(selectinload(Station.fuel_states))
    if city:
        q = q.where(Station.city == city)
    if brand:
        q = q.where(Station.brand == brand)
    result = await db.execute(q)
    stations = result.scalars().unique().all()

    items = []
    for s in stations:
        fuel_states = s.fuel_states
        if grade:
            fuel_states = [fs for fs in fuel_states if fs.grade == grade]
        if not fuel_states:
            continue
        items.append(SummaryItem(
            station_alias=s.aliases[0] if s.aliases else "АЗС",
            brand=s.brand,
            fuel_states=[FuelStateOut.model_validate(fs) for fs in fuel_states],
        ))
    return items
```

- [ ] **Step 6: Создай `api/main.py`**

```python
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from api.routers import reports, stations, heatmap, summary

app = FastAPI(title="Fuel Monitor API")
app.include_router(reports.router)
app.include_router(stations.router)
app.include_router(heatmap.router)
app.include_router(summary.router)
app.mount("/", StaticFiles(directory="web", html=True), name="web")
```

- [ ] **Step 7: Напиши базовые тесты API**

```python
# tests/test_api.py
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock
from api.main import app
from api.services.report_processor import ProcessResult
from api.services.parser import FuelItem

@pytest.mark.asyncio
async def test_post_report_text():
    mock_result = ProcessResult(success=True, station_name="Лукойл", fuels=[], parse_failed=False)
    with patch("api.routers.reports.process_report", AsyncMock(return_value=mock_result)), \
         patch("api.routers.reports.get_db"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/reports", data={"telegram_user_id": 123, "text": "тест"})
    assert r.status_code == 200
    assert r.json()["success"] is True
```

- [ ] **Step 8: Запусти все тесты**

```bash
pytest tests/ -v
```

- [ ] **Step 9: Коммит**

```bash
git add api/ tests/test_api.py
git commit -m "feat: FastAPI routes for reports, stations, heatmap, summary"
```

---

## Task 7: Telegram-бот

**Files:**
- Create: `bot/handlers/report.py`
- Create: `bot/handlers/query.py`
- Create: `bot/main.py`

**Interfaces:**
- Consumes: FastAPI `/api/reports`, `/api/summary` через HTTP (httpx)
- Produces: работающий Telegram webhook-бот

- [ ] **Step 1: Создай `bot/handlers/report.py`**

```python
import os, httpx
from aiogram import Router, Bot, F, types

router = Router()
API_URL = os.getenv("API_URL", "http://api:8000")

def _format_fuels(fuels: list[dict]) -> str:
    lines = []
    for f in fuels:
        status = "✅" if f["available"] else "❌"
        price = f" {f['price']}₽/л" if f.get("price") else " (цена не указана)" if f["available"] else ""
        lines.append(f"{f['grade']}: {status}{price}")
    return "\n".join(lines) if lines else "данные не извлечены"

@router.message(F.text & ~F.text.startswith("/"))
async def handle_text_report(message: types.Message):
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{API_URL}/api/reports", data={
            "telegram_user_id": message.from_user.id,
            "text": message.text,
        })
    _reply_result(message, r.json())

@router.message(F.photo)
async def handle_photo_report(message: types.Message, bot: Bot):
    file = await bot.get_file(message.photo[-1].file_id)
    raw = await bot.download_file(file.file_path)
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{API_URL}/api/reports", data={
            "telegram_user_id": message.from_user.id,
        }, files={"photo": ("photo.jpg", raw.read(), "image/jpeg")})
    await _reply_result(message, r.json())

@router.message(F.voice)
async def handle_voice_report(message: types.Message, bot: Bot):
    file = await bot.get_file(message.voice.file_id)
    raw = await bot.download_file(file.file_path)
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{API_URL}/api/reports", data={
            "telegram_user_id": message.from_user.id,
        }, files={"voice": ("voice.ogg", raw.read(), "audio/ogg")})
    await _reply_result(message, r.json())

async def _reply_result(message: types.Message, data: dict):
    if data.get("parse_failed"):
        await message.answer("Не смог разобрать сообщение. Укажи: название АЗС, марку топлива, есть/нет?")
        return
    fuels_text = _format_fuels(data.get("fuels", []))
    station = data.get("station_name") or "АЗС"
    await message.answer(f"Принято! АЗС: {station}\n{fuels_text}\n\nСпасибо за помощь 🙏")
```

- [ ] **Step 2: Создай `bot/handlers/query.py`**

```python
import os, httpx
from aiogram import Router, types
from aiogram.filters import Command

router = Router()
API_URL = os.getenv("API_URL", "http://api:8000")
WEB_URL = os.getenv("WEBHOOK_HOST", "https://yourdomain.ru")

@router.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Fuel Monitor — мониторинг топлива на АЗС России.\n\n"
        "Чтобы сообщить о ситуации на АЗС — напиши, пришли фото табло или голосовое сообщение.\n"
        "Например: «Лукойл на Ленинском, АИ-95 есть по 79 руб, АИ-92 закончился»\n\n"
        "Команды:\n"
        "/city Казань — сводка по городу\n"
        "/map — открыть карту"
    )

@router.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(
        "Как отправить отчёт:\n"
        "• Текстом: название АЗС + марка топлива + есть/нет + цена\n"
        "• Фото: сфотографируй табло с ценами\n"
        "• Голосом: надиктуй информацию\n\n"
        "Геолокацию можно отправить вместе с сообщением — привяжем к ближайшей АЗС."
    )

@router.message(Command("map"))
async def cmd_map(message: types.Message):
    await message.answer(f"🗺 Карта АЗС: {WEB_URL}")

@router.message(Command("city"))
async def cmd_city(message: types.Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Укажи город: /city Казань")
        return
    city = parts[1].strip()
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{API_URL}/api/summary", params={"city": city})
    items = r.json()
    if not items:
        await message.answer(f"По городу {city} данных пока нет.")
        return
    lines = [f"⛽ {city} — последние отчёты:\n"]
    for item in items[:10]:
        lines.append(f"• {item['station_alias']} ({item['brand'] or 'АЗС'})")
        for fs in item["fuel_states"]:
            status = "✅" if fs["available"] else "❌"
            price = f" {fs['price']}₽/л" if fs.get("price") else ""
            from_now = _ago(fs["updated_at"])
            lines.append(f"  {fs['grade']}: {status}{price} ({from_now})")
        lines.append("")
    await message.answer("\n".join(lines))

def _ago(iso: str) -> str:
    from datetime import datetime, timezone
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    diff = int((datetime.now(timezone.utc) - dt).total_seconds() / 60)
    if diff < 60:
        return f"{diff} мин назад"
    if diff < 1440:
        return f"{diff // 60} ч назад"
    return f"{diff // 1440} дн назад"
```

- [ ] **Step 3: Создай `bot/main.py`**

```python
import asyncio, os, logging
from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from bot.handlers import report, query

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST")
WEBHOOK_PATH = "/bot"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

async def on_startup(bot: Bot):
    await bot.set_webhook(WEBHOOK_URL)

async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(report.router)
    dp.include_router(query.router)
    dp.startup.register(on_startup)

    app = web.Application()
    handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    handler.register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: Обнови `docker-compose.yml` — бот слушает на порту 8080**

В секции `bot` добавь: `ports: ["8080:8080"]`  
В nginx добавь: `location /bot { proxy_pass http://bot:8080/bot; }`

- [ ] **Step 5: Коммит**

```bash
git add bot/
git commit -m "feat: Telegram bot with text/photo/voice handlers"
```

---

## Task 8: Веб-карта

**Files:**
- Create: `web/index.html`
- Create: `web/app.js`
- Create: `web/style.css`

**Interfaces:**
- Consumes: `GET /api/stations`, `GET /api/heatmap`
- Produces: публичный дашборд с маркерами и тепловым слоем

- [ ] **Step 1: Создай `web/index.html`**

```html
<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Fuel Monitor — мониторинг топлива на АЗС России</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
  <link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css">
  <link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css">
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <div id="toolbar">
    <span class="logo">⛽ Fuel Monitor</span>
    <select id="filter-brand"><option value="">Все бренды</option></select>
    <select id="filter-grade">
      <option value="">Все марки</option>
      <option>АИ-92</option><option>АИ-95</option>
      <option>АИ-100</option><option>ДТ</option><option>ГАЗ</option>
    </select>
    <button id="btn-refresh">🔄 Обновить</button>
  </div>
  <div id="map"></div>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>
  <script src="https://unpkg.com/leaflet.heat@0.2.0/dist/leaflet-heat.js"></script>
  <script src="app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Создай `web/style.css`**

```css
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: system-ui, sans-serif; display: flex; flex-direction: column; height: 100vh; }
#toolbar { display: flex; align-items: center; gap: 12px; padding: 10px 16px; background: #1a1a2e; color: #fff; z-index: 1000; flex-shrink: 0; }
.logo { font-weight: 700; font-size: 1.1rem; margin-right: 8px; }
#toolbar select, #toolbar button { padding: 6px 10px; border-radius: 6px; border: none; cursor: pointer; font-size: 0.9rem; }
#btn-refresh { background: #4CAF50; color: white; }
#map { flex: 1; }
.popup-title { font-weight: 700; font-size: 1rem; margin-bottom: 6px; }
.fuel-row { display: flex; justify-content: space-between; gap: 16px; padding: 2px 0; font-size: 0.85rem; }
.fuel-ago { color: #888; font-size: 0.75rem; }
```

- [ ] **Step 3: Создай `web/app.js`**

```javascript
const map = L.map("map").setView([62, 95], 4);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution: "© OpenStreetMap"
}).addTo(map);

const markers = L.markerClusterGroup();
let heatLayer = null;
map.addLayer(markers);

const greenIcon = L.divIcon({className:"", html:'<div style="width:12px;height:12px;background:#4CAF50;border-radius:50%;border:2px solid white"></div>'});
const redIcon   = L.divIcon({className:"", html:'<div style="width:12px;height:12px;background:#f44336;border-radius:50%;border:2px solid white"></div>'});
const greyIcon  = L.divIcon({className:"", html:'<div style="width:12px;height:12px;background:#9e9e9e;border-radius:50%;border:2px solid white"></div>'});

function ago(iso) {
  const diff = Math.floor((Date.now() - new Date(iso)) / 60000);
  if (diff < 60) return `${diff} мин назад`;
  if (diff < 1440) return `${Math.floor(diff/60)} ч назад`;
  return `${Math.floor(diff/1440)} дн назад`;
}

function buildPopup(s) {
  const name = s.aliases[0] || "АЗС";
  const brand = s.brand || "";
  let html = `<div class="popup-title">${brand} ${name}</div>`;
  for (const fs of s.fuel_states) {
    const status = fs.available ? "✅" : "❌";
    const price  = fs.available && fs.price ? ` ${fs.price}₽/л` : fs.available ? " (цена не указана)" : "";
    html += `<div class="fuel-row"><span>${fs.grade}: ${status}${price}</span><span class="fuel-ago">${ago(fs.updated_at)}</span></div>`;
  }
  return html;
}

function stationColor(s) {
  if (!s.fuel_states.length) return greyIcon;
  const hasAny = s.fuel_states.some(f => f.available);
  return hasAny ? greenIcon : redIcon;
}

async function loadStations() {
  const brand = document.getElementById("filter-brand").value;
  const grade = document.getElementById("filter-grade").value;
  const params = new URLSearchParams();
  if (brand) params.set("brand", brand);
  if (grade) params.set("grade", grade);
  const r = await fetch(`/api/stations?${params}`);
  const stations = await r.json();

  markers.clearLayers();
  const brands = new Set();

  for (const s of stations) {
    if (s.brand) brands.add(s.brand);
    const loc = s.location;
    if (!loc) continue;
    const [lon, lat] = loc.coordinates;
    const m = L.marker([lat, lon], {icon: stationColor(s)});
    m.bindPopup(buildPopup(s));
    markers.addLayer(m);
  }

  const sel = document.getElementById("filter-brand");
  const cur = sel.value;
  sel.innerHTML = '<option value="">Все бренды</option>';
  for (const b of [...brands].sort()) {
    const opt = document.createElement("option");
    opt.value = b; opt.textContent = b;
    if (b === cur) opt.selected = true;
    sel.appendChild(opt);
  }

  await loadHeatmap(brand, grade);
}

async function loadHeatmap(brand, grade) {
  const params = new URLSearchParams();
  if (brand) params.set("brand", brand);
  if (grade) params.set("grade", grade);
  const r = await fetch(`/api/heatmap?${params}`);
  const regions = await r.json();
  if (heatLayer) map.removeLayer(heatLayer);
  // Тепловой слой по центроидам регионов (упрощённо — используем данные из БД)
  // В production заменить на реальные координаты центров субъектов РФ
  const points = regions
    .filter(r => r.deficit_ratio > 0)
    .map(r => [r._lat || 55.75, r._lon || 37.62, r.deficit_ratio]);
  heatLayer = L.heatLayer(points, {radius: 40, blur: 25, maxZoom: 6}).addTo(map);
}

document.getElementById("btn-refresh").addEventListener("click", loadStations);
document.getElementById("filter-brand").addEventListener("change", loadStations);
document.getElementById("filter-grade").addEventListener("change", loadStations);

loadStations();
setInterval(loadStations, 5 * 60 * 1000);
```

**Примечание:** тепловой слой в `app.js` использует упрощённые координаты. В следующей итерации добавь таблицу `region_centroids` с реальными координатами центров субъектов РФ и возвращай их из `/api/heatmap`.

- [ ] **Step 4: Коммит**

```bash
git add web/
git commit -m "feat: web map with markers, clustering and heatmap"
```

---

## Task 9: Деплой на FirstVDS

**Files:**
- Create: `deploy.sh`

**Interfaces:**
- Produces: работающее приложение на сервере с HTTPS

- [ ] **Step 1: На сервере — первичная настройка**

```bash
# На FirstVDS (Ubuntu 22.04)
apt update && apt install -y docker.io docker-compose-plugin certbot
systemctl enable --now docker
```

- [ ] **Step 2: Клонируй репо и настрой `.env`**

```bash
git clone <your-repo> /opt/fuel-monitor
cd /opt/fuel-monitor
cp .env.example .env
nano .env   # заполни все переменные
```

- [ ] **Step 3: Получи SSL сертификат**

```bash
# Сначала запусти только nginx на 80-м порту (без SSL блока)
docker compose up -d nginx
certbot certonly --webroot -w /var/www/certbot -d yourdomain.ru
```

- [ ] **Step 4: Запусти все сервисы**

```bash
docker compose up -d
docker compose exec api alembic upgrade head
```

- [ ] **Step 5: Проверь работоспособность**

```bash
curl https://yourdomain.ru/api/stations
# ожидаемый ответ: []

curl -X POST https://yourdomain.ru/api/reports \
  -F "telegram_user_id=123" \
  -F "text=Лукойл на Тверской, АИ-95 есть 80 руб"
# ожидаемый ответ: {"success": true, ...}
```

- [ ] **Step 6: Создай `deploy.sh` для последующих деплоев**

```bash
#!/bin/bash
set -e
cd /opt/fuel-monitor
git pull
docker compose build
docker compose up -d
docker compose exec api alembic upgrade head
echo "✅ Deployed successfully"
```

```bash
chmod +x deploy.sh
git add deploy.sh
git commit -m "feat: deployment script"
```

---

## Самопроверка плана

**Покрытие спека:**
- ✅ Фаза 0 — технический спайк (Task 0)
- ✅ Telegram-бот: текст, фото, голос (Task 7)
- ✅ YandexGPT парсинг + SpeechKit (Task 3)
- ✅ Нечёткий матчинг АЗС + псевдонимы (Task 4)
- ✅ Все 4 таблицы БД (Task 2)
- ✅ station_fuel_states с UPSERT по марке (Task 5)
- ✅ /api/reports, /api/stations, /api/heatmap, /api/summary (Task 6)
- ✅ Веб-карта с маркерами + тепловой слой + фильтры (Task 8)
- ✅ Docker Compose + Nginx + SSL (Task 1, 9)
- ⚠️ Координаты центров регионов для теплового слоя — упрощены, требуют доработки в следующей итерации
