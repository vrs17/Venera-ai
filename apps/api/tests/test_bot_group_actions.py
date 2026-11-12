"""Guruhda CRM - vazifa taklifi va CRM savoli (`app/bot/group_actions.py`)."""

from __future__ import annotations

import itertools
import time

from types import SimpleNamespace

import pytest

from app.bot import group_actions as ga
from app.bot.group_actions import NO_CRM, NOT_LINKED, QUESTION_MAX, crm_intent
from app.bot.groups import TASK_COMMAND, GroupAssistant
from app.bot.runner import _GROUP_ONLY, Backend, VeneraBot
from app.core.security import hash_password
from app.services.integrations.assistant import AnswerStream, AssistantError
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
    # CRM qo'lda ulanmaydi (2026-11-12): yo'l - vebga BRB-Tech ID bilan kirish.
    assert "BRB-Tech ID" in NO_CRM and "veb" in NO_CRM
    assert "CRM hisobingizga" not in NO_CRM and "menyu" not in NO_CRM
    # Manzil sozlanmagan - tugma yo'q: shaxsiy chat tugmasi CRM ni ulamaydigan joyga olib borardi.
    assert not note.get("reply_markup")


def test_crm_ulanmagan_izohida_veb_tugmasi(w, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "sso_app_url", "https://llm.test/")
    w.backend.crm_actors = {2}
    send(w, gmsg(f"@{BOT} crmga kiritib qo'y", user=ISLOM))
    [note] = group_sent(w)
    [button] = all_buttons(note["reply_markup"])
    assert button["url"] == "https://llm.test" and "t.me" not in button["url"]


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
    assert toasts(w.tg)[-1] == ("Barno bu guruhda yoqilmagan", True) and w.backend.actions == []


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
    # v4 da agent o'zi ham guruh deb biladi (`assistant._V4_GROUP`); v1-v3 da e'tiborsiz.
    assert calls["audience"] == "group"

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



# --- maxfiylik (2026-10-10, F0): niqob, agentdagi suhbatlar, diskdagi holat ----------------------


def _forgetting(w, *errors):
    """Soxta `Backend.forget_chat`: chaqiruvlarni yozadi; `errors` - navbat bilan xato."""
    w.forgotten = []
    queue = list(errors)

    def forget_chat(chat_id, user_id):
        if queue:
            error = queue.pop(0)
            if error is not None:
                raise error
        w.forgotten.append((chat_id, user_id))

    w.backend.forget_chat = forget_chat
    return w


def _later(w, seconds):
    """Guruh CRM holatining soati `seconds` oldinda (muddatlar uchun)."""
    w.bot.group_actions.state._clock = lambda: time.time() + seconds


def _crm_rows(w, table):
    with w.store._tx() as conn:
        return conn.execute(f"SELECT * FROM {table}").fetchall()


def test_javob_qilingan_xabar_niqoblanadi(w):
    secret = "Mijoz: +998 90 123 45 67, aziz.k@brb.uz, karta 8600 1234 5678 9012, parol: Qwerty123"
    reply = {"message_id": 77, "date": int(time.time()) - 60, "text": secret,
             "from": {"id": YUSUF[0], "is_bot": False, "first_name": YUSUF[1], "username": YUSUF[2]}}
    send(w, gmsg(f"@{BOT} shuni crmga kiritib qo'y", user=ISLOM, reply=reply))
    [(question, _, _)] = w.backend.group_questions
    line = [x for x in question.splitlines() if x.startswith("Javob qilingan xabar:")][0]
    assert "<telefon>" in line and "<email>" in line and "<karta>" in line and "parol: ***" in line
    for raw in ("123 45 67", "aziz.k@brb.uz", "8600 1234", "Qwerty123"):
        assert raw not in question, raw
    assert "@brb" not in question                    # email domeni "guruh a'zosi" bo'lib chiqmaydi


