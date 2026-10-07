"""Telegram bot: hisobni ulash, savol-javob, ovoz, tasdiqlash, fayllar.

Telegram ham, yuqoridagi xizmat ham SOXTA - tarmoqqa chiqilmaydi.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.parse

from types import SimpleNamespace

import pytest

from app.bot import render
from app.bot.runner import COMMANDS, VeneraBot
from app.core.config import settings
from app.core.security import hash_password
from app.services.integrations.assistant import AnswerStream, AssistantError
from app.services.integrations.telegram import InitDataError, TelegramError, verify_init_data
from app.services.stt import SttError, Transcript
from app.services.telegram_links import LinkStore
from app.services.users import StoredUser, UserStore

BOT_TOKEN = "123456:TEST-token-for-tests-only_abcdefghij"
TG_ID = 5550001


def sign_init(user: dict, *, token: str = BOT_TOKEN, auth_date: int | None = None, **extra) -> str:
    """Telegram qanday imzolasa, shunday."""
    fields = {"auth_date": str(auth_date or int(time.time())), "query_id": "AAE1",
              "user": json.dumps(user, separators=(",", ":")), **extra}
    check = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(fields)


# --- initData ----------------------------------------------------------------


def test_initdata_togri_imzo():
    user = verify_init_data(sign_init({"id": TG_ID, "first_name": "Ali"}), BOT_TOKEN, max_age=60)
    assert user["id"] == TG_ID


@pytest.mark.parametrize("mutate", [
    lambda s: s.replace("Ali", "Vali"),                       # mazmun o'zgargan
    lambda s: sign_init({"id": TG_ID}, token="999:boshqa"),   # boshqa bot imzosi
    lambda s: s.split("&hash=")[0],                           # imzo yo'q
    lambda s: s + "&user=%7B%22id%22%3A1%7D",                 # takroriy maydon
    lambda s: "",
])
def test_initdata_soxtasi_rad_etiladi(mutate):
    with pytest.raises(InitDataError) as info:
        verify_init_data(mutate(sign_init({"id": TG_ID, "first_name": "Ali"})), BOT_TOKEN, max_age=60)
    assert not info.value.stale


def test_initdata_eskirgani_alohida_aytiladi():
    old = sign_init({"id": TG_ID}, auth_date=int(time.time()) - 7200)
    with pytest.raises(InitDataError) as info:
        verify_init_data(old, BOT_TOKEN, max_age=3600)
    assert info.value.stale


def test_initdata_bot_foydalanuvchi_emas():
    with pytest.raises(InitDataError):
        verify_init_data(sign_init({"id": 7, "is_bot": True}), BOT_TOKEN, max_age=60)


# --- ulash endpointi ---------------------------------------------------------


class FakeTelegram:
    """Bot API o'rnida: chaqiruvlarni yozib boradi."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.next_id = 100
        self.files: dict[str, bytes] = {}
        self.fail_html_once = False
        self.commands: list = []
        self.token = "fake"

    @property
    def configured(self) -> bool:
        return True

    def _rec(self, name, **kw):
        self.calls.append((name, kw))

    def sent(self, name="send_message"):
        return [kw for n, kw in self.calls if n == name]

    def texts(self):
        return [kw["text"] for kw in self.sent()]

    def send_message(self, chat_id, text, *, html=True, reply_markup=None, reply_to=None):
        if html and self.fail_html_once:
            self.fail_html_once = False
            raise TelegramError("sendMessage: 400", code=400,
                                description="Bad Request: can't parse entities")
        self.next_id += 1
        self._rec("send_message", chat_id=chat_id, text=text, html=html,
                  reply_markup=reply_markup, reply_to=reply_to, message_id=self.next_id)
        return {"message_id": self.next_id}

    def edit_message_text(self, chat_id, message_id, text, *, html=True, reply_markup=None):
        self._rec("edit_message_text", chat_id=chat_id, message_id=message_id, text=text)

    def edit_reply_markup(self, chat_id, message_id, reply_markup=None):
        self._rec("edit_reply_markup", chat_id=chat_id, message_id=message_id, reply_markup=reply_markup)

    def delete_message(self, chat_id, message_id):
        self._rec("delete_message", chat_id=chat_id, message_id=message_id)

    def send_chat_action(self, chat_id, action="typing"):
        self._rec("send_chat_action", chat_id=chat_id)

    def answer_callback(self, callback_id, text="", *, alert=False):
        self._rec("answer_callback", id=callback_id, text=text, alert=alert)

    def get_file(self, file_id):
        return {"file_path": f"voice/{file_id}.oga"}

    def download(self, file_path, *, limit):
        return self.files[file_path]

    def send_document(self, chat_id, filename, content, content_type, *, caption=None, reply_markup=None):
        self._rec("send_document", chat_id=chat_id, filename=filename, size=len(content),
                  content_type=content_type, caption=caption, reply_markup=reply_markup)

    def get_me(self):
        return {"username": "venera_test_bot"}

    def get_my_commands(self):
        return self.commands

    def set_my_commands(self, commands):
        self.commands = commands
        self._rec("set_my_commands", commands=commands)


