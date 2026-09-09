"""Ovoz -> matn javobi.

`apps/web/src/types.ts` dagi `Transcript` bilan MOS bo'lishi shart -
`tests/test_contract.py` shuni qo'riqlaydi.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class TranscriptResponse(BaseModel):
    text: str = Field(description="Tanib olingan matn")
    language: str = Field(default="", description="Matn qaysi tilda tanildi - har doim so'ralgan til")
    durationSec: float = Field(default=0.0, description="Audio uzunligi (soniya)")
    lowConfidence: bool = Field(
        default=False,
        description="Router matnga ishonchi past (WER ~60-70%). Hujjat: avtomatik "
                    "harakat qilmang - foydalanuvchidan tasdiq oling. uz backend "
                    "buni `null` qaytaradi, shuning uchun bu yerda doim bool.",
    )
    truncated: bool = Field(default=False, description="Audio Router limitidan uzun bo'lib kesildi")
    backend: str = Field(default="", description="`uzbek_stt` yoki `multilang` - debug uchun")


class WakeResponse(BaseModel):
    """Uyg'otish tekshiruvi natijasi.

    Qaror SERVERDA qabul qilinadi - brauzer faqat `matched` ga qaraydi.
    `reason` va `text` diagnostika uchun: brauzer konsolida nima
    eshitilganini ko'rish, moslashtirgichni sozlashda juda qimmat.
    """

    text: str = Field(default="", description="STT nima eshitgani")
    matched: bool = Field(default=False, description="Uyg'otish so'zi tanildimi")
    reason: str = Field(default="", description="Nega tanildi yoki tanilmadi")
    checked: bool = Field(
        default=True,
        description="Tekshiruv HAQIQATAN bajarildimi. `false` - STT javob "
                    "bermadi, ya'ni matn yo'q va 'uyg'onmadi' xulosasi "
                    "audioga emas, nosozlikka asoslangan. Klient shunda "
                    "urinishlar oralig'ini uzaytiradi.",
    )
    distorted: bool = Field(
        default=False,
        description="Audio brauzerga yetguncha buzilgan: nutq ichida tekis "
                    "nol uzunliklari (OS/drayver shovqin darvozasi). Bunda "
                    "'uyg'onmadi' aybi so'zda emas, yozuvda - klient buni "
                    "foydalanuvchiga ko'rsatadi, chunki darvozani faqat u "
                    "o'chira oladi.",
    )
