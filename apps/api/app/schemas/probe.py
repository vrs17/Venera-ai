"""Admin "Tizim xaritasi" sinovlari (`api/v1/admin_probe.py`) - so'rov va javob shakli.

Javob HAR SINOVDA bir xil: `{ok, trace, result, cost_note}`. Sahifa bitta
komponent bilan chizadi (qadamlar ro'yxati + natija), sinov turi ko'paysa ham
frontend o'zgarmaydi. `result` ATAYLAB erkin (`Any`): har qadamning natijasi
o'zicha (transkript, matn bosqichlari, prompt), va uni sxemaga qotirish har
ishlab chiqarish o'zgarishida sinovni ham buzardi.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ProbeStep(BaseModel):
    #: Qadam nomi (`upload`, `pick`, `stt_gapi`, `clip`, `dates`...).
    step: str
    #: Shu qadamga ketgan vaqt (ms). Tez, sof qadamlarda ~0.
    ms: float = 0.0
    detail: dict[str, Any] = Field(default_factory=dict)


class ProbeResult(BaseModel):
    ok: bool
    trace: list[ProbeStep] = Field(default_factory=list)
    result: Any = None
    #: Pullik yoki tashqi xizmatga chiqqan bo'lsa - nima va qancha (sahifa buni
    #: ishga tushirishdan OLDIN ham ko'rsatadi, bu yerda - amalda nima bo'lgani).
    cost_note: str | None = None


class TtsTextProbe(BaseModel):
    text: str = Field(min_length=1, max_length=4000, description="Matn (javob yoki gap)")
    language: str = Field(default="uz", description="UI tili - hozircha ovoz faqat `uz`")
    #: `speak` - `/tts/speak` (chegara `TTS_MAX_CHARS`), `clip` - `/tts/clip` (600 belgi).
    mode: Literal["speak", "clip"] = "speak"


class WakeProbe(BaseModel):
    text: str = Field(max_length=500, description="STT eshitgan matn")


class HoldProbe(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    #: `true` - gemma tasnifi HAQIQATAN chaqiriladi (pullik, savol ollama.com ga chiqadi).
    use_llm: bool = False
    #: Pullik yo'l (`use_llm`) uchun aniq tasdiq - tasdiqsiz 428.
    confirm_cost: bool = False


class MaskProbe(BaseModel):
    text: str = Field(min_length=1, max_length=20000)


class BrainProbe(BaseModel):
    """Miya funksiyasi namunasi. `input` - funksiyaga qarab: guruh xabarlari
    (`Ism: matn` qatorlari), yig'ilish matni (`S1: matn`), vazifalar ro'yxati."""

    input: str = Field(default="", max_length=60000)
    question: str = Field(default="", max_length=2000)
    #: Brif: guruh turi.
    kind: Literal["project", "support"] = "project"
    #: `false` (default) - model CHAQIRILMAYDI, faqat prompt va agent tanasi.
    execute: bool = False
    #: `execute` (pullik) uchun aniq tasdiq - tasdiqsiz 428.
    confirm_cost: bool = False
