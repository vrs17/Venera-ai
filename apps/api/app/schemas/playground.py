"""Admin "Agent playground" (`api/v1/admin_playground.py`) - so'rov va javob shakli.

Ega qarori (2026-10-15): agent nega "aqlsiz" javob berganini topish uchun HAR BOSQICHNING
aniq kirishini (system prompt, xabarlar, ma'lumot jadvali) ko'rish, bittasini tahrirlab
qayta ishga tushirish, modelni almashtirib solishtirish va holatni regressiya sinoviga
saqlash. Bosqich ichi (prompt, xabarlar) agentniki - shakli agent shartnomasida
(`/api/v4/debug/*`), shuning uchun bu yerda ATAYLAB erkin (`dict`): agent bosqich
qo'shsa yoki maydon o'zgartirsa, sahifa va server o'zgarmaydi.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field, field_validator

#: Bosqich va model nomi: agent beradigan identifikatorlar (`router`, `bank_writer`,
#: `gemma4:31b-cloud`, `gpt-6-luna`). Erkin matn emas - URL va jurnalga tushadi.
_STAGE = re.compile(r"^[a-z0-9_.:-]{1,48}$")
_MODEL = re.compile(r"^[A-Za-z0-9_.:/-]{1,80}$")


def _stage(value: str) -> str:
    if not _STAGE.match(value or ""):
        raise ValueError("bosqich nomi: kichik lotin harf, raqam va _.:- (48 belgigacha)")
    return value


def _model(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    if not _MODEL.match(value):
        raise ValueError("model nomi noto'g'ri")
    return value


class RunParams(BaseModel):
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=16, le=8000)


class StageRun(BaseModel):
    """Bitta bosqichni berilgan kirish bilan ishga tushirish. Agent vosita chaqiruvlarini
    QAYTARADI, bajarmaydi (CRM/HRM ga hech narsa yozilmaydi)."""

    stage: str
    #: Agentdagi kirish shakli: `{system, messages, tools?, extra?}` - agent nima bergan
    #: bo'lsa (`/debug/turns`), tahrirlangan holda qaytariladi.
    input: dict[str, Any]
    model: str | None = None
    #: Ikkinchi model - ikkalasi AYNI kirish bilan, yonma-yon.
    compare_model: str | None = None
    params: RunParams = Field(default_factory=RunParams)
    #: Model chaqiruvi pullik (OpenAI) yoki umumiy kvotadan (Ollama Cloud) - aniq tasdiq.
    confirm_cost: bool = False

    @field_validator("stage")
    @classmethod
    def check_stage(cls, value: str) -> str:
        return _stage(value)

    @field_validator("model", "compare_model")
    @classmethod
    def check_model(cls, value: str | None) -> str | None:
        return _model(value)


class PromptQuery(BaseModel):
    """Yangi savol uchun bosqich promptini YIG'ISH (model chaqirilmaydi, bepul)."""

    stage: str
    question: str = Field(min_length=1, max_length=4000)
    lang: str = Field(default="uz_latn", pattern=r"^[a-z]{2}(_[a-z]{4})?$")
    platforms: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("stage")
    @classmethod
    def check_stage(cls, value: str) -> str:
        return _stage(value)

    @field_validator("platforms")
    @classmethod
    def check_platforms(cls, value: list[str]) -> list[str]:
        for item in value:
            if not re.match(r"^[a-z0-9_]{1,32}$", item):
                raise ValueError("platforma nomi noto'g'ri")
        return value


class CaseIn(BaseModel):
    """Regressiya sinovi: savollar ketma-ketligi va kutilgan xulq (oddiy gaplar).
    Bosqich kirishi (prompt, ma'lumot) SAQLANMAYDI - unda xodim va bank ma'lumoti bor;
    sinov har safar haqiqiy yo'ldan qayta o'tadi."""

    title: str = Field(min_length=1, max_length=200)
    dialog: list[str] = Field(min_length=1, max_length=12)
    expect: list[str] = Field(min_length=1, max_length=12)
    turn_id: str | None = Field(default=None, max_length=64)
    stage: str | None = None
    area: str = Field(default="playground", pattern=r"^[a-z0-9_]{1,32}$")
    #: `none` - hisobsiz savol; `owner` - egasining CRM/HRM ma'lumoti kerak.
    needs: str = Field(default="none", pattern=r"^(none|owner)$")
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("dialog", "expect")
    @classmethod
    def check_lines(cls, value: list[str]) -> list[str]:
        out = [line.strip() for line in value if line and line.strip()]
        if not out:
            raise ValueError("bo'sh bo'lmasin")
        if any(len(line) > 2000 for line in out):
            raise ValueError("bitta qator 2000 belgigacha")
        return out

    @field_validator("stage")
    @classmethod
    def check_opt_stage(cls, value: str | None) -> str | None:
        return None if value in (None, "") else _stage(value)
