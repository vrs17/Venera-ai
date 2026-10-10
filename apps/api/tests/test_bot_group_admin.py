"""Guruhlarni botda boshqarish (`app/bot/group_admin.py`) va guruhlar ro'yxati
(`services/tg_groups.GroupRegistry`)."""

from __future__ import annotations

import io
import itertools
import json
import sqlite3
import threading
import time
import urllib.error

from types import SimpleNamespace

import pytest

from app.bot.briefs import BTN_GROUPS, REMOVE_KEYBOARD, REPLY_KEYBOARD_ADMIN, BriefEngine, BriefService, _CLOSED
from app.bot.group_admin import FAREWELL, GROUP_NOT_ENABLED, GROUP_PAUSED, GroupAdmin, parse_cb
from app.bot.groups import GroupAssistant
from app.bot.runner import _UNKNOWN, VeneraBot
from app.services.integrations.telegram import TelegramApi, TelegramError
from app.services.telegram_links import LinkStore
from app.services.tg_groups import GroupRegistry, GroupStore, _effective
from tests.test_bot_briefs import ScriptWriter
from tests.test_bot_groups import FakeWriter, GroupTelegram
from tests.test_bot_ux import BOT_NAME, WEBAPP, Directory, _stored, all_buttons, press, toasts
from tests.test_telegram_bot import TG_ID, FakeBackend, text_update

BOT_ID = 9990001
EXEC_TG = TG_ID
STAFF_TG = 5550002
G_NEW = -1003000000001
G_ENV = -1001111111111
_ids = itertools.count(1000)


class AdminTelegram(GroupTelegram):
    """`GroupTelegram` + guruh boshqaruvi usullari va xato berish."""

    def __init__(self, *, read_all: bool = False) -> None:
        super().__init__()
        self.read_all = read_all
        self.members: dict[int, dict] = {}
        self.titles: dict[int, str] = {}
        self.errors: dict[str, Exception] = {}

    def _fail(self, key):
        error = self.errors.get(key)
        if error is not None:
            raise error

    def get_me(self):
        return {"id": BOT_ID, "username": BOT_NAME, "can_read_all_group_messages": self.read_all}

    def send_message(self, chat_id, text, *, html=True, reply_markup=None, reply_to=None, thread_id=None):
        self._fail(f"send:{chat_id}")
        return super().send_message(chat_id, text, html=html, reply_markup=reply_markup, reply_to=reply_to,
                                    thread_id=thread_id)

    def edit_message_text(self, chat_id, message_id, text, *, html=True, reply_markup=None):
        self._rec("edit_message_text", chat_id=chat_id, message_id=message_id, text=text,
                  reply_markup=reply_markup)

    def get_chat_member(self, chat_id, user_id):
        self._fail(f"member:{chat_id}")
        self._rec("get_chat_member", chat_id=chat_id, user_id=user_id)
        return {"user": {"id": user_id}, **self.members.get(chat_id, {"status": "administrator",
                                                                      "can_pin_messages": True})}

    def get_chat(self, chat_id):
        self._rec("get_chat", chat_id=chat_id)
        return {"id": chat_id, "title": self.titles.get(chat_id, "")}

    def pin_message(self, chat_id, message_id, *, silent=True):
        self._fail(f"pin:{chat_id}")
        self._rec("pin_message", chat_id=chat_id, message_id=message_id, silent=silent)

    def unpin_message(self, chat_id, message_id):
        self._rec("unpin_message", chat_id=chat_id, message_id=message_id)

    def leave_chat(self, chat_id):
        self._rec("leave_chat", chat_id=chat_id)


