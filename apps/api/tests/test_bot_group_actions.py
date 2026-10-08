"""Guruhda CRM - vazifa taklifi va CRM savoli (`app/bot/group_actions.py`)."""

from __future__ import annotations

import itertools
import time

from types import SimpleNamespace

import pytest

from app.bot.group_actions import NO_CRM, NOT_LINKED, QUESTION_MAX, crm_intent
from app.bot.groups import TASK_COMMAND, GroupAssistant
from app.bot.runner import _GROUP_ONLY, Backend, VeneraBot
from app.core.security import hash_password
from app.services.integrations.assistant import AnswerStream
from app.services.telegram_links import LinkStore
from app.services.tg_groups import GroupStore
from app.services.users import StoredUser
from tests.test_bot_groups import BOT, GROUP, FakeWriter, GroupTelegram
from tests.test_bot_ux import Directory, all_buttons, toasts
from tests.test_telegram_bot import PROPOSAL, FakeBackend, _frames

ISLOM = (601, "Islom", "islom_kaizen")
YUSUF = (602, "Yusufxon Mamadjanov", "yusufxon_m")
GUEST = (603, "Mehmon", "mehmon")
_ids = itertools.count(5000)


class CrmBackend(FakeBackend):
    """`FakeBackend` + guruh yo'li: faqat CRM, o'z tokeni."""

    def __init__(self) -> None:
        super().__init__()
        self.group_questions: list[tuple[str, int, str]] = []
        self.crm_actors = {1, 2}
        self.frames = _frames({"type": "token", "text": "DVSIB loyihasida vazifa yaratish taklif qilindi."},
                              {"type": "proposal", "proposal": PROPOSAL}, {"type": "done", "route": "crm"})
        self.own_flags: list[bool] = []

    def stream_group(self, question, user, chat_id):
        self.group_questions.append((question, user.actorId, chat_id))
        backend = self

        def gen():
            yield from backend.frames

        return AnswerStream(request_id="req-g", frames=gen())

    def own_crm(self, user):
        return user.actorId in self.crm_actors

    def action(self, verb, token, user, *, own_tokens=False):
        self.own_flags.append(own_tokens)
        return super().action(verb, token, user)


def make_world(tmp_path, *, actions=True):
    tg = GroupTelegram()
    store = GroupStore(tmp_path / "telegram" / "groups.db")
    writer = FakeWriter()
    allowed = {GROUP}
    groups = GroupAssistant(tg, store, writer, allowed=lambda: frozenset(allowed), inline=True,
                            limits=lambda: ((50, 60.0), (500, 3600.0)))
    backend = CrmBackend()
    directory = Directory(
        StoredUser(actor_id=1, email="islom@brb.uz", full_name="Islom Amanullayev", password_hash=hash_password("x")),
        StoredUser(actor_id=2, email="yusuf@brb.uz", full_name="Yusufxon Mamajonov", password_hash=hash_password("x")))
    links = LinkStore(tmp_path / "links.json")
    links.link(ISLOM[0], 1)
    links.link(YUSUF[0], 2)
    bot = VeneraBot(tg, links, users=lambda: directory, backend=backend, inline=True, typing_every=None,
                    groups=groups, group_actions=actions)
    bot.username = BOT
    return SimpleNamespace(tg=tg, store=store, writer=writer, backend=backend, bot=bot, allowed=allowed,
                           groups=groups)


@pytest.fixture
def w(tmp_path):
    return make_world(tmp_path)


def gmsg(text, *, user, reply=None, ago=30):
    message = {"message_id": next(_ids), "date": int(time.time()) - ago,
               "chat": {"id": GROUP, "type": "supergroup", "title": "AI team"},
               "from": {"id": user[0], "is_bot": False, "first_name": user[1], "username": user[2]}, "text": text}
    if reply is not None:
        message["reply_to_message"] = reply
    return message


def send(w, message):
    w.bot.handle_update({"update_id": next(_ids), "message": message})
    return message


def press(w, data, *, user, message_id):
    w.bot.handle_update({"update_id": next(_ids), "callback_query": {
        "id": f"cb{next(_ids)}", "from": {"id": user[0]}, "data": data,
        "message": {"message_id": message_id, "chat": {"id": GROUP, "type": "supergroup"}}}})


def group_sent(w):
    return [kw for kw in w.tg.sent() if kw["chat_id"] == GROUP]


def mockup(w):
    """Maketdagi yozishma: rahbar vazifa aytadi, ijrochi Venera'ga "crmga kiritib qo'y"."""
    send(w, gmsg("Deepseek 4.1 modelini testlash kere, qanchalik ozbek tilini tushunadi, qanaqa server kerak",
                 user=YUSUF, ago=300))
    second = send(w, gmsg("Shuni ertaga ertalab korib chiqish kere @islom_kaizen", user=YUSUF, ago=200))
    return send(w, gmsg(f"Aha hop, @{BOT} crmga kiritib qoy", user=ISLOM, reply=second))


# --- niyat -------------------------------------------------------------------------------------


