"""Slack hisobi -> Barno hisobi: Slack'dagi Barno AI kimning nomidan ishlaydi.

OLDIN Slack'dagi hamma odam BITTA umumiy hisobda edi (`SLACK_ACTOR_ID`). Endi
(2026-11-12, ega qarori) har kim o'z hisobini BIR MARTA ulaydi: Barno AI
birinchi xabarga «Connect Barno AI account» tugmasi bilan javob beradi, tugma
Barno kirish sahifasini ochadi (SSO yoki login + parol), odam kirgach
ulanishni TASDIQLAYDI (`app/slack/link.py`, `api/v1/slack.py`). Shundan keyin
Slack'dagi audio va savollar o'sha odamning O'Z hisobiga tegishli.

MUDDAT - Telegram ulanishidagi kabi (`telegram_links.py`): ulanish OXIRGI
FAOLLIKDAN `ttl_days` yashaydi; Slack'da Barno'dan foydalanib tursa qayta
so'ralmaydi. Bekor qilish: Slack'dagi "Home" varag'idagi «Uzish», admin
panelidagi "hamma joydan chiqarish" (`admin_users.signout`) va hisobning
o'chirilishi (keyingi xabarda uziladi).

KALIT - `<team_id>:<user_id>`: Slack foydalanuvchi id'si faqat o'z ish maydoni
ichida noyob, shuning uchun ish maydoni ham kalitda. Id'lar FAQAT Slack'ning
o'zi yetkazgan hodisadan olinadi (Socket Mode) - URL yoki so'rov tanasidagi
id'ga ishonilmaydi (uni har kim yoza oladi).

SAQLANADIGAN NARSA - faqat id'lar va vaqtlar: ism, email, token YO'Q. Fayl
`data/` da (gitignore), 600, atomik.
"""

from __future__ import annotations

import json
import logging
import os
import stat
import tempfile
import threading
import time

from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: `touch` diskka bundan tez-tez yozmaydi: har xabarda fayl qayta yozilmasin.
#: Muddat kunlarda o'lchanadi - bir soatlik aniqlik yetarli.
TOUCH_EVERY = 3600.0


@dataclass(frozen=True)
class SlackLink:
    team_id: str
    user_id: str
    actor_id: int
    linked_at: float
    #: Oxirgi faollik (ulash yoki Slack'dagi so'rov). Muddat shundan hisoblanadi.
    seen_at: float


def key_of(team_id: str | None, user_id: str | None) -> str:
    return f"{(team_id or '').strip()}:{(user_id or '').strip()}"


