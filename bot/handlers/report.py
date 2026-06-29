import os
import logging
import httpx
from aiogram import Router, Bot, F, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove

router = Router()
API_URL = os.getenv("API_URL", "http://api:8000")
WEB_URL = os.getenv("WEBHOOK_HOST", "https://fuel.weatherpath.ru")


def _location_keyboard(station_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="🗺 Указать место на карте",
            url=f"{WEB_URL}/pick.html?station={station_id}",
        )
    ]])


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
        await message.answer(
            "Укажи точное место АЗС на карте:",
            reply_markup=_location_keyboard(station_id),
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
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{API_URL}/api/reports", data={
            "telegram_user_id": message.from_user.id,
        }, files={"photo": ("photo.jpg", image_bytes, "image/jpeg")})
    if not r.is_success:
        await message.answer("Ошибка сервера. Попробуй позже.")
        return
    r_data = r.json()
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