@pytest.mark.parametrize("text, expected", [
    ("crmga kiritib qo'y", True), ("crmga kiritib qoʻy", True), ("CRM ga qo'shib qo'y", True),
    ("task yarat", True), ("vazifani kiritib qo'y", True), ("Создай задачу", True),
    ("DVSIB-120 holati crm da qanday?", True),
    ("task nima bo'ldi?", False), ("bu hafta nima qildi", False), ("vazifa haqida gapirdik", False),
])
def test_crm_niyati(text, expected):
    assert crm_intent(text) is expected


# --- so'rov ----------------------------------------------------------------------------------


def test_maket_kontekst_bilan_taklif(w):
    request = mockup(w)
    [(question, actor, conversation)] = w.backend.group_questions
    assert actor == 1 and conversation
    assert "So'rov: Aha hop, crmga kiritib qoy" in question
    assert "Javob qilingan xabar: Yusufxon Mamadjanov: Shuni ertaga ertalab korib chiqish kere @islom_kaizen" in question
    assert "Deepseek 4.1 modelini testlash kere" in question
    names = question.split("Ismlar: ")[1]
    assert "@islom_kaizen = Islom Amanullayev" in names and "@yusufxon_m = Yusufxon Mamajonov" in names
    assert "HAMMAGA ko'rinadi" in question and len(question) <= QUESTION_MAX
    assert "Hozir: " in question and "(Toshkent)" in question
    sent = group_sent(w)
    answer = [m for m in sent if "taklif qilindi" in m["text"]][0]
    card = [m for m in sent if "Taklif qilingan o'zgarish" in m["text"]][0]
    assert answer["reply_to"] == request["message_id"] and card["reply_to"] == request["message_id"]
    assert [b["callback_data"] for b in all_buttons(card["reply_markup"])] == [
        f"a:x:{PROPOSAL['token']}", f"a:c:{PROPOSAL['token']}"]
    assert ("delete_message", {"chat_id": GROUP, "message_id": sent[0]["message_id"]}) in w.tg.calls   # ⏳
    assert w.writer.calls == []                                               # /askvenera emas


def test_ulanmagan_odamga_izoh(w):
    send(w, gmsg(f"@{BOT} crmga kiritib qo'y", user=GUEST))
    [note] = group_sent(w)
    assert note["text"] == NOT_LINKED and note["reply_markup"] and w.backend.group_questions == []


def test_crm_ulanmagan_odamga_izoh(w):
    w.backend.crm_actors = {2}
    send(w, gmsg(f"@{BOT} crmga kiritib qo'y", user=ISLOM))
    [note] = group_sent(w)
    assert note["text"] == NO_CRM and w.backend.group_questions == []


def test_oddiy_savol_avvalgidek(w):
    send(w, gmsg("Bugun deploy bo'ldi", user=YUSUF))
    send(w, gmsg(f"@{BOT} bu hafta nima qildik?", user=ISLOM))
    assert w.backend.group_questions == [] and len(w.writer.calls) == 1


def test_task_buyrugi(w):
    send(w, gmsg("/task Deepseek testini kiritib qo'y", user=ISLOM))
    [(question, actor, _)] = w.backend.group_questions
    assert actor == 1 and "So'rov: Deepseek testini kiritib qo'y" in question


def test_davomi_shu_suhbatda(w):
    mockup(w)
    card = [m for m in group_sent(w) if "Taklif qilingan" in m["text"]][0]
    reply = {"message_id": card["message_id"], "text": "Taklif qilingan o'zgarish",
             "from": {"id": 999, "is_bot": True, "username": BOT}}
    send(w, gmsg("nomini Deepseek 4.1 LLM testlash qil", user=ISLOM, reply=reply))
    first, second = w.backend.group_questions
    assert second[2] == first[2] and "davomi" in second[0]
    assert "So'rov: nomini Deepseek 4.1 LLM testlash qil" in second[0]


def test_boshqa_odam_davom_ettira_olmaydi(w):
    mockup(w)
    card = [m for m in group_sent(w) if "Taklif qilingan" in m["text"]][0]
    reply = {"message_id": card["message_id"], "text": "Taklif", "from": {"id": 999, "is_bot": True, "username": BOT}}
    send(w, gmsg("yaxshi", user=YUSUF, reply=reply))
    assert len(w.backend.group_questions) == 1
    assert "Islom Amanullayev davom ettira oladi" in group_sent(w)[-1]["text"]


# --- tasdiqlash ---------------------------------------------------------------------------------


def test_faqat_soragan_tasdiqlaydi(w):
    mockup(w)
    card = [m for m in group_sent(w) if "Taklif qilingan" in m["text"]][0]
    press(w, f"a:c:{PROPOSAL['token']}", user=YUSUF, message_id=card["message_id"])
    assert toasts(w.tg)[-1] == ("Faqat Islom Amanullayev tasdiqlay oladi", True) and w.backend.actions == []
    press(w, f"a:c:{PROPOSAL['token']}", user=GUEST, message_id=card["message_id"])
    assert w.backend.actions == []
    press(w, f"a:c:{PROPOSAL['token']}", user=ISLOM, message_id=card["message_id"])
    assert w.backend.actions == [("confirm", PROPOSAL["token"], 1)] and w.backend.own_flags == [True]
    result = group_sent(w)[-1]
    assert result["reply_to"] == card["message_id"] and "DVSIB-123" in result["text"]
    assert ("edit_reply_markup", {"chat_id": GROUP, "message_id": card["message_id"],
                                  "reply_markup": None}) in w.tg.calls


