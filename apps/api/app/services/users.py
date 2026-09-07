"""Foydalanuvchilar ombori.

HOZIR: YAML fayl (`config/users.yaml`) - demo uchun 2-3 ta xodim.
KEYIN: ma'lumotlar bazasi yoki LDAP/Active Directory.

Almashtirish arzon bo'lishi uchun butun ilova FAQAT `UserStore` interfeysini
biladi: `authenticate()` va `by_email()`. Router'lar YAML haqida hech narsa
bilmaydi. DB kelganda shu fayldagi sinf almashtiriladi, boshqa joyga
tegilmaydi.

Nima uchun YAML, JSON emas: unda IZOH yozish mumkin, va IT xodimi faylni
qo'lda tahrirlaydi.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ..core.security import verify_password
from ..schemas.auth import AuthUser

log = logging.getLogger(__name__)


@dataclass
class StoredUser:
    """Fayldagi yozuv. `password_hash` HECH QACHON tashqariga chiqmaydi."""

    actor_id: int
    email: str
    full_name: str
    password_hash: str
    actor_type: str = "EMPLOYEE"
    position: str | None = None
    department: str | None = None
    roles: list[str] = field(default_factory=list)
    password_change_required: bool = False

    def to_public(self) -> AuthUser:
        """Frontend ko'radigan shakl - parol xeshisiz."""
        return AuthUser(
            actorId=self.actor_id,
            actorType=self.actor_type,
            email=self.email,
            fullName=self.full_name,
            position=self.position,
            department=self.department,
            roles=list(self.roles),
            passwordChangeRequired=self.password_change_required,
        )


class UserStore:
    """Email bo'yicha qidirish va parol tekshirish."""

    def __init__(self, users: dict[str, StoredUser] | None = None) -> None:
        self._users = users or {}

    @classmethod
    def from_file(cls, path: Path) -> "UserStore":
        """YAML dan yuklaydi. Fayl yo'q yoki buzuq bo'lsa BO'SH ombor qaytaradi.

        Ataylab istisno tashlamaydi: server ishga tushishi va `/health` da
        muammoni ko'rsatishi kerak. Aks holda IT xodimi xizmat nima uchun
        ko'tarilmayotganini log ichidan qidiradi.
        """
        try:
            raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        except FileNotFoundError:
            log.warning("Foydalanuvchilar fayli topilmadi: %s", path)
            return cls()
        except Exception as exc:  # noqa: BLE001
            log.error("Foydalanuvchilar fayli o'qilmadi (%s): %s", path, exc)
            return cls()

        entries = raw.get("users") if isinstance(raw, dict) else raw
        if not isinstance(entries, list):
            log.error("%s: `users` ro'yxati kutilgan edi", path)
            return cls()

        users: dict[str, StoredUser] = {}
        for index, item in enumerate(entries):
            if not isinstance(item, dict):
                log.warning("%s: %d-yozuv dict emas - o'tkazib yuborildi", path, index)
                continue
            email = str(item.get("email", "")).strip().lower()
            password_hash = str(item.get("password_hash", "")).strip()
            if not email or not password_hash:
                log.warning("%s: %d-yozuvda email yoki password_hash yo'q", path, index)
                continue
            users[email] = StoredUser(
                actor_id=int(item.get("actor_id", index + 1)),
                email=email,
                full_name=str(item.get("full_name") or email),
                password_hash=password_hash,
                actor_type=str(item.get("actor_type") or "EMPLOYEE"),
                position=item.get("position"),
                department=item.get("department"),
                roles=[str(r) for r in (item.get("roles") or [])],
                password_change_required=bool(item.get("password_change_required", False)),
            )

        log.info("Foydalanuvchilar yuklandi: %d ta (%s)", len(users), path)
        return cls(users)

    def by_email(self, email: str) -> StoredUser | None:
        return self._users.get(str(email).strip().lower())

    def authenticate(self, email: str, password: str) -> StoredUser | None:
        """Email + parol to'g'ri bo'lsa foydalanuvchi, aks holda None.

        MUHIM: foydalanuvchi topilmasa ham parol tekshiruvi BAJARILADI
        (soxta xesh bilan). Aks holda javob vaqti bo'yicha qaysi email
        ro'yxatda borligini aniqlash mumkin bo'lardi.
        """
        user = self.by_email(email)
        stored = user.password_hash if user else _DUMMY_HASH
        ok = verify_password(password, stored)
        return user if (ok and user is not None) else None

    def __len__(self) -> int:
        return len(self._users)


#: Mavjud bo'lmagan foydalanuvchi uchun - vaqt bo'yicha hujumdan himoya.
#: Qiymati ahamiyatsiz, faqat FORMAT to'g'ri bo'lishi kerak.
_DUMMY_HASH = (
    "pbkdf2$600000$0123456789abcdef0123456789abcdef$"
    "0000000000000000000000000000000000000000000000000000000000000000"
)
