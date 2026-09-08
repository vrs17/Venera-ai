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