def test_eskirgan_va_ochirilgan_guruh_tugmasi(w):
    press(w, "a:c:" + "b" * 32, user=ISLOM, message_id=1)
    assert toasts(w.tg)[-1] == ("Tugma eskirgan", True)
    mockup(w)
    w.allowed.clear()
    press(w, f"a:c:{PROPOSAL['token']}", user=ISLOM, message_id=1)
    assert toasts(w.tg)[-1] == ("Venera bu guruhda yoqilmagan", True) and w.backend.actions == []


def test_crm_yoqilmagan_bot_avvalgidek(tmp_path):
    w = make_world(tmp_path, actions=False)
    send(w, gmsg("Server sozlash kerak", user=YUSUF))
    send(w, gmsg(f"@{BOT} crmga kiritib qo'y", user=ISLOM))
    assert w.backend.group_questions == [] and len(w.writer.calls) == 1
    press(w, f"a:c:{PROPOSAL['token']}", user=ISLOM, message_id=1)
    assert toasts(w.tg)[-1][0] == _GROUP_ONLY


def test_menyu_va_yordam_crm_bilan(w):
    send(w, gmsg("/help", user=ISLOM))
    assert "/task" in group_sent(w)[-1]["text"] and "faqat so'ragan odam tasdiqlaydi" in group_sent(w)[-1]["text"]
    commands = [c for n, kw in w.tg.calls if n == "set_my_commands" for c in kw["commands"]]
    assert TASK_COMMAND in commands


# --- yordamchiga: faqat CRM, faqat o'z tokeni ------------------------------------------------------


def test_backend_guruhda_faqat_oz_crm_tokeni(monkeypatch):
    from app.api.v1 import chat

    calls = {}

    def fake_open(question, user, chat_id, **kwargs):
        calls.update(kwargs)
        return "stream"

    monkeypatch.setattr(chat, "open_stream", fake_open)
    user = SimpleNamespace(actorId=7)
    assert Backend().stream_group("savol", user, "c1") == "stream"
    assert calls["platforms"] == ("crm",) and calls["own_tokens"] is True and calls["channel"] == "bot"

    seen = {}
    monkeypatch.setattr(chat._connectors.hub, "tokens", lambda uid: {"crm": "own-crm", "hrm": "own-hrm"})
    monkeypatch.setattr(chat._assistant, "confirm_action",
                        lambda token, user_id, tokens: seen.update(tokens=tokens, user_id=user_id) or {"ok": True})
    Backend().action("confirm", "t" * 32, user, own_tokens=True)
    assert seen["tokens"] == {"crm": "own-crm"} and seen["user_id"] == "venera:7"


def test_open_stream_platforma_va_oz_tokeni(monkeypatch):
    from app.api.v1 import chat

    sent = {}

    class Assistant:
        def stream(self, question, **kwargs):
            sent.update(kwargs)
            return SimpleNamespace(request_id="r")

    monkeypatch.setattr(chat, "_assistant", Assistant())
    monkeypatch.setattr(chat, "_live_tokens", lambda user: {"crm": "agent", "hrm": "shared"})
    monkeypatch.setattr(chat._connectors.hub, "tokens", lambda uid: {"crm": "own", "hrm": "own-hrm"})
    user = SimpleNamespace(actorId=7, roles=[], email="", fullName="")
    chat.open_stream("savol", user, "c1", channel="bot", platforms=("crm",), own_tokens=True)
    assert sent["tokens"] == {"crm": "own"}
    chat.open_stream("savol", user, "c1", channel="bot")
    assert sent["tokens"] == {"crm": "agent", "hrm": "shared"}                 # odatiy yo'l o'zgarmagan


def test_savol_chegarasi_uzun_yozishmada(w):
    for n in range(30):
        send(w, gmsg(f"{n:02d} " + "uzun xabar matni " * 20, user=YUSUF, ago=600 - n))
    send(w, gmsg(f"@{BOT} crmga kiritib qo'y", user=ISLOM))
    [(question, _, _)] = w.backend.group_questions
    assert len(question) <= QUESTION_MAX and "29 uzun" in question            # eng yangilari qoladi
    assert "Ismlar:" in question


def test_aniq_summary_va_askvenera_crm_sozi_bilan_ham_oz_manosida(w):
    send(w, gmsg("CRM loyihasi bo'yicha kelishildi: dashboard ertaga", user=YUSUF))
    send(w, gmsg("/askvenera CRM bo'yicha nima kelishildi?", user=ISLOM))
    send(w, gmsg("/summary crm", user=ISLOM))
    assert w.backend.group_questions == [] and len(w.writer.calls) == 2

