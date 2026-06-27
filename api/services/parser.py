import json
import base64
import os
from dataclasses import dataclass, field

import httpx

YANDEX_API_KEY = os.getenv("YANDEX_API_KEY")
YANDEX_FOLDER_ID = os.getenv("YANDEX_FOLDER_ID")
GPT_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
OCR_URL = "https://ocr.api.cloud.yandex.net/ocr/v1/recognizeText"
CONFIDENCE_THRESHOLD = 0.5

SYSTEM_PROMPT = """Ты парсер отчётов об АЗС. Извлеки из сообщения пользователя данные и верни ТОЛЬКО валидный JSON без пояснений:
{
  "station_alias": "название или ориентир АЗС или null",
  "brand": "сеть АЗС (Лукойл/Роснефть/Газпромнефть/Татнефть/независимая/null)",
  "fuels": [{"grade": "АИ-92|АИ-95|АИ-100|ДТ|ГАЗ", "available": true/false, "price": число или null}],
  "confidence": число от 0 до 1
}
Если данных недостаточно — ставь низкий confidence."""

OCR_SYSTEM_PROMPT = """Ты парсер текста с ценового табло АЗС, распознанного через OCR.
Правила:
1. Извлеки марки топлива (АИ-92, АИ-95, АИ-100, ДТ, ГАЗ и аналоги).
2. Цена всегда указана в той же строке что и марка топлива. Число в той же строке — это цена за литр.
3. Если у марки есть цена — available: true, price: число.
4. Если марка упомянута, но цены в той же строке нет — available: false, price: null.
5. Игнорируй маркетинговые названия: ЭКТО, PULSAR, ULTIMATE, G-Drive и подобные — это суббренды, не марки топлива.
6. Не выдумывай данные которых нет в тексте.
Ответь ТОЛЬКО валидным JSON: {"station_alias": "...", "brand": "...", "fuels": [...], "confidence": 0.9}"""


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


async def _call_ocr(image_bytes: bytes) -> str:
    """Call Yandex Vision OCR and return extracted text."""
    b64 = base64.b64encode(image_bytes).decode()
    async with httpx.AsyncClient(timeout=90) as client:
        r = await client.post(
            OCR_URL,
            headers={
                "Authorization": f"Api-Key {YANDEX_API_KEY}",
                "x-folder-id": YANDEX_FOLDER_ID or "",
            },
            json={
                "mimeType": "JPEG",
                "languageCodes": ["ru", "en"],
                "content": b64,
            },
        )
        r.raise_for_status()
        data = r.json()
        blocks = (
            data.get("result", {})
            .get("textAnnotation", {})
            .get("blocks", [])
        )
        lines: list[str] = []
        for block in blocks:
            for line in block.get("lines", []):
                text = line.get("text", "").strip()
                if text:
                    lines.append(text)
        return "\n".join(lines)


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
        return ParsedReport(
            station_alias=None, brand=None, fuels=[], confidence=0.0, parse_failed=True
        )


async def parse_text(text: str) -> ParsedReport:
    raw = await _call_yandex_gpt([
        {"role": "system", "text": SYSTEM_PROMPT},
        {"role": "user", "text": text},
    ])
    return _parse_response(raw)


async def parse_photo(image_bytes: bytes) -> ParsedReport:
    """Parse a fuel price board photo using OCR + YandexGPT pipeline."""
    # Step A: extract text via Yandex Vision OCR
    ocr_text = await _call_ocr(image_bytes)

    # Step B: parse the extracted text with a specialised OCR prompt
    raw = await _call_yandex_gpt([
        {"role": "system", "text": OCR_SYSTEM_PROMPT},
        {"role": "user", "text": ocr_text},
    ])
    return _parse_response(raw)
