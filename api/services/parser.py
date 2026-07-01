import json
import re
import base64
import os
import logging
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
  "city": "город из сообщения или null",
  "fuels": [{"grade": "АИ-92|АИ-95|АИ-100|ДТ|ГАЗ", "available": true/false, "price": число или null}],
  "confidence": число от 0 до 1
}
Если данных недостаточно — ставь низкий confidence."""

OCR_PARSE_PROMPT = """Ты парсер текста с ценового табло АЗС, распознанного через OCR.
Правила:
1. Извлеки марки топлива (АИ-92, АИ-95, АИ-100, ДТ, ГАЗ и аналоги).
2. Цена всегда в той же строке что и марка. Если есть — available: true, price: число (за литр).
3. Если марка есть, цены нет — available: false, price: null.
4. Игнорируй маркетинговые суббренды: ЭКТО, PULSAR, ULTIMATE, G-Drive — это не марки топлива.
5. Если виден бренд или название АЗС — укажи в station_alias/brand. Если нет — null.
6. Не выдумывай данные которых нет в тексте.
Ответь ТОЛЬКО валидным JSON без пояснений. Используй поле "grade" (не "fuel_type", не "type", не "name").
Пример: {"station_alias": "Октан", "brand": "независимая", "city": null, "fuels": [{"grade": "АИ-95", "available": true, "price": 79.5}, {"grade": "АИ-92", "available": false, "price": null}], "confidence": 0.9}"""


@dataclass
class FuelItem:
    grade: str
    available: bool
    price: float | None = None


@dataclass
class ParsedReport:
    station_alias: str | None
    brand: str | None
    city: str | None
    fuels: list[FuelItem] = field(default_factory=list)
    confidence: float = 0.0
    parse_failed: bool = False


async def _call_yandex_gpt(messages: list[dict]) -> str:
    async with httpx.AsyncClient(timeout=60) as client:
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
    """Extract text from image via Yandex Vision OCR."""
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
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r'^```[a-z]*\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw).strip()
    try:
        data = json.loads(raw)
        raw_fuels = data.get("fuels", [])
        fuels = [
            FuelItem(
                grade=f.get("grade") or f.get("fuel_type") or f.get("type") or f.get("name") or "?",
                available=f.get("available", False),
                price=f.get("price"),
            )
            for f in raw_fuels
        ]
        raw_conf = data.get("confidence")
        if raw_conf is None:
            confidence = 0.9 if data.get("fuels") else 0.0
        else:
            confidence = float(raw_conf)
        return ParsedReport(
            station_alias=data.get("station_alias"),
            brand=data.get("brand"),
            city=data.get("city"),
            fuels=fuels,
            confidence=confidence,
            parse_failed=confidence < CONFIDENCE_THRESHOLD,
        )
    except Exception as exc:
        logging.warning("Failed to parse GPT response: %s | raw=%r", exc, raw)
        return ParsedReport(
            station_alias=None, brand=None, city=None, fuels=[], confidence=0.0, parse_failed=True
        )


async def parse_text(text: str) -> ParsedReport:
    raw = await _call_yandex_gpt([
        {"role": "system", "text": SYSTEM_PROMPT},
        {"role": "user", "text": text},
    ])
    return _parse_response(raw)


async def parse_photo(image_bytes: bytes) -> ParsedReport:
    """Parse a fuel price board photo: Yandex Vision OCR → YandexGPT text parse."""
    ocr_text = await _call_ocr(image_bytes)
    logging.info("OCR extracted text (%d chars): %r", len(ocr_text), ocr_text[:300])
    if not ocr_text.strip():
        logging.warning("OCR returned empty text — photo unreadable")
        return ParsedReport(
            station_alias=None, brand=None, city=None, fuels=[], confidence=0.0,
            parse_failed=True,
        )
    raw = await _call_yandex_gpt([
        {"role": "system", "text": OCR_PARSE_PROMPT},
        {"role": "user", "text": ocr_text},
    ])
    return _parse_response(raw)
