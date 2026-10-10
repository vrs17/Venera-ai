"""Barno xotirasi va platforma kalitlari sxemalari (`/api/v1/assistant/...`).

Maydon nomlari yuqoridagi xizmatnikidek (snake_case, `schemas/chats.py`
dagi kabi): javob o'sha xizmatdan keladi va mobil ilova ham xizmat
hujjatiga qarab yoziladi - nomlarni almashtirish ikki lug'at yaratardi.
Bitta istisno: xizmatning `connectors` ro'yxati bizda `platforms` -
`/api/v1/connectors` nomi bizda HRM/CRM LOGIN tokenlariga band.

Xizmat javobi bu modellarga TO'G'RIDAN-TO'G'RI quyilmaydi: u yerda
`created_at: ""` yoki yetishmagan maydon bo'lsa 500 chiqardi. Avval
`normalize_*` funksiyalari (`api/v1/assistant_extras.py`) shaklini to'g'rilaydi.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, StrictBool


class MemoryItem(BaseModel):
    """Barno odam haqida eslab qolgan bitta narsa."""

    #: `m12` (eslab qolingan yoki o'rganilgan odat) yoki `h3f2a...` (CRM
    #: vazifalaridan o'rganilgan tartib). O'chirish shu kalit bilan.
    id: str
    #: Bitta gap, odamning tilida. UI uni MATN sifatida ko'rsatadi (HTML emas).
    text: str
    #: preference | fact | routine (xizmat yangisini qo'shsa - o'zgarmasdan o'tadi)
    kind: str = ""
    #: user (odam "eslab qol" degan) | learned (so'rashidan yoki ishidan o'rganilgan)
    source: str = ""
    #: ISO vaqt. CRM dan o'rganilgan tartibda bo'lmaydi - `null`.
    created_at: str | None = None
    updated_at: str | None = None


class MemoryList(BaseModel):
    """`GET /assistant/memory` javobi."""

    items: list[MemoryItem] = Field(default_factory=list)
    count: int = 0


class MemoryDeleted(BaseModel):
    """`DELETE /assistant/memory/{id}` va `DELETE /assistant/memory` javobi."""

    #: O'chirilgan bandlar kalitlari.
    deleted: list[str] = Field(default_factory=list)
    #: deleted | empty (o'chiradigan narsa yo'q edi)
    status: str


class Platform(BaseModel):
    """Barno javob berishda o'qiydigan bitta platforma va odamning kaliti."""

    #: hrm | crm | dwh | biznes247 | superapp | biznes247_kb | biznes247_help
    id: str
    #: Ko'rsatiladigan nom ("Biznes 24/7"). UI o'z tarjimasini ishlatadi,
    #: notanish `id` uchun shu nom.
    name: str
    #: Bir qator izoh (xizmatniki - o'zbekcha).
    description: str = ""
    #: live (odamning o'z hisobi) | data (bank raqamlari) | knowledge (qo'llanmalar)
    kind: str = ""
    #: Chat so'rovida odamning shu platforma tokeni kerak (HRM/CRM - "+" menyusidagi
    #: login, `/api/v1/connectors`).
    needs_login: bool = False
    #: Serverda yoqilgan. `false` - kulrang, odam yoqa olmaydi.
    available: bool = True
    #: Odamning o'z kaliti (o'chirmaguncha `true`).
    user_enabled: bool = True
    #: available VA user_enabled: Barno shu odam uchun undan foydalanadi.
    enabled: bool = True


class PlatformList(BaseModel):
    """`GET /assistant/platforms` javobi."""

    platforms: list[Platform] = Field(default_factory=list)


class PlatformToggle(BaseModel):
    """`PUT /assistant/platforms/{id}` tanasi - faqat `{"enabled": bool}`.

    `StrictBool`: `"false"` satri yoki `0` yoqish/o'chirish deb tushunilmasin.
    Ortiqcha maydon (masalan `user_id`) - 422: kimlik HECH QACHON so'rovdan
    olinmaydi, va buni klient darhol bilgani yaxshi.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: StrictBool
