"""Guruhlarni boshqarish - rahbar botning SHAXSIY chatida (2026-10-08).

NIMA UCHUN. Avval guruh `.env` dagi `TELEGRAM_GROUPS` ga qo'lda yozilardi -
dasturchisiz bo'lmasdi. Endi bosh direktor yoki operatsion direktor guruhni
o'zi qo'shadi, turini tanlaydi (🛠 support / 📁 loyiha - brif ko'rinishi),
to'xtatadi yoki o'chiradi. Ro'yxat va qoida - `services/tg_groups.GroupRegistry`.

KIM. Brif ko'radiganlar: ADMIN roli va `TELEGRAM_BRIEF_LOGINS` (`brief_allowed`).
Har tugmada QAYTA tekshiriladi. Tugma ma'lumoti (`g:...`) faqat amal va id:
holat har safar ombordan yangi o'qiladi, qaror ombor ichida solishtirib
yoziladi - ikki bosish bitta natija beradi.

QO'SHISH.
  1. "➕ Guruh qo'shish" -> Telegram'ning guruh tanlash oynasi
     (`?startgroup&admin=pin_messages`): Venera ADMINISTRATOR bo'lib
     qo'shiladi. Botda privacy mode yoqiq - faqat admin bo'lsa guruhdagi
     barcha xabarni ko'radi; qadash huquqi - e'lon uchun.
  2. Telegram `my_chat_member` yuboradi (kim qo'shgani bilan). Qo'shgan
     rahbar bo'lsa - unga shaxsiy xabar: "turini tanlang".
  3. Tur tanlandi = guruh yoqildi: guruhga e'lon yoziladi va qadaladi.
  Qo'shgan odam rahbar bo'lmasa - guruh "kutilayotgan": guruhga bitta izoh,
  rahbarlar uni ro'yxatda ko'radi. Hamma rahbarga xabar YUBORILMAYDI - begona
  odam botni guruhlarga qo'shib rahbarlarni xabarga ko'mib tashlay olmasin.

SUPERGROUP. Oddiy guruhda botga admin huquqi berilsa Telegram uni
supergroup'ga aylantiradi - id o'zgaradi. Ro'yxat yangi id ga o'zi o'tadi
(`GroupRegistry.migrate`), `.env` ni tuzatish kerak emas.

AUDIT VA JURNAL. Har qaror - `audit_log` (`tg_group.*`, admin panelda). Jurnalga
guruh nomi va ism yozilmaydi - faqat id va sonlar.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
import time

from typing import Any, Callable

from ..core.config import telegram_brief_logins_now
from ..schemas.auth import AuthUser
from ..services.integrations.telegram import TelegramApi, TelegramError
from ..services.tg_groups import GONE, KINDS, GroupInfo, GroupRegistry, GroupStore
from . import render
from .briefs import _CLOSED, BTN_GROUPS, PAGE, REMOVE_KEYBOARD, brief_allowed, short_title
from .groups import uz_date
from .render import esc

log = logging.getLogger(__name__)

KIND_ICON = {"support": "🛠", "project": "📁"}
KIND_NAME = {"support": "🛠 Support", "project": "📁 Loyiha"}
_KIND_CODE = {"s": "support", "p": "project"}
_CODE_OF = {kind: code for code, kind in _KIND_CODE.items()}
#: Guruh tanlash havolasi so'raydigan huquq: Venera ADMINISTRATOR bo'ladi (privacy
#: mode yoqiq botga barcha xabar faqat shunda keladi) va e'lonni qadaydi.
ADD_RIGHTS = "pin_messages"
#: Qo'shilgandan keyin shuncha vaqt ichidagi "admin qilindi" xabari yuborilmaydi -
#: qo'shilish va admin qilish bir harakatda ikki yangilanish bo'lib keladi.
_JOIN_QUIET = 120.0

NOTICE = (
    "📣 <b>Barno shu guruhda ishlay boshladi</b>\n\n"
    "Barno — kompaniyaning AI yordamchisi. U shu guruh yozishmasini o'qiydi va saqlaydi.\n\n"
    "• /summary — guruh xulosasi, masalan: <code>/summary 3 kun</code>\n"
    "• /askbarno — yozishma bo'yicha savol\n"
    "• CRM: Barnoni belgilab «crmga kiritib qo'y» deb yozing — yozishmadan vazifa taklifi chiqadi; "
    "tasdiqlamaguningizcha CRM o'zgarmaydi.\n"
    "• Kompaniya rahbariyati shu guruhdagi ish holati bo'yicha qisqa brif oladi "
    "(guruh a'zosi bo'lmasa ham).\n"
    "• {kept}\n"
    "• Shaxsiy masalalar — maosh, ta'til, kasallik — xulosa va briflarga kiritilmaydi.\n\n"
    "Shaxsiy savollaringizni Barnoga shaxsiy chatda yozing."
)


def notice(days: int) -> str:
    """Guruhga e'lon: saqlash muddati bilan (0 - muddatsiz, `telegram_group_days`)."""
    return NOTICE.format(kept=f"Xabarlar {days} kun saqlanadi, keyin o'chiriladi." if days else "Xabarlar saqlanadi.")


