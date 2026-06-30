# Fuel Monitor — Отчёт по разработке, июнь 2026

## 1. Обзор фазы

**Период**: июнь 2026  
**Цель фазы**: запуск MVP краудсорсинговой карты АЗС с Telegram-ботом для сбора данных о наличии и ценах топлива.

Фаза охватывает полный цикл: от проектного спайка через реализацию ядра системы до первого деплоя с реальными данными (6 станций в Ессентуках).

---

## 2. Архитектура системы

```
Telegram пользователь
        │
        ▼
  ┌─────────────┐        ┌──────────────────┐
  │  aiogram    │───────▶│   FastAPI API    │
  │    bot      │  http  │  port 8000/8001  │
  └─────────────┘        └────────┬─────────┘
                                  │ SQLAlchemy async
                                  ▼
                         ┌──────────────────┐
                         │  PostgreSQL +    │
                         │    PostGIS       │
                         └──────────────────┘

  Внешние сервисы:
  ├── Yandex Vision OCR  (фото → текст)
  ├── YandexGPT          (текст → JSON)
  ├── Yandex SpeechKit   (голос → текст)
  └── Nominatim OSM      (GPS → город)
```

**Docker Compose**:
| Сервис | Образ | Порт |
|--------|-------|------|
| `db`   | postgis/postgis:15-3.4 | 5432 |
| `api`  | Python 3.11 / FastAPI  | 8001→8000 |
| `bot`  | Python 3.11 / aiogram  | 8080 |

**Домен**: `fuel.weatherpath.ru` (nginx → api:8001)

---

## 3. Реализованные функции

### 3.1 Telegram-бот

| Тип сообщения | Поведение |
|---|---|
| Текст | Парсинг через YandexGPT → сохранение станции и цен |
| Фото | Yandex Vision OCR → YandexGPT → сохранение |
| Голос | Yandex SpeechKit (транскрипция) → YandexGPT → сохранение |
| Геолокация (кнопка) | Обновление GPS станции + определение города |
| `/near` | Поиск АЗС в радиусе 50 км по GPS (PostGIS) |

После каждого отчёта бот предлагает уточнить местоположение:
- кнопка «📍 Поделиться геолокацией» (Telegram native)
- ссылка на `pick.html` — пикер на Leaflet-карте

### 3.2 AI/NLP пайплайн обработки отчёта

```
Текст/голос:
  пользовательское сообщение
        │
        ▼
  YandexGPT (SYSTEM_PROMPT)
        │
        ▼
  ParsedReport { station_alias, brand, city, fuels[], confidence }
        │
        ▼
  find_or_create_station → Station в БД

Фото:
  image_bytes
        │
        ▼
  Yandex Vision OCR → raw_text
        │
        ▼
  YandexGPT (OCR_PARSE_PROMPT)
        │
        ▼
  ParsedReport → Station в БД
```

**Порог уверенности**: `confidence < 0.5` → `parse_failed = True`, станция не создаётся.

### 3.3 Матчинг и создание станций

`find_or_create_station` работает в три шага:

1. **Нечёткий поиск по городу** — среди станций с тем же городом, threshold 75% (rapidfuzz)
2. **Фолбэк на станции без города** — если нашли совпадение, проставляем город
3. **Создание новой станции** — если совпадений нет; при наличии GPS → reverse geocoding

### 3.4 Reverse Geocoding

Автоматическое определение города по GPS через **Nominatim (OpenStreetMap)**:
- вызывается при создании новой станции, если `city=None` и GPS есть
- вызывается при `PATCH /location`, если у станции ещё нет города
- fallback-цепочка: `city → town → village`
- бесплатно, без API-ключа, rate limit 1 req/s

### 3.5 REST API

| Метод | Путь | Описание |
|-------|------|----------|
| `POST` | `/api/reports` | Принять отчёт (text/photo/voice + GPS) |
| `GET`  | `/api/stations` | Список станций (фильтры: brand, grade, city, region) |
| `GET`  | `/api/stations/nearby` | Ближайшие АЗС по GPS (PostGIS, radius_km, limit) |
| `GET`  | `/api/stations/{id}` | Карточка станции |
| `PATCH`| `/api/stations/{id}/location` | Установить GPS + автогеокодинг города |
| `POST` | `/api/stations/{src}/merge-into/{tgt}` | Слияние дублей (X-Admin-Key) |
| `GET`  | `/api/summary` | Сводка топлива по станциям (city, brand, grade) |
| `GET`  | `/api/heatmap` | Дефицит по регионам (агрегат для тепловой карты) |

### 3.6 Web-карта

