import os
import logging
import httpx
from aiogram import Router, Bot, F, types
from aiogram.filters import Command
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove

router = Router()
API_URL = os.getenv("API_URL", "http://api:8000")
WEB_URL = os.getenv("WEBHOOK_HOST", "https://fuel.weatherpath.ru")

# user_id -> station_id — ожидание геолокации от кнопки "Поделиться"
_pending_location: dict[int, str] = {}

# user_id -> True — ожидание геолокации от /near команды
_pending_query: dict[int, bool] = {}


def _location_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📍 Поделиться геолокацией", request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


async def _download_tg_file(bot: Bot, file_path: str) -> bytes:
    url = f"https://api.telegram.org/file/bot{bot.token}/{file_path}"
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.content


def _format_fuels(fuels: list[dict]) -> str:
    lines = []
    for f in fuels:
        status = "✅" if f["available"] else "❌"
        price = f" {f['price']}₽/л" if f.get("price") else " (цена не указана)" if f["available"] else ""
        lines.append(f"{f['grade']}: {status}{price}")
    return "\n".join(lines) if lines else "данные не извлечены"


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


def _format_fuels_fallback(r_data: dict) -> str:
    station_name = r_data.get("station_name") or "АЗС"
    fuels_text = _format_fuels(r_data.get("fuels", []))
    return f"Принято! АЗС: {station_name}\n{fuels_text}\n\nСпасибо за помощь 🙏"


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


@router.message(Command("near"))
async def handle_near_command(message: types.Message):
    _pending_query[message.from_user.id] = True
    await message.answer(
        "Поделись геолокацией — покажу АЗС рядом с тобой.",
        reply_markup=_location_keyboard(),
    )


async def _handle_report_response(message: types.Message, r_data: dict):
    """Common logic after receiving r_data from POST /api/reports."""
    if r_data.get("parse_failed"):
        await message.answer("Не смог разобрать сообщение. Укажи: название АЗС, марку топлива, есть/нет?")
        return

    station_id = r_data.get("station_id")

    if station_id:
        full = await _fetch_full_station(station_id)
        reply_text = _format_full_station(full) if full else _format_fuels_fallback(r_data)
    else:
        reply_text = _format_fuels_fallback(r_data)

    await message.answer(reply_text)

    if station_id:
        map_url = f"{WEB_URL}/pick.html?station={station_id}"
        _pending_location[message.from_user.id] = station_id
        await message.answer(
            f"Укажи место АЗС — это поможет отобразить её на карте.\n"
            f"📍 Кнопка ниже — если ты сейчас там\n"
            f"🗺 <a href='{map_url}'>Выбрать на карте</a> — если пишешь по памяти",
            reply_markup=_location_keyboard(),
            parse_mode="HTML",
        )


@router.message(F.text & ~F.text.startswith("/"))
async def handle_text_report(message: types.Message):
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{API_URL}/api/reports", data={
            "telegram_user_id": message.from_user.id,
            "text": message.text,
        })
    if not r.is_success:
        await message.answer("Ошибка сервера. Попробуй позже.")
        return
    r_data = r.json()
    await _handle_report_response(message, r_data)


@router.message(F.photo)
async def handle_photo_report(message: types.Message, bot: Bot):
    file = await bot.get_file(message.photo[-1].file_id)
    if file.file_size and file.file_size > 5_000_000:
        await message.answer("Фото слишком большое. Пришли фото меньше 5 МБ.")
        return
    image_bytes = await _download_tg_file(bot, file.file_path)
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(f"{API_URL}/api/reports", data={
                "telegram_user_id": message.from_user.id,
            }, files={"photo": ("photo.jpg", image_bytes, "image/jpeg")})
    except httpx.TimeoutException:
        await message.answer("Сервер долго не отвечал. Попробуй ещё раз или напиши текстом.")
        return
    if not r.is_success:
        await message.answer("Ошибка сервера. Попробуй позже.")
        return
    r_data = r.json()
    if r_data.get("parse_failed"):
        await message.answer(
            "Не удалось распознать данные с фото.\n\n"
            "Убедись что на снимке чётко видно ценовое табло АЗС.\n"
            "Или напиши текстом: «Лукойл АИ-95 79р есть»"
        )
        return
    await _handle_report_response(message, r_data)


@router.message(F.voice)
async def handle_voice_report(message: types.Message, bot: Bot):
    file = await bot.get_file(message.voice.file_id)
    if file.file_size and file.file_size > 5_000_000:
        await message.answer("Голосовое сообщение слишком длинное.")
        return
    voice_bytes = await _download_tg_file(bot, file.file_path)
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{API_URL}/api/reports", data={
            "telegram_user_id": message.from_user.id,
        }, files={"voice": ("voice.ogg", voice_bytes, "audio/ogg")})
    if not r.is_success:
        await message.answer("Ошибка сервера. Попробуй позже.")
        return
    r_data = r.json()
    await _handle_report_response(message, r_data)


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
