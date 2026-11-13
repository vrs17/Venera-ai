"""Slack'dagi Barno AI yordamchisi (`app/slack/assistant.py`, ega so'rovi 2026-11-13): veb chatdagi AYNI assistent -
HR hujjatlari, HRM va CRM. Ega qarori ("thread qoidasi"): chatning o'zidagi har matn - yordamchiga, yozuv savollari -
yozuv xabarining thread'ida; yordamchi javobining thread'i - o'sha suhbat.

Yuqoridagi xizmat soxta (`chat.open_stream`, `chat._assistant`): tarmoq ham, pul ham yo'q.
"""

from __future__ import annotations

import json
import re
import time

import pytest

from app.api.v1 import chat as chat_api
from app.core.config import settings
from app.services import analytics
from app.services.analytics.db import get_db
from app.services.integrations.assistant import AssistantError
from app.slack import assistant, link, meeting, render
from slack_fakes import BOT_USER, FakeSlack, setup

APP = "https://llm.test"
LEX = "https://lex.uz/docs/6257288?ONDATE=01.01.2026&x=1"
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
SOURCES = {"type": "sources", "items": [
    {"kind": "doc", "doc_id": "HR_045", "title": "Ichki mehnat tartibi", "page": 22, "citation_index": 1},
    {"kind": "law", "citation_index": 2, "title": "Mehnat kodeksi, 160-modda", "url": LEX},
    {"kind": "hrm", "tool": "hrm_today_late", "digest": "count=9"},
]}
ANSWER = [{"type": "stage", "text": "HRM dan ma'lumot olinmoqda"}, SOURCES,
          {"type": "token", "text": "## Ta'til\nAsosiy ta'til **21 kun** [1], qonunda ham [2]. "},
          {"type": "token", "text": "Batafsil: [ariza namunasi](https://hr.example.uz/a?x=1&y=2)."},
          {"type": "done", "route": "rules"}]
PROPOSAL = {"type": "proposal", "proposal": {
    "token": "tok-1", "connector": "crm", "summary": "Vazifa yaratiladi", "target": {"title": "Mijoz: Aloqa MCHJ"},
    "changes": [{"field": "Muddat", "from": "1-dekabr", "to": "5-dekabr"}, {"field": "Mas'ul", "to": "B.Aliyev"}],
    "warnings": ["Muddat o'tgan sana bo'lmasin"]}}


class FakeStream:
    """`chat.open_stream` natijasi (`AnswerStream`): kadrlar NDJSON baytlari; `broken_after` - shuncha kadrdan keyin
    uziladi."""

    def __init__(self, frames, *, broken_after=None):
        self._frames = [json.dumps(f).encode() + b"\n" for f in frames]
        self._broken_after = broken_after
        self.request_id = "req-1"
        self.outcome = {"route": "live"}
        self.engine = "v4"
        self.closed = False
        self.frames = self._iter()

    def _iter(self):
        for index, raw in enumerate(self._frames):
            if self._broken_after is not None and index == self._broken_after:
                raise AssistantError("uzildi", status=502)
            yield raw

    def close(self):
        self.closed = True


class FakeUpstream:
    """`chat._assistant` - taklif amallari va hujjat fayllari."""

    def __init__(self):
        self.calls = []
        self.results = {}
        self.files = {("AbC123", "docx"): b"PK-DOCX", ("AbC123", "pdf"): b"%PDF-1"}

    def confirm_action(self, token, *, user_id, tokens=None):
        self.calls.append(("confirm", token, user_id, dict(tokens or {})))
        return self._result(token, {"status": "executed", "ok": True, "result": {"key": "CRM-12"}})

    def cancel_action(self, token, *, user_id, tokens=None):
        self.calls.append(("cancel", token, user_id, dict(tokens or {})))
        return self._result(token, {"status": "cancelled"})

    def _result(self, token, default):
        found = self.results.get(token, default)
        if isinstance(found, Exception):
            raise found
        return found

    def fetch_artifact(self, token, kind):
        self.calls.append(("artifact", token, kind))
        data = self.files[(token, kind)]
        return ("application/octet-stream", f"upstream.{kind}", iter([data[:3], data[3:]]))


def _linking_on(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "sso_app_url", APP, raising=False)
    monkeypatch.setattr(settings, "slack_link_required", True, raising=False)
    monkeypatch.setattr(settings, "slack_links_file", tmp_path / "slack" / "links.json", raising=False)
    monkeypatch.setattr(link, "_offered", {})
    link.TICKETS.clear()