Статический фронтенд (`/web/`):
- `index.html` — Leaflet-карта с маркерами станций и тепловой картой по регионам
- `pick.html` — пикер локации: пользователь ставит булавку → `PATCH /location`
- Кластеризация маркеров при большом зуме
- Для станций без GPS — приближённые координаты по центроидам города

### 3.7 Данные (состояние на конец фазы)

- 6 станций в Ессентуках (после слияния 16 дублей)
- Город проставлен у всех станций
- Выполнена чистка данных: SQL UPDATE + 11 merge-операций через admin endpoint

---

## 4. Технический стек

| Компонент | Технология |
|---|---|
| API фреймворк | FastAPI 0.111 |
| ORM | SQLAlchemy 2.x async (asyncpg) |
| БД | PostgreSQL 15 + PostGIS 3.4 |
| Telegram-бот | aiogram 3.x |
| HTTP-клиент | httpx |
| Нечёткий поиск | rapidfuzz |
| Геометрия | GeoAlchemy2 + Shapely |
| Миграции | Alembic |
| Тесты | pytest-asyncio |
| OCR | Yandex Vision API |
| NLP | YandexGPT (yandexgpt/latest) |
| Речь | Yandex SpeechKit |
| Геокодинг | Nominatim (OpenStreetMap) |
| Контейнеризация | Docker Compose |
| Прокси | nginx (host) |

---

## 5. План vs Реализация

### Реализовано ✅

| Задача | Коммит |
|--------|--------|
| Скаффолдинг проекта, Docker Compose | `3d7e639` |
| Модели БД, миграции Alembic | `1eaf3d8` |
| YandexGPT парсер + SpeechKit | `b983d1c` |
| FastAPI роуты (reports, stations, heatmap, summary) | `cc66ec9` |
| Fuzzy-матчинг станций (rapidfuzz) | `3122fce` |
| Веб-карта Leaflet с маркерами и кластеризацией | `6b21fb3` |
| Telegram-бот (текст/фото/голос) | `d624e93` |
| Атомарные транзакции + guard размера файла | `a505456` |
| Извлечение города из GPT-ответа | `37f2a28` |
| Запрос геолокации после отчёта + PATCH location | `00a1962` |
| Полная карточка станции после отчёта | `08c9d0f` |
| Центроиды городов (fallback маркер без GPS) | `d438c70` |
| Map picker (pick.html) + inline-кнопка | `255b11c` |
| Admin merge endpoint + station_id в попапе | `8331555` |
| Команда `/near` (PostGIS proximity) | `9896014` |
| Гибридный пайплайн фото: OCR + YandexGPT | `db5c9b5` |
| Исправление матчера: двухшаговый поиск + city backfill | `8e915a3` |
| Reverse geocoding модуль (Nominatim) | `4a4cdd5` |
| Геокодинг на PATCH /location | `73672f7` |
| Чистка данных: 16 → 6 станций, city = Ессентуки | ручная операция |

### Отложено / не реализовано ❌

| Задача | Причина |
|--------|---------|
| DeepSeek Vision для фото | API deepseek.com не поддерживает vision; гибрид OCR+YandexGPT оставлен как решение |
| Геокодинг при матче cityless-станции с GPS | `Station.location` возвращается как `WKBElement`, требует `geoalchemy2.shape.to_shape()` — отдельная задача |
| LED-дисплеи на ценовых табло | Yandex Vision OCR не читает 7-segment дисплеи; решение — переход на LLM с vision (OpenAI GPT-4o-mini) — отложено |
| Перенос на сервер FirstVDS | Деплой заблокирован Telegram API на текущем сервере; перенос запланирован отдельно |

---

## 6. Аудит кода (июнь 2026)

Проведён статический анализ всех Python-файлов. Итого: **5 критических** / **11 важных** / **8 незначительных**.

### Критические

| Файл | Проблема | Рекомендация |
|------|----------|--------------|
| `db/models.py` | Нет индекса на `Station.city` — seq scan при каждом городском запросе | Добавить `Index("ix_stations_city", "city")` в модель и миграцию |
| `db/models.py` | Нет GIST-индекса на `Station.location` — PostGIS не использует spatial index | `Index("ix_stations_location", "location", postgresql_using="gist")` |
| `db/models.py` | Не проверен UniqueConstraint на `(station_id, grade)` в `StationFuelState` — без него `ON CONFLICT` в `_upsert_fuel_states` упадёт в рантайме | Проверить миграции; добавить если нет |
| `stations.py:97-111` | `reverse_geocode` (httpx, до 10 сек) вызывается внутри открытой транзакции — держит соединение из пула всё время HTTP-запроса | Переместить geocoder-вызов до `db.execute` или после `db.commit` |
| `station_matcher.py:59-62` | То же: `reverse_geocode` внутри сессии при создании станции | Вынести geocoder до начала транзакции или передавать `city` снаружи |