GROUP_NOT_ENABLED = ("👋 Barno guruhga qo'shildi, lekin hali yoqilmagan. Uni kompaniya rahbariyati "
                     "Barno botida yoqadi.")
GROUP_PAUSED = "⏸ Barno bu guruhda vaqtincha to'xtatilgan."
FAREWELL = "👋 Barno bu guruhdan chiqdi. Saqlangan xabarlar o'chirildi."

_LIST_HEAD = ("⚙️ <b>Guruhlar</b> — Barno o'qiydigan guruhlar\n"
              "<i>✅ yoqilgan · ⏸ to'xtatilgan · 🕓 yoqilmagan · ⚠️ e'tibor kerak\n"
              "🛠 Support · 📁 Loyiha · ❔ turi tanlanmagan</i>")
_EMPTY = "Hozircha guruh yo'q. «➕ Guruh qo'shish» bilan boshlang."
_ADD = ("➕ <b>Guruh qo'shish</b>\n\n"
        "1. «Guruhni tanlash» tugmasini bosing va guruhni tanlang.\n"
        "2. Barnoni <b>administrator</b> qilib qo'shing — shunda u xabarlarni o'qiy oladi "
        "va e'lonni qadaydi.\n"
        "3. Shu chatga xabar keladi: guruh turini tanlaysiz.\n\n"
        "<i>Botni administrator qilib faqat guruh egasi yoki administratori qo'sha oladi.</i>")
_JOINED = ("🆕 Barno <b>«{title}»</b> guruhiga qo'shildi.\n\n"
           "Guruh turini tanlang — Barno guruhga qisqa e'lon yozib, uni qadaydi va xabarlarni "
           "o'qishni boshlaydi.")
_CANT_READ = ("⚠️ Barno guruhda oddiy a'zo — xabarlarni o'qiy olmaydi. Uni administrator qiling: "
              "«👑 Administrator qilish» tugmasi yoki guruh → «Tahrirlash» → «Administratorlar».")
_BACK = "✅ Barno <b>«{title}»</b> guruhiga qaytdi — o'qish davom etadi."
_KICKED = "⚠️ Barno <b>«{title}»</b> guruhidan chiqarildi — guruh endi o'qilmaydi va brifga kirmaydi."
_DEMOTED = ("⚠️ <b>«{title}»</b>: Barno endi administrator emas va guruh xabarlarini o'qiy olmaydi. "
            "Uni qayta administrator qiling.")
_PROMOTED = "✅ <b>«{title}»</b>: Barno administrator — endi barcha xabarlarni o'qiydi."
_NOTICE_RESULT = {
    "pinned": "📣 E'lon guruhga yozildi va qadaldi.",
    "posted": "📣 E'lon yozildi, lekin qadab bo'lmadi — Barnoga «Xabarlarni qadash» huquqini bering.",
    "failed": "⚠️ E'lonni yozib bo'lmadi. «📣 E'lonni yuborish» bilan qayta urinib ko'ring.",
}
_STALE = "Tugma eskirgan"
_REFUSED = {"already": "Guruh allaqachon yoqilgan.", "paused": "Guruh to'xtatilgan — «▶️ Davom ettirish».",
            "gone": "Barno bu guruhda emas.", "unknown": _STALE}

_ID = re.compile(r"-\d{1,20}")
#: Bot guruhda emasligini bildiradigan Telegram xatolari.
_NOT_THERE = ("chat not found", "kicked", "not a member", "deactivated", "bot was blocked")


def parse_cb(data: str) -> tuple[str, int | None, str | None] | None:
    """`g:<amal>[:<id>[:s|p]]` -> (amal, guruh id, tur). Noto'g'ri - `None`."""
    parts = data.split(":")
    if len(parts) < 2 or parts[0] != "g":
        return None
    action = parts[1]
    if action in ("m", "a", "i") and len(parts) == 2:
        return action, None, None
    if action == "l" and len(parts) == 3 and parts[2].isdigit() and len(parts[2]) <= 4:
        return action, int(parts[2]), None
    if action in ("c", "p", "r", "n", "v", "x", "xy", "no") and len(parts) == 3 and _ID.fullmatch(parts[2]):
        return action, int(parts[2]), None
    if action in ("on", "k") and len(parts) == 4 and _ID.fullmatch(parts[2]) and parts[3] in _KIND_CODE:
        return action, int(parts[2]), _KIND_CODE[parts[3]]
    return None