@pytest.fixture
def world(users_file, monkeypatch, tmp_path):
    """Ulangan Slack odami (T1/U2 -> actor 2), soxta oqim va xizmat. Qaytaradi: (Slack, oqim chaqiruvlari, xizmat,
    navbatdagi javob kadrlari ro'yxati)."""
    setup(monkeypatch, users_file)
    _linking_on(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "slack_assistant_chats_file", tmp_path / "slack" / "assistant_chats.json",
                        raising=False)
    monkeypatch.setattr(settings, "telegram_webapp_url", "https://llm.test/tg/", raising=False)
    link.store().link("T1", "U2", 2)
    opened, script, streams = [], [], []

    def open_stream(question, user, chat_id, **kwargs):
        opened.append({"question": question, "actor": user.actorId, "chat": chat_id, **kwargs})
        frames = script.pop(0) if script else ANSWER
        if isinstance(frames, Exception):
            raise frames
        stream = frames if isinstance(frames, FakeStream) else FakeStream(frames)
        streams.append(stream)
        return stream

    upstream = FakeUpstream()
    monkeypatch.setattr(chat_api, "open_stream", open_stream)
    monkeypatch.setattr(chat_api, "_assistant", upstream)
    monkeypatch.setattr(chat_api, "_live_tokens", lambda user: {"crm": f"crm-{user.actorId}", "hrm": "h"})
    yield FakeSlack(), opened, upstream, script, streams
    link.TICKETS.clear()


def _top(slack, text="Ta'tilim necha kun?", *, user="U2", channel="D2"):
    assistant.on_text(slack, slack.say(channel, text, user=user, team="T1"))


def _press(slack, action_id, value, message, *, user="U2"):
    body = {"actions": [{"action_id": action_id, "value": value}], "channel": {"id": "D2"},
            "user": {"id": user, "team_id": "T1"}, "team": {"id": "T1"}, "message": message}
    assert assistant.handles(body)
    assistant.on_action(slack, body)


# --- yo'nalish va javob --------------------------------------------------------------------------


def test_chatdagi_matn_yordamchiga_javob_manbalar_va_tugmalar(world):
    """Chatning o'zidagi matn - yordamchiga: odamning O'Z hisobi (actor 2), kanal `slack`, standart rejim, dvigatel -
    admin siyosati. "⏳" bosqich matni bilan, so'ng o'sha xabar o'rnida javob: mrkdwn (sarlavha qalin, `**` -> `*`,
    havola bosiladigan), «📚 Manbalar» (LEX.UZ havolasi, ichki hujjat nomi va beti; HRM so'rovi manba emas), ostida
    hujjat tugmasi va «🔄 Yangi suhbat» - javob belgisi bilan. Savol izi admin panelda: kanal `slack`, tur `bot`."""
    slack, opened, _, _, streams = world
    _top(slack)
    [call] = opened
    assert (call["question"], call["actor"], call["channel"], call["mode"], call["engine"]) == (
        "Ta'tilim necha kun?", 2, "slack", "standard", None)
    assert UUID.fullmatch(call["chat"]) and streams[0].closed
    [holder] = slack.posted
    assert holder["text"] == assistant.WORKING and "thread_ts" not in holder
    stage, answer = slack.updated
    assert stage["text"] == "⏳ HRM dan ma'lumot olinmoqda" and answer["ts"] == holder["ts"]
    text = answer["text"]
    assert text.startswith("*Ta'til*\nAsosiy ta'til *21 kun* [1], qonunda ham [2].")
    assert "<https://hr.example.uz/a?x=1&amp;y=2|ariza namunasi>" in text
    assert "📚 *Manbalar*\n[1] Ichki mehnat tartibi, 22-bet\n" in text
    law = "<https://lex.uz/docs/6257288?ONDATE=01.01.2026&amp;x=1|Mehnat kodeksi, 160-modda>"
    assert f"[2] LEX.UZ · qonunchilik: {law}" in text
    assert "hrm_today_late" not in text
    actions = answer["blocks"][-1]
    assert actions["block_id"] == f"{assistant.MARK}{call['chat']}"
    assert [(e["action_id"], e["value"]) for e in actions["elements"]] == [
        (assistant.DOC_ACTION, "HR_045|Ichki mehnat tartibi"), (assistant.NEW_ACTION, call["chat"])]
    assert actions["elements"][0]["text"]["text"] == "📄 [1] Ichki mehnat tartibi"
    analytics.flush(2.0)
    [turn] = get_db().rows("SELECT actor_id, channel, kind, chat_id FROM turns")
    assert turn == {"actor_id": 2, "channel": "slack", "kind": "bot", "chat_id": call["chat"]}