def make_admin_world(tmp_path, *, env=(G_ENV,), logins=("a@b.uz",), read_all=False):
    tg = AdminTelegram(read_all=read_all)
    store = GroupStore(tmp_path / "telegram" / "groups.db")
    env_ids = set(env)
    clock = [1_800_000_000.0]
    registry = GroupRegistry(store, env=lambda: frozenset(env_ids), ttl=0, clock=lambda: clock[0])
    audits: list[tuple] = []
    admin = GroupAdmin(tg, registry, store, logins=lambda: frozenset(logins),
                       audit=lambda user, action, chat_id, detail: audits.append(
                           (getattr(user, "actorId", None), action, chat_id, detail)),
                       settle=0, clock=lambda: clock[0])
    groups = GroupAssistant(tg, store, FakeWriter(), allowed=registry.allowed_ids, inline=True,
                            limits=lambda: ((10, 60.0), (120, 3600.0)))
    engine = BriefEngine(store, ScriptWriter(), groups=registry.allowed_ids)
    briefs = BriefService(tg, engine, groups=registry.allowed_ids, logins=lambda: frozenset(logins),
                          inline=True, manage=True)
    directory = Directory(_stored(actor_id=1, email="a@b.uz"), _stored(actor_id=2, email="c@d.uz"))
    links = LinkStore(tmp_path / "links.json")
    links.link(EXEC_TG, 1)
    links.link(STAFF_TG, 2)
    bot = VeneraBot(tg, links, users=lambda: directory, backend=FakeBackend(), webapp_url=WEBAPP, inline=True,
                    typing_every=None, groups=groups, briefs=briefs, admin=admin)
    bot._prepare()
    return SimpleNamespace(tg=tg, store=store, registry=registry, admin=admin, bot=bot, env=env_ids,
                           audits=audits, clock=clock, briefs=briefs)


@pytest.fixture
def w(tmp_path):
    return make_admin_world(tmp_path)


def _bot_member(status, *, can_pin=True):
    member = {"user": {"id": BOT_ID, "is_bot": True, "username": BOT_NAME}, "status": status}
    if status == "administrator":
        member["can_pin_messages"] = can_pin
    return member


def member_update(chat_id, old, new, *, by=EXEC_TG, title="Yangi guruh", chat_type="supergroup", can_pin=True):
    return {"update_id": next(_ids), "my_chat_member": {
        "chat": {"id": chat_id, "type": chat_type, "title": title},
        "from": {"id": by, "is_bot": by == BOT_ID, "first_name": "X"}, "date": 1,
        "old_chat_member": _bot_member(old), "new_chat_member": _bot_member(new, can_pin=can_pin)}}


def gmessage(chat_id, text=None, *, by=(501, "Makhmud"), title="Yangi guruh", chat_type="supergroup", **extra):
    message = {"message_id": next(_ids), "date": int(time.time()) - 30,
               "chat": {"id": chat_id, "type": chat_type, "title": title},
               "from": {"id": by[0], "is_bot": False, "first_name": by[1]}, **extra}
    if text is not None:
        message["text"] = text
    return message


def send(w, message):
    w.bot.handle_update({"update_id": next(_ids), "message": message})


def to(w, chat_id):
    return [kw for kw in w.tg.sent() if kw["chat_id"] == chat_id]


def last_screen(w):
    """Shaxsiy chatdagi oxirgi menyu: tahrir yoki yangi xabar - matn va tugmalar."""
    for name, kw in reversed(w.tg.calls):
        if name in ("edit_message_text", "send_message") and kw["chat_id"] == EXEC_TG:
            return kw["text"], kw.get("reply_markup")
    return "", None


def join(w, chat_id=G_NEW, *, by=EXEC_TG, status="administrator"):
    w.bot.handle_update(member_update(chat_id, "left", status, by=by))


# --- ro'yxat qoidasi ----------------------------------------------------------------------


def test_royxat_qatorsiz_aynan_env(w):
    assert w.registry.allowed_ids() == frozenset({G_ENV})
    assert w.registry.kind_of(G_ENV) is None
    w.env.add(-1002)
    assert w.registry.allowed_ids() == frozenset({G_ENV, -1002})          # .env - jonli


@pytest.mark.parametrize("row, in_env, expected", [
    (None, True, True), (None, False, False),
    ({"state": "pending", "decided_by": None, "bot_status": None}, True, True),
    ({"state": "pending", "decided_by": None, "bot_status": None}, False, False),
    ({"state": "pending", "decided_by": 1, "bot_status": None}, True, False),      # o'chirilib qayta qo'shilgan
    ({"state": "active", "decided_by": 1, "bot_status": "administrator"}, False, True),
    ({"state": "active", "decided_by": 1, "bot_status": "kicked"}, True, False),
    ({"state": "paused", "decided_by": 1, "bot_status": None}, True, False),
    ({"state": "removed", "decided_by": 1, "bot_status": None}, True, False),
    ({"state": "migrated", "decided_by": None, "bot_status": None}, True, False),
])
def test_samarali_qoida(row, in_env, expected):
    assert _effective(row, in_env) is expected