def test_javob_qilingan_rasm_izohi_turi_bilan(w):
    reply = {"message_id": 78, "date": int(time.time()) - 60, "photo": [{"file_id": "x"}],
             "caption": "Sxema, savol: 90 123 45 67",
             "from": {"id": YUSUF[0], "is_bot": False, "first_name": YUSUF[1], "username": YUSUF[2]}}
    send(w, gmsg(f"@{BOT} crmga kiritib qo'y", user=ISLOM, reply=reply))
    [(question, _, _)] = w.backend.group_questions
    assert "Javob qilingan xabar: Yusufxon Mamadjanov: [rasm] Sxema, savol: <telefon>" in question


def test_agent_suhbati_guruhga_bogliq_va_prefiksli(w):
    mockup(w)
    [(_, _, conversation)] = w.backend.group_questions
    assert conversation.startswith("tgcrm-")
    [row] = _crm_rows(w, "crm_chats")
    assert row[:4] == (conversation, GROUP, 1, "venera:1") and row[6] is None and row[7] is None
    owners = _crm_rows(w, "crm_messages")
    assert {r[5] for r in owners} == {"Islom Amanullayev"} and PROPOSAL["token"] in {r[6] for r in owners}
    # Xabar matni diskka (bu jadvallarga) tushmaydi.
    assert not any("crmga" in str(cell) for r in owners for cell in r)


def test_qayta_ishga_tushgandan_keyin_tugma_va_davomi_ishlaydi(tmp_path):
    first = make_world(tmp_path)
    mockup(first)
    card = [m for m in group_sent(first) if "Taklif qilingan" in m["text"]][0]
    [(_, _, conversation)] = first.backend.group_questions
    # API qayta ishga tushdi - xotira bo'sh, ombor o'sha.
    w = make_world(tmp_path)
    press(w, f"a:c:{PROPOSAL['token']}", user=YUSUF, message_id=card["message_id"])
    assert toasts(w.tg)[-1] == ("Faqat Islom Amanullayev tasdiqlay oladi", True) and w.backend.actions == []
    press(w, f"a:c:{PROPOSAL['token']}", user=ISLOM, message_id=card["message_id"])
    assert w.backend.actions == [("confirm", PROPOSAL["token"], 1)] and w.backend.own_flags == [True]
    reply = {"message_id": card["message_id"], "text": "Taklif", "from": {"id": 999, "is_bot": True, "username": BOT}}
    send(w, gmsg("muddatini juma qil", user=ISLOM, reply=reply))
    [(question, _, again)] = w.backend.group_questions
    assert again == conversation and "davomi" in question


def test_notanish_va_muddati_otgan_tugma_eskirgan(w):
    from app.services.tg_groups import CRM_MESSAGE_TTL

    press(w, "a:c:" + "e" * 32, user=ISLOM, message_id=1)
    assert toasts(w.tg)[-1] == ("Tugma eskirgan", True)
    mockup(w)
    card = [m for m in group_sent(w) if "Taklif qilingan" in m["text"]][0]
    _later(w, CRM_MESSAGE_TTL + 60)
    w.bot.group_actions._tokens.clear()              # qayta ishga tushgandek: xotirada yo'q
    press(w, f"a:c:{PROPOSAL['token']}", user=ISLOM, message_id=card["message_id"])
    assert toasts(w.tg)[-1] == ("Tugma eskirgan", True) and w.backend.actions == []


def test_muddati_tugagan_suhbat_agentda_ochiriladi(w):
    from app.bot.group_actions import DELETE_MARGIN, IDLE

    _forgetting(w)
    mockup(w)
    [(_, _, old)] = w.backend.group_questions
    actions = w.bot.group_actions
    assert actions.sweep() == 0 and w.forgotten == []                          # hali faol
    _later(w, IDLE + DELETE_MARGIN + 60)
    assert actions.sweep() == 1 and w.forgotten == [(old, "venera:1")]
    assert actions.state.counts() == {"open": 0, "closing": 0, "deleted": 1, "stuck": 0}
    assert actions.sweep() == 0 and len(w.forgotten) == 1                      # takror o'chirilmaydi
    send(w, gmsg(f"@{BOT} yana crmga kiritib qo'y", user=ISLOM))
    assert w.backend.group_questions[-1][2] not in (old,)                      # o'chirilgani tiklanmaydi
    assert w.backend.group_questions[-1][2].startswith("tgcrm-")


