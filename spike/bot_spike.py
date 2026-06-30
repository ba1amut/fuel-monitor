import asyncio, base64, os, httpx, logging, io
from PIL import Image
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.client.session.aiohttp import AiohttpSession

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
YANDEX_API_KEY = os.getenv("YANDEX_API_KEY")
YANDEX_FOLDER_ID = os.getenv("YANDEX_FOLDER_ID")

bot = Bot(token=BOT_TOKEN, session=AiohttpSession(timeout=60))
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
        if not r.is_success:
            logging.error(f"YandexGPT error {r.status_code}: {r.text}")
            r.raise_for_status()
        return r.json()["result"]["alternatives"][0]["message"]["text"]

def compress_image(image_bytes: bytes, max_size: int = 1280) -> bytes:
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    img.thumbnail((max_size, max_size), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    compressed = buf.getvalue()
    logging.info(f"Image compressed: {len(image_bytes)//1024}KB → {len(compressed)//1024}KB")
    return compressed

async def ocr_photo(image_bytes: bytes) -> str:
    """Yandex Vision OCR — извлекает текст с фото, затем GPT парсит результат."""
    b64 = base64.b64encode(image_bytes).decode()
    logging.info(f"Image size for OCR: {len(image_bytes)//1024}KB")
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://ocr.api.cloud.yandex.net/ocr/v1/recognizeText",
            headers={"Authorization": f"Api-Key {YANDEX_API_KEY}", "x-folder-id": YANDEX_FOLDER_ID},
            json={
                "mimeType": "JPEG",
                "languageCodes": ["ru", "en"],
                "content": b64,
            },
            timeout=90,
        )
        if not r.is_success:
            logging.error(f"Vision OCR error {r.status_code}: {r.text}")
            r.raise_for_status()
        # Собираем весь текст из блоков
        blocks = r.json().get("result", {}).get("textAnnotation", {}).get("blocks", [])
        lines = []
        for block in blocks:
            for line in block.get("lines", []):
                lines.append(line.get("text", ""))
        return "\n".join(lines)

async def transcribe_voice(ogg_bytes: bytes) -> str:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize",
            headers={"Authorization": f"Api-Key {YANDEX_API_KEY}"},
            params={"folderId": YANDEX_FOLDER_ID, "lang": "ru-RU", "format": "oggopus"},
            content=ogg_bytes,
            timeout=30,
        )
        if not r.is_success:
            logging.error(f"SpeechKit error {r.status_code}: {r.text}")
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

async def download_tg_file(file_path: str) -> bytes:
    url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.content

@dp.message(F.photo)
async def handle_photo(message: types.Message):
    file = await bot.get_file(message.photo[-1].file_id)
    image_bytes = await download_tg_file(file.file_path)
    # Шаг 1: OCR — извлекаем текст с фото
    ocr_text = await ocr_photo(image_bytes)
    logging.info(f"OCR result: {ocr_text!r}")
    if not ocr_text.strip():
        await message.answer("❌ Не удалось извлечь текст с фото. Попробуй более чёткое фото табло.")
        return
    # Шаг 2: GPT парсит извлечённый текст
    result = await call_yandex_gpt([
        {"role": "system", "text": """Ты парсер текста с ценового табло АЗС, распознанного через OCR.
Правила:
1. Извлеки марки топлива (АИ-92, АИ-95, АИ-100, ДТ, D, ГАЗ, СУГ и аналоги).
2. Цена всегда указана в той же строке что и марка топлива. Число в той же строке — это цена за литр.
3. Если у марки есть цена — available: true, price: число.
4. Если марка упомянута, но цены в той же строке нет — available: false, price: null (топливо отсутствует).
4. Игнорируй маркетинговые названия: ЭКТО, PULSAR, ULTIMATE, G-Drive и подобные — это суббренды, не марки топлива.
5. Не выдумывай данные которых нет в тексте.
Ответь ТОЛЬКО валидным JSON:
{"station_alias": "...", "brand": "...", "fuels": [{"grade": "АИ-95", "available": true, "price": 78.8}], "confidence": 0.9}"""},
        {"role": "user", "text": ocr_text},
    ])
    await message.answer(f"✅ Фото (OCR → GPT):\n\nТекст с фото:\n{ocr_text}\n\nРаспознано:\n{result}")

@dp.message(F.voice)
async def handle_voice(message: types.Message):
    file = await bot.get_file(message.voice.file_id)
    voice_bytes = await download_tg_file(file.file_path)
    transcript = await transcribe_voice(voice_bytes)
    result = await call_yandex_gpt([
        {"role": "system", "text": "Извлеки из текста: название АЗС, марки топлива, наличие, цену. Ответь в формате JSON."},
        {"role": "user", "text": transcript},
    ])
    await message.answer(f"✅ Голос → текст: {transcript}\n\nРаспознано:\n{result}")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
