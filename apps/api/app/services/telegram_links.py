"""Telegram hisobi -> Venera hisobi: bot kimning nomidan javob beradi.

ULANISH FAQAT MINI APP ORQALI (`api/v1/telegram.py`): odam ilovani ochadi va
o'z Venera sessiyasi bilan kiradi, ilova esa Telegram imzolagan `initData`
ni yuboradi. Ikkalasi birga "shu Telegram hisobi shu xodimniki" degan
isbot bo'ladi. Bot chatida parol so'ralmaydi va so'ralmasligi kerak: u
Telegram serverida suhbat tarixida qolardi.

MUDDAT. Ulanish `ttl_days` yashaydi va faqat mini app ochilganda
yangilanadi (`seen_at`). Bot bilan yozishish uni UZAYTIRMAYDI - aks holda
faol odam uchun bot muddatsiz sessiyaga aylanardi, veb sessiya esa 12
soatda tugaydi.

SAQLANADIGAN NARSA - faqat raqamlar: Telegram `id`, Venera `actor_id`,
vaqtlar va joriy suhbat kaliti. Ism, username, telefon SAQLANMAYDI - ular
bot ishlashi uchun kerak emas. Fayl `data/` da (gitignore), 600, atomik.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import stat
import tempfile
import threading
import time
import uuid

from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TelegramLink:
    tg_id: int
    actor_id: int
    linked_at: float
    #: Oxirgi marta mini app orqali (sessiya bilan) tasdiqlangan payt.
    seen_at: float
    #: Botdagi joriy suhbat (`chatId`) va undagi oxirgi faollik.
    chat_id: str | None = None
    chat_at: float = 0.0


class LinkStore:
    """`{"links": {tg_id: {...}}}` - bitta JSON fayl.

    Xotirada keshlanadi; fayl o'zgargani `stat` bilan aniqlanadi
    (`ConnectorStore` dagi kabi) - qo'lda tahrirlangan fayl ham ko'rinadi.
    """

    def __init__(self, path: Path, *, ttl_days: float = 30) -> None:
        self.path = Path(path)
        self.ttl = max(1.0, float(ttl_days)) * 86400.0
        self._lock = threading.Lock()
        self._links: dict[str, dict[str, Any]] = {}
        self._mark: tuple[int, int] | None = None

    # --- o'qish -------------------------------------------------------------

    def lookup(self, tg_id: int, *, now: float | None = None) -> tuple[TelegramLink | None, str]:
        """(ulanish, holat). Holat: `linked` | `expired` | `none`.

        Muddati o'tgan ulanish O'CHIRILMAYDI: odamga "muddati tugadi" deyish
        uchun kerak ("ulanmagan" dan boshqa gap), va mini app ochilishi bilan
        yana yangilanadi.
        """
        now = time.time() if now is None else now
        with self._lock:
            self._reload()
            raw = self._links.get(str(tg_id))
        if not raw:
            return None, "none"
        link = _parse(tg_id, raw)
        if link is None:
            return None, "none"
        if now - link.seen_at > self.ttl:
            return None, "expired"
        return link, "linked"

    def count(self, *, now: float | None = None) -> int:
        """Amaldagi (muddati o'tmagan) ulanishlar soni - `/api/health/detail`."""
        now = time.time() if now is None else now
        with self._lock:
            self._reload()
            return sum(1 for raw in self._links.values()
                       if now - float(raw.get("seen_at") or 0) <= self.ttl)

    # --- yozish ---------------------------------------------------------------

    def link(self, tg_id: int, actor_id: int, *, now: float | None = None) -> str:
        """Ulaydi yoki muddatini yangilaydi. Natija:

          `new`       - avval ulanmagan (yoki muddati o'tgan) edi;
          `refreshed` - o'sha hisobga ulangan edi, muddat yangilandi;
          `switched`  - BOSHQA Venera hisobiga ulangan edi.

        Hisob almashsa suhbat ham yangidan boshlanadi: oldingi odamning
        suhbat kaliti yangi odamga o'tmaydi.
        """
        now = time.time() if now is None else now
        key = str(tg_id)
        with self._lock:
            self._reload()
            old = self._links.get(key)
            old_actor = old.get("actor_id") if isinstance(old, dict) else None
            fresh = isinstance(old, dict) and now - float(old.get("seen_at") or 0) <= self.ttl
            if isinstance(old, dict) and old_actor == actor_id:
                entry = dict(old)
                entry["seen_at"] = now
                result = "refreshed" if fresh else "new"
            else:
                entry = {"actor_id": actor_id, "linked_at": now, "seen_at": now,
                         "chat_id": None, "chat_at": 0.0}
                result = "switched" if old_actor is not None and fresh else "new"
            self._links[key] = entry
            self._write()
        return result

    def unlink(self, tg_id: int, *, actor_id: int | None = None) -> bool:
        """Uzadi. `actor_id` berilsa - faqat o'sha hisobga ulangan bo'lsa
        (mini app'dan chiqish BOSHQA odamning ulanishini uzmasligi uchun)."""
        key = str(tg_id)
        with self._lock:
            self._reload()
            old = self._links.get(key)
            if not isinstance(old, dict):
                return False
            if actor_id is not None and old.get("actor_id") != actor_id:
                return False
            del self._links[key]
            self._write()
        return True

    def chat_for(self, tg_id: int, *, idle_sec: float, now: float | None = None) -> str:
        """Joriy suhbat kaliti. Uzoq jimlikdan keyin - YANGI suhbat.

        Faollik vaqti har savolda yangilanadi.
        """
        now = time.time() if now is None else now
        key = str(tg_id)
        with self._lock:
            self._reload()
            entry = self._links.get(key)
            if not isinstance(entry, dict):
                # Ulanish shu orada uzildi - bir martalik kalit, saqlanmaydi.
                return _new_chat_id()
            chat = entry.get("chat_id")
            if not isinstance(chat, str) or not chat or now - float(entry.get("chat_at") or 0) > idle_sec:
                chat = _new_chat_id()
            entry["chat_id"] = chat
            entry["chat_at"] = now
            self._write()
            return chat

    def new_chat(self, tg_id: int, *, now: float | None = None) -> str | None:
        """`/new` - keyingi savol yangi suhbatda. Ulanish yo'q bo'lsa `None`."""
        now = time.time() if now is None else now
        with self._lock:
            self._reload()
            entry = self._links.get(str(tg_id))
            if not isinstance(entry, dict):
                return None
            entry["chat_id"] = _new_chat_id()
            entry["chat_at"] = now
            self._write()
            return entry["chat_id"]

    # --- fayl -------------------------------------------------------------------

    def _reload(self) -> None:
        try:
            info = self.path.stat()
        except OSError:
            self._links, self._mark = {}, None
            return
        mark = (info.st_mtime_ns, info.st_size)
        if mark == self._mark:
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            # Buzilgan fayl xotiradagini O'CHIRMAYDI: keyingi yozuv uni
            # to'g'ri shaklda qayta yozadi.
            log.warning("Telegram ulanishlari o'qilmadi (%s): %s", self.path, exc)
            return
        links = raw.get("links") if isinstance(raw, dict) else None
        self._links = copy.deepcopy(links) if isinstance(links, dict) else {}
        self._mark = mark

    def _write(self) -> None:
        """ATOMIK va 600 - `ConnectorStore._write` bilan bir xil sabablarga ko'ra."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            handle = tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=self.path.parent,
                prefix=".links.", suffix=".tmp", delete=False,
            )
            try:
                with handle:
                    json.dump({"version": 1, "links": self._links}, handle, ensure_ascii=False)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.chmod(handle.name, stat.S_IRUSR | stat.S_IWUSR)
                os.replace(handle.name, self.path)
            except BaseException:
                Path(handle.name).unlink(missing_ok=True)
                raise
            info = self.path.stat()
            self._mark = (info.st_mtime_ns, info.st_size)
        except OSError as exc:
            # Yozilmadi - xotirada qoladi, ya'ni xizmat qayta ishga tushguncha
            # ishlaydi. Sabab jurnalda.
            log.error("Telegram ulanishlari saqlanmadi (%s): %s", self.path, exc)


def _parse(tg_id: int, raw: Any) -> TelegramLink | None:
    if not isinstance(raw, dict):
        return None
    try:
        return TelegramLink(
            tg_id=int(tg_id),
            actor_id=int(raw["actor_id"]),
            linked_at=float(raw.get("linked_at") or 0),
            seen_at=float(raw.get("seen_at") or 0),
            chat_id=raw.get("chat_id") if isinstance(raw.get("chat_id"), str) else None,
            chat_at=float(raw.get("chat_at") or 0),
        )
    except (KeyError, TypeError, ValueError):
        log.warning("Telegram ulanishi buzilgan yozuv - e'tiborsiz qoldirildi")
        return None


def _new_chat_id() -> str:
    """Veb ilova va mini app kabi - UUID (`[\\w-]`, yuqoridagi xizmat qabul qiladi)."""
    return str(uuid.uuid4())