@pytest.fixture
def telegram_on(monkeypatch):
    import app.bot as bot_module

    fake = FakeTelegram()
    monkeypatch.setattr(settings, "telegram_bot_token", BOT_TOKEN)
    monkeypatch.setattr(bot_module, "api", fake)
    # Ulanish xabari fonda yuboriladi - testda darhol.
    monkeypatch.setattr(bot_module, "welcome",
                        lambda tg_id, user: fake.send_message(tg_id, "welcome:" + user.email))
    return fake


def test_ulash_sessiya_va_imzo_bilan(client, auth, telegram_on):
    import app.bot as bot_module

    r = client.post("/api/v1/telegram/link", headers=auth,
                    json={"initData": sign_init({"id": TG_ID, "first_name": "Ali"})})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "new" and r.json()["days"] == settings.telegram_link_days
    link, state = bot_module.links.lookup(TG_ID)
    assert state == "linked" and link.actor_id == 1
    assert telegram_on.texts() == ["welcome:admin@venera.uz"]
    # Takror ochish - faqat muddat yangilanadi, xabar qayta kelmaydi.
    r = client.post("/api/v1/telegram/link", headers=auth,
                    json={"initData": sign_init({"id": TG_ID})})
    assert r.json()["status"] == "refreshed" and len(telegram_on.texts()) == 1


def test_ulash_sessiyasiz_yoki_soxta_imzo_bilan_yoq(client, auth, telegram_on):
    import app.bot as bot_module

    init = sign_init({"id": TG_ID})
    assert client.post("/api/v1/telegram/link", json={"initData": init}).status_code == 401
    bad = sign_init({"id": TG_ID}, token="999:boshqa-bot")
    r = client.post("/api/v1/telegram/link", headers=auth, json={"initData": bad})
    assert r.status_code == 400 and r.json()["message"] == "Telegram ma'lumoti tasdiqlanmadi"
    old = sign_init({"id": TG_ID}, auth_date=int(time.time()) - 3 * 86400)
    r = client.post("/api/v1/telegram/link", headers=auth, json={"initData": old})
    assert r.status_code == 400 and "eskirgan" in r.json()["message"]
    assert bot_module.links.lookup(TG_ID) == (None, "none")


