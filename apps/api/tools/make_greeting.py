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

import sys

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.services.tts import TtsClient  # noqa: E402

#: `voiceGreeting` bilan bir xil bo'lishi SHART.
#: AYNAN foydalanuvchi bergan matn - tinish belgilari va "beraolaman" ning
#: qo'shma yozilishi ham o'zgartirilmagan (aniq talab).
GREETING = "Assalomu Alaykum. Men Venera ovozli yordamchisiman sizga qanday yordam beraolaman"
OUT = Path(__file__).resolve().parents[3] / "apps/web/src/assets/greeting-uz.wav"


def main() -> int:
    if not settings.tts_client_secret:
        print("TTS_CLIENT_SECRET yo'q - .env ni to'ldiring", file=sys.stderr)
        return 1

    client = TtsClient(
        settings.tts_base_url,
        settings.tts_client_id,
        settings.tts_client_secret,
        timeout=settings.tts_timeout,
    )
    # `synthesize_wav` oqimni to'liq yig'ib, HAQIQIY uzunlikli sarlavha
    # yozadi. Serverning `format=wav` i buni bermaydi - u oqim boshida
    # umumiy uzunlikni bilmagani uchun `0xFFFFFFFF` yozadi va pleyerlar
    # davomiylikni 74 soat deb ko'rsatadi. Bu yerda kutish muhim emas,
    # sarlavhaning to'g'riligi esa muhim: fayl saytga tushadi.
    audio = client.synthesize_wav(
        GREETING,
        voice=settings.tts_voice,
        speed=settings.tts_speed,
        normalize_numbers=False,   # matnda raqam yo'q, normalizator faqat xavf
        max_chars=len(GREETING) + 1,
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(audio)
    frames = (len(audio) - 44) // 2
    print(f"{OUT}  ({len(audio) // 1024} KB, ~{frames / 8000:.2f} s, "
          f"ovoz={settings.tts_voice})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