def test_suhbat_davom_etadi_yangi_suhbat_va_thread(world, monkeypatch):
    """Odamning joriy suhbati: ikkinchi savol - o'sha suhbatda; «🔄 Yangi suhbat» - keyingisi yangisida. Eski javobning
    thread'idagi savol - O'SHA (eski) suhbatda va javob o'sha thread'da (`meeting.question` -> `assistant.on_thread`).
    Uzoq jimlikdan keyin - yangi suhbat."""
    slack, opened, _, _, _ = world
    _top(slack)
    first_answer = slack.updated[-1]
    _top(slack, "Kasallik varaqasi qanday?")
    assert opened[0]["chat"] == opened[1]["chat"]
    _press(slack, assistant.NEW_ACTION, opened[0]["chat"], first_answer)
    assert slack.posted[-1]["text"] == assistant.NEW_DONE
    _top(slack, "Yangi savol")
    assert opened[2]["chat"] != opened[0]["chat"] and UUID.fullmatch(opened[2]["chat"])

    # Birinchi javobning thread'i - o'sha suhbat (yozuv chati emas).
    monkeypatch.setattr(meeting.service, "chat_send", lambda *a, **k: pytest.fail("yozuv chatiga bormasligi kerak"))
    thread = slack.thread_under(first_answer)
    meeting.on_message(slack, slack.say("D2", "Batafsilroq", user="U2", team="T1", thread=thread),
                       bot_user=BOT_USER)
    assert opened[3]["chat"] == opened[0]["chat"] and opened[3]["question"] == "Batafsilroq"
    assert slack.posted[-1]["thread_ts"] == thread and slack.posted[-1]["text"] == assistant.WORKING
    assert slack.updated[-1]["ts"] == slack.posted[-1]["ts"]
    # Begona botning (yoki belgisiz) javobi - yordamchiniki emas.
    assert assistant.owns({**first_answer, "bot_id": "B9", "user": "UOTHER"}, bot_user=BOT_USER) is None
    assert assistant.owns({"bot_id": "B1", "user": BOT_USER, "blocks": [{"block_id": "barno-hr:x"}]}) is None

    # Jimlik: `SLACK_CHAT_IDLE_HOURS` dan keyin - yangi suhbat (fayl orqali ham saqlanadi).
    store = assistant.store()
    now = time.time()
    chat = store.current("T1:U9", idle_sec=3600, now=now)
    assert store.current("T1:U9", idle_sec=3600, now=now + 60) == chat
    assert store.current("T1:U9", idle_sec=3600, now=now + 60 + 3601) != chat
    assert json.loads(store.path.read_text())["T1:U9"]["chat"] != chat


def test_ulanmagan_bloklangan_va_umumiy_hisob(world, monkeypatch):
    """Ulanmagan odamga - faqat o'ziga ko'rinadigan ulash xabari (javob ham, savol ham yo'q); ulash o'chiq o'rnatmada
    (umumiy hisob) yordamchi ishlamaydi - HR ma'lumoti bitta hisobda aralashardi."""
    slack, opened, _, _, _ = world
    _top(slack, user="U7")
    assert opened == [] and slack.posted == [] and len(slack.ephemeral) == 1
    monkeypatch.setattr(settings, "slack_link_required", False, raising=False)
    _top(slack)
    assert opened == [] and slack.posted[-1]["text"] == assistant.SHARED


def test_bir_odamning_navbati_chegaralangan(world, monkeypatch):
    """Bir odamning bir vaqtdagi savollari `QUEUE_LIMIT` tagacha (bittasi ishlanadi, qolgani navbatda): ortig'iga
    "kuting" - umumiy navbat iplari (audio bilan) bitta odamga band bo'lib qolmasin. Savol tugagach hisob kamayadi."""
    slack, opened, _, _, _ = world
    monkeypatch.setitem(assistant._pending, "T1:U2", assistant.QUEUE_LIMIT)
    _top(slack)
    assert opened == [] and slack.posted[-1]["text"] == assistant.BUSY
    monkeypatch.setitem(assistant._pending, "T1:U2", assistant.QUEUE_LIMIT - 1)
    _top(slack)
    assert len(opened) == 1 and assistant._pending["T1:U2"] == assistant.QUEUE_LIMIT - 1
    del assistant._pending["T1:U2"]
    _top(slack)
    assert len(opened) == 2 and "T1:U2" not in assistant._pending