def test_yangi_suhbat_ochilsa_eskisi_yopiladi_va_ochiriladi(w):
    from app.bot.group_actions import DELETE_MARGIN, IDLE

    _forgetting(w)
    mockup(w)
    [(_, _, old)] = w.backend.group_questions
    _later(w, IDLE + 60)
    send(w, gmsg(f"@{BOT} boshqa vazifani crmga kiritib qo'y", user=ISLOM))
    new = w.backend.group_questions[-1][2]
    assert new != old
    _later(w, IDLE + 60 + DELETE_MARGIN + 60)
    w.bot.group_actions.sweep()
    assert (old, "venera:1") in w.forgotten


def test_guruh_ochirilsa_agentdagi_suhbat_ochiriladi(w):
    from app.bot.group_actions import DELETE_MARGIN
    from app.services.tg_groups import GroupRegistry

    _forgetting(w)
    mockup(w)
    [(_, _, conversation)] = w.backend.group_questions
    card = [m for m in group_sent(w) if "Taklif qilingan" in m["text"]][0]
    registry = GroupRegistry(w.store, env=lambda: frozenset({GROUP}), ttl=0)
    kicked = []
    registry.removed_hooks.append(kicked.append)
    assert registry.remove(GROUP, actor_id=1) is not None
    assert kicked == [GROUP]
    assert _crm_rows(w, "crm_messages") == []                                  # tugmalar - yo'q
    assert w.bot.group_actions.state.counts()["closing"] == 1
    w.bot.group_actions._tokens.clear()
    press(w, f"a:c:{PROPOSAL['token']}", user=ISLOM, message_id=card["message_id"])
    assert toasts(w.tg)[-1] == ("Tugma eskirgan", True) and w.backend.actions == []
    w.bot.group_actions.sweep()
    assert w.forgotten == []                         # oqimdagi javob tugashini kutadi (`DELETE_MARGIN`)
    _later(w, DELETE_MARGIN + 60)
    assert w.bot.group_actions.sweep() == 1 and w.forgotten == [(conversation, "venera:1")]


def test_saqlash_muddati_otganda_suhbat_ochiriladi_va_izi_ketadi(w):
    _forgetting(w)
    mockup(w)
    [(_, _, conversation)] = w.backend.group_questions
    days = w.store.days
    w.store.purge(now=time.time() + days * 86400 + 3600)
    assert w.bot.group_actions.state.counts()["closing"] == 1
    _later(w, days * 86400 + 7200)
    assert w.bot.group_actions.sweep() == 1 and w.forgotten == [(conversation, "venera:1")]
    w.store.purge(now=time.time() + 2 * days * 86400 + 10800)
    assert _crm_rows(w, "crm_chats") == [] and _crm_rows(w, "crm_messages") == []


def test_agent_ishlamasa_keyinroq_qayta_urinadi(w):
    from app.bot.group_actions import DELETE_MARGIN, IDLE
    from app.services.integrations.assistant import AssistantError

    _forgetting(w, AssistantError("band", status=503))
    mockup(w)
    [(_, _, conversation)] = w.backend.group_questions
    _later(w, IDLE + DELETE_MARGIN + 60)
    actions = w.bot.group_actions
    assert actions.sweep() == 0 and w.forgotten == []
    [row] = _crm_rows(w, "crm_chats")
    assert row[7] is None and row[8] == 1                                      # deleted_at yo'q, attempts 1
    assert actions.sweep() == 1 and w.forgotten == [(conversation, "venera:1")]


def test_agentda_yoq_suhbat_ochirilgan_hisoblanadi(w):
    from app.bot.group_actions import DELETE_MARGIN, IDLE
    from app.services.integrations.assistant import AssistantError

    _forgetting(w, AssistantError("yo'q", status=404))
    mockup(w)
    _later(w, IDLE + DELETE_MARGIN + 60)
    assert w.bot.group_actions.sweep() == 1
    assert w.bot.group_actions.state.counts() == {"open": 0, "closing": 0, "deleted": 1, "stuck": 0}