def test_env_guruhi_toxtatiladi_va_bot_boshqaruviga_otadi(w):
    assert w.registry.pause(G_ENV, actor_id=1) and G_ENV not in w.registry.allowed_ids()
    assert w.registry.resume(G_ENV, actor_id=1) and G_ENV in w.registry.allowed_ids()
    w.env.clear()
    assert G_ENV in w.registry.allowed_ids()                               # qaror - endi .env emas


def test_ombor_oqilmasa_env_bilan_ishlaydi(w, monkeypatch):
    w.registry.pause(G_ENV, actor_id=1)

    def broken():
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(w.store, "_tx", broken)
    w.registry.invalidate()
    assert w.registry.allowed_ids() == frozenset({G_ENV})


def test_yoqish_bir_marta_parallel_bosishda(w):
    w.registry.seen({"id": G_NEW, "type": "supergroup", "title": "Yangi"})
    results = []
    threads = [threading.Thread(target=lambda: results.append(
        w.registry.activate(G_NEW, "support", actor_id=1, owner_tg=EXEC_TG))) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results.count("activated") == 1 and results.count("already") == 5


def test_kutilayotgan_guruhlar_chegarasi(tmp_path):
    store = GroupStore(tmp_path / "g.db")
    registry = GroupRegistry(store, env=lambda: frozenset(), ttl=0, pending_max=2)
    for n in range(4):
        registry.seen({"id": -100 - n, "type": "group", "title": f"G{n}"})
    assert len(registry.listing()) == 2


def test_supergroupga_otish_holat_va_tarix(w):
    w.registry.seen({"id": -500, "type": "group", "title": "Oddiy"})
    w.registry.activate(-500, "project", actor_id=1, owner_tg=EXEC_TG)
    first = gmessage(-500, "birinchi", chat_type="group")
    second = gmessage(-500, "javob", chat_type="group", reply_to_message={"message_id": first["message_id"]})
    w.store.add(first)
    w.store.add(second)
    assert w.registry.migrate(-500, -100500, title="Oddiy")
    assert not w.registry.migrate(-500, -100500)                             # takror - zararsiz
    rows = w.store.window(-100500, 0, time.time() + 60)
    assert [r.text for r in rows] == ["birinchi", "javob"] and all(r.message_id < 0 for r in rows)
    assert rows[1].reply_to == rows[0].message_id
    assert w.registry.allowed_ids() == frozenset({G_ENV, -100500}) and w.registry.kind_of(-100500) == "project"
    assert w.registry.get(-500).chat_id == -100500                           # eski tugmalar yangisiga
    w.store.add(gmessage(-100500, "yangi", message_id=first["message_id"]))  # raqam to'qnashmaydi
    assert len(w.store.window(-100500, 0, time.time() + 60)) == 3


def test_env_guruhi_supergroupga_otsa_yoqilgan_qoladi(w):
    w.registry.migrate(G_ENV, -1009)
    assert w.registry.allowed_ids() == frozenset({-1009})                    # .env ni tuzatish shart emas


def test_ochirish_hammasini_ochiradi_va_supuradi(w):
    w.store.add(gmessage(G_ENV, "salom"))
    assert w.registry.remove(G_ENV, actor_id=1) == 1
    assert G_ENV not in w.registry.allowed_ids() and w.registry.remove(G_ENV, actor_id=1) is None
    w.store.add(gmessage(G_ENV, "kech qolgan"))                              # ip poygasi
    w.store.purge()
    assert w.store.count() == 0


def test_eski_v3_ombor_v4_ga(tmp_path):
    path = tmp_path / "groups.db"
    conn = sqlite3.connect(path)
    conn.executescript("CREATE TABLE messages (chat_id INTEGER NOT NULL, message_id INTEGER NOT NULL,"
                       " thread_id INTEGER, date INTEGER NOT NULL, from_id INTEGER, from_name TEXT NOT NULL"
                       " DEFAULT '', username TEXT, text TEXT NOT NULL, reply_to INTEGER, edited_at INTEGER,"
                       " orig_date INTEGER, PRIMARY KEY (chat_id, message_id)); PRAGMA user_version = 3;")
    conn.close()
    store = GroupStore(path)
    assert GroupRegistry(store, env=lambda: frozenset({-1})).allowed_ids() == frozenset({-1})
    check = sqlite3.connect(path)
    assert check.execute("PRAGMA user_version").fetchone()[0] == 4
    check.close()


# --- Telegram qatlami -------------------------------------------------------------------


def test_polling_bot_qoshilishini_ham_oladi(monkeypatch):
    api = TelegramApi("123:abc")
    seen = {}
    monkeypatch.setattr(api, "call", lambda method, params=None, timeout=None: seen.update(params) or [])
    api.get_updates(None)
    assert "my_chat_member" in seen["allowed_updates"]


def test_supergroup_xatosi_yangi_id_ni_beradi(monkeypatch):
    api = TelegramApi("123:abc")
    body = json.dumps({"ok": False, "error_code": 400,
                       "description": "Bad Request: group chat was upgraded to a supergroup chat",
                       "parameters": {"migrate_to_chat_id": -1009}}).encode()

    def fail(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 400, "Bad Request", {}, io.BytesIO(body))

    monkeypatch.setattr("urllib.request.urlopen", fail)
    with pytest.raises(TelegramError) as caught:
        api.send_message(-500, "salom")
    assert caught.value.migrate_to == -1009 and "123:abc" not in str(caught.value)


def test_webhook_turlar_ozgarsa_qayta_ornatiladi(tmp_path):
    from tests.test_telegram_bot import WEBHOOK_URL, WebhookTelegram, webhook_bot

    tg = WebhookTelegram()
    bot = webhook_bot(tmp_path, tg)
    bot.check_webhook(now=1000.0)
    tg.info = {"url": WEBHOOK_URL, "pending_update_count": 0,
               "allowed_updates": ["message", "edited_message", "callback_query"]}
    assert bot.check_webhook(now=1060.0) and len(tg.set_calls) == 2
    tg.info = {"url": WEBHOOK_URL, "pending_update_count": 0, "allowed_updates": list(reversed(
        ["message", "edited_message", "callback_query", "my_chat_member"]))}
    assert bot.check_webhook(now=1120.0) and len(tg.set_calls) == 2


def test_bot_ozini_taniydi(w):
    assert w.bot.bot_id == BOT_ID and w.admin.bot_id == BOT_ID and w.admin.can_read_all is False


# --- qo'shilish -------------------------------------------------------------------------


def test_rahbar_qoshsa_turi_soraladi_guruhga_jim(w):
    join(w)
    [dm] = to(w, EXEC_TG)
    assert "«Yangi guruh»" in dm["text"] and "Guruh turini tanlang" in dm["text"]
    data = [b.get("callback_data") for b in all_buttons(dm["reply_markup"])]
    assert data == [f"g:on:{G_NEW}:s", f"g:on:{G_NEW}:p", f"g:no:{G_NEW}"]
    assert to(w, G_NEW) == [] and G_NEW not in w.registry.allowed_ids()


def test_bir_qoshilish_uch_signal_bitta_xabar(w):
    send(w, gmessage(G_NEW, by=(EXEC_TG, "Rahbar"), new_chat_members=[
        {"id": BOT_ID, "is_bot": True, "username": BOT_NAME}]))
    join(w)
    w.bot.handle_update(member_update(G_NEW, "member", "administrator"))
    assert len(to(w, EXEC_TG)) == 1
    assert to(w, G_NEW) == []                                                # "faqat shaxsiy chat" yo'q


def test_turi_tanlansa_elon_qadaladi_va_oqiladi(w):
    join(w)
    w.bot.handle_update(press(f"g:on:{G_NEW}:s", tg_id=EXEC_TG))
    assert w.registry.allowed_ids() == frozenset({G_ENV, G_NEW}) and w.registry.kind_of(G_NEW) == "support"
    [notice] = to(w, G_NEW)
    for part in ("/summary", "/askbarno", "rahbariyati", "90 kun", "maosh, ta'til, kasallik"):
        assert part in notice["text"], part
    assert w.tg.sent("pin_message") == [{"chat_id": G_NEW, "message_id": notice["message_id"], "silent": True}]
    assert w.registry.get(G_NEW).notice_id == notice["message_id"]
    assert [a[:3] for a in w.audits] == [(1, "tg_group.activate", G_NEW)]
    assert w.audits[0][3]["kind"] == "support" and w.audits[0][3]["notice"] == "pinned"
    text, _ = last_screen(w)
    assert "Yoqildi" in text and "qadaldi" in text
    send(w, gmessage(G_NEW, "Pul o'tkazish ishlamayapti"))
    assert w.store.count() == 1


def test_qadash_huquqi_bolmasa_aytiladi(w):
    join(w)
    w.tg.errors[f"pin:{G_NEW}"] = TelegramError("pin: 400", code=400, description="Bad Request: not enough rights")
    w.bot.handle_update(press(f"g:on:{G_NEW}:p", tg_id=EXEC_TG))
    text, _ = last_screen(w)
    assert "qadab bo'lmadi" in text and w.registry.get(G_NEW).notice_id is not None


def test_oddiy_xodim_qoshsa_kutadi(w):
    join(w, by=STAFF_TG)
    assert to(w, STAFF_TG) == [] and to(w, EXEC_TG) == []
    [note] = to(w, G_NEW)
    assert note["text"] == GROUP_NOT_ENABLED
    w.bot.handle_update(text_update(BTN_GROUPS, tg_id=EXEC_TG))
    text, markup = last_screen(w)
    assert "1 ta guruh</b> yoqilishini kutmoqda" in text
    assert any(b.get("callback_data") == f"g:c:{G_NEW}" and b["text"].startswith("🕓")
               for b in all_buttons(markup))


def test_rahbarga_yozib_bolmasa_guruhga_izoh(w):
    w.tg.errors[f"send:{EXEC_TG}"] = TelegramError("403", code=403, description="Forbidden: bot was blocked by the user")
    join(w)
    assert [m["text"] for m in to(w, G_NEW)] == [GROUP_NOT_ENABLED]


def test_oddiy_azo_bolsa_ogohlantirish_va_admin_havolasi(w):
    w.tg.members[G_NEW] = {"status": "member"}
    join(w, status="member")
    [dm] = to(w, EXEC_TG)
    assert "oddiy a'zo" in dm["text"]
    urls = [b.get("url") for b in all_buttons(dm["reply_markup"]) if b.get("url")]
    assert urls == [f"https://t.me/{BOT_NAME}?startgroup&admin=pin_messages"]


def test_keyinroq_admin_qilinsa_xabar(w):
    w.tg.members[G_NEW] = {"status": "member"}
    join(w, status="member")
    w.clock[0] += 300
    w.bot.handle_update(member_update(G_NEW, "member", "administrator"))
    assert "endi barcha xabarlarni o'qiydi" in to(w, EXEC_TG)[-1]["text"]


def test_admin_huquqi_olinsa_ogohlantiriladi(w):
    join(w)
    w.bot.handle_update(press(f"g:on:{G_NEW}:p", tg_id=EXEC_TG))
    w.bot.handle_update(member_update(G_NEW, "administrator", "member", by=501))
    assert "endi administrator emas" in to(w, EXEC_TG)[-1]["text"]


def test_chiqarilsa_va_qaytsa(w):
    join(w)
    w.bot.handle_update(press(f"g:on:{G_NEW}:p", tg_id=EXEC_TG))
    w.bot.handle_update(member_update(G_NEW, "administrator", "kicked", by=501))
    assert G_NEW not in w.registry.allowed_ids()
    assert "guruhidan chiqarildi" in to(w, EXEC_TG)[-1]["text"]
    assert w.audits[-1][:3] == (None, "tg_group.bot_left", G_NEW)
    join(w)
    assert G_NEW in w.registry.allowed_ids() and "qaytdi" in to(w, EXEC_TG)[-1]["text"]


def test_ozimiz_chiqsak_jim(w):
    join(w)
    before = len(w.tg.sent())
    w.bot.handle_update(member_update(G_NEW, "administrator", "left", by=BOT_ID))
    assert len(w.tg.sent()) == before and not w.registry.get(G_NEW).present


def test_yoqilmagan_guruh_mazmuni_saqlanmaydi(w):
    send(w, gmessage(-1004, "maxfiy reja", title="Begona"))
    assert w.store.count() == 0
    info = w.registry.get(-1004)
    assert info.state == "pending" and info.title == "Begona" and not info.effective


# --- menyu va tugmalar ------------------------------------------------------------------


def test_start_rahbarga_guruhlar_tugmasi(w):
    w.bot.handle_update(text_update("/start", tg_id=EXEC_TG))
    keyboards = [kw["reply_markup"] for kw in to(w, EXEC_TG) if kw.get("reply_markup") == REPLY_KEYBOARD_ADMIN]
    assert keyboards and REPLY_KEYBOARD_ADMIN["keyboard"][1] == [{"text": BTN_GROUPS}]


def test_menyu_faqat_rahbarga(w):
    join(w)
    w.bot.handle_update(text_update(BTN_GROUPS, tg_id=STAFF_TG))
    assert to(w, STAFF_TG)[-1]["text"] == _CLOSED and to(w, STAFF_TG)[-1]["reply_markup"] == REMOVE_KEYBOARD
    w.bot.handle_update(text_update("/guruhlar", tg_id=STAFF_TG))
    assert to(w, STAFF_TG)[-1]["text"] == _UNKNOWN
    w.bot.handle_update(press(f"g:on:{G_NEW}:s", tg_id=STAFF_TG))
    assert toasts(w.tg)[-1] == (_CLOSED, True) and G_NEW not in w.registry.allowed_ids()


def test_royxat_sahifalar_va_tugmalar_64_bayt(w):
    w.registry.pending_max = 100
    for n in range(11):
        w.registry.seen({"id": -1000000000000 - n, "type": "supergroup", "title": f"Guruh {n:02d}"})
    w.bot.handle_update(text_update("/guruhlar", tg_id=EXEC_TG))
    text, markup = last_screen(w)
    buttons = all_buttons(markup)
    data = [b["callback_data"] for b in buttons if "callback_data" in b]
    assert "12 ta guruh</b> yoqilishini kutmoqda" not in text and "11 ta guruh" in text
    assert "g:l:1" in data and "b:m" in data and "g:a" in data
    assert all(len(d.encode()) <= 64 for d in data)
    assert all(parse_cb(d) is not None for d in data if d.startswith("g:"))
    w.bot.handle_update(press("g:l:1", tg_id=EXEC_TG))
    _, markup = last_screen(w)
    assert sum(1 for b in all_buttons(markup) if b.get("callback_data", "").startswith("g:c:")) == 4


def test_qoshish_havolasi(w):
    w.bot.handle_update(press("g:a", tg_id=EXEC_TG))
    text, markup = last_screen(w)
    assert "administrator" in text
    assert [b["url"] for b in all_buttons(markup) if "url" in b] == [
        f"https://t.me/{BOT_NAME}?startgroup&admin=pin_messages"]


def test_toxtatilsa_saqlanmaydi_va_izoh(w):
    join(w)
    w.bot.handle_update(press(f"g:on:{G_NEW}:p", tg_id=EXEC_TG))
    w.bot.handle_update(press(f"g:p:{G_NEW}", tg_id=EXEC_TG))
    assert G_NEW not in w.registry.allowed_ids() and w.audits[-1][1] == "tg_group.pause"
    send(w, gmessage(G_NEW, "oddiy gap"))
    send(w, gmessage(G_NEW, f"@{BOT_NAME} xulosa ber"))
    assert w.store.count() == 0 and to(w, G_NEW)[-1]["text"] == GROUP_PAUSED
    w.bot.handle_update(press(f"g:r:{G_NEW}", tg_id=EXEC_TG))
    send(w, gmessage(G_NEW, "yana gap"))
    assert w.store.count() == 1


def test_ochirish_tasdiq_bilan_va_guruhdan_chiqish(w):
    send(w, gmessage(G_ENV, "salom"))
    w.bot.handle_update(press(f"g:x:{G_ENV}", tg_id=EXEC_TG))
    text, markup = last_screen(w)
    assert "o'chirilsinmi" in text and "1 ta xabar" in text and w.store.count() == 1
    assert [b["callback_data"] for b in all_buttons(markup)] == [f"g:xy:{G_ENV}", f"g:c:{G_ENV}"]
    w.bot.handle_update(press(f"g:xy:{G_ENV}", tg_id=EXEC_TG))
    assert w.store.count() == 0 and G_ENV not in w.registry.allowed_ids()
    names = [name for name, kw in w.tg.calls if kw.get("chat_id") == G_ENV]
    assert names[-2:] == ["send_message", "leave_chat"] and to(w, G_ENV)[-1]["text"] == FAREWELL
    assert w.audits[-1][1] == "tg_group.remove" and w.audits[-1][3]["messages"] == 1
    assert G_ENV in w.env and G_ENV not in w.registry.allowed_ids()        # .env qaytarib yoqmaydi


def test_kerak_emas_guruhdan_chiqadi(w):
    join(w)
    w.bot.handle_update(press(f"g:no:{G_NEW}", tg_id=EXEC_TG))
    assert w.tg.sent("leave_chat") == [{"chat_id": G_NEW}] and w.audits[-1][1] == "tg_group.decline"
    assert all(m["text"] != FAREWELL for m in to(w, G_NEW))


def test_soxta_va_eskirgan_tugmalar(w):
    for data in ("g:on:-1009:s", "g:zz", "g:c:123", "g:on:-5:q", "g:l:x"):
        w.bot.handle_update(press(data, tg_id=EXEC_TG))
        assert toasts(w.tg)[-1] == ("Tugma eskirgan", True), data


def test_karta_supergroupga_otganini_aniqlaydi(w):
    w.registry.seen({"id": -500, "type": "group", "title": "Oddiy"})
    w.tg.errors["member:-500"] = TelegramError("400", code=400, description="Bad Request: group chat was upgraded",
                                               migrate_to=-100500)
    w.bot.handle_update(press("g:c:-500", tg_id=EXEC_TG))
    _, markup = last_screen(w)
    assert any(b.get("callback_data") == "g:on:-100500:s" for b in all_buttons(markup))
    assert w.registry.get(-500).chat_id == -100500


def test_karta_nomini_telegramdan_oladi(w):
    w.tg.titles[G_ENV] = "test summary"
    w.bot.handle_update(press(f"g:c:{G_ENV}", tg_id=EXEC_TG))
    text, _ = last_screen(w)
    assert "test summary" in text and ".env ro'yxatidan" in text


def test_env_guruhiga_elon_va_turi(w):
    w.bot.handle_update(press(f"g:n:{G_ENV}", tg_id=EXEC_TG))
    assert to(w, G_ENV) and w.tg.sent("pin_message") and w.registry.get(G_ENV).notice_id
    assert G_ENV in w.registry.allowed_ids()
    w.bot.handle_update(press(f"g:k:{G_ENV}:s", tg_id=EXEC_TG))
    info = w.registry.get(G_ENV)
    assert info.kind == "support" and info.adopted and info.effective
    w.env.clear()
    assert G_ENV in w.registry.allowed_ids()


def test_migratsiya_xabarlari_ikki_tartibda(w):
    w.registry.seen({"id": -500, "type": "group", "title": "Oddiy"})
    w.registry.activate(-500, "support", actor_id=1, owner_tg=EXEC_TG)
    w.store.add(gmessage(-500, "eski gap", chat_type="group"))
    send(w, gmessage(-100500, migrate_from_chat_id=-500, title="Oddiy"))
    send(w, gmessage(-500, chat_type="group", migrate_to_chat_id=-100500, title="Oddiy"))
    assert -100500 in w.registry.allowed_ids() and -500 not in w.registry.allowed_ids()
    assert [r.text for r in w.store.window(-100500, 0, time.time() + 60)] == ["eski gap"]
    assert [a[1] for a in w.audits] == ["tg_group.migrate"]


def test_brif_royxati_registrdan(w):
    join(w)
    w.bot.handle_update(press(f"g:on:{G_NEW}:p", tg_id=EXEC_TG))
    assert w.briefs._allowed_groups() == sorted([G_ENV, G_NEW])
    w.registry.pause(G_NEW, actor_id=1)
    assert w.briefs._allowed_groups() == [G_ENV]


def test_royxat_nomsiz_guruh_nomini_oladi(w):
    w.tg.titles[G_ENV] = "test summary"
    w.bot.handle_update(text_update(BTN_GROUPS, tg_id=EXEC_TG))
    _, markup = last_screen(w)
    assert any(b.get("callback_data") == f"g:c:{G_ENV}" and "test summary" in b["text"] for b in all_buttons(markup))
    assert w.store.titles([G_ENV]) == {G_ENV: "test summary"}

