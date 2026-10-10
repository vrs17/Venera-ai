"""Matn -> ovoz so'rovi.

Javob JSON EMAS: endpoint WAV baytlarini to'g'ridan-to'g'ri qaytaradi, ya'ni
javob sxemasi yo'q. Sabab - base64 JSON ichida audioni ~33% shishirardi va
brauzer uni `<audio>` ga bermasdan oldin qo'lda dekodlashi kerak bo'lardi.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000, description="O'qiladigan matn")
    language: str = Field(default="uz", description="Hozircha faqat `uz` (o'zbek, lotin)")
    # `Literal` - erkin satr EMAS: noma'lum qiymat xato matniga, u esa
    # log'ga aynan ko'chirilardi, ya'ni foydalanuvchi log'ga o'z qatorini
    # yozdira olardi. Endi u so'rov tanasidayoq 422 bo'lib to'xtaydi.
    voice: Literal["uz_female_calm", "uz_male_news"] | None = Field(
        default=None,
        description="Bo'sh bo'lsa server sozlamasi (`TTS_VOICE`).",
    )


#: Bitta `/tts/clip` so'rovidagi eng ko'p belgi. Klient javobni GAP
#: chegarasida o'zi bo'laklaydi (birinchisi <=160, keyingilari <=350), ya'ni
#: 600 - zaxira bilan qo'yilgan to'siq. Kichik bo'lishi SHART: TTS ning ikki
#: sloti BARCHA foydalanuvchilarga umumiy, va qisqa so'rov slotni ~2 s ushlaydi,
#: 3000 belgilik oqim esa ~40 s.
CLIP_MAX_CHARS = 600


class ClipRequest(BaseModel):
    text: str = Field(
        min_length=1, max_length=CLIP_MAX_CHARS,
        description="Bitta bo'lak (1-3 gap); klient gap chegarasida bo'laklaydi",
    )
    language: str = Field(default="uz", description="Hozircha faqat `uz`")
    # `SpeakRequest.voice` bilan bir xil sabab: erkin satr log'ga aynan
    # ko'chirilardi, `Literal` esa uni so'rov tanasidayoq 422 bilan to'xtatadi.
    voice: Literal["uz_female_calm", "uz_male_news"] | None = Field(
        default=None, description="Bo'sh - `TTS_VOICE`",
    )
    # Chegaralar klient sozlamasidan kengroq (0.85-1.1): server o'zi qabul
    # qiladigan oraliqdan tashqariga chiqmasin, lekin klientni ham siqmasin.
    # `allow_inf_nan=False` - `NaN` taqqoslashda jimgina o'tib ketmasin.
    speed: float | None = Field(
        default=None, ge=0.7, le=1.3, allow_inf_nan=False,
        description="Bo'sh - `TTS_SPEED` (server 0.95)",
    )