def _btn(text: str, data: str) -> dict[str, str]:
    return {"text": text, "callback_data": data}


def _member(member: dict[str, Any]) -> tuple[str | None, bool | None]:
    """`ChatMember` -> (holat, qadashi mumkinmi)."""
    status = member.get("status")
    if not isinstance(status, str):
        return None, None
    if status == "restricted" and member.get("is_member") is False:
        status = "left"
    if status == "creator":
        return status, True
    return status, bool(member.get("can_pin_messages")) if status == "administrator" else False


def _db_audit(user: AuthUser | None, action: str, chat_id: int, detail: dict[str, Any]) -> None:
    from ..services.admin_users import write_audit
    from ..services.analytics.db import get_db

    with get_db().transaction() as conn:
        write_audit(conn, user, action, "tg_group", chat_id, detail)


class GroupAdmin:
    """Guruhlar menyusi, guruh kartasi va botning guruhdagi holati o'zgarishlari."""

    def __init__(self, api: TelegramApi, registry: GroupRegistry, store: GroupStore, *,
                 logins: Callable[[], frozenset[str]] = telegram_brief_logins_now,
                 audit: Callable[[AuthUser | None, str, int, dict[str, Any]], None] = _db_audit,
                 days: int = 90, settle: float = 2.0, clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.api = api
        self.registry = registry
        self.store = store
        self._logins = logins
        self._audit_write = audit
        self.days = days
        self.settle = settle
        self._clock = clock
        self._sleep = sleep
        self.bot_id: int | None = None
        self.username = ""
        #: BotFather'da privacy mode o'chiq - oddiy a'zo bo'lsa ham hamma xabarni ko'radi.
        self.can_read_all = False
        self._busy: set[int] = set()
        self._busy_lock = threading.Lock()

    def set_me(self, *, bot_id: int | None, username: str, can_read_all: bool) -> None:
        self.bot_id = bot_id if isinstance(bot_id, int) else None
        self.username = username or ""
        self.can_read_all = bool(can_read_all)

    def allowed(self, user: AuthUser, login: str | None) -> bool:
        try:
            return brief_allowed(user, login, self._logins())
        except Exception:  # noqa: BLE001 - sozlama o'qilmasa - yopiq
            log.exception("Guruhlar: ruxsat ro'yxati o'qilmadi")
            return False

    # --- shaxsiy chat ----------------------------------------------------------------

    def on_text(self, chat_id: int, text: str, user: AuthUser, login: str | None) -> bool:
        """"⚙️ Guruhlar" tugmasi - shu yerda; boshqa matn - `False`."""
        if text != BTN_GROUPS:
            return False
        if not self.allowed(user, login):
            # Eskirgan klaviatura (ruxsat olib tashlangan) - o'chiriladi.
            self._send(chat_id, esc(_CLOSED), markup=REMOVE_KEYBOARD)
            return True
        self._list(chat_id, 0, edit_id=None)
        return True

    def on_command(self, chat_id: int) -> None:
        """`/guruhlar` - ruxsat chaqiruvchida tekshirilgan."""
        self._list(chat_id, 0, edit_id=None)

    def on_callback(self, cq_id: str, chat_id: int, msg: dict[str, Any], user: AuthUser,
                    login: str | None, data: str) -> None:
        if not self.allowed(user, login):
            self._answer(cq_id, _CLOSED, alert=True)
            return
        parsed = parse_cb(data)
        if parsed is None:
            self._answer(cq_id, _STALE, alert=True)
            return
        action, value, kind = parsed
        edit_id = msg.get("message_id")
        if action == "i":
            self._answer(cq_id)
        elif action in ("m", "l"):
            self._answer(cq_id)
            self._list(chat_id, value or 0, edit_id=edit_id)
        elif action == "a":
            self._answer(cq_id)
            self._show(chat_id, _ADD, self._add_markup(), edit_id)
        else:
            info = self.registry.get(value) if value is not None else None
            if info is None or info.state in ("removed", "migrated"):
                self._answer(cq_id, _STALE, alert=True)
                return
            if not self._take(info.chat_id):
                self._answer(cq_id, "⏳ Bajarilmoqda…")
                return
            try:
                self._act(cq_id, chat_id, edit_id, user, action, info, kind)
            finally:
                self._release(info.chat_id)

    def _act(self, cq_id: str, chat_id: int, edit_id: Any, user: AuthUser, action: str, info: GroupInfo,
             kind: str | None) -> None:
        gid = info.chat_id
        title = self._title(info)
        if action in ("c", "v"):
            self._answer(cq_id, "Tekshirildi" if action == "v" else "")
            self._card(chat_id, self._refresh(info), edit_id)
        elif action == "on" and kind is not None:
            result = self.registry.activate(gid, kind, actor_id=user.actorId, owner_tg=chat_id)
            if result != "activated":
                self._answer(cq_id, _REFUSED[result], alert=True)
                self._card(chat_id, self.registry.get(gid) or info, edit_id)
                return
            self._answer(cq_id, "Yoqildi")
            notice = self._post_notice(gid)
            self._audit(user, "tg_group.activate", gid, {"kind": kind, "notice": notice, "title": title[:64]})
            log.info("Guruhlar: %s yoqildi (%s, e'lon: %s) - %s", gid, kind, notice, user.actorId)
            self._card(chat_id, self.registry.get(gid) or info, edit_id,
                       note=f"✅ <b>Yoqildi</b> · {KIND_NAME[kind]}\n{_NOTICE_RESULT[notice]}")
        elif action == "k" and kind is not None:
            if not self.registry.set_kind(gid, kind, actor_id=user.actorId, owner_tg=chat_id):
                self._answer(cq_id, _STALE, alert=True)
                return
            self._answer(cq_id, f"Turi: {KIND_NAME[kind]}")
            self._audit(user, "tg_group.kind", gid, {"kind": kind, "title": title[:64]})
            self._card(chat_id, self.registry.get(gid) or info, edit_id)
        elif action in ("p", "r"):
            changed = (self.registry.pause(gid, actor_id=user.actorId) if action == "p"
                       else self.registry.resume(gid, actor_id=user.actorId))
            if not changed:
                self._answer(cq_id, _STALE, alert=True)
            else:
                self._answer(cq_id, "To'xtatildi" if action == "p" else "Davom etmoqda")
                self._audit(user, "tg_group.pause" if action == "p" else "tg_group.resume", gid,
                            {"title": title[:64]})
            self._card(chat_id, self.registry.get(gid) or info, edit_id)
        elif action == "n":
            if not info.present:
                self._answer(cq_id, _REFUSED["gone"], alert=True)
                return
            self._answer(cq_id)
            notice = self._post_notice(gid, previous=info.notice_id)
            self._audit(user, "tg_group.notice", gid, {"notice": notice, "title": title[:64]})
            self._card(chat_id, self.registry.get(gid) or info, edit_id, note=_NOTICE_RESULT[notice])
        elif action == "x":
            self._answer(cq_id)
            count, _ = self.store.chat_stats(gid)
            text = (f"🗑 <b>«{esc(title)}»</b> o'chirilsinmi?\n\n"
                    "• Barno guruhni o'qishni to'xtatadi va guruhdan chiqadi.\n"
                    f"• Saqlangan {count} ta xabar va brif ma'lumotlari o'chiriladi — qaytarib bo'lmaydi.")
            self._show(chat_id, text, {"inline_keyboard": [[_btn("🗑 Ha, o'chirish", f"g:xy:{gid}"),
                                                             _btn("⬅ Bekor", f"g:c:{gid}")]]}, edit_id)
        elif action in ("xy", "no"):
            removed = self.registry.remove(gid, actor_id=user.actorId)
            if removed is None:
                self._answer(cq_id, _STALE, alert=True)
                self._list(chat_id, 0, edit_id=edit_id)
                return
            self._answer(cq_id, "O'chirildi" if action == "xy" else "Barno guruhdan chiqdi")
            if info.present:
                self._leave(gid, notice_id=info.notice_id, farewell=action == "xy")
            self._audit(user, "tg_group.remove" if action == "xy" else "tg_group.decline", gid,
                        {"messages": removed, "title": title[:64]})
            log.info("Guruhlar: %s o'chirildi (%d xabar) - %s", gid, removed, user.actorId)
            note = (f"🗑 <b>«{esc(title)}»</b> o'chirildi." if action == "xy"
                    else f"✖️ <b>«{esc(title)}»</b> qo'shilmadi — Barno guruhdan chiqdi.")
            self._list(chat_id, 0, edit_id=edit_id, note=note)
        else:
            self._answer(cq_id, _STALE, alert=True)

    # --- ro'yxat va karta --------------------------------------------------------------

    def _list(self, chat_id: int, page: int, *, edit_id: Any, note: str = "") -> None:
        groups = sorted(self.registry.listing(), key=self._order)
        pages = max(1, (len(groups) + PAGE - 1) // PAGE)
        page = min(max(page, 0), pages - 1)
        if self._fill_titles(groups[page * PAGE:(page + 1) * PAGE]):
            groups = sorted(self.registry.listing(), key=self._order)
        waiting = sum(1 for g in groups if self._icon(g) == "🕓")
        lines = ([note, ""] if note else []) + [_LIST_HEAD]
        if waiting:
            lines.append(f"\n🕓 <b>{waiting} ta guruh</b> yoqilishini kutmoqda.")
        if not groups:
            lines.append("\n" + _EMPTY)
        rows = [[_btn(f"{self._icon(g)}{KIND_ICON.get(g.kind, '❔')} {short_title(self._title(g), 40)}",
                      f"g:c:{g.chat_id}")] for g in groups[page * PAGE:(page + 1) * PAGE]]
        if pages > 1:
            rows.append([_btn("‹", f"g:l:{max(page - 1, 0)}"), _btn(f"{page + 1}/{pages}", "g:i"),
                         _btn("›", f"g:l:{min(page + 1, pages - 1)}")])
        rows.append([_btn("➕ Guruh qo'shish", "g:a")])
        rows.append([_btn("⬅ Brif menyusi", "b:m")])
        self._show(chat_id, "\n".join(lines), {"inline_keyboard": rows}, edit_id)

    def _fill_titles(self, groups: list[GroupInfo]) -> bool:
        """Nomi saqlanmagan guruh (masalan xabar kelmagan `.env` guruhi) - nomi
        Telegram'dan, faqat ko'rinayotgan sahifadagilar uchun."""
        filled = False
        for info in groups:
            if info.title or not info.present:
                continue
            try:
                title = str(self.api.get_chat(info.chat_id).get("title") or "")
            except TelegramError as exc:
                self._lost(info.chat_id, exc)
                continue
            if title:
                self.store.set_title(info.chat_id, title)
                filled = True
        return filled

    def _card(self, chat_id: int, info: GroupInfo, edit_id: Any, *, note: str = "") -> None:
        count, first = self.store.chat_stats(info.chat_id)
        if not info.present:
            state = "⚠️ Barno guruhda emas"
        elif info.effective:
            state = "✅ yoqilgan"
        else:
            state = "⏸ to'xtatilgan" if info.state == "paused" else "🕓 yoqilmagan"
        if info.bot_status in ("administrator", "creator"):
            venera = "👑 administrator · " + ("📌 e'lonni qadashi mumkin" if info.can_pin else "📌 qadash huquqi yo'q")
        elif info.bot_status in ("member", "restricted"):
            venera = "👤 oddiy a'zo" + ("" if self.can_read_all else " — ⚠️ xabarlarni o'qiy olmaydi")
        elif not info.present:
            venera = "guruhdan chiqarilgan"
        else:
            venera = "❔ noma'lum — «🔄 Tekshirish»"
        lines = [f"{self._icon(info)}{KIND_ICON.get(info.kind, '❔')} <b>{esc(self._title(info))}</b>",
                 f"Holat: {state}", f"Turi: {KIND_NAME.get(info.kind, '❔ tanlanmagan')}", f"Barno: {venera}",
                 f"E'lon: {'📌 yozilgan' if info.notice_id else 'yozilmagan'}",
                 f"Saqlangan: {count} ta xabar" + (f" · {uz_date(first)} dan beri" if first else "")]
        if info.from_env and not info.adopted:
            lines.append("<i>.env ro'yxatidan — biror qaror qilsangiz, endi bot boshqaradi.</i>")
        if note:
            lines = [note, ""] + lines
        self._show(chat_id, "\n".join(lines), self._card_markup(info), edit_id)

    def _card_markup(self, info: GroupInfo) -> dict[str, Any]:
        gid = info.chat_id
        link = self._add_link()

        def kinds(action: str) -> list[dict[str, str]]:
            return [_btn(("✓ " if info.kind == kind else "") + KIND_NAME[kind], f"g:{action}:{gid}:{_CODE_OF[kind]}")
                    for kind in KINDS]

        rows: list[list[dict[str, str]]] = []
        pending = info.present and not info.effective and info.state != "paused"
        if not info.present:
            if link:
                rows.append([{"text": "👑 Qayta qo'shish", "url": link}])
        elif info.effective:
            rows.append(kinds("k"))
            rows.append([_btn("⏸ To'xtatish", f"g:p:{gid}"), _btn("📣 E'lonni yuborish", f"g:n:{gid}")])
        elif info.state == "paused":
            rows.append(kinds("k"))
            rows.append([_btn("▶️ Davom ettirish", f"g:r:{gid}")])
        else:
            rows.append(kinds("on"))
            rows.append([_btn("✖️ Kerak emas", f"g:no:{gid}")])
        if info.present and self._cant_read(info) and link:
            rows.append([{"text": "👑 Administrator qilish", "url": link}])
        rows.append([_btn("🔄 Tekshirish", f"g:v:{gid}")] + ([] if pending else [_btn("🗑 O'chirish", f"g:x:{gid}")]))
        rows.append([_btn("⬅ Guruhlar", "g:m")])
        return {"inline_keyboard": rows}

    def _add_link(self) -> str | None:
        if not re.fullmatch(r"\w{3,64}", self.username):
            return None
        return f"https://t.me/{self.username}?startgroup&admin={ADD_RIGHTS}"

    def _add_markup(self) -> dict[str, Any]:
        rows: list[list[dict[str, str]]] = []
        link = self._add_link()
        if link:
            rows.append([{"text": "➕ Guruhni tanlash", "url": link}])
        rows.append([_btn("⬅ Guruhlar", "g:m")])
        return {"inline_keyboard": rows}

    def _cant_read(self, info: GroupInfo) -> bool:
        return info.bot_status in ("member", "restricted") and not self.can_read_all

    def _icon(self, info: GroupInfo) -> str:
        if not info.present or (info.effective and self._cant_read(info)):
            return "⚠️"
        if info.effective:
            return "✅"
        return "⏸" if info.state == "paused" else "🕓"

    def _order(self, info: GroupInfo) -> tuple[int, str]:
        return {"🕓": 0, "⚠️": 1, "✅": 2, "⏸": 3}[self._icon(info)], self._title(info).lower()

    @staticmethod
    def _title(info: GroupInfo) -> str:
        return info.title or f"Guruh …{str(info.chat_id)[-4:]}"

    # --- Telegram bilan --------------------------------------------------------------

    def _refresh(self, info: GroupInfo) -> GroupInfo:
        """Kartani ochganda: botning guruhdagi holati va nomi - Telegram'dan jonli."""
        if self.bot_id is None:
            return info
        try:
            member = self.api.get_chat_member(info.chat_id, self.bot_id)
        except TelegramError as exc:
            moved = self._lost(info.chat_id, exc)
            return (self.registry.get(moved) if moved else self.registry.get(info.chat_id, follow=False)) or info
        status, can_pin = _member(member)
        if status is not None and (status != info.bot_status or can_pin != info.can_pin):
            self.registry.member_status(info.chat_id, status, can_pin)
        if not info.title:
            try:
                self.store.set_title(info.chat_id, str(self.api.get_chat(info.chat_id).get("title") or ""))
            except (TelegramError, sqlite3.Error) as exc:
                log.info("Guruhlar: nom olinmadi (%s): %s", info.chat_id, exc)
        return self.registry.get(info.chat_id, follow=False) or info

    def _lost(self, chat_id: int, exc: TelegramError) -> int | None:
        """Telegram xatosidan: guruh supergroup'ga aylangan (yangi id qaytadi) yoki bot
        guruhda emas (holat yoziladi)."""
        if exc.migrate_to:
            self.registry.migrate(chat_id, exc.migrate_to)
            return exc.migrate_to
        description = exc.description.lower()
        if exc.code in (400, 403) and any(mark in description for mark in _NOT_THERE):
            self.registry.member_status(chat_id, "kicked" if "kicked" in description else "left", None)
        log.info("Guruhlar: Telegram xatosi (%s): %s", chat_id, exc.code)
        return None

    def _post_notice(self, chat_id: int, *, previous: int | None = None, retried: bool = False) -> str:
        """Guruhga e'lon va uni qadash. Natija: pinned | posted | failed."""
        try:
            sent = self.api.send_message(chat_id, notice(self.days))
        except TelegramError as exc:
            moved = self._lost(chat_id, exc)
            if moved and not retried:
                return self._post_notice(moved, retried=True)
            return "failed"
        message_id = sent.get("message_id") if isinstance(sent, dict) else None
        if not isinstance(message_id, int):
            return "posted"
        pinned = False
        try:
            self.api.pin_message(chat_id, message_id, silent=True)
            pinned = True
        except TelegramError as exc:
            log.info("Guruhlar: e'lon qadalmadi (%s): %s", chat_id, exc.code)
        if previous and previous != message_id:
            try:
                self.api.unpin_message(chat_id, previous)
            except TelegramError:
                pass
        self.registry.set_notice(chat_id, message_id)
        return "pinned" if pinned else "posted"

    def _leave(self, chat_id: int, *, notice_id: int | None, farewell: bool) -> None:
        """O'chirilgan guruhdan chiqish - hammasi "imkon bo'lsa" (bot allaqachon chiqarilgan bo'lishi mumkin)."""
        if notice_id:
            try:
                self.api.unpin_message(chat_id, notice_id)
            except TelegramError:
                pass
        if farewell:
            try:
                self.api.send_message(chat_id, esc(FAREWELL))
            except TelegramError:
                pass
        try:
            self.api.leave_chat(chat_id)
        except TelegramError as exc:
            log.info("Guruhlar: guruhdan chiqilmadi (%s): %s", chat_id, exc.code)

    # --- botning guruhdagi holati -------------------------------------------------------

    def on_member(self, update: dict[str, Any], *,
                  resolve: Callable[[int], tuple[AuthUser, str | None] | None]) -> None:
        """`my_chat_member`: bot qo'shildi, chiqarildi, admin qilindi yoki huquqi olindi."""
        chat = update.get("chat") or {}
        if chat.get("type") not in ("group", "supergroup") or not isinstance(chat.get("id"), int):
            return
        new = update.get("new_chat_member") or {}
        old = update.get("old_chat_member") or {}
        me = (new.get("user") or {}).get("id")
        if self.bot_id is not None and me != self.bot_id:
            return
        status, can_pin = _member(new)
        old_status, _ = _member(old)
        if status is None:
            return
        actor = (update.get("from") or {}).get("id")
        if self.bot_id is not None and actor == self.bot_id:
            # O'zimiz chiqdik (guruh o'chirildi) - faqat holat.
            self.registry.member_status(chat["id"], status, can_pin)
            return
        if status not in GONE and (old_status is None or old_status in GONE):
            self._joined(chat, actor if isinstance(actor, int) else None, status, can_pin, resolve)
        else:
            self._status_changed(chat, status, can_pin, old_status, resolve)

    def on_inactive(self, msg: dict[str, Any], *,
                    resolve: Callable[[int], tuple[AuthUser, str | None] | None]) -> str:
        """Yoqilmagan guruhdagi xabar. Natija: "join" - bot qo'shildi (guruhga
        "faqat shaxsiy chat" izohi kerak emas), "paused" / "pending" - guruhdagi
        izoh matni uchun, "" - noma'lum guruh (eski xulq)."""
        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        if not isinstance(chat_id, int):
            return ""
        members = msg.get("new_chat_members")
        if isinstance(members, list) and any(self._is_me(m) for m in members):
            adder = (msg.get("from") or {}).get("id")
            self._joined(chat, adder if isinstance(adder, int) else None, None, None, resolve)
            return "join"
        self.registry.seen(chat)
        state, asked = self.registry.state_of(chat_id)
        if state == "paused":
            return "paused"
        return "pending" if state == "pending" and asked else ""

    def on_migration(self, msg: dict[str, Any]) -> bool:
        """`migrate_to_chat_id` (eski guruhda) / `migrate_from_chat_id` (yangisida) -
        ro'yxat va tarix yangi id ga o'tadi. Ikkalasi ham keladi - takror zararsiz."""
        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        if not isinstance(chat_id, int):
            return False
        if isinstance(msg.get("migrate_to_chat_id"), int):
            old, new = chat_id, msg["migrate_to_chat_id"]
        elif isinstance(msg.get("migrate_from_chat_id"), int):
            old, new = msg["migrate_from_chat_id"], chat_id
        else:
            return False
        try:
            if self.registry.migrate(old, new, title=str(chat.get("title") or "")):
                self._audit(None, "tg_group.migrate", new, {"from": old})
        except sqlite3.Error as exc:
            log.error("Guruhlar: supergroup'ga o'tish yozilmadi (%s -> %s): %s", old, new, exc)
        return True

    def _joined(self, chat: dict[str, Any], adder: int | None, status: str | None, can_pin: bool | None,
                resolve: Callable[[int], tuple[AuthUser, str | None] | None]) -> None:
        chat_id = chat["id"]
        if status is None or (status in ("member", "restricted") and not self.can_read_all):
            # Holat noma'lum yoki oddiy a'zo: admin qilish bir lahzadan keyin
            # keladi - jonli tekshiramiz, keraksiz ogohlantirish bo'lmasin.
            if status is not None and self.settle > 0:
                self._sleep(self.settle)
            live = self._live(chat_id)
            if live is not None:
                status, can_pin = live
        info, first = self.registry.joined(chat, adder_tg=adder, bot_status=status, can_pin=can_pin)
        if info is None or not first:
            return
        title = esc(self._title(info))
        if info.effective:
            target = info.owner_tg or adder
            if isinstance(target, int) and resolve(target) is not None:
                self._send(target, _BACK.format(title=title))
            return
        if adder is not None and resolve(adder) is not None:
            text = _JOINED.format(title=title) + ("\n\n" + _CANT_READ if self._cant_read(info) else "")
            rows = [[_btn(KIND_NAME[kind], f"g:on:{chat_id}:{_CODE_OF[kind]}") for kind in KINDS],
                    [_btn("✖️ Kerak emas", f"g:no:{chat_id}")]]
            link = self._add_link()
            if self._cant_read(info) and link:
                rows.append([{"text": "👑 Administrator qilish", "url": link}, _btn("🔄 Tekshirish", f"g:v:{chat_id}")])
            if self._send(adder, text, markup={"inline_keyboard": rows}) is not None:
                log.info("Guruhlar: bot guruhga qo'shildi (%s) - rahbarga turi so'raldi", chat_id)
                return
        log.info("Guruhlar: bot guruhga qo'shildi (%s) - kutilmoqda", chat_id)
        try:
            self.api.send_message(chat_id, esc(GROUP_NOT_ENABLED))
        except TelegramError as exc:
            self._lost(chat_id, exc)

    def _status_changed(self, chat: dict[str, Any], status: str, can_pin: bool | None, old_status: str | None,
                        resolve: Callable[[int], tuple[AuthUser, str | None] | None]) -> None:
        before, after = self.registry.member_status(chat["id"], status, can_pin)
        if after is None:
            return
        target = after.owner_tg or after.added_tg
        if not isinstance(target, int) or resolve(target) is None:
            target = None
        title = esc(self._title(after))
        if status in GONE:
            if before is not None and before.effective:
                self._audit(None, "tg_group.bot_left", after.chat_id, {"status": status, "title": after.title[:64]})
                log.info("Guruhlar: bot guruhdan chiqarildi (%s)", after.chat_id)
                if target:
                    self._send(target, _KICKED.format(title=title))
            return
        was_admin = old_status in ("administrator", "creator")
        is_admin = status in ("administrator", "creator")
        quiet = after.asked_at is not None and self._clock() - after.asked_at < _JOIN_QUIET
        if was_admin and not is_admin and not self.can_read_all and before is not None and before.effective:
            if target:
                self._send(target, _DEMOTED.format(title=title))
        elif is_admin and not was_admin and not quiet and target and (after.effective or after.state == "pending"):
            self._send(target, _PROMOTED.format(title=title))

    def _live(self, chat_id: int) -> tuple[str | None, bool | None] | None:
        if self.bot_id is None:
            return None
        try:
            return _member(self.api.get_chat_member(chat_id, self.bot_id))
        except TelegramError as exc:
            log.info("Guruhlar: bot holati olinmadi (%s): %s", chat_id, exc.code)
            return None

    def _is_me(self, member: Any) -> bool:
        if not isinstance(member, dict):
            return False
        if self.bot_id is not None:
            return member.get("id") == self.bot_id
        name = self.username.lower()
        return bool(member.get("is_bot")) and bool(name) and str(member.get("username") or "").lower() == name

    # --- yordamchilar ---------------------------------------------------------------

    def _audit(self, user: AuthUser | None, action: str, chat_id: int, detail: dict[str, Any]) -> None:
        """Qaror BAJARILGAN - audit yozilmasa faqat jurnalga (admin_users dagi kabi)."""
        try:
            self._audit_write(user, action, chat_id, detail)
        except Exception as exc:  # noqa: BLE001
            log.error("Audit yozilmadi (guruh %s, %s): %s", chat_id, action, exc)

    def _take(self, chat_id: int) -> bool:
        with self._busy_lock:
            if chat_id in self._busy:
                return False
            self._busy.add(chat_id)
            return True

    def _release(self, chat_id: int) -> None:
        with self._busy_lock:
            self._busy.discard(chat_id)

    def _show(self, chat_id: int, text: str, markup: dict[str, Any] | None, edit_id: Any) -> int | None:
        if isinstance(edit_id, int):
            try:
                self.api.edit_message_text(chat_id, edit_id, text, reply_markup=markup)
                return edit_id
            except TelegramError as exc:
                if exc.not_modified:
                    return edit_id
                log.debug("Guruhlar: xabar tahrirlanmadi: %s", exc)
        return self._send(chat_id, text, markup=markup)

    def _send(self, chat_id: int, text: str, *, markup: dict[str, Any] | None = None) -> int | None:
        try:
            sent = self.api.send_message(chat_id, text, reply_markup=markup)
        except TelegramError as exc:
            if not exc.bad_markup:
                log.info("Guruhlar: xabar yuborilmadi: %s", exc.code)
                return None
            try:
                sent = self.api.send_message(chat_id, render.plain(text), html=False, reply_markup=markup)
            except TelegramError as again:
                log.info("Guruhlar: xabar yuborilmadi: %s", again.code)
                return None
        message_id = sent.get("message_id") if isinstance(sent, dict) else None
        return message_id if isinstance(message_id, int) else None

    def _answer(self, cq_id: str | None, text: str = "", *, alert: bool = False) -> None:
        if not cq_id:
            return
        try:
            self.api.answer_callback(cq_id, text, alert=alert)
        except TelegramError as exc:
            log.debug("Guruhlar: tugma javobi: %s", exc)