class LinkStore:
    """`{"links": {"<team>:<user>": {...}}}` - bitta JSON fayl.

    Xotirada keshlanadi; fayl o'zgargani `stat` bilan aniqlanadi
    (`telegram_links.LinkStore` dagi kabi) - qo'lda tahrirlangan fayl ham ko'rinadi.
    """

    def __init__(self, path: Path, *, ttl_days: float = 30) -> None:
        self.path = Path(path)
        self.ttl = max(1.0, float(ttl_days)) * 86400.0
        self._lock = threading.Lock()
        self._links: dict[str, dict[str, Any]] = {}
        self._mark: tuple[int, int] | None = None

    # --- o'qish -------------------------------------------------------------

    def lookup(self, team_id: str | None, user_id: str | None, *,
               now: float | None = None) -> tuple[SlackLink | None, str]:
        """(ulanish, holat). Holat: `linked` | `expired` | `none`.

        Muddati o'tgan ulanish O'CHIRILMAYDI: odamga "muddati tugadi" deyish
        uchun kerak, va qayta ulanganda yangilanadi.
        """
        if not (user_id or "").strip():
            return None, "none"
        now = time.time() if now is None else now
        key = key_of(team_id, user_id)
        with self._lock:
            self._reload()
            raw = self._links.get(key)
        link = _parse(key, raw)
        if link is None:
            return None, "none"
        if now - link.seen_at > self.ttl:
            return None, "expired"
        return link, "linked"

    def by_actor(self, actor_id: int) -> list[SlackLink]:
        """Shu Barno hisobiga ulangan HAMMA Slack hisoblari (muddati o'tganlari ham) -
        admin panel uchun."""
        with self._lock:
            self._reload()
            items = list(self._links.items())
        found = [_parse(key, raw) for key, raw in items
                 if isinstance(raw, dict) and raw.get("actor_id") == actor_id]
        return [link for link in found if link is not None]

    def count(self, *, now: float | None = None) -> int:
        """Amaldagi (muddati o'tmagan) ulanishlar soni - `/api/health/detail`."""
        now = time.time() if now is None else now
        with self._lock:
            self._reload()
            return sum(1 for raw in self._links.values()
                       if isinstance(raw, dict) and now - _number(raw.get("seen_at")) <= self.ttl)

    # --- yozish -------------------------------------------------------------

    def link(self, team_id: str | None, user_id: str, actor_id: int, *,
             now: float | None = None) -> str:
        """Ulaydi yoki muddatini yangilaydi. Natija:

          `new`       - avval ulanmagan (yoki muddati o'tgan) edi;
          `refreshed` - o'sha hisobga ulangan edi, muddat yangilandi;
          `switched`  - BOSHQA Barno hisobiga ulangan edi.
        """
        if not (user_id or "").strip():
            raise ValueError("Slack foydalanuvchi id'si bo'sh")
        now = time.time() if now is None else now
        key = key_of(team_id, user_id)
        with self._lock:
            self._reload()
            old = self._links.get(key)
            old_actor = old.get("actor_id") if isinstance(old, dict) else None
            fresh = isinstance(old, dict) and now - _number(old.get("seen_at")) <= self.ttl
            if isinstance(old, dict) and old_actor == actor_id:
                entry = dict(old)
                entry["seen_at"] = now
                result = "refreshed" if fresh else "new"
            else:
                entry = {"actor_id": int(actor_id), "linked_at": now, "seen_at": now}
                result = "switched" if old_actor is not None and fresh else "new"
            self._links[key] = entry
            self._write()
        return result

    def touch(self, team_id: str | None, user_id: str | None, actor_id: int, *,
              now: float | None = None) -> bool:
        """Faqat muddatni yangilaydi - ulanish HALI SHU hisobniki va tirik bo'lsa.

        Yo'q, muddati o'tgan yoki boshqa hisobga o'tgan ulanishni QAYTA
        YARATMAYDI: tekshiruv va yozuv orasida admin "hamma joydan chiqarish"
        ni bossa, uzilgan ulanish jimgina tirilib qolmasin. Diskka `TOUCH_EVERY`
        da bir marta yoziladi. `False` - ulanish endi yo'q.
        """
        now = time.time() if now is None else now
        with self._lock:
            self._reload()
            entry = self._links.get(key_of(team_id, user_id))
            if not isinstance(entry, dict) or entry.get("actor_id") != actor_id:
                return False
            seen = _number(entry.get("seen_at"))
            if now - seen > self.ttl:
                return False
            if now - seen >= TOUCH_EVERY:
                entry["seen_at"] = now
                self._write()
        return True

    def unlink(self, team_id: str | None, user_id: str | None, *,
               actor_id: int | None = None) -> bool:
        """Uzadi. `actor_id` berilsa - faqat o'sha hisobga ulangan bo'lsa."""
        key = key_of(team_id, user_id)
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

    def unlink_actor(self, actor_id: int) -> int:
        """Shu hisobning HAMMA Slack ulanishlarini uzadi -> nechtasi uzildi.

        Admin "hamma sessiyalardan chiqarish" ni bosganda: Slack'dagi kirish JWT
        emas, u faqat shu ulanish bilan yashaydi.
        """
        with self._lock:
            self._reload()
            keys = [key for key, raw in self._links.items()
                    if isinstance(raw, dict) and raw.get("actor_id") == actor_id]
            for key in keys:
                del self._links[key]
            if keys:
                self._write()
        return len(keys)

    # --- ichki --------------------------------------------------------------

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
            log.warning("Slack ulanishlari fayli o'qilmadi (%s): %s", self.path, exc)
            return
        links = raw.get("links") if isinstance(raw, dict) else None
        self._links = links if isinstance(links, dict) else {}
        self._mark = mark

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=self.path.parent,
            prefix=".slack-links.", suffix=".tmp", delete=False,
        )
        try:
            with handle:
                json.dump({"links": self._links}, handle, ensure_ascii=False, indent=1)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(handle.name, stat.S_IRUSR | stat.S_IWUSR)
            os.replace(handle.name, self.path)
        except BaseException:
            Path(handle.name).unlink(missing_ok=True)
            raise
        info = self.path.stat()
        self._mark = (info.st_mtime_ns, info.st_size)


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _parse(key: str, raw: Any) -> SlackLink | None:
    if not isinstance(raw, dict):
        return None
    actor = raw.get("actor_id")
    if isinstance(actor, bool) or not isinstance(actor, int):
        return None
    team_id, _, user_id = key.partition(":")
    if not user_id:
        return None
    return SlackLink(team_id=team_id, user_id=user_id, actor_id=actor,
                     linked_at=_number(raw.get("linked_at")), seen_at=_number(raw.get("seen_at")))
