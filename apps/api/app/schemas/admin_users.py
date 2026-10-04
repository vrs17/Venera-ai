"""Admin panel: foydalanuvchilar - `apps/web/src/types.ts` dagi `AdminUser`,
`AdminUserDetail`, `AdminUserUpdate`, `AdminConnector`, `AuditEntry` ning
aynan nusxasi; `tests/test_contract.py` mosligini tekshiradi.

Vaqtlar ISO-8601 UTC. TOKEN, PAROL BU YERDA YO'Q va bo'lmaydi: ulanishlar
faqat holat bilan ko'rinadi (`ConnectorStatus` kabi).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .engines import UserEngine


class AdminUser(BaseModel):
    """types.ts: AdminUser - ro'yxatdagi bitta odam."""

    actorId: int
    name: str
    #: SSO login (`y.mamajonov`); zahira hisobda - email.
    login: str | None = None
    email: str | None = None
    department: str | None = None
    position: str | None = None
    #: sso | local | both | telemetry (hisob manbadan olib tashlangan, faqat
    #: savollar tarixida qolgan).
    source: str
    #: SAMARALI rollar - sessiya aynan shularni oladi.
    roles: list[str] = Field(default_factory=list)
    #: admin (panelda qo'yilgan) | source (SSO / users.yaml dan).
    rolesSource: str = "source"
    #: `admin_logins` da - ADMIN ni olib ham, bloklab ham bo'lmaydi.
    rolesLocked: bool = False
    disabled: bool = False
    lastSeenAt: str | None = None
    lastLoginAt: str | None = None
    #: Tanlangan oraliqdagi savollar, kanallar va shikoyatlar.
    turns: int = 0
    channels: list[str] = Field(default_factory=list)
    reports: int = 0


class AdminUserList(BaseModel):
    """types.ts: AdminUserList"""

    items: list[AdminUser] = Field(default_factory=list)


class AdminUserStats(BaseModel):
    """types.ts: AdminUserStats - tanlangan oraliq bo'yicha."""

    turns: int = 0
    errors: int = 0
    medianTtftMs: int | None = None
    reports: int = 0
    voiceTurns: int = 0


class AdminConnector(BaseModel):
    """types.ts: AdminConnector - odamning HRM/CRM ulanishi, TOKENSIZ."""

    platform: str                  # hrm | crm
    connected: bool
    enabled: bool = False
    login: str | None = None
    expiresAt: str | None = None
    #: disconnected | connected | expired (`ConnectorStatus.state`).
    state: str = "disconnected"


class AdminTelegram(BaseModel):
    """types.ts: AdminTelegram - bot ulanishlari (muddati o'tganlari ham)."""

    links: int = 0
    lastSeenAt: str | None = None


class AuditEntry(BaseModel):
    """types.ts: AuditEntry - kim, qachon, nimani o'zgartirdi."""

    id: int
    createdAt: str | None = None
    adminActorId: int | None = None
    adminName: str | None = None
    #: user.roles | user.block | user.unblock | user.note | user.signout |
    #: user.connector.disconnect | user.telegram.unlink | report.status | report.note |
    #: engine.policy | engine.access.set | engine.access.remove
    action: str
    targetType: str | None = None
    targetId: str | None = None
    detail: dict[str, Any] | None = None


class AdminUserDetail(AdminUser):
    """types.ts: AdminUserDetail - foydalanuvchi varag'i."""

    stats: AdminUserStats
    connectors: list[AdminConnector] = Field(default_factory=list)
    telegram: AdminTelegram
    #: types.ts: TurnSummary[] (`schemas/admin.py`), oxirgi 10 ta.
    recentTurns: list[dict[str, Any]] = Field(default_factory=list)
    audit: list[AuditEntry] = Field(default_factory=list)
    #: Admin izohi (faqat panelda ko'rinadi).
    note: str | None = None
    #: Yordamchi dvigateli: shu odamga HOZIR nima ishlaydi (kanal bo'yicha)
    #: va unga alohida qaysi versiyalar berilgan (`/admin/engines/access`).
    engine: UserEngine


class AdminUserUpdate(BaseModel):
    """types.ts: AdminUserUpdate - `PATCH /admin/users/{actorId}` tanasi.

    Yuborilmagan maydon O'ZGARMAYDI. `roles: null` - admin qo'ygan rollarni
    olib tashlab, manba (SSO / users.yaml) rollariga qaytarish; bu "rollar
    bo'sh" (`[]`) dan boshqa narsa.
    """

    roles: list[str] | None = Field(default=None, max_length=20)
    disabled: bool | None = None
    #: Admin izohi; bo'sh satr - o'chirish.
    note: str | None = Field(default=None, max_length=500)


class SignoutResult(BaseModel):
    """types.ts: SignoutResult - yangi sessiya versiyasi."""

    tokenVersion: int


class TelegramUnlinked(BaseModel):
    """types.ts: TelegramUnlinked - nechta Telegram ulanishi uzildi."""

    unlinked: int