def test_uzun_savol_va_xatolar(world, monkeypatch):
    """Juda uzun savol - xizmatga bormaydi. Oqim ochilmasa - sababi "⏳" o'rnida (veb chatdagi matn); o'rtada uzilsa -
    kelgan qism va izoh; `error` kadri - xizmatning o'z matni."""
    slack, opened, _, script, streams = world
    monkeypatch.setattr(settings, "hrm_assistant_max_question_chars", 10, raising=False)
    _top(slack, "x" * 11)
    assert opened == [] and slack.posted[-1]["text"] == assistant.TOO_LONG.format(n=11, limit=10)
    monkeypatch.setattr(settings, "hrm_assistant_max_question_chars", 2000, raising=False)

    script.append(AssistantError("band", status=503, reason="queue_full"))
    _top(slack)
    assert slack.updated[-1]["text"] == "⚠️ " + render.escape(chat_api._MESSAGES[503])

    script.append(FakeStream([{"type": "token", "text": "Qisman javob"}, {"type": "token", "text": "!"}],
                             broken_after=1))
    _top(slack)
    broken = slack.updated[-1]["text"]
    assert broken.startswith("Qisman javob\n\n⚠️ _") and render.escape(chat_api._MESSAGES[502]) in broken
    assert streams[-1].closed

    script.append([{"type": "error", "code": "auth_missing"}])
    _top(slack)
    assert slack.updated[-1]["text"].startswith("⚠️ Bu savol uchun jonli ma'lumot kerak")
    analytics.flush(2.0)
    codes = [r["error_code"] for r in get_db().rows("SELECT error_code FROM turns ORDER BY started_at")]
    assert codes[:2] == ["queue_full", "stream_broken"]


# --- takliflar, hujjatlar, havola ----------------------------------------------------------------------------


def test_taklif_tasdiqlash_rad_etish_va_muddati(world, monkeypatch):
    """CRM taklifi - karta (nima o'zgaradi, ogohlantirish) va «✖️ Rad etish» / «✅ Tasdiqlash»; tasdiq odamning O'Z
    kimligi va tokenlari bilan, natija - tugmalar olinadi, ostida natija; rad etish ham. Muddati o'tgan taklif -
    tugmalar olinadi. Holat admin paneldagi izga ham (`set_proposal_status`)."""
    slack, _, upstream, script, _ = world
    statuses = []
    monkeypatch.setattr(assistant, "set_proposal_status", lambda token, status: statuses.append((token, status)))
    script.append([{"type": "token", "text": "Vazifa tayyor."}, PROPOSAL])
    _top(slack, "Aloqa MCHJ ga vazifa yarat")
    card = slack.posted[-1]
    text = card["text"]
    assert text.startswith("✏️ *Taklif qilingan o'zgarish* · CRM\n\nVazifa yaratiladi\n\n*Obyekt:* Mijoz: Aloqa MCHJ")
    assert "*Muddat:* ~1-dekabr~ → 5-dekabr" in text and "*Mas'ul:* B.Aliyev" in text
    assert "⚠️ Muddat o'tgan sana bo'lmasin" in text and "15 daqiqada" in text
    buttons = card["blocks"][-1]["elements"]
    assert [(b["action_id"], b["value"]) for b in buttons] == [(assistant.NO_ACTION, "tok-1"),
                                                             (assistant.OK_ACTION, "tok-1")]
    assert buttons[1]["style"] == "primary"

    _press(slack, assistant.OK_ACTION, "tok-1", {**card, "blocks": card["blocks"]})
    assert upstream.calls[-1] == ("confirm", "tok-1", "venera:2", {"crm": "crm-2", "hrm": "h"})
    done = slack.updated[-1]
    assert done["ts"] == card["ts"] and not [b for b in done["blocks"] if b["type"] == "actions"]
    assert done["blocks"][-1]["elements"][0]["text"] == "✅ *Bajarildi*: `CRM-12`"
    assert statuses == [("tok-1", "executed")]

    _press(slack, assistant.NO_ACTION, "tok-2", card)
    assert upstream.calls[-1][0] == "cancel" and "Rad etildi" in slack.updated[-1]["blocks"][-1]["elements"][0]["text"]
    upstream.results["tok-3"] = AssistantError("yo'q", status=410)
    _press(slack, assistant.OK_ACTION, "tok-3", card)
    assert "muddati tugagan" in slack.updated[-1]["blocks"][-1]["elements"][0]["text"]
    assert statuses[-1] == ("tok-3", "expired")
    # Yaroqsiz kalit - xizmatga bormaydi.
    calls = len(upstream.calls)
    _press(slack, assistant.OK_ACTION, "yomon kalit!", card)
    assert len(upstream.calls) == calls and slack.posted[-1]["text"] == assistant.STALE


