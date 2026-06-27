import os
import httpx
from datetime import datetime, timezone
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
    if not r.is_success:
        await message.answer(f"Не удалось получить данные по городу {city}.")
        return
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
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    diff = int((datetime.now(timezone.utc) - dt).total_seconds() / 60)
    if diff < 60:
        return f"{diff} мин назад"
    if diff < 1440:
        return f"{diff // 60} ч назад"
    return f"{diff // 1440} дн назад"
