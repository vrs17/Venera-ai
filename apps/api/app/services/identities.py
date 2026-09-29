"""SSO orqali kirgan odamlar: Keycloak `sub` -> Venera `actor_id`.

NEGA KERAK. Butun ilova odamni `actorId` bilan taniydi: suhbat xotirasi
(`venera:{actorId}`), ulanishlar ombori (`data/connectors/tokens.json`),
Telegram ulanishi (`data/telegram/links.json`). Keycloak esa odamni `sub`
(UUID) bilan beradi. Shu fayl ikkisini bog'laydi va bog'lanish BIR MARTA
qilinib, keyin o'zgarmaydi - aks holda odam har kirganda yangi "shaxs"
bo'lib, tarixi va ulanishlari yo'qolardi.

ESKI HISOBLAR. `config/users.yaml` dagi odam Keycloak bilan birinchi marta
kirganda uning ESKI `actor_id` si beriladi (email bo'yicha, bo'lmasa
email'ning `@` gacha qismi login bilan bir xil bo'lsa). Shunda tarixi va
Telegram ulanishi joyida qoladi. Yangi odamga bo'sh raqam beriladi:
mavjudlarning (ikkala manbadagi) eng kattasi + 1.

SAQLASH. Sir YO'Q - faqat shaxs ma'lumoti. Baribir `data/` da, 600, atomik
(`ConnectorStore` bilan bir xil sabab: yarim yozilgan fayl hammani
"yo'q" qilardi). Fayl o'zgargani `stat` bilan sezilib qayta o'qiladi.
"""

from __future__ import annotations

import json
import logging
import os
import stat
import tempfile
import threading
import time

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..schemas.auth import AuthUser
from .users import StoredUser, UserStore

log = logging.getLogger(__name__)


@dataclass
class Identity:
    """Bitta odam. `subject` - Keycloak `sub`, o'zgarmas."""

    subject: str
    actor_id: int
    username: str
    email: str
    full_name: str
    position: str | None = None
    department: str | None = None
    roles: list[str] = field(default_factory=list)
    created_at: float = 0.0
    last_login_at: float = 0.0

    def to_public(self) -> AuthUser:
        """Frontend ko'radigan shakl - `StoredUser.to_public` bilan bir xil."""
        return AuthUser(
            actorId=self.actor_id,
            actorType="EMPLOYEE",
            # `email` majburiy maydon; Keycloak bermasa login turadi.
            email=self.email or self.username,
            fullName=self.full_name or self.username,
            position=self.position,
            department=self.department,
            roles=list(self.roles),
            passwordChangeRequired=False,
        )


@dataclass(frozen=True)
class SsoProfile:
    """Keycloak tokenidan o'qilgan shaxs (`services/sso.py` yasaydi)."""

    subject: str
    username: str
    email: str = ""
    full_name: str = ""
    roles: tuple[str, ...] = ()


