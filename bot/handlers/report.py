import os
import httpx
from aiogram import Router, Bot, F, types
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove

router = Router()
API_URL = os.getenv("API_URL", "http://api:8000")

# user_id -> station_id (str UUID) — хранит ожидание геолокации между webhook-вызовами
_pending_location: dict[int, str] = {}


def _location_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Поделиться геолокацией", request_location=True)]],
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


async def _reply_result(message: types.Message, data: dict):
    if data.get("parse_failed"):
        await message.answer("Не смог разобрать сообщение. Укажи: название АЗС, марку топлива, есть/нет?")
        return
    fuels_text = _format_fuels(data.get("fuels", []))
    station = data.get("station_name") or "АЗС"
    await message.answer(f"Принято! АЗС: {station}\n{fuels_text}\n\nСпасибо за помощь 🙏")


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
    await _reply_result(message, r_data)
    if r_data.get("station_id"):
        _pending_location[message.from_user.id] = r_data["station_id"]
        await message.answer(
            "Укажи местоположение АЗС — это поможет отобразить её на карте.",
            reply_markup=_location_keyboard(),
        )


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
    await _reply_result(message, r_data)
    if r_data.get("station_id"):
        _pending_location[message.from_user.id] = r_data["station_id"]
        await message.answer(
            "Укажи местоположение АЗС — это поможет отобразить её на карте.",
            reply_markup=_location_keyboard(),
        )


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
    await _reply_result(message, r_data)
    if r_data.get("station_id"):
        _pending_location[message.from_user.id] = r_data["station_id"]
        await message.answer(
            "Укажи местоположение АЗС — это поможет отобразить её на карте.",
            reply_markup=_location_keyboard(),
        )


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
