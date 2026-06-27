import os
import httpx
from aiogram import Router, Bot, F, types

router = Router()
API_URL = os.getenv("API_URL", "http://api:8000")


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
    await _reply_result(message, r.json())


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
    await _reply_result(message, r.json())


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
    await _reply_result(message, r.json())