class IdentityStore:
    """`{subject: {...}}` - bitta JSON fayl, 600, atomik."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._data: dict[str, dict[str, Any]] = {}
        self._mark: tuple[int, int] | None = None

    # --- o'qish -------------------------------------------------------------

    def by_subject(self, subject: str) -> Identity | None:
        with self._lock:
            self._reload()
            raw = self._data.get(subject)
            return self._identity(raw) if raw else None

    def by_actor_id(self, actor_id: int) -> Identity | None:
        with self._lock:
            self._reload()
            found = [raw for raw in self._data.values() if raw.get("actor_id") == actor_id]
            if len(found) > 1:
                # Sozlama/fayl xatosi: taxmin qilib boshqa odamning hisobini
                # berib yuborishdan ko'ra rad etgan yaxshi (`UserStore` kabi).
                log.error("actor_id %s bir nechta SSO hisobda takrorlanyapti - rad etildi", actor_id)
                return None
            return self._identity(found[0]) if found else None

    def actor_ids(self) -> set[int]:
        with self._lock:
            self._reload()
            return {int(raw["actor_id"]) for raw in self._data.values() if "actor_id" in raw}

    def __len__(self) -> int:
        with self._lock:
            self._reload()
            return len(self._data)

    # --- yozish -------------------------------------------------------------

    def upsert(self, profile: SsoProfile, *, legacy: UserStore | None = None) -> Identity:
        """Kirgan odamni saqlaydi/yangilaydi va qaytaradi.

        Birinchi kirishda `actor_id` tanlanadi (yuqoridagi qoida) va SHU
        BILAN QOTADI. Keyingi kirishlarda faqat ism, email, rollar va vaqt
        yangilanadi - Keycloak'dagi o'zgarish shu yerga ko'chadi.
        """
        now = time.time()
        with self._lock:
            self._reload()
            raw = self._data.get(profile.subject)
            if raw is None:
                actor_id, how = self._pick_actor_id(profile, legacy)
                raw = {"subject": profile.subject, "actor_id": actor_id, "created_at": now}
                log.info("Yangi SSO hisob: %s -> actor_id %s (%s)", profile.username, actor_id, how)
            raw.update({
                "username": profile.username,
                "email": (profile.email or "").strip().lower(),
                "full_name": profile.full_name or profile.username,
                "roles": list(profile.roles),
                "last_login_at": now,
            })
            self._data[profile.subject] = raw
            self._write()
            return self._identity(raw)

    # --- ichki --------------------------------------------------------------

    def _pick_actor_id(self, profile: SsoProfile, legacy: UserStore | None) -> tuple[int, str]:
        taken = {int(r["actor_id"]) for r in self._data.values() if "actor_id" in r}
        if legacy is not None:
            old = _legacy_match(profile, legacy)
            if old is not None and old.actor_id not in taken:
                return old.actor_id, f"eski hisob {old.email}"
            taken |= legacy.actor_ids()
        return (max(taken, default=0) + 1), "yangi raqam"

    @staticmethod
    def _identity(raw: dict[str, Any]) -> Identity:
        known = {f for f in Identity.__dataclass_fields__}
        clean = {k: v for k, v in raw.items() if k in known}
        clean["actor_id"] = int(clean.get("actor_id", 0))
        clean["roles"] = [str(r) for r in (clean.get("roles") or [])]
        return Identity(**clean)

    def _reload(self) -> None:
        try:
            info = self.path.stat()
        except OSError:
            self._data, self._mark = {}, None
            return
        mark = (info.st_mtime_ns, info.st_size)
        if mark == self._mark:
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.warning("SSO hisoblar fayli o'qilmadi (%s): %s", self.path, exc)
            return
        self._data = raw if isinstance(raw, dict) else {}
        self._mark = mark

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=self.path.parent,
            prefix=".identities.", suffix=".tmp", delete=False,
        )
        try:
            with handle:
                json.dump(self._data, handle, ensure_ascii=False, indent=1)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(handle.name, stat.S_IRUSR | stat.S_IWUSR)
            os.replace(handle.name, self.path)
        except BaseException:
            Path(handle.name).unlink(missing_ok=True)
            raise
        info = self.path.stat()
        self._mark = (info.st_mtime_ns, info.st_size)


def _legacy_match(profile: SsoProfile, legacy: UserStore) -> StoredUser | None:
    """`users.yaml` dagi o'sha odam: email bo'yicha, bo'lmasa login bo'yicha."""
    email = (profile.email or "").strip().lower()
    if email:
        user = legacy.by_email(email)
        if user is not None:
            return user
    return legacy.by_login(profile.username)


class Directory:
    """Ikki manba, bitta qidiruv - Telegram bot uchun (`bot/runner.py`).

    Bot ulanishda faqat `actor_id` saqlaydi va har xabarda hisob hali
    borligini tekshiradi. Odam SSO bilan kirgan bo'lsa u `identities.json`
    da, `users.yaml` dagi eski hisob bo'lsa - u yerda.
    """

    def __init__(self, identities: IdentityStore, users: UserStore) -> None:
        self.identities = identities
        self.users = users

    def by_actor_id(self, actor_id: int) -> Identity | StoredUser | None:
        return self.identities.by_actor_id(actor_id) or self.users.by_actor_id(actor_id)
