"""Yordamchi dvigateli (versiyasi): klient tanlovi va admin boshqaruvi.

`apps/web/src/types.ts` dagi `EngineInfo`, `EngineChoice`, `AdminEngines`,
`EnginePolicyUpdate`, `EngineAccess*` ning aynan nusxasi;
`tests/test_contract.py` mosligini tekshiradi.

Dvigatel NOMI va TAVSIFI bu yerda YO'Q: ular frontend tarjimalarida (uch
tilda). Server faqat kalit (`v1`, `v2`) va imkoniyatlarni (`pro`, `law`)
beradi - `core/engines.ENGINES`.

Vaqtlar ISO-8601 UTC (admin panelning qolgan qismi kabi).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class EngineInfo(BaseModel):
    """types.ts: EngineInfo - katalogdagi bitta dvigatel."""

    id: str
    #: "Pro" rejimi bor (faqat `v2`).
    pro: bool = False
    #: Javobda LEX.UZ qonunchilik manbalari bor.
    law: bool = False


class EngineChoice(BaseModel):
    """types.ts: EngineChoice - `GET /api/v1/chat/engines`.

    `current` - klient hech narsa so'ramasa ishlaydigan dvigatel (shu
    kanalda, shu odam uchun). `selectable` - odamga bir nechta versiya
    berilgan va u tanlay oladi; `available` - tanlasa bo'ladiganlar
    (tanlov bo'lmasa `[current]`). Klient tanlovini `/chat/stream`
    tanasidagi `engine` bilan yuboradi.
    """

    current: str
    selectable: bool = False
    available: list[str] = Field(default_factory=list)
    catalog: list[EngineInfo] = Field(default_factory=list)


class EnginePolicy(BaseModel):
    """types.ts: EnginePolicy - admin saqlagan umumiy siyosat.

    `channels` da faqat admin AYTGAN kanallar; yo'q kanal - `default` ga,
    u ham bo'lmasa `.env` ga tushadi. `source: env` - admin hali hech narsa
    saqlamagan (hammasi `.env` dan).
    """

    default: str | None = None
    channels: dict[str, str] = Field(default_factory=dict)
    #: Hamma chatda TANLAY oladigan versiyalar (default'dan tashqari) - hech kim o'z-o'zidan
    #: ko'chmaydi (`engine_control.SELECTABLE_PREFIX`).
    selectable: list[str] = Field(default_factory=list)
    source: Literal["admin", "env"] = "env"
    updatedAt: str | None = None
    updatedBy: str | None = None


class EnvDefaults(BaseModel):
    """types.ts: EnvDefaults - `.env` dagi boshlang'ich qiymatlar
    (`HRM_ASSISTANT_ENGINE`, `HRM_ASSISTANT_ENGINE_BY_CHANNEL`).

    `default` bo'sh satr bo'lishi mumkin - versiyasiz yo'l (favqulodda
    chiqish, admin panelda tanlanmaydi)."""

    default: str
    channels: dict[str, str] = Field(default_factory=dict)


class EffectiveEngines(BaseModel):
    """types.ts: EffectiveEngines - hozir HAQIQATDA ishlaydigan dvigatel."""

    web: str
    miniapp: str
    bot: str


class EngineUsage(BaseModel):
    """types.ts: EngineUsage - oxirgi 7 kun, dvigatel bo'yicha. `engine`:
    `v1` | `v2` | `default` (yozilmagan: versiyasiz yo'l yoki ma'lumotnoma
    javobi - umumiy ko'rinishdagi `EngineStat` bilan bir xil nom)."""

    engine: str
    turns: int = 0
    errors: int = 0
    medianTtftMs: int | None = None
    users: int = 0


class EngineAccessRow(BaseModel):
    """types.ts: EngineAccessRow - odamga berilgan versiyalar."""

    actorId: int
    name: str
    login: str | None = None
    engines: list[str] = Field(default_factory=list)
    defaultEngine: str | None = None
    note: str | None = None
    updatedAt: str | None = None
    updatedBy: str | None = None


class AdminEngines(BaseModel):
    """types.ts: AdminEngines - `GET /api/v1/admin/engines` (va
    `PUT .../policy` javobi)."""

    catalog: list[EngineInfo] = Field(default_factory=list)
    policy: EnginePolicy
    envDefaults: EnvDefaults
    #: Alohida versiya berilmagan odam uchun (ya'ni "hamma uchun").
    effective: EffectiveEngines
    stats: list[EngineUsage] = Field(default_factory=list)
    access: list[EngineAccessRow] = Field(default_factory=list)


class EnginePolicyUpdate(BaseModel):
    """types.ts: EnginePolicyUpdate - `PUT /api/v1/admin/engines/policy`.

    QO'SHILADIGAN o'zgarish: yuborilmagan maydon va kanal O'ZGARMAYDI,
    `null` - kalitni o'chiradi (keyingi bo'g'inga, oxiri `.env` ga
    qaytaradi). Noma'lum dvigatel yoki kanal - 422.
    """

    default: str | None = None
    channels: dict[str, str | None] = Field(default_factory=dict, max_length=16)
    #: Berilsa - "hamma tanlay oladi" ro'yxati shuning o'zi (`[]` - hech biri). Berilmasa o'zgarmaydi.
    selectable: list[str] | None = Field(default=None, max_length=16)


class EngineAccessUpdate(BaseModel):
    """types.ts: EngineAccessUpdate - `PUT /api/v1/admin/engines/access/{actorId}`.

    `engines` - kamida bitta, katalogdan. `defaultEngine` - ulardan biri
    yoki `null` (bitta versiya berilgan bo'lsa u o'zi default). `note`
    yuborilmasa - eskisi qoladi, `null`/`""` - o'chiriladi.
    """

    engines: list[str] = Field(min_length=1, max_length=10)
    defaultEngine: str | None = None
    note: str | None = Field(default=None, max_length=500)


class EngineAccessRemoved(BaseModel):
    """types.ts: EngineAccessRemoved - `DELETE .../access/{actorId}`."""

    removed: bool


class UserEngineAccess(BaseModel):
    """types.ts: UserEngineAccess - foydalanuvchi varag'ida."""

    engines: list[str] = Field(default_factory=list)
    defaultEngine: str | None = None


class UserEngine(BaseModel):
    """types.ts: UserEngine - `AdminUserDetail.engine`: shu odamga hozir
    qaysi dvigatel ishlaydi (kanal bo'yicha) va unga alohida nima berilgan."""

    effective: EffectiveEngines
    access: UserEngineAccess | None = None


# --- miya flag'lari (LLM ishlarining agentga ko'chishi, `services/brain`) ---------------------
#
# Frontend sahifasi hali yo'q (W0: API va audit); `types.ts` ga qo'shilganda
# `tests/test_contract.py` ga ham qo'shiladi.


class BrainFeatureRow(BaseModel):
    """Bitta funksiya: sozlangan holat (`state`, manbasi), hozir ishlayotgani
    (`effective`) va nega pastroq (`reason`, masalan `agent_disabled`)."""

    feature: str
    label: str
    ops: list[str] = Field(default_factory=list)
    state: str
    source: str
    sampleRate: float
    envState: str
    effective: str
    reason: str | None = None
    note: str | None = None
    updatedAt: str | None = None
    updatedBy: str | None = None


class AdminBrain(BaseModel):
    """`GET /api/v1/admin/engines/brain` (va `PUT .../brain/{feature}` javobi).
    `agent`, `shadow` - holat sonlari va imkoniyatlar ro'yxati (sir yo'q)."""

    states: list[str] = Field(default_factory=list)
    features: list[BrainFeatureRow] = Field(default_factory=list)
    agent: dict = Field(default_factory=dict)
    shadow: dict = Field(default_factory=dict)
    holdClassifier: str


class BrainFeatureUpdate(BaseModel):
    """`PUT /api/v1/admin/engines/brain/{feature}` - QO'SHILADIGAN o'zgarish.

    `state`: `local | shadow | agent`, `null` - admin qarori olib tashlanadi
    (`.env` ga qaytadi). `sampleRate`: 0..1, `null` - `.env` dagisi. Yuborilmagan
    maydon o'zgarmaydi."""

    state: str | None = None
    sampleRate: float | None = None
    note: str | None = Field(default=None, max_length=500)
