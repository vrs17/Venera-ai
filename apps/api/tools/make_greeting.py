#!/usr/bin/env python3
"""Ovoz panelining salomlashish audiosini OLDINDAN tayyorlaydi.

NEGA OLDINDAN. Salomlashish matni o'zgarmas, sintez esa ~2 s oladi va bitta
GPU navbatida turadi. "Salom Venera" deganidan keyin odam shuncha kutib
turishi kerak emas - va uyg'otish so'zi ko'p ishlatiladigan yo'l bo'lgani
uchun har safar GPU'ni band qilish ham ma'nosiz. Fayl bir marta yasaladi,
brauzer uni statik resurs sifatida keshlaydi va ijro DARHOL boshlanadi.

Matn `apps/web/src/i18n.ts` dagi `voiceGreeting` bilan MOS bo'lishi shart -
u ekranda ko'rinadi, bu esa yangraydi.

Ishlatish (apps/api ichidan, .env da TTS_CLIENT_SECRET bo'lishi kerak):

    venv/bin/python tools/make_greeting.py
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402

#: `voiceGreeting` bilan bir xil bo'lishi SHART.
#: AYNAN foydalanuvchi bergan matn - tinish belgilari va "beraolaman" ning
#: qo'shma yozilishi ham o'zgartirilmagan (aniq talab).
GREETING = "Assalomu Alaykum. Men Venera ovozli yordamchisiman sizga qanday yordam beraolaman"
OUT = Path(__file__).resolve().parents[3] / "apps/web/src/assets/greeting-uz.wav"


def main() -> int:
    if not settings.tts_client_secret:
        print("TTS_CLIENT_SECRET yo'q - .env ni to'ldiring", file=sys.stderr)
        return 1

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call(path: str, body: dict | None = None, token: str | None = None) -> bytes:
        headers = {"Accept": "*/*"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(
            f"{settings.tts_base_url}{path}", data=data,
            method="POST" if data else "GET", headers=headers,
        )
        with opener.open(request, timeout=120) as response:
            return response.read()

    token = json.loads(call("/api/v1/auth/token", {
        "client_id": settings.tts_client_id,
        "client_secret": settings.tts_client_secret,
    }))["access_token"]

    result = json.loads(call("/api/v1/tts/generate", {
        "user_id": "greeting", "phone": "-", "text": GREETING,
        "voice_profile": settings.tts_voice, "speed": settings.tts_speed,
        # Matnda raqam yo'q, va normalizator faqat xavf qo'shadi.
        "normalize_numbers": False,
    }, token))

    # `download_url` EMAS - u `user_id` bo'yicha eng so'nggini beradi.
    name = result["audio_path"].rsplit("/", 1)[-1]
    audio = call(f"/api/v1/tts/file/{name}", token=token)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(audio)
    print(f"{OUT}  ({len(audio) // 1024} KB, {result['duration_sec']} s, "
          f"ovoz={settings.tts_voice})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