def test_ulash_bot_sozlanmagan_bolsa_501(client, auth, monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    r = client.post("/api/v1/telegram/link", headers=auth, json={"initData": "a=b"})
    assert r.status_code == 501


def test_uzish_faqat_oz_ulanishini(client, auth, telegram_on):
    import app.bot as bot_module

    bot_module.links.link(TG_ID, 2)          # boshqa odamga ulangan
    init = sign_init({"id": TG_ID})
    r = client.post("/api/v1/telegram/unlink", headers=auth, json={"initData": init})
    assert r.json() == {"unlinked": False}
    assert bot_module.links.lookup(TG_ID)[0].actor_id == 2
    bot_module.links.link(TG_ID, 1)
    r = client.post("/api/v1/telegram/unlink", headers=auth, json={"initData": init})
    assert r.json() == {"unlinked": True}


# --- ulanishlar ombori ---------------------------------------------------------


def test_ombor_muddat_va_suhbat(tmp_path):
    store = LinkStore(tmp_path / "links.json", ttl_days=30)
    assert store.link(1, 10, now=1000.0) == "new"
    chat = store.chat_for(1, idle_sec=3600, now=1100.0)
    assert store.chat_for(1, idle_sec=3600, now=2000.0) == chat          # davom
    assert store.chat_for(1, idle_sec=3600, now=9000.0) != chat          # jimlikdan keyin yangi
    assert store.link(1, 11, now=9100.0) == "switched"                   # boshqa hisob
    assert store.lookup(1, now=9100.0)[0].chat_id is None                # suhbat o'tmaydi
    assert store.lookup(1, now=9100.0 + 31 * 86400)[1] == "expired"
    assert store.link(1, 11, now=9100.0 + 31 * 86400) == "new"
    # Fayl - 600, va boshqa nusxa uni o'qiydi.
    assert oct((tmp_path / "links.json").stat().st_mode & 0o777) == "0o600"
    assert LinkStore(tmp_path / "links.json").lookup(1, now=9100.0 + 31 * 86400)[0].actor_id == 11


# --- bot ---------------------------------------------------------------------


def _frames(*frames):
    return [json.dumps(f, ensure_ascii=False).encode() + b"\n" for f in frames]


class FakeBackend:
    def __init__(self) -> None:
        self.frames: list[bytes] = _frames({"type": "token", "text": "Javob **muhim**."},
                                           {"type": "done", "route": "rules"})
        self.questions: list[tuple[str, int, str]] = []
        self.actions: list[tuple[str, str, int]] = []
        self.action_result: dict | Exception = {"token": "t", "status": "executed", "ok": True,
                                                "result": {"key": "DVSIB-123"}}
        self.open_error: Exception | None = None
        self.closed = False
        self.transcript: Transcript | Exception = Transcript(text="bugun kech qoldimmi", backend="gapi")
        self.audio: list[tuple[bytes, str]] = []
        self.files: list[tuple[str, str]] = []
        self.links: list[tuple[str, int, str]] = []
        self.link_error: Exception | None = None
        self.histories: list[tuple[str, int]] = []

    def stream(self, question, user, chat_id):
        if self.open_error:
            raise self.open_error
        self.questions.append((question, user.actorId, chat_id))
        backend = self

        def gen():
            try:
                yield from backend.frames
            finally:
                backend.closed = True

        return AnswerStream(request_id="req-1", frames=gen())

    def action(self, verb, token, user):
        self.actions.append((verb, token, user.actorId))
        if isinstance(self.action_result, Exception):
            raise self.action_result
        return self.action_result

    def artifact(self, token, kind):
        self.files.append((kind, token))
        ctype = "application/pdf" if kind == "pdf" else "application/octet-stream"
        return ctype, f"{token}.{kind}", iter([b"PK" * 10])

    def doc_link(self, doc_id, user, filename):
        """`chat.doc_link` o'rnida - imzo o'rniga belgi (haqiqiysi `test_bot_ux.py` da)."""
        self.links.append((doc_id, user.actorId, filename))
        if isinstance(self.link_error, Exception):
            raise self.link_error
        return SimpleNamespace(url=f"/api/v1/chat/file/SIGNED-{doc_id}", filename=f"{filename}.pdf",
                               expiresIn=600)

    def history(self, chat_id, user):
        self.histories.append((chat_id, user.actorId))
        return {"chat_id": chat_id, "messages": []}

    def transcribe(self, audio, content_type):
        self.audio.append((audio, content_type))
        if isinstance(self.transcript, Exception):
            raise self.transcript
        return self.transcript


@pytest.fixture
def world(tmp_path):
    users = UserStore({
        "a@b.uz": StoredUser(actor_id=1, email="a@b.uz", full_name="Ali Valiyev",
                             password_hash=hash_password("x")),
    })
    tg = FakeTelegram()
    links = LinkStore(tmp_path / "links.json")
    backend = FakeBackend()
    bot = VeneraBot(tg, links, users=lambda: users, backend=backend,
                    webapp_url="https://llm.brb-tech.uz/tg/", inline=True, typing_every=None)
    return bot, tg, links, backend, users


def text_update(text, *, tg_id=TG_ID, chat_type="private", message_id=10):
    return {"update_id": 1, "message": {"message_id": message_id, "text": text,
                                        "from": {"id": tg_id, "is_bot": False},
                                        "chat": {"id": tg_id, "type": chat_type}}}


def test_ulanmagan_odamga_korsatma_va_ilova_tugmasi(world):
    bot, tg, links, backend, _ = world
    bot.handle_update(text_update("salom"))
    bot.handle_update(text_update("yana"))          # takror - jim (1 daqiqa)
    assert len(tg.sent()) == 1
    first = tg.sent()[0]
    assert "bir marta" in first["text"]
    button = first["reply_markup"]["inline_keyboard"][0][0]
    assert button == {"text": "Venera'ni ochish", "web_app": {"url": "https://llm.brb-tech.uz/tg/"}}
    assert backend.questions == []


def test_guruhda_jim(world):
    bot, tg, links, backend, _ = world
    links.link(TG_ID, 1)
    bot.handle_update(text_update("salom", chat_type="group"))
    assert tg.calls == [] and backend.questions == []


def test_savol_javob_matn_bilan(world):
    bot, tg, links, backend, _ = world
    links.link(TG_ID, 1)
    backend.frames = _frames(
        {"type": "stage", "text": "Hujjatlar qidirilmoqda"},
        {"type": "sources", "items": [
            {"kind": "doc", "doc_id": "HR_045", "title": "Ichki mehnat tartibi", "page": 22},
            {"kind": "hrm", "tool": "hrm_today_late", "digest": "count=9"}]},
        {"type": "token", "text": "## Ta'til\n* **21 kun** asosiy ta'til [1] [T1].\n\n"},
        {"type": "token", "text": "Tekshirilgan HRM ma'lumotlari:\n[T1] hrm_today_late - status=200\n"},
        {"type": "done", "route": "rules"})
    bot.handle_update(text_update("ta'til necha kun?"))
    question, actor, chat = backend.questions[0]
    assert (question, actor) == ("ta'til necha kun?", 1) and chat
    assert backend.closed, "oqim yopilishi kerak (slot bo'shaydi)"
    placeholder = tg.sent()[0]
    assert placeholder["text"].startswith("⏳")
    assert ("edit_message_text", {"chat_id": TG_ID, "message_id": placeholder["message_id"],
                                  "text": "⏳ Hujjatlar qidirilmoqda"}) in tg.calls
    assert ("delete_message", {"chat_id": TG_ID, "message_id": placeholder["message_id"]}) in tg.calls
    answer = tg.sent()[1]
    assert answer["text"] == ("<b>Ta'til</b>\n• <b>21 kun</b> asosiy ta'til [1].\n\n"
                              "📚 <b>Manbalar</b>\n[1] Ichki mehnat tartibi, 22-bet")
    doc_row, report_row = answer["reply_markup"]["inline_keyboard"]
    assert doc_row == [{"text": "📄 Hujjatni ochish", "callback_data": "d:HR_045"}]
    assert report_row[0]["text"] == "⚑" and report_row[0]["callback_data"].startswith("r:")
    # Keyingi savol - o'sha suhbatda.
    bot.handle_update(text_update("rahmat"))
    assert backend.questions[1][2] == chat


def test_yangi_suhbat_buyrugi(world):
    bot, tg, links, backend, _ = world
    links.link(TG_ID, 1)
    bot.handle_update(text_update("birinchi"))
    bot.handle_update(text_update("/new"))
    bot.handle_update(text_update("ikkinchi"))
    assert backend.questions[0][2] != backend.questions[1][2]
    assert any("Yangi suhbat" in t for t in tg.texts())


def test_xizmat_band_bolsa_tushunarli_xabar(world):
    bot, tg, links, backend, _ = world
    links.link(TG_ID, 1)
    backend.open_error = AssistantError("navbat to'la", status=503)
    bot.handle_update(text_update("savol"))
    assert tg.texts()[-1] == "⚠️ Savol-javob xizmati band, biroz kutib qayta urinib ko'ring"


def test_xato_kadri_xizmat_matni_bilan(world):
    bot, tg, links, backend, _ = world
    links.link(TG_ID, 1)
    backend.frames = _frames({"type": "error", "code": "auth_missing", "text": "CRM tizimiga kiring"},
                             {"type": "done"})
    bot.handle_update(text_update("vazifalarim"))
    assert tg.texts()[-1] == "⚠️ CRM tizimiga kiring"


def test_html_rad_etilsa_oddiy_matn(world):
    bot, tg, links, backend, _ = world
    links.link(TG_ID, 1)
    bot.handle_update(text_update("savol"))
    tg.calls.clear()
    tg.fail_html_once = True
    bot._send(TG_ID, "<b>qalin</b> &amp; oddiy")
    assert tg.sent() == [dict(tg.sent()[0], text="qalin & oddiy", html=False)]


def test_hisob_ochirilsa_ulanish_uziladi(world):
    bot, tg, links, backend, users = world
    links.link(TG_ID, 42)                    # bunday actor yo'q
    bot.handle_update(text_update("savol"))
    assert links.lookup(TG_ID) == (None, "none") and backend.questions == []
    assert "topilmadi" in tg.texts()[0]


def voice_update(file_id="v1", duration=4, size=4000):
    return {"update_id": 2, "message": {"message_id": 20, "from": {"id": TG_ID}, "chat": {"id": TG_ID, "type": "private"},
                                        "voice": {"file_id": file_id, "duration": duration, "file_size": size,
                                                  "mime_type": "audio/ogg"}}}


def test_ovozli_xabar_matnga_va_javob(world):
    bot, tg, links, backend, _ = world
    links.link(TG_ID, 1)
    tg.files["voice/v1.oga"] = b"OggS-fake"
    bot.handle_update(voice_update())
    assert backend.audio == [(b"OggS-fake", "audio/ogg")]
    transcript = tg.sent()[0]
    assert transcript["text"] == "🎙 <i>bugun kech qoldimmi</i>" and transcript["reply_to"] == 20
    assert backend.questions[0][0] == "bugun kech qoldimmi"
    # TTS YO'Q: faqat matnli xabarlar.
    assert not [n for n, _ in tg.calls if n not in ("send_message", "delete_message", "edit_message_text")]


def test_ovoz_uzun_yoki_stt_xatosi(world):
    bot, tg, links, backend, _ = world
    links.link(TG_ID, 1)
    bot.handle_update(voice_update(duration=settings.telegram_voice_max_sec + 1))
    assert "juda uzun" in tg.texts()[-1] and backend.audio == []
    tg.files["voice/v2.oga"] = b"x"
    backend.transcript = SttError("band", status=503)
    bot.handle_update(voice_update("v2"))
    assert tg.texts()[-1] == "Ovoz xizmati band, biroz kutib qayta urinib ko'ring"
    backend.transcript = Transcript(text="  ")
    bot.handle_update(voice_update("v2"))
    assert "matn ajratib bo'lmadi" in tg.texts()[-1] and backend.questions == []


PROPOSAL = {"token": "a" * 32, "connector": "crm", "summary": "DVSIB loyihasida yangi Task",
            "target": {"kind": "new_issue", "key": None, "project": "DVSIB", "summary": "Bot"},
            "changes": [{"field": "status", "from": "Open", "to": "In Progress"}],
            "warnings": ["Yangi vazifani bu yerdan o'chirib bo'lmaydi."]}


def callback(data, *, message_id=77, tg_id=TG_ID):
    return {"update_id": 3, "callback_query": {"id": "cb1", "from": {"id": tg_id}, "data": data,
                                               "message": {"message_id": message_id,
                                                           "chat": {"id": tg_id, "type": "private"}}}}


def test_taklif_kartasi_va_tasdiqlash(world):
    bot, tg, links, backend, _ = world
    links.link(TG_ID, 1)
    backend.frames = _frames({"type": "token", "text": "Iltimos, tasdiqlang."},
                             {"type": "proposal", "proposal": PROPOSAL}, {"type": "done"})
    bot.handle_update(text_update("CRM da task yarat"))
    card = tg.sent()[-1]
    assert card["text"].startswith("✏️ <b>Taklif qilingan o'zgarish</b> · CRM")
    assert "<b>Obyekt:</b> Bot" in card["text"] and "<s>Open</s> → In Progress" in card["text"]
    assert "15 daqiqada" in card["text"]
    buttons = card["reply_markup"]["inline_keyboard"][0]
    assert [b["callback_data"] for b in buttons] == ["a:x:" + "a" * 32, "a:c:" + "a" * 32]
    bot.handle_update(callback("a:c:" + "a" * 32))
    assert backend.actions == [("confirm", "a" * 32, 1)]
    assert ("edit_reply_markup", {"chat_id": TG_ID, "message_id": 77, "reply_markup": None}) in tg.calls
    done = tg.sent()[-1]
    assert done["text"] == "✅ <b>Bajarildi</b>: <code>DVSIB-123</code>" and done["reply_to"] == 77


def test_rad_etish_va_eskirgan_taklif(world):
    bot, tg, links, backend, _ = world
    links.link(TG_ID, 1)
    backend.action_result = {"token": "t", "status": "cancelled"}
    bot.handle_update(callback("a:x:" + "b" * 32))
    assert backend.actions[-1][0] == "cancel" and "Rad etildi" in tg.texts()[-1]
    backend.action_result = AssistantError("yo'q", status=404)
    bot.handle_update(callback("a:c:" + "c" * 32, message_id=78))
    alert = [kw for n, kw in tg.calls if n == "answer_callback"][-1]
    assert alert["alert"] and alert["text"] == "Taklif topilmadi yoki muddati tugagan"
    assert ("edit_reply_markup", {"chat_id": TG_ID, "message_id": 78, "reply_markup": None}) in tg.calls
    # Xizmatning yangi javobi - 410 `expired`: xuddi shunday, aniq matn bilan.
    backend.action_result = AssistantError("expired", status=410)
    bot.handle_update(callback("a:c:" + "d" * 32, message_id=79))
    alert = [kw for n, kw in tg.calls if n == "answer_callback"][-1]
    assert alert["alert"] and "muddati tugagan" in alert["text"]
    assert ("edit_reply_markup", {"chat_id": TG_ID, "message_id": 79, "reply_markup": None}) in tg.calls


def test_tugma_ulanmagan_odamdan(world):
    bot, tg, links, backend, _ = world
    bot.handle_update(callback("a:c:" + "a" * 32))
    assert backend.actions == []
    assert [kw for n, kw in tg.calls if n == "answer_callback"][0]["alert"]


def test_ariza_fayli_chatga_keladi(world):
    bot, tg, links, backend, _ = world
    links.link(TG_ID, 1)
    token = "T" * 43
    backend.frames = _frames({"type": "token", "text": "Arizangiz tayyor."},
                             {"type": "artifact", "artifact": {
                                 "title": "Ta'til arizasi (shablon)",
                                 "docx_url": f"/api/v1/chat/artifact/{token}/docx",
                                 "pdf_url": f"/api/v1/chat/artifact/{token}/pdf"}},
                             {"type": "done"})
    bot.handle_update(text_update("ariza tayyorla"))
    doc = tg.sent("send_document")[0]
    assert doc["filename"] == "Ta'til arizasi shablon.docx" and backend.files == [("docx", token)]
    assert doc["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == f"f:p:{token}"
    bot.handle_update(callback(f"f:p:{token}"))
    assert tg.sent("send_document")[1]["filename"] == "Ta'til arizasi shablon.pdf"
    # Manba hujjati esa FAYL bo'lib kelmaydi - imzolangan havola (`test_bot_ux.py`).
    bot.handle_update(callback("d:HR_045"))
    assert len(tg.sent("send_document")) == 2 and backend.links == [("HR_045", 1, "HR_045")]


def test_buyruqlar_menyusi_va_offset(world):
    bot, tg, links, backend, _ = world
    tg.get_updates = lambda offset, timeout=25: [text_update("/help"), {"update_id": 9}]
    bot._prepare()
    # Menyu faqat jonli ishga tushishda yoziladi (`sync_commands`) - test nusxasida yo'q.
    assert tg.commands == [] and not tg.sent("set_my_commands") and bot.username == "venera_test_bot"
    bot.sync_commands = True
    bot._prepared = False
    bot._prepare()
    assert tg.commands == COMMANDS
    assert bot.poll_once() == 2 and bot._offset == 10
    assert "Venera" in tg.texts()[0]


# --- render --------------------------------------------------------------------


def test_render_kesishgan_belgilash_xavfsiz():
    blocks = render.to_blocks("**a ~~b** c~~ <script> & 5 * 3")
    assert all(render._balanced(b) for b in blocks)
    assert "&lt;script&gt;" in blocks[0] and "<b>" not in blocks[0]


def test_render_uzun_javob_bolinadi():
    text = "\n\n".join(f"**{i}-band.** " + "so'z " * 300 for i in range(10))
    chunks = render.pack(render.to_blocks(text))
    assert len(chunks) > 1 and all(len(c) <= render.LIMIT for c in chunks)
    assert all(render._balanced(c) for c in chunks)


def test_render_jadval_va_kod():
    blocks = render.to_blocks("| Kun | Soat |\n|---|---|\n| Dush | 9:00 |\n\n```\nx < 1\n```")
    assert blocks == ["Kun | Soat\nDush | 9:00", "<pre>x &lt; 1</pre>"]


# --- faqat matn va ovoz: video (kamera) qabul qilinmaydi ------------------------

VIDEO_NOTE = "📵 Video qabul qilinmaydi - xabar o'chirildi. Savolni yozing yoki 🎙 ovozli xabar yuboring."


def media_update(kind, payload, *, message_id=30):
    return {"update_id": 5, "message": {"message_id": message_id, "from": {"id": TG_ID},
                                        "chat": {"id": TG_ID, "type": "private"}, kind: payload}}


@pytest.mark.parametrize("kind,payload", [
    ("video_note", {"file_id": "vn", "length": 240, "duration": 5}),          # dumaloq video
    ("video", {"file_id": "vd", "duration": 5, "mime_type": "video/mp4"}),
    ("document", {"file_id": "dc", "mime_type": "video/quicktime", "file_name": "a.mov"}),
])
def test_video_qabul_qilinmaydi_va_ochiriladi(world, kind, payload):
    bot, tg, links, backend, _ = world
    links.link(TG_ID, 1)
    bot.handle_update(media_update(kind, payload))
    assert ("delete_message", {"chat_id": TG_ID, "message_id": 30}) in tg.calls
    assert tg.texts() == [VIDEO_NOTE]
    # Yuklab olinmaydi, STT ga ham, yordamchiga ham bormaydi.
    assert backend.questions == [] and backend.audio == []


def test_video_ulanmagan_odamdan_ham_ochiriladi(world):
    bot, tg, links, backend, _ = world
    bot.handle_update(media_update("video_note", {"file_id": "vn"}))
    assert ("delete_message", {"chat_id": TG_ID, "message_id": 30}) in tg.calls
    assert tg.texts() == [VIDEO_NOTE]


def test_albomdagi_videolar_hammasi_ochiriladi_izoh_bitta(world):
    bot, tg, links, backend, _ = world
    links.link(TG_ID, 1)
    for i in range(3):
        bot.handle_update(media_update("video", {"file_id": f"v{i}"}, message_id=40 + i))
    assert [kw["message_id"] for n, kw in tg.calls if n == "delete_message"] == [40, 41, 42]
    assert tg.texts() == [VIDEO_NOTE]


def test_rasm_va_fayl_ochirilmaydi_faqat_izoh(world):
    bot, tg, links, backend, _ = world
    links.link(TG_ID, 1)
    bot.handle_update(media_update("photo", [{"file_id": "p", "width": 1, "height": 1}]))
    assert not [n for n, _ in tg.calls if n == "delete_message"]
    assert tg.texts() == ["Faqat matn va 🎙 ovozli xabar qabul qilinadi."]
    assert backend.questions == []


def test_ovoz_va_matn_ishlashda_davom_etadi(world):
    bot, tg, links, backend, _ = world
    links.link(TG_ID, 1)
    bot.handle_update(media_update("video_note", {"file_id": "vn"}))
    tg.files["voice/v1.oga"] = b"OggS"
    bot.handle_update(voice_update())
    bot.handle_update(text_update("savol"))
    assert [q[0] for q in backend.questions] == ["bugun kech qoldimmi", "savol"]


def test_faol_foydalanuvchidan_qayta_kirish_soralmaydi(tmp_path):
    """Bir marta ulangan odam botdan foydalanib tursa, 30 kundan keyin ham
    ulanish tirik; faqat 30 kun umuman ishlatilmagani tugaydi."""
    day = 86400.0
    store = LinkStore(tmp_path / "links.json", ttl_days=30)
    store.link(1, 10, now=0.0)
    for d in range(1, 91, 10):                         # har 10 kunda bitta savol
        assert store.lookup(1, now=d * day)[1] == "linked", d
        store.chat_for(1, idle_sec=6 * 3600, now=d * day)
    last = 81 * day
    assert store.lookup(1, now=last + 29 * day)[1] == "linked"
    assert store.lookup(1, now=last + 31 * day)[1] == "expired"


def test_yangi_suhbat_ham_muddatni_yangilaydi(tmp_path):
    store = LinkStore(tmp_path / "links.json", ttl_days=30)
    store.link(1, 10, now=0.0)
    store.new_chat(1, now=25 * 86400.0)
    assert store.lookup(1, now=50 * 86400.0)[1] == "linked"


# --- webhook ---------------------------------------------------------------------

WEBHOOK_URL = "https://llm.brb-tech.uz/api/v1/telegram/webhook"


class WebhookTelegram(FakeTelegram):
    """Telegram'ning webhook holati bilan."""

    def __init__(self) -> None:
        super().__init__()
        self.info = {"url": "", "pending_update_count": 0}
        self.set_calls: list[tuple[str, str]] = []
        self.deleted = 0

    def set_webhook(self, url, *, secret, allowed_updates):
        self.set_calls.append((url, secret))
        self.info = {"url": url, "pending_update_count": 0}

    def get_webhook_info(self):
        return dict(self.info)

    def delete_webhook(self):
        self.deleted += 1
        self.info = {"url": "", "pending_update_count": 0}


def webhook_bot(tmp_path, tg):
    users = UserStore({"a@b.uz": StoredUser(actor_id=1, email="a@b.uz", full_name="Ali",
                                            password_hash=hash_password("x"))})
    return VeneraBot(tg, LinkStore(tmp_path / "links.json"), users=lambda: users,
                     backend=FakeBackend(), inline=True, typing_every=None, mode="webhook",
                     webhook_url=WEBHOOK_URL, webhook_secret="s" * 64)


def test_webhook_ornatiladi_va_qayta_ornatiladi(tmp_path):
    tg = WebhookTelegram()
    bot = webhook_bot(tmp_path, tg)
    assert bot.mode == "webhook"
    assert bot.check_webhook(now=1000.0) and tg.set_calls == [(WEBHOOK_URL, "s" * 64)]
    assert bot.check_webhook(now=1060.0) and len(tg.set_calls) == 1       # joyida - tegilmaydi
    tg.info = {"url": "https://boshqa.example/hook", "pending_update_count": 0}
    assert bot.check_webhook(now=1120.0) and len(tg.set_calls) == 2       # kimdir o'zgartirdi


def test_webhook_sir_rad_etilsa_bir_marta_qayta_ornatiladi(tmp_path):
    tg = WebhookTelegram()
    bot = webhook_bot(tmp_path, tg)
    bot.check_webhook(now=1000.0)
    tg.info = {"url": WEBHOOK_URL, "pending_update_count": 2,
               "last_error_date": 1050, "last_error_message": "Wrong response from the webhook: 401 Unauthorized"}
    assert bot.check_webhook(now=1060.0) and len(tg.set_calls) == 2


def test_webhook_yetib_bormasa_pollingga_qaytadi(tmp_path):
    tg = WebhookTelegram()
    bot = webhook_bot(tmp_path, tg)
    bot.check_webhook(now=1000.0)
    results = []
    for i in range(1, 6):
        now = 1000.0 + 60 * i
        tg.info = {"url": WEBHOOK_URL, "pending_update_count": 3, "last_error_date": now - 10,
                   "last_error_message": "Connection timed out"}
        results.append(bot.check_webhook(now=now))
    assert results == [True, True, True, True, False]
    assert tg.deleted == 1 and bot.mode == "polling"
    assert "polling" in bot.status()["note"]


def test_webhook_qisqa_uzilish_qaytarmaydi(tmp_path):
    """Qayta ishga tushish paytidagi bir martalik xato - polling'ga o'tilmaydi."""
    tg = WebhookTelegram()
    bot = webhook_bot(tmp_path, tg)
    bot.check_webhook(now=1000.0)
    tg.info = {"url": WEBHOOK_URL, "pending_update_count": 1, "last_error_date": 1050,
               "last_error_message": "Wrong response from the webhook: 502 Bad Gateway"}
    assert bot.check_webhook(now=1060.0)
    tg.info = {"url": WEBHOOK_URL, "pending_update_count": 0, "last_error_date": 1050,
               "last_error_message": "Wrong response from the webhook: 502 Bad Gateway"}
    for i in range(2, 8):
        assert bot.check_webhook(now=1000.0 + 60 * i)
    assert tg.deleted == 0 and bot.mode == "webhook" and bot.status()["error"] is None


@pytest.fixture
def webhook_on(tmp_path, monkeypatch):
    import app.bot as bot_module

    tg = WebhookTelegram()
    bot = webhook_bot(tmp_path, tg)
    monkeypatch.setattr(settings, "telegram_bot_token", BOT_TOKEN)
    monkeypatch.setattr(bot_module, "_bot", bot)
    return tg, bot, bot_module.webhook_secret()


def test_webhook_endpoint_sirsiz_rad_etiladi(client, webhook_on):
    tg, bot, secret = webhook_on
    update = text_update("/help")
    assert client.post("/api/v1/telegram/webhook", json=update).status_code == 401
    r = client.post("/api/v1/telegram/webhook", json=update,
                    headers={"X-Telegram-Bot-Api-Secret-Token": "x" * 64})
    assert r.status_code == 401 and tg.calls == []


def test_webhook_endpoint_xabarni_botga_beradi_takrorini_tashlaydi(client, webhook_on):
    tg, bot, secret = webhook_on
    headers = {"X-Telegram-Bot-Api-Secret-Token": secret}
    update = dict(text_update("/help"), update_id=777)
    assert client.post("/api/v1/telegram/webhook", json=update, headers=headers).json() == {"ok": True}
    assert client.post("/api/v1/telegram/webhook", json=update, headers=headers).status_code == 200
    help_texts = [t for t in tg.texts() if "Venera" in t and "/new" in t]
    assert len(help_texts) == 1, "takroriy yangilanish ikkinchi marta ishlanmasligi kerak"


def test_webhook_endpoint_bot_ishlamasa_503(client, monkeypatch):
    import app.bot as bot_module

    monkeypatch.setattr(settings, "telegram_bot_token", BOT_TOKEN)
    monkeypatch.setattr(bot_module, "_bot", None)
    r = client.post("/api/v1/telegram/webhook", json={"update_id": 1},
                    headers={"X-Telegram-Bot-Api-Secret-Token": bot_module.webhook_secret()})
    assert r.status_code == 503


def test_webhook_siri_barqaror_va_telegram_belgilarida():
    from app.services.integrations.telegram import webhook_secret

    a = webhook_secret(BOT_TOKEN, "kalit-1")
    assert a == webhook_secret(BOT_TOKEN, "kalit-1") and a != webhook_secret(BOT_TOKEN, "kalit-2")
    assert len(a) == 64 and all(c in "0123456789abcdef" for c in a)
    assert webhook_secret("", "kalit") == "" and webhook_secret(BOT_TOKEN, "") == ""


def test_manzil_yoki_sir_bolmasa_polling(tmp_path):
    tg = WebhookTelegram()
    bot = VeneraBot(tg, LinkStore(tmp_path / "l.json"), users=lambda: UserStore({}),
                    inline=True, mode="webhook", webhook_url="", webhook_secret="s")
    assert bot.mode == "polling"


# --- polling: boshqa nusxa bilan to'qnashuv --------------------------------------

def _conflict():
    text = "Conflict: terminated by other getUpdates request; make sure that only one bot instance is running"
    # `TelegramApi._send` shakli: "usul: kod tavsif".
    return TelegramError(f"getUpdates: 409 {text}", code=409, description=text)


def test_boshqa_nusxa_bolsa_darhol_qayta_soraydi(world):
    bot, tg, *_ = world
    wait, backoff = bot.poll_error(_conflict(), 1.0)
    assert wait == 0.1 and backoff == 1.0
    assert bot.status()["conflicts_10min"] == 1 and bot.status()["error"] is None


def test_ikkinchi_nusxa_ham_shoshsa_sekinlashadi(world):
    bot, *_ = world
    waits = [bot.poll_error(_conflict(), 1.0, now=1000.0 + i * 0.5)[0] for i in range(40)]
    assert waits[0] == 0.1 and waits[-1] == 2.0


def test_webhook_ornatilgan_bolsa_kutadi_va_aytadi(world):
    bot, *_ = world
    text = ("Conflict: can't use getUpdates method while webhook is active; "
            "use deleteWebhook to delete the webhook first")
    exc = TelegramError(f"getUpdates: 409 {text}", code=409, description=text)
    assert bot.poll_error(exc, 1.0, now=1000.0)[0] == 30.0
    assert "webhook" in bot.status()["error"] and bot.status()["conflicts_10min"] == 0


def test_tarmoq_xatosida_backoff_va_token_rad(world):
    bot, *_ = world
    assert bot.poll_error(TelegramError("tarmoq xatosi"), 1.0) == (1.0, 2.0)
    assert bot.poll_error(TelegramError("tarmoq xatosi"), 16.0) == (16.0, 30.0)
    assert bot.poll_error(TelegramError("401", code=401, description="Unauthorized"), 1.0)[0] == 300.0
