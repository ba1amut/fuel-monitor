import os

import httpx

YANDEX_API_KEY = os.getenv("YANDEX_API_KEY")
YANDEX_FOLDER_ID = os.getenv("YANDEX_FOLDER_ID")
STT_URL = "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize"


async def transcribe_voice(ogg_bytes: bytes) -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            STT_URL,
            headers={"Authorization": f"Api-Key {YANDEX_API_KEY}"},
            params={"folderId": YANDEX_FOLDER_ID, "lang": "ru-RU", "format": "oggopus"},
            content=ogg_bytes,
        )
        r.raise_for_status()
        return r.json().get("result", "")