### Важные

| Файл | Проблема |
|------|----------|
| `report_processor.py` | 3-4 `commit()` на один отчёт (`_upsert_user` + `find_or_create_station` × 2 + финальный). Нужен один коммит в конце |
| `station_matcher.py:32-54` | Два SELECT на всю таблицу без LIMIT при каждом матчинге. Растёт линейно с числом станций |
| `db/models.py` | Нет индекса на `Report.station_id` (FK без автоиндекса в PostgreSQL) |
| `db/models.py` | Нет индексов на `Station.brand`, `Station.region` (используются в WHERE/GROUP BY) |
| `parser.py` | Новый `httpx.AsyncClient` на каждый вызов OCR/GPT — множество TCP-соединений без пула |
| `geocoder.py` | Новый `AsyncClient` + HTTP-запрос к Nominatim без кэша; результат для тех же координат всегда одинаков — нужен `lru_cache` по `(round(lat,2), round(lon,2))` |
| `bot/handlers/report.py` | Новый `AsyncClient` на каждый апдейт Telegram-бота; нужен singleton или aiogram lifespan |
| `schemas.py:38` | `except Exception: loc = None` без логирования — битая геометрия в БД останется незамеченной |
| `bot/handlers/report.py` | `_fetch_full_station` проглатывает все исключения без логирования |
| `bot/handlers/report.py` | `if not r.is_success` без логирования статуса/тела — отладка в проде невозможна |
| `report_processor.py` | Нет `try/except` вокруг `_upsert_fuel_states` — constraint violation → 500 без объяснений |

### Незначительные

- `stations.py:111-114`: повторный SELECT вместо `await db.refresh(station)`
- `report_processor.py:74`: `refresh(report)` сразу после `flush` — лишний round-trip
- `stations.py:41-44`, `summary.py:29-31`: in-memory фильтрация `fuel_states` по grade вместо SQL
- `heatmap.py:26`: `== False` вместо `.is_(False)` в SQLAlchemy-выражении
- `stations.py:108`, `station_matcher.py:61`: `except Exception` без `exc_info=True` — причина ошибки теряется
- Кэш ответов YandexGPT для одинаковых текстов (дублирующие отчёты — повторные платные вызовы)
- HTTP `Cache-Control` на `/api/summary` и `/api/heatmap` (данные меняются редко)

---

## 7. Известные ограничения

1. **LED-дисплеи**: Yandex Vision OCR не читает электронные ценовые табло с 7-segment дисплеями. Парсер распознаёт марки топлива, но цены теряет. Решение — vision LLM (GPT-4o-mini и аналоги), отложено.

2. **Геокодинг cityless-матча**: если в базе уже есть станция без города, но с GPS, и новый отчёт на неё совпадает — геокодинг для неё не вызывается. Нужен `geoalchemy2.shape.to_shape()` для WKBElement.

3. **Telegram API на текущем сервере**: бот работает через webhook, но текущий российский сервер имеет блокировку `api.telegram.org` на уровне провайдера. Решение — перенос на зарубежный сервер (FirstVDS), запланирован.

4. **Один город в базе**: все тестовые данные — Ессентуки. Матчер не тестировался на межгородских сценариях.

---

## 8. Следующие шаги (беклог)

### P0 — критические для стабильности
- [ ] Добавить индексы `city`, `region`, `brand` в модели + миграцию
- [ ] Добавить GIST-индекс на `location`
- [ ] Вынести `reverse_geocode` из-под транзакции (stations.py + station_matcher.py)
- [ ] Один финальный `commit` в `process_report` (убрать промежуточные)

### P1 — важные для производительности
- [ ] Кэш geocoder: `lru_cache` по округлённым координатам
- [ ] Singleton `httpx.AsyncClient` для YandexGPT/OCR/SpeechKit
- [ ] Singleton httpx в боте (aiogram lifespan)
- [ ] Логирование в `_fetch_full_station` и `except` блоках

### P2 — улучшения
- [ ] Геокодинг cityless-матча через `geoalchemy2.shape.to_shape()`
- [ ] Vision LLM для LED-дисплеев (GPT-4o-mini или YandexGPT Vision)
- [ ] Перенос на зарубежный сервер (Telegram доступен)
- [ ] In-memory → SQL фильтрация `fuel_states` по grade

---

*Документ сформирован: 2026-07-01*  
*Версия кода: коммит `73672f7`*
