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