def test_ombor_ishlamasa_xotirada_zaxira(w, monkeypatch):
    import sqlite3

    state = w.bot.group_actions.state

    def broken(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    for name in ("conversation", "remember", "owner_of", "token_owner"):
        monkeypatch.setattr(state, name, broken)
    mockup(w)
    [(_, _, conversation)] = w.backend.group_questions
    assert conversation.startswith("tgcrm-")                                   # shaxsiy tarixda baribir yo'q
    card = [m for m in group_sent(w) if "Taklif qilingan" in m["text"]][0]
    press(w, f"a:c:{PROPOSAL['token']}", user=ISLOM, message_id=card["message_id"])
    assert w.backend.actions == [("confirm", PROPOSAL["token"], 1)]


def test_backend_agentdagi_suhbatni_oz_kaliti_bilan_ochiradi(monkeypatch):
    from app.api.v1 import chat

    seen = []
    monkeypatch.setattr(chat._assistant, "delete_chat", lambda chat_id, user_id: seen.append((chat_id, user_id)))
    user = SimpleNamespace(actorId=7)
    backend = Backend()
    assert backend.agent_user_id(user) == "venera:7"
    backend.forget_chat("tgcrm-abc", backend.agent_user_id(user))
    assert seen == [("tgcrm-abc", "venera:7")]


def test_bot_guruh_ochirilishini_tozalovchiga_ulaydi(tmp_path):
    from app.bot.group_admin import GroupAdmin
    from app.services.tg_groups import GroupRegistry

    tg = GroupTelegram()
    store = GroupStore(tmp_path / "groups.db")
    registry = GroupRegistry(store, env=lambda: frozenset({GROUP}), ttl=0)
    admin = GroupAdmin(tg, registry, store, logins=lambda: frozenset(), audit=lambda *a: None, settle=0)
    groups = GroupAssistant(tg, store, FakeWriter(), allowed=registry.allowed_ids, inline=True)
    bot = VeneraBot(tg, LinkStore(tmp_path / "links.json"), users=lambda: Directory(), backend=CrmBackend(),
                    inline=True, typing_every=None, groups=groups, admin=admin, group_actions=True)
    assert registry.removed_hooks == [bot.group_actions.kick]
    registry.remove(GROUP, actor_id=1)
    assert bot.group_actions._wake.is_set()


def test_guruh_supergroupga_aylansa_eski_suhbat_yopiladi(w):
    from app.services.tg_groups import GroupRegistry

    mockup(w)
    registry = GroupRegistry(w.store, env=lambda: frozenset({GROUP}), ttl=0)
    assert registry.migrate(GROUP, GROUP - 1)
    assert _crm_rows(w, "crm_messages") == []
    assert w.bot.group_actions.state.counts()["closing"] == 1


def test_fon_tozalovchisi_ishlaydi_va_toxtaydi(w):
    from app.bot.group_actions import DELETE_MARGIN, IDLE

    _forgetting(w)
    mockup(w)
    [(_, _, conversation)] = w.backend.group_questions
    _later(w, IDLE + DELETE_MARGIN + 60)
    actions = w.bot.group_actions
    actions.start()
    try:
        deadline = time.monotonic() + 5
        while not w.forgotten and time.monotonic() < deadline:
            time.sleep(0.02)
        assert w.forgotten == [(conversation, "venera:1")]
    finally:
        actions.stop()
        actions._thread.join(timeout=5)
    assert not actions._thread.is_alive()


# --- sharhdan keyin (2026-10-10): tozalovchi navbati, so'rovchi matni -------------------------------


def _two_closed(w):
    """Ikki yopilgan, eski suhbat (birinchisi eskiroq) - tozalovchi uchun."""
    state = w.bot.group_actions.state
    now = time.time()
    first = state.conversation(-1001, 1, "venera:1", idle=ga.IDLE)
    second = state.conversation(-1002, 2, "venera:2", idle=ga.IDLE)
    with state.store._tx() as conn:
        for conv, age in ((first, 99999), (second, 99000)):
            conn.execute("UPDATE crm_chats SET last_at = ?, closed_at = ? WHERE conversation = ?",
                         (int(now - age), int(now - age), conv))
    return first, second


def _forget_by(w, errors):
    w.forgotten = []

    def forget_chat(chat_id, user_id):
        error = errors.get(chat_id)
        if error is not None:
            raise error
        w.forgotten.append((chat_id, user_id))

    w.backend.forget_chat = forget_chat


@pytest.mark.parametrize("error", [
    AssistantError("rad", status=422), AssistantError("noto'g'ri", status=400), AssistantError("ziddiyat", status=409),
    ValueError("kutilmagan"),
])
def test_bitta_yiqiladigan_suhbat_qolganlarini_tosmaydi(w, error):
    first, second = _two_closed(w)
    _forget_by(w, {first: error})
    actions = w.bot.group_actions
    assert actions.sweep() == 1 and w.forgotten == [(second, "venera:2")]
    rows = {r[0]: r for r in _crm_rows(w, "crm_chats")}
    assert rows[first][7] is None and rows[first][8] == 1 and rows[first][9] is not None   # 400 ham "yo'q" emas
    assert actions.sweep() == 0                                       # tanaffus: darhol qayta urinmaydi
    _later(w, ga.SWEEP_EVERY + 5)
    _forget_by(w, {})
    assert actions.sweep() == 1 and w.forgotten == [(first, "venera:1")]


def test_agentning_ozi_ishlamasa_aylanish_toxtaydi(w):
    import urllib.error

    first, second = _two_closed(w)
    down = AssistantError("Assistant 500: -", status=502, reason="upstream_http")
    down.__cause__ = urllib.error.HTTPError("http://x", 500, "err", {}, None)
    _forget_by(w, {first: down, second: down})
    seen = []
    w.backend.forget_chat = lambda chat_id, user_id: (seen.append(chat_id), (_ for _ in ()).throw(down))
    assert w.bot.group_actions.sweep() == 0 and seen == [first]          # ikkinchisiga borilmaydi
    rows = {r[0]: r for r in _crm_rows(w, "crm_chats")}
    assert rows[first][8] == 1 and rows[first][9] is None                # tanaffussiz: aybi suhbatda emas
    seen.clear()
    w.bot.group_actions.sweep()
    assert seen == [second]                                              # keyingisi navbat boshida


def test_tiqilgan_suhbat_hisoblanadi(w):
    from app.services.tg_groups import CRM_DELETE_STUCK

    first, _ = _two_closed(w)
    state = w.bot.group_actions.state
    for _ in range(CRM_DELETE_STUCK):
        state.failed(first, retry_in=1)
    assert state.counts()["stuck"] == 1


def test_prefiksisiz_yozuv_agentga_yuborilmaydi(w):
    state = w.bot.group_actions.state
    now = int(time.time())
    with state.store._tx() as conn:
        conn.execute("INSERT INTO crm_chats (conversation, chat_id, actor_id, user_id, created_at, last_at, closed_at)"
                     " VALUES ('shaxsiy-uuid', -1001, 1, 'venera:1', ?, ?, ?)", (now - 99999, now - 99999, now - 99999))
    _forget_by(w, {})
    assert w.bot.group_actions.sweep() == 0 and w.forgotten == []
    [row] = _crm_rows(w, "crm_chats")
    assert row[7] is None and row[9] is not None and row[9] > now + 3600


def test_sorovchi_matnida_sirlar_niqoblanadi(w):
    send(w, gmsg(f"@{BOT} crmga vazifa: mijoz +998 90 123 45 67, ali@client.uz parol: Qwerty123", user=ISLOM))
    [(question, _, _)] = w.backend.group_questions
    line = [x for x in question.splitlines() if x.startswith("So'rov:")][0]
    assert "Qwerty123" not in question and "parol: ***" in line
    assert "+998 90 123 45 67" in line and "ali@client.uz" in line     # CRM vazifasi uchun qoladi
    assert "@client - guruh a'zosi" not in question                    # email domeni a'zo emas


def test_bot_holatida_guruh_crm_sonlari(w):
    """`/api/health/detail` (`telegram.groupCrm`): tiqilgan suhbatlar ko'rinsin - faqat sonlar."""
    mockup(w)
    assert w.bot.status()["groupCrm"] == {"open": 1, "closing": 0, "deleted": 0, "stuck": 0}