def test_tayyorlangan_hujjat_word_va_pdf_tugmasi(world):
    """Tayyorlangan hujjat (ariza): matnsiz javobda "⏳" o'chiriladi; Word fayli yuklanadi (nomi sarlavhadan),
    PDF esa tugma bilan - bosilganda alohida yuklanadi (ikkinchi fayl behuda chizilmaydi)."""
    slack, _, upstream, script, _ = world
    script.append([{"type": "artifact", "artifact": {
        "title": "Ta'til arizasi", "docx_url": "/api/v1/chat/artifact/AbC123/docx",
        "pdf_url": "/api/v1/chat/artifact/AbC123/pdf"}}])
    _top(slack, "Ta'til arizasini tayyorla")
    assert [d["ts"] for d in slack.deleted] == [slack.posted[0]["ts"]]
    [docx] = slack.uploaded
    assert docx["filename"] == "Ta'til arizasi.docx" and docx["file"] == b"PK-DOCX"
    prompt = slack.posted[-1]
    [button] = prompt["blocks"][-1]["elements"]
    assert (button["action_id"], button["value"]) == (assistant.FILE_ACTION, "pdf|AbC123|Ta'til arizasi")
    _press(slack, assistant.FILE_ACTION, button["value"], prompt)
    assert slack.uploaded[-1]["filename"] == "Ta'til arizasi.pdf" and slack.uploaded[-1]["file"] == b"%PDF-1"
    assert [c for c in upstream.calls if c[0] == "artifact"] == [("artifact", "AbC123", "docx"),
                                                                 ("artifact", "AbC123", "pdf")]
    # Kalitsiz hujjat - "ilovadan yuklab oling".
    script.append([{"type": "artifact", "artifact": {"title": "X", "docx_url": "https://boshqa.uz/x.docx"}}])
    _top(slack, "Yana")
    assert "Barno ilovasidan" in slack.posted[-1]["text"]


def test_hujjat_havolasi_imzolangan_va_qisqa(world):
    """«📄 [1] ...» - imzolangan, 10 daqiqalik havola (veb ilova va Telegram bot bilan bitta imzolovchi, kanal `slack`):
    yangi xabarda havola-tugma; bank hujjatining o'zi Slack'ka yuklanmaydi. Yaroqsiz kalit - "eskirgan"."""
    import jwt

    slack, _, _, _, _ = world
    _press(slack, assistant.DOC_ACTION, "HR_045|Ichki mehnat tartibi", {"ts": "100.1"})
    message = slack.posted[-1]
    assert message["text"].startswith("📄 *Ichki mehnat tartibi*\n_Havola 10 daqiqa ishlaydi")
    [button] = message["blocks"][-1]["elements"]
    assert button["url"].startswith("https://llm.test/api/v1/chat/file/") and slack.uploaded == []
    claims = jwt.decode(button["url"].rsplit("/", 1)[1], settings.secret_key, algorithms=["HS256"],
                        audience=chat_api._FILE_AUDIENCE)
    assert (claims["doc"], claims["uid"], claims["ch"]) == ("HR_045", 2, "slack")
    _press(slack, assistant.DOC_ACTION, "../etc|X", {"ts": "100.1"})
    assert "ochib bo'lmadi" in slack.posted[-1]["text"]
    # Havola-tugmaning o'z hodisasi - ish yo'q.
    posted = len(slack.posted)
    _press(slack, assistant.OPEN_ACTION, "", {"ts": "100.1"})
    assert len(slack.posted) == posted


def test_matn_korinishi():
    """Markdown -> Slack mrkdwn: havola faqat `http(s)`, `&` qochiriladi; iqtibos `[1]` havola emas."""
    assert assistant.answer_text("**Qalin** [1] va [sahifa](https://a.uz/p?x=1&y=2)") == \
        "*Qalin* [1] va <https://a.uz/p?x=1&amp;y=2|sahifa>"
    assert assistant.answer_text("[yomon](javascript:alert(1))") == "[yomon](javascript:alert(1))"
    assert assistant.answer_text("a < b") == "a &lt; b"
