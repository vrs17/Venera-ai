"""Slack ilovasi (`app/slack/meeting.py`): transkriptdan keyingi imkoniyatlar - yozuv chati (chatning
o'zidagi savol - oxirgi yozuv bo'yicha, thread'dagisi - o'sha yozuv bo'yicha; suhbat xotirasi, har Slack
odamining suhbati alohida, «🔄 Yangi suhbat»), vazifalar, eksport, boshqa
tilda qayta o'girish, bayonnoma (til menyusi, Word va PDF; chatda - yozishdan oldingi ko'rsatma va tayyor
hujjatni o'zgartirish).

Hammasi soxta (`slack_fakes.py`, `meetings_fakes.py`): tarmoq ham, pul ham yo'q.
"""

from __future__ import annotations

import json

import pytest

from app.core.config import settings
from app.schemas import meetings as schemas
from app.services.meetings import llm, prompts, service
from app.services.meetings.chat import CANNED
from app.slack import home, meeting, render, transcribe
from slack_fakes import (AUDIO, BOT_USER, FakeSlack, as_parent, card, choose_language, drive, elements, question_of,
                         send_audio, setup, shown)
from meetings_fakes import CHAT_ACTION_ANSWER, FakeAnthropic, chat_reply, gapi_segments, run_all


@pytest.fixture
def delivered(users_file, monkeypatch, _isolated_meetings):
    """Audio o'girilgan: (Slack, yig'ilish id, "Qisqa xulosa" xabari)."""
    setup(monkeypatch, users_file)
    client = FakeSlack(files={"F1": AUDIO})
    meeting.handle(client, "D1", None, [AUDIO], sleep=drive(_isolated_meetings))
    summary = card(client)
    client.updated.clear()          # jarayon xabarining tahrirlari (`intake.Progress`) - bu testlar mavzusi emas
    return client, render.marked(summary), summary


def _click(client, element, value, rt, *, selected=False):
    action = {"action_id": element, **({"selected_option": {"value": value}} if selected else {"value": value})}
    meeting.on_action(client, {"actions": [action], "channel": {"id": "D1"}, "message": {}}, sleep=drive(rt))


def _ask(client, thread, text="Kim hisobot yuboradi?"):
    event = {"channel_type": "im", "channel": "D1", "user": "U1", "text": text, "ts": "200.1", "thread_ts": thread}
    assert meeting.wants(event)
    meeting.on_message(client, event, bot_user=BOT_USER)


def test_slack_yozuvi_manbasi_bazada(delivered, _isolated_meetings):
    """Plaud filtri (2026-11-11): Slack yozuvi `channel=api` - manba alohida ustunda, shuning uchun
    odam nomini o'zgartirsa ham "Slack" filtrida qoladi."""
    _, mid, _ = delivered
    store = _isolated_meetings.store
    row = store.meeting_any(mid)
    assert row["origin"] == "slack"
    store.update_meeting(mid, title="Kredit bo'yicha qo'ng'iroq")
    rows, total = store.list_meetings(row["actor_id"], limit=10, offset=0, origin="slack")
    assert total == 1 and rows[0]["id"] == mid and rows[0]["effective_origin"] == "slack"


def _press(client, rt, action, message):
    meeting.on_action(client, {"actions": [action], "channel": {"id": "D1"}, "message": message,
                               "user": {"id": "U1"}}, sleep=drive(rt))


def test_transkript_tugmasi_fayl_kartaning_threadiga(delivered, _isolated_meetings):
    """Ega talabi (2026-11-11): transkript chatda yo'q - tugma .txt faylni kartaning THREAD'iga yuboradi
    (asosiy chat toza qoladi), bosgan odamga fayl qayerdaligi aytiladi (faqat unga ko'rinadi)."""
    client, mid, summary = delivered
    posted = len(client.posted)
    _press(client, _isolated_meetings, {"action_id": "barno_transcript", "value": mid}, {"ts": summary["ts"]})

    [sent] = client.uploaded
    assert (sent["channel"], sent["thread_ts"]) == ("D1", summary["ts"]) and sent["filename"].endswith(".txt")
    assert "Assalomu alaykum".encode() in sent["file"] and b"[00:00:00]" in sent["file"]
    assert len(client.posted) == posted                     # asosiy chatga hech narsa yozilmadi
    assert client.ephemeral == [{"channel": "D1", "user": "U1", "text": render.TRANSCRIPT_SENT}]

    # Karta o'zi thread ichida - fayl o'sha thread'ga (ichma-ich thread yo'q), izoh shart emas.
    _press(client, _isolated_meetings, {"action_id": "barno_transcript", "value": mid},
           {"ts": "300.1", "thread_ts": "111.222"})
    assert client.uploaded[-1]["thread_ts"] == "111.222" and len(client.ephemeral) == 1

    # Eski kartadagi "Eksport -> Transkript (TXT)" ham shu yo'ldan.
    _press(client, _isolated_meetings, {"action_id": "barno_export", "selected_option": {"value": f"{mid}|transcript_txt"}},
           {"ts": summary["ts"]})
    assert client.uploaded[-1]["thread_ts"] == summary["ts"] and len(client.posted) == posted


def test_juda_qisqa_yozuv_matni_kartaning_ozida(users_file, monkeypatch, _isolated_meetings):
    """Xulosa yozilmagan juda qisqa yozuv: bitta gapni faylga solib bo'lmaydi - kartaning o'zida."""
    setup(monkeypatch, users_file, seconds=5.0)
    _isolated_meetings.gapi.result = {**_isolated_meetings.gapi.result, "audio_seconds": 5.0,
                                      "segments": gapi_segments([(0, 0.0, 4.5, "Ertaga soat o'nda uchrashamiz.")])}
    client = FakeSlack(files={"F1": AUDIO})
    meeting.handle(client, "D1", None, [AUDIO], sleep=drive(_isolated_meetings))

    [summary] = client.visible()
    text = shown(summary)
    assert "Xulosa yozilmadi: Yozuv juda qisqa - xulosa yozilmadi." in text
    assert "*Matn:* Ertaga soat o'nda uchrashamiz." in text
    assert elements(summary)[0]["action_id"] == "barno_download"


def test_yuklab_olish_menyusi_transkript_fayllari(delivered, _isolated_meetings):
    """«📥 Yuklab olish» (ega tartibi 2026-11-12): Transkript (TXT) - kartaning thread'iga (asosiy chat toza), bosgan
    odamga izoh; Transkript (SRT) - fayl (eksport yo'li)."""
    client, mid, summary = delivered
    posted = len(client.posted)
    _press(client, _isolated_meetings, {"action_id": "barno_download",
                                        "selected_option": {"value": f"{mid}|transcript_txt"}}, {"ts": summary["ts"]})
    [sent] = client.uploaded
    assert (sent["thread_ts"], sent["filename"][-4:]) == (summary["ts"], ".txt") and len(client.posted) == posted
    assert client.ephemeral == [{"channel": "D1", "user": "U1", "text": render.TRANSCRIPT_SENT}]

    _press(client, _isolated_meetings, {"action_id": "barno_download",
                                        "selected_option": {"value": f"{mid}|transcript_srt"}}, {"ts": summary["ts"]})
    srt = client.uploaded[-1]
    assert srt["filename"].endswith(".srt") and b"-->" in srt["file"]


def test_xulosa_xabari_ostidagi_savolga_javob(delivered):
    client, mid, summary = delivered
    client.parents[summary["ts"]] = as_parent(summary)
    before = len(client.posted)
    _ask(client, summary["ts"])

    placeholder = client.posted[before]
    assert placeholder["thread_ts"] == summary["ts"] and placeholder["text"].startswith("⏳")
    [update] = client.updated
    assert update["ts"] == placeholder["ts"]
    assert "*Manbalar:*" in update["text"] and "• Kim?" in update["text"]
    # Javob bloklarda (matni o'sha), oxirida - «🔄 Yangi suhbat»: `block_id` yig'ilish belgisi `chat` tegi bilan.
    assert "*Manbalar:*" in shown(update)
    actions = update["blocks"][-1]
    assert actions["type"] == "actions" and actions["block_id"] == render.mark(mid, "chat")
    [button] = actions["elements"]
    assert (button["action_id"], button["value"], button["text"]["text"]) == ("barno_chat_reset", mid,
                                                                              "🔄 Yangi suhbat")


def test_audio_xabari_ostidagi_savolga_javob(delivered):
    client, _, _ = delivered
    client.parents["50.1"] = {"user": "U1", "ts": "50.1", "files": [AUDIO]}
    _ask(client, "50.1")

    assert "*Manbalar:*" in client.updated[0]["text"]


def test_begona_threadda_va_begona_bot_xabarida_jim(delivered):
    client, _, summary = delivered
    client.parents["60.1"] = {"user": "U1", "ts": "60.1", "text": "boshqa gap"}
    client.parents["70.1"] = {**summary, "bot_id": "B9", "user": "UOTHER"}
    before = len(client.posted)
    _ask(client, "60.1")
    _ask(client, "70.1")

    assert len(client.posted) == before and client.updated == []
    assert not meeting.wants({"channel_type": "im", "channel": "D1", "text": "salom", "ts": "1.1"})


# --- 💬 yozuv chati: suhbat xotirasi va «🔄 Yangi suhbat» -----------------------------------------


@pytest.fixture
def claude(_isolated_meetings, monkeypatch):
    """Prod'dagidek: chat zanjiri faqat Claude (`MEETINGS_ASK_CHAIN=claude`), klient - `FakeAnthropic`."""
    monkeypatch.setattr(settings, "meetings_ask_chain", "claude", raising=False)
    fake = FakeAnthropic()
    _isolated_meetings.ask_claude = llm.ClaudeChat(lambda: "sk-ant-test-SLACK", "claude-sonnet-5-5", timeout=10,
                                                   client_factory=fake, fallbacks=True)
    return fake


def _thread(delivered):
    """Savollar "Qisqa xulosa" kartasining thread'ida (karta - thread boshida, bot yozgan)."""
    client, mid, summary = delivered
    client.parents[summary["ts"]] = as_parent(summary)
    return client, mid, summary["ts"]


def test_kartadagi_eslatma_chat_haqida(delivered):
    """Eslatma - chatga yozilgan savol shu (oxirgi) yozuv bo'yicha, oldingilari - o'z xabarining thread'ida."""
    _, _, summary = delivered
    assert render.CHAT_HINT in shown(summary) and "eslab qoladi" in render.CHAT_HINT
    assert "shu chatga yozing" in render.CHAT_HINT and "thread'ida so'rang" in render.CHAT_HINT
    assert "Savol bo'lsa, shu xabarga thread'da yozing." not in shown(summary)


def test_savol_chatga_slack_kanali_bilan_yoziladi(delivered, _isolated_meetings):
    """Thread'dagi savol - yozuv chatining navbati: kanal `slack`, so'rovchi `slack:<user id>` (umumiy hisobda har odam
    alohida), javob bergan model va javob tili saqlanadi; hisob egasining suhbatiga (ilova, `/questions`) tushmaydi."""
    client, mid, thread = _thread(delivered)
    _ask(client, thread, "Hisobotni kim yuboradi?")

    store = _isolated_meetings.store
    [turn] = store.chat_turns(mid, asker="slack:U1")
    assert (turn["question"], turn["channel"], turn["language"], turn["asker"]) == (
        "Hisobotni kim yuboradi?", "slack", "uz", "slack:U1")
    assert turn["model"] == _isolated_meetings.ask_llm.model          # default zanjir (testda FakeLLM)
    assert store.chat_turns(mid) == [] and store.questions(mid) == []


def test_davom_savoli_claudega_xotira_bilan(delivered, claude, _isolated_meetings):
    """Ikkinchi savol: Claude so'rovida birinchi savol-javob - suhbat xotirasi (user/assistant navbatlari)."""
    client, mid, thread = _thread(delivered)
    _ask(client, thread, "Hisobotni kim yuboradi?")
    _ask(client, thread, "Batafsilroq?")

    one, two = claude.chats()
    assert [m["role"] for m in one["messages"]] == ["user"]
    assert [m["role"] for m in two["messages"]] == ["user", "assistant", "user"]
    assert two["messages"][0]["content"] == prompts.chat_question("Hisobotni kim yuboradi?", "uz")
    assert json.loads(two["messages"][1]["content"])["answer"] == "[S1] hisobotni ertaga yuboradi."
    assert two["messages"][2]["content"] == prompts.chat_question("Batafsilroq?", "uz")
    assert [(t["channel"], t["model"]) for t in _isolated_meetings.store.chat_turns(mid, asker="slack:U1")] == [
        ("slack", "claude-sonnet-5-5")] * 2
    assert all(u["blocks"][-1]["block_id"] == render.mark(mid, "chat") for u in client.updated)


def test_yangi_suhbat_tugmasi_xotirani_tozalaydi(delivered, claude, _isolated_meetings):
    """«🔄 Yangi suhbat»: bosgan odamning faol savol-javoblari arxivga (yumshoq), tasdiq o'sha thread'da, keyingi
    savol xotirasiz."""
    client, mid, thread = _thread(delivered)
    _ask(client, thread, "Hisobotni kim yuboradi?")
    answer = client.updated[-1]
    [button] = answer["blocks"][-1]["elements"]
    # Tugma javob xabarida, ya'ni thread ichida - tasdiq o'sha thread'ga.
    _press(client, _isolated_meetings, button, {"ts": answer["ts"], "thread_ts": thread})

    reset = client.posted[-1]
    assert (reset["text"], reset["thread_ts"]) == (render.CHAT_RESET_DONE, thread)
    store = _isolated_meetings.store
    assert store.chat_turns(mid, asker="slack:U1") == []
    # Yumshoq: savol-javob bazada qoladi (arxivda).
    assert store.row("SELECT COUNT(*) AS n FROM questions WHERE meeting_id=? AND archived_at IS NOT NULL",
                     (mid,))["n"] == 1
    _ask(client, thread, "Batafsilroq?")
    assert [m["role"] for m in claude.chats()[-1]["messages"]] == ["user"]     # yangi suhbat - xotirasiz
    assert [t["question"] for t in store.chat_turns(mid, asker="slack:U1")] == ["Batafsilroq?"]


def test_javob_xatosida_yangi_suhbat_tugmasi_yoq(delivered, monkeypatch):
    """Chegara (429) - sabab "⏳" o'rnida, tugmasiz: javob yo'q."""
    client, mid, thread = _thread(delivered)
    monkeypatch.setattr(settings, "meetings_ask_per_hour", 1, raising=False)
    _ask(client, thread, "Birinchi?")
    _ask(client, thread, "Ikkinchi?")

    answered, limited = client.updated
    assert answered["blocks"][-1]["block_id"] == render.mark(mid, "chat")
    assert limited["text"] == "Javob berib bo'lmadi: So'rovlar ko'p - birozdan keyin qayta urinib ko'ring"
    assert elements(limited) == []


def test_uzun_javob_tugmasi_oxirgi_xabarda():
    """`replace` bloklar bilan: `render.MESSAGE_BLOCKS` tadan bo'linadi, «🔄 Yangi suhbat» - oxirgi xabarda."""
    client = FakeSlack()
    mid = "a" * 32
    blocks = render.sections("\n".join(["x" * 2000] * 50)) + [render.chat_actions(mid)]
    meeting.replace(client, "D1", "100.0", "50.1", "javob", blocks)

    [first] = client.updated
    assert first["ts"] == "100.0" and len(first["blocks"]) == render.MESSAGE_BLOCKS
    [rest] = client.posted
    assert rest["thread_ts"] == "50.1" and len(rest["blocks"]) == 50 - render.MESSAGE_BLOCKS + 1
    assert rest["blocks"][-1] == render.chat_actions(mid) and render.marked(rest) == mid


# --- umumiy hisob: har Slack odamining suhbati o'ziniki ---------------------------------------------------------

#: Ikkinchi audio fayl - boshqa yig'ilish.
AUDIO2 = {**AUDIO, "id": "F2", "name": "ikkinchi.m4a",
          "url_private_download": "https://files.slack.com/files-pri/T1-F2/download/ikkinchi.m4a"}


def _send(client, rt, file=AUDIO, *, channel="D1", user="U1"):
    """Odam o'z chatiga audio yuboradi (yoki oldin yuborilgan faylni ulashadi) - Bolt yo'li (`wants` ->
    `on_message`), navbat qo'lda. Qaytaradi: yig'ilish id ("Qisqa xulosa" kartasi o'sha chatda)."""
    event = client.say(channel, files=[file], user=user)
    assert meeting.wants(event)
    send_audio(client, event, rt, user=user)
    summary = card(client)
    assert summary["channel"] == channel and "thread_ts" not in summary
    client.parents[summary["ts"]] = as_parent(summary)
    return render.marked(summary)


def _reply(client, thread, text, *, channel="D1", user="U1"):
    """Yozuv xabarining thread'idagi savol."""
    event = client.say(channel, text, user=user, thread=thread)
    assert meeting.wants(event)
    meeting.on_message(client, event, bot_user=BOT_USER)


def _reset(client, rt, answer, *, user="U1"):
    """«🔄 Yangi suhbat» - javob xabari ostidagi tugmani `user` bosdi."""
    [button] = elements(answer)
    message = {"ts": answer["ts"], **({"thread_ts": answer["thread_ts"]} if answer.get("thread_ts") else {})}
    meeting.on_action(client, {"actions": [button], "channel": {"id": answer["channel"]}, "user": {"id": user},
                               "message": message}, sleep=drive(rt))


def _dump(request) -> str:
    return json.dumps(request, ensure_ascii=False)


def test_ikki_odam_bitta_faylda_alohida_suhbat(users_file, monkeypatch, _isolated_meetings, claude):
    """Slack'dagi hamma odam bitta hisobda: A (U1) yuborgan faylni B (U2) o'z chatiga ulashsa - bitta yig'ilish, lekin
    suhbat har kimniki: B ning so'rovida A ning savoli yo'q, A ning «batafsilroq»i o'z savoliga bog'lanadi; B ning
    «🔄 Yangi suhbat»i faqat B nikini tozalaydi."""
    setup(monkeypatch, users_file)
    rt = _isolated_meetings
    client = FakeSlack(files={"F1": AUDIO})
    mid = _send(client, rt, channel="D1", user="U1")
    card_a = client.parents[card(client)["ts"]]
    assert _send(client, rt, channel="D2", user="U2") == mid           # bitta fayl - bitta yig'ilish
    card_b = client.parents[card(client)["ts"]]

    _reply(client, card_a["ts"], "A-SAVOL: kim qaysi vazifani oldi?", channel="D1", user="U1")
    _reply(client, card_b["ts"], "B-SAVOL: budjet qancha?", channel="D2", user="U2")
    answer_b = client.updated[-1]
    _reply(client, card_a["ts"], "Batafsilroq", channel="D1", user="U1")
    _, to_b, follow = claude.chats()
    assert len(to_b["messages"]) == 1 and "A-SAVOL" not in _dump(to_b)
    assert [m["role"] for m in follow["messages"]] == ["user", "assistant", "user"]
    assert "A-SAVOL" in follow["messages"][0]["content"] and "B-SAVOL" not in _dump(follow)

    _reset(client, rt, {**answer_b, "thread_ts": card_b["ts"]}, user="U2")
    done = client.posted[-1]
    assert (done["channel"], done["thread_ts"], done["text"]) == ("D2", card_b["ts"], render.CHAT_RESET_DONE)
    store = rt.store
    assert store.chat_turns(mid, asker="slack:U2") == []
    assert [t["question"] for t in store.chat_turns(mid, asker="slack:U1")] == [
        "A-SAVOL: kim qaysi vazifani oldi?", "Batafsilroq"]
    _reply(client, card_a["ts"], "Yana?", channel="D1", user="U1")
    assert len(claude.chats()[-1]["messages"]) == 5                    # A ning ikki navbati xotirada
    assert store.chat_turns(mid) == []                                 # hisob egasining suhbati bo'sh


def test_egasining_ilovadagi_suhbati_slack_odamiga_bormaydi(delivered, claude, _isolated_meetings, client, auth):
    """Slack hisobining egasi ilovada (`POST /chat`) va Slack odami bitta yozuv haqida so'rasa: egasining savoli
    Slack odamining so'roviga bormaydi va aksincha; ilovadagi chat (`GET /chat`) - faqat egasiniki."""
    slack, mid, thread = _thread(delivered)
    url = f"/api/v1/meetings/{mid}/chat"
    own = client.post(url, headers=auth, json={"message": "EGA-MAXFIY: bonus kimga?", "channel": "mobile"})
    assert own.status_code == 200, own.text
    _ask(slack, thread, "Oldin qanday savollar berilgan?")
    to_slack = claude.chats()[-1]
    assert len(to_slack["messages"]) == 1 and "EGA-MAXFIY" not in _dump(to_slack)

    follow = client.post(url, headers=auth, json={"message": "Batafsilroq?", "channel": "mobile"})
    assert follow.status_code == 200, follow.text
    back = claude.chats()[-1]
    assert [m["role"] for m in back["messages"]] == ["user", "assistant", "user"]
    assert "EGA-MAXFIY" in back["messages"][0]["content"] and "Oldin qanday savollar" not in _dump(back)
    items = client.get(url, headers=auth).json()["items"]
    assert [t["id"] for t in items] == [own.json()["id"], follow.json()["id"]]


# --- 💬 chatning o'zidagi savol - oxirgi yozuv bo'yicha (ega tasdig'i 2026-11-11, "variant A") ------------------


def _top(client, text="Hisobotni kim yuboradi?", *, channel="D1", user="U1"):
    """Chatning o'ziga (thread'siz) yozilgan savol - dispetcher yo'li: `home.is_text` -> navbatda `meeting.on_text`."""
    event = client.say(channel, text, user=user)
    assert home.is_text(event) and not meeting.wants(event)
    meeting.on_text(client, event, bot_user=BOT_USER)


def test_chatdagi_savol_oxirgi_yozuv_boyicha_xotira_bilan(users_file, monkeypatch, _isolated_meetings, claude):
    """Chatning o'ziga yozilgan savol - chatdagi OXIRGI yozuv bo'yicha. Javob ham chatda (thread'siz): boshida qaysi
    yozuv, ostida yig'ilish belgili «🔄 Yangi suhbat» - karta tarixdan chiqib ketsa ham keyingi savol shu yozuvga,
    suhbat xotirasi bilan."""
    setup(monkeypatch, users_file)
    rt = _isolated_meetings
    client = FakeSlack(files={"F1": AUDIO})
    mid = _send(client, rt)
    _top(client, "Hisobotni kim yuboradi?")

    holder, answer = client.posted[-1], client.updated[-1]
    assert holder["text"] == "⏳ Javob tayyorlanmoqda…" and "thread_ts" not in holder
    assert answer["ts"] == holder["ts"] and answer["channel"] == "D1"
    assert answer["text"].startswith("📼 «Slack: ovoz.aac» bo'yicha:\n")
    assert shown(answer).startswith("📼 «Slack: ovoz.aac» bo'yicha:\n") and "*Manbalar:*" in shown(answer)
    assert answer["blocks"][-1] == render.chat_actions(mid)
    assert client.history_reads[-1] == {"channel": "D1", "limit": 50}
    [turn] = rt.store.chat_turns(mid, asker="slack:U1")
    assert (turn["question"], turn["channel"]) == ("Hisobotni kim yuboradi?", "slack")

    # Tarixda faqat oxirgi 3 xabar (savol, javob, oldingi savol) - kartaga yetmaydi, yozuvni javobdagi belgi beradi.
    monkeypatch.setattr(meeting, "HISTORY", 3)
    _top(client, "Batafsilroq?")
    one, two = claude.chats()
    assert [m["role"] for m in one["messages"]] == ["user"]
    assert [m["role"] for m in two["messages"]] == ["user", "assistant", "user"]
    assert two["messages"][0]["content"] == prompts.chat_question("Hisobotni kim yuboradi?", "uz")
    assert client.updated[-1]["text"].startswith("📼 «Slack: ovoz.aac» bo'yicha:\n")
    assert [t["question"] for t in rt.store.chat_turns(mid, asker="slack:U1")] == [
        "Hisobotni kim yuboradi?", "Batafsilroq?"]
    assert rt.store.chat_turns(mid) == []                              # hisob egasining suhbatiga tushmaydi


def test_yangi_yozuv_kelsa_savollar_unga_otadi_eskisi_threadda(users_file, monkeypatch, _isolated_meetings, claude):
    """Yangi audio yuborilsa chatdagi savollar YANGI yozuvga o'tadi (o'z suhbati, xotirasiz); eski yozuv haqida - o'sha
    yozuv kartasining thread'ida: shu odamning o'sha yozuv bo'yicha suhbati davom etadi."""
    setup(monkeypatch, users_file)
    rt = _isolated_meetings
    client = FakeSlack(files={"F1": AUDIO, "F2": AUDIO2})
    first = _send(client, rt)
    old_card = card(client)
    _top(client, "Birinchi yozuvda kim gapirdi?")
    second = _send(client, rt, AUDIO2)
    assert second != first
    _top(client, "Hisobotni kim yuboradi?")

    answer = client.updated[-1]
    assert answer["text"].startswith("📼 «Slack: ikkinchi.m4a» bo'yicha:\n") and render.marked(answer) == second
    assert [m["role"] for m in claude.chats()[-1]["messages"]] == ["user"]
    assert "Birinchi yozuvda" not in _dump(claude.chats()[-1])
    assert [t["question"] for t in rt.store.chat_turns(second, asker="slack:U1")] == ["Hisobotni kim yuboradi?"]

    _reply(client, old_card["ts"], "Batafsilroq?")
    assert client.posted[-1]["thread_ts"] == old_card["ts"]
    reply = client.updated[-1]
    assert render.marked(reply) == first and not reply["text"].startswith("📼")
    assert [m["role"] for m in claude.chats()[-1]["messages"]] == ["user", "assistant", "user"]
    assert [t["question"] for t in rt.store.chat_turns(first, asker="slack:U1")] == [
        "Birinchi yozuvda kim gapirdi?", "Batafsilroq?"]
    # Thread'dagi javob chat tarixida yo'q - chatdagi keyingi savol baribir oxirgi yozuvga.
    _top(client, "Muddat qachon?")
    assert render.marked(client.updated[-1]) == second


def test_eski_kartadagi_bayonnoma_chatdagi_savolni_burmaydi(users_file, monkeypatch, _isolated_meetings, claude):
    """Eski yozuv kartasidagi «📄 Bayonnoma»: til menyusi chatga (thread'siz) tushadi va yig'ilish belgisini olib yuradi
    (`minutes` tegi), lekin u "oxirgi yozuv" emas (`render.LATEST_TAGS` - xulosa kartasi, chat javobi va tayyor
    bayonnoma natijasi; menyuning o'zi emas): chatdagi savol baribir eng yangi yozuv bo'yicha."""
    setup(monkeypatch, users_file)
    rt = _isolated_meetings
    client = FakeSlack(files={"F1": AUDIO, "F2": AUDIO2})
    first = _send(client, rt)
    old_card = card(client)
    second = _send(client, rt, AUDIO2)
    _press(client, rt, {"action_id": "barno_minutes", "value": first}, {"ts": old_card["ts"]})
    menu = client.posted[-1]
    assert menu["text"] == render.MINUTES_PROMPT and "thread_ts" not in menu and render.marked(menu) == first
    assert render.marked(menu, tags=render.LATEST_TAGS) is None

    _top(client, "Asosiy qarorlar nima edi?")
    answer = client.updated[-1]
    assert answer["text"].startswith("📼 «Slack: ikkinchi.m4a» bo'yicha:\n") and render.marked(answer) == second
    assert [t["question"] for t in rt.store.chat_turns(second, asker="slack:U1")] == ["Asosiy qarorlar nima edi?"]
    assert rt.store.chat_turns(first, asker="slack:U1") == []


def test_oxirgi_audio_hali_tayyorlanmoqda(users_file, monkeypatch, _isolated_meetings, claude):
    """Oxirgi audio hali matnga o'girilmoqda - yig'ilishi hali yo'q (Slack'dan yuklanmoqda) yoki bor, lekin matni tayyor
    emas (qayta o'girish ham): "tayyorlanmoqda" (thread'siz), model chaqirilmaydi, eski yozuvga ham javob berilmaydi.
    O'girilgach (karta hali chiqmagan bo'lsa ham) - o'sha yozuv bo'yicha javob; o'girib bo'lmagan bo'lsa -
    "tayyorlanmoqda" emas (abadiy osilib qolardi): savol oldingi yozuvga."""
    setup(monkeypatch, users_file)
    rt = _isolated_meetings
    client = FakeSlack(files={"F1": AUDIO, "F2": AUDIO2})
    first = _send(client, rt)
    client.say("D1", files=[AUDIO2])                                   # yangi audio - hali navbatda
    _top(client)
    pending = client.posted[-1]
    assert pending["text"] == render.CHAT_PENDING and "thread_ts" not in pending
    assert claude.chats() == [] and rt.store.chat_turns(first, asker="slack:U1") == []

    user = transcribe.account()
    second = transcribe.ingest(client, user, AUDIO2)                   # yuklandi, hali o'girilmagan
    _top(client)
    assert client.posted[-1]["text"] == render.CHAT_PENDING and claude.chats() == []

    run_all(rt)                                                        # o'girildi, karta esa hali chatda yo'q
    _top(client)
    answer = client.updated[-1]
    assert answer["text"].startswith("📼 «Slack: ikkinchi.m4a» bo'yicha:\n") and render.marked(answer) == second
    assert [t["question"] for t in rt.store.chat_turns(second, asker="slack:U1")] == ["Hisobotni kim yuboradi?"]

    # Qayta o'girilmoqda: oxirgi javobning yozuvi bor, matni esa hali yo'q - yana "tayyorlanmoqda".
    service.retranscribe(user, second, schemas.RetranscribeRequest(language="uz", confirmCharge=True))
    _top(client)
    assert client.posted[-1]["text"] == render.CHAT_PENDING and len(claude.chats()) == 1

    rt.store.update_meeting(second, status="failed", error_code="stt_timeout")
    posted = len(client.posted)
    _top(client)
    answer = client.updated[-1]
    assert answer["text"].startswith("📼 «Slack: ovoz.aac» bo'yicha:\n") and render.marked(answer) == first
    assert render.CHAT_PENDING not in [m["text"] for m in client.posted[posted:]] and len(claude.chats()) == 2


#: Uchinchi audio fayl - "oldingi yozuvi yo'q" chat uchun.
AUDIO3 = {**AUDIO, "id": "F3", "name": "uchinchi.mp3",
          "url_private_download": "https://files.slack.com/files-pri/T1-F3/download/uchinchi.mp3"}


def _daily_limit(monkeypatch):
    """Kunlik transkripsiya limiti tugagan (hisob umumiy): yig'ilish yaratiladi, `waiting_quota` da o'chiriladi."""
    monkeypatch.setattr(settings, "meetings_user_daily_minutes", 0, raising=False)


def _not_audio(monkeypatch):
    """Slack bergan fayl audio emas: yig'ilish umuman yaratilmaydi."""
    def download(url, dest, limit):
        dest.write_bytes(b"NOTAUDIO" * 100)
        return 800, "0" * 64, b"NOTAUDIO"

    monkeypatch.setattr(transcribe, "download", download)


@pytest.mark.parametrize(("breaks", "reason"), [(_daily_limit, "limiti tugagan"),
                                                (_not_audio, "formati qo'llab-quvvatlanmaydi")])
def test_oxirgi_audio_otmasa_savol_oldingi_yozuvga(users_file, monkeypatch, _isolated_meetings, claude, breaks, reason):
    """Yangi audioni o'girib bo'lmadi (kunlik limit tugagan yoki format yaroqsiz) - yig'ilishi yo'q: xato xabari faylni
    belgilaydi (`render.fail_mark`), chatdagi savol esa "tayyorlanmoqda" da abadiy osilib qolmaydi - oldingi yozuv
    bo'yicha javob, uning suhbati davom etadi. Oldingi yozuv yo'q bo'lsa - «🎙 Plaud» yo'riqnomasi."""
    setup(monkeypatch, users_file)
    monkeypatch.setattr(home, "_hint_at", {})
    rt = _isolated_meetings
    client = FakeSlack(files={"F1": AUDIO, "F2": AUDIO2, "F3": AUDIO3})
    first = _send(client, rt)
    _top(client, "Hisobotni kim yuboradi?")

    breaks(monkeypatch)
    send_audio(client, client.say("D1", files=[AUDIO2]), rt)
    failure = client.visible()[-1]
    assert failure["text"].startswith("Matnga o'girib bo'lmadi: ") and reason in failure["text"]
    assert render.fail_marked(failure) == "F2" and render.marked(failure) is None
    assert transcribe.meeting_of_file(transcribe.account(), "F2") is None

    posted = len(client.posted)
    for text in ("Batafsilroq?", "Muddat qachon?"):
        _top(client, text)
        answer = client.updated[-1]
        assert answer["text"].startswith("📼 «Slack: ovoz.aac» bo'yicha:\n") and render.marked(answer) == first
    assert render.CHAT_PENDING not in [m["text"] for m in client.posted[posted:]]
    assert [m["role"] for m in claude.chats()[-1]["messages"]] == ["user", "assistant"] * 2 + ["user"]

    # Boshqa odamning chatida bu birinchi audio edi - oldingi yozuv yo'q: yo'riqnoma (chatga `TEXT_EVERY` da bir marta).
    send_audio(client, client.say("D2", files=[AUDIO3], user="U2"), rt, user="U2")
    assert render.fail_marked(client.visible()[-1]) == "F3"
    posted = len(client.posted)
    _top(client, "Qarorlar?", channel="D2", user="U2")
    _top(client, "Javob bormi?", channel="D2", user="U2")
    assert [m["text"] for m in client.posted[posted:]] == [home.PROMPT] and len(claude.chats()) == 3


def test_eski_audio_yigilishsiz_otkaziladi(users_file, monkeypatch, _isolated_meetings, claude):
    """Yig'ilishi yo'q audio `AUDIO_PENDING_SEC` dan eski (xato xabari o'chirilgan yoki server restartida yozilmay
    qolgan) - yo'lda emas: savol oldingi yozuvga. Yuklanishi yarim qolgan (`uploading`) yig'ilish ham: eski audioda -
    o'tkaziladi, yangisida - hali yo'lda, "tayyorlanmoqda"."""
    setup(monkeypatch, users_file)
    rt = _isolated_meetings
    client = FakeSlack(files={"F1": AUDIO, "F2": AUDIO2})
    old = meeting.AUDIO_PENDING_SEC + 60
    first = _send(client, rt)
    client.say("D1", files=[AUDIO2], ago=old)
    _top(client)
    answer = client.updated[-1]
    assert answer["text"].startswith("📼 «Slack: ovoz.aac» bo'yicha:\n") and render.marked(answer) == first

    second = transcribe.ingest(client, transcribe.account(), AUDIO2)
    rt.store.update_meeting(second, status="uploading")                # yuklash yarim qolgan (server restarti)
    assert _send(client, rt, channel="D2", user="U2") == first         # oldingi yozuv - o'sha fayl
    client.say("D2", files=[AUDIO2], user="U2", ago=old)
    _top(client, channel="D2", user="U2")
    answer = client.updated[-1]
    assert answer["channel"] == "D2" and render.marked(answer) == first
    assert _send(client, rt, channel="D3", user="U3") == first
    client.say("D3", files=[AUDIO2], user="U3")
    _top(client, channel="D3", user="U3")
    assert (client.posted[-1]["channel"], client.posted[-1]["text"]) == ("D3", render.CHAT_PENDING)
    assert len(claude.chats()) == 2


def test_tili_tanlanmagan_audio_chatdagi_savolga_avval_tilni_tanlang(users_file, monkeypatch, _isolated_meetings,
                                                                    claude):
    """Yangi audioning tili hali tanlanmagan (til savoli javobsiz): chatdagi savolga «avval tilni tanlang» (thread'siz),
    model chaqirilmaydi va eski yozuvga ham javob berilmaydi. Til tanlangach - savollar yangi yozuvga."""
    setup(monkeypatch, users_file)
    rt = _isolated_meetings
    client = FakeSlack(files={"F1": AUDIO, "F2": AUDIO2})
    first = _send(client, rt)
    meeting.acknowledge(client, client.say("D1", files=[AUDIO2]))
    _top(client)
    asked = client.posted[-1]
    assert asked["text"] == render.CHAT_CHOOSE_LANG and "thread_ts" not in asked
    assert claude.chats() == [] and rt.store.chat_turns(first, asker="slack:U1") == []

    choose_language(client, question_of(client, "F2"), "uz", rt)
    second = render.marked(card(client))
    assert second != first
    _top(client, "Muddat qachon?")
    answer = client.updated[-1]
    assert answer["text"].startswith("📼 «Slack: ikkinchi.m4a» bo'yicha:\n") and render.marked(answer) == second


def test_ochirilgan_yozuv_otkaziladi(users_file, monkeypatch, _isolated_meetings, claude):
    """Oxirgi yozuv o'chirilgan (hisob egasi ilovada o'chirdi): uning kartasi va chat javobi belgisi yo'q yig'ilishni
    ko'rsatadi - xato emas, o'tkaziladi (eski audiosi ham), savol oldingi yozuv bo'yicha."""
    setup(monkeypatch, users_file)
    rt = _isolated_meetings
    client = FakeSlack(files={"F1": AUDIO, "F2": AUDIO2})
    first = _send(client, rt)
    event = client.say("D1", files=[AUDIO2], ago=meeting.AUDIO_PENDING_SEC + 60)
    send_audio(client, event, rt)
    second = render.marked(card(client))
    _top(client, "Hisobotni kim yuboradi?")
    assert render.marked(client.updated[-1]) == second != first

    service.delete(transcribe.account(), second)
    _top(client, "Muddat qachon?")
    answer = client.updated[-1]
    assert answer["text"].startswith("📼 «Slack: ovoz.aac» bo'yicha:\n") and render.marked(answer) == first
    assert [t["question"] for t in rt.store.chat_turns(first, asker="slack:U1")] == ["Muddat qachon?"]


def test_chatda_yozuv_yoq_yoriqnoma(monkeypatch):
    """Chatda yozuv yo'q (begona botning belgili xabari hisob emas) - avvalgidek «🎙 Plaud» yo'riqnomasi, chatga
    `TEXT_EVERY` da bir marta. Tarix o'qilmasa - yo'riqnoma emas, har savolga qisqa sabab. Slack hisobi kerak emas
    (bu testda sozlanmagan)."""
    monkeypatch.setattr(home, "_hint_at", {})
    client = FakeSlack()
    client.timeline[("D1", "1.1")] = {"type": "message", "bot_id": "B9", "user": "UOTHER", "ts": "1.1", "text": "x",
                                      "blocks": [render.chat_actions("a" * 32)]}
    _top(client, "Salom")
    _top(client, "Yana salom")
    [hint] = client.posted
    assert hint["text"] == home.PROMPT and "thread_ts" not in hint and client.updated == []
    assert len(client.history_reads) == 2

    broken = FakeSlack()
    broken.history_error = RuntimeError("tarmoq")
    _top(broken, "Salom", channel="D2")
    _top(broken, "Yana salom", channel="D2")
    assert [m["text"] for m in broken.posted] == [render.CHAT_UNREAD] * 2


def test_chat_tarixi_oqilmasa_har_savolga_qisqa_sabab(users_file, monkeypatch, _isolated_meetings, claude):
    """Chat tarixini o'qib bo'lmadi (Slack istisnosi yoki `ok: false`), odamning esa yozuvi bor: «🎙 Plaud» yo'riqnomasi
    yolg'on bo'lardi (va chatga 10 daqiqada bir marta - ikkinchi savol javobsiz qolardi) - har savolga qisqa sabab
    (thread'siz), model chaqirilmaydi. Tarix tiklangach - odatdagidek oxirgi yozuv bo'yicha."""
    setup(monkeypatch, users_file)
    monkeypatch.setattr(home, "_hint_at", {})
    rt = _isolated_meetings
    client = FakeSlack(files={"F1": AUDIO})
    mid = _send(client, rt)
    posted, updated = len(client.posted), len(client.updated)
    client.history_error = RuntimeError("ratelimited")
    _top(client, "Kim hisobot yuboradi?")
    _top(client, "Javob bering iltimos")
    client.history_error = {"ok": False, "error": "ratelimited"}
    _top(client, "Yana?")
    sent = client.posted[posted:]
    assert [m["text"] for m in sent] == [render.CHAT_UNREAD] * 3 and not any("thread_ts" in m for m in sent)
    assert "thread'ida" in render.CHAT_UNREAD and claude.chats() == [] and len(client.updated) == updated

    client.history_error = None
    _top(client, "Kim hisobot yuboradi?")
    assert render.marked(client.updated[-1]) == mid and len(claude.chats()) == 1


def test_chatdagi_savol_xatolari_tugmasiz(users_file, monkeypatch, _isolated_meetings):
    """Xato - thread'dagi savoldagidek: sabab "⏳" o'rnida, tugmasiz (javob yo'q, yozuv belgisi ham); hisob
    sozlanmagan bo'lsa - sabab chatga."""
    setup(monkeypatch, users_file)
    client = FakeSlack(files={"F1": AUDIO})
    _send(client, _isolated_meetings)
    monkeypatch.setattr(settings, "meetings_ask_per_hour", 1, raising=False)
    _top(client, "Birinchi?")
    _top(client, "Ikkinchi?")

    answered, limited = client.updated[-2:]
    assert answered["text"].startswith("📼 «Slack: ovoz.aac» bo'yicha:\n")
    assert limited["text"] == "Javob berib bo'lmadi: So'rovlar ko'p - birozdan keyin qayta urinib ko'ring"
    assert elements(limited) == [] and render.marked(limited) is None
    monkeypatch.setattr(settings, "slack_actor_id", "", raising=False)
    _top(client, "Uchinchi?")
    assert client.posted[-1]["text"] == "Javob berib bo'lmadi: Slack uchun Venera hisobi sozlanmagan (SLACK_ACTOR_ID)."


def test_chatdagi_savol_va_yangi_suhbat_har_odamniki(users_file, monkeypatch, _isolated_meetings, claude):
    """Bitta faylni ikki kishi o'z chatiga yuborgan (bitta yig'ilish): chatdagi savollarda ham har kimning xotirasi
    o'ziniki. Chatdagi javob ostidagi «🔄 Yangi suhbat» - tasdiq chatning o'ziga (thread'siz), faqat bosganniki
    tozalanadi; tasdiq xabari belgisiz - keyingi savol o'sha yozuvga, xotirasiz."""
    setup(monkeypatch, users_file)
    rt = _isolated_meetings
    client = FakeSlack(files={"F1": AUDIO})
    mid = _send(client, rt, channel="D1", user="U1")
    assert _send(client, rt, channel="D2", user="U2") == mid
    _top(client, "A-SAVOL: kim qaysi vazifani oldi?", channel="D1", user="U1")
    _top(client, "B-SAVOL: budjet qancha?", channel="D2", user="U2")
    answer_b = client.updated[-1]
    _top(client, "Batafsilroq", channel="D1", user="U1")
    _, to_b, follow = claude.chats()
    assert len(to_b["messages"]) == 1 and "A-SAVOL" not in _dump(to_b)
    assert "A-SAVOL" in follow["messages"][0]["content"] and "B-SAVOL" not in _dump(follow)

    _reset(client, rt, answer_b, user="U2")
    done = client.posted[-1]
    assert (done["channel"], done["text"], "thread_ts" in done) == ("D2", render.CHAT_RESET_DONE, False)
    assert rt.store.chat_turns(mid, asker="slack:U2") == []
    assert len(rt.store.chat_turns(mid, asker="slack:U1")) == 2
    _top(client, "Yana?", channel="D2", user="U2")
    assert render.marked(client.updated[-1]) == mid
    assert [m["role"] for m in claude.chats()[-1]["messages"]] == ["user"]


def test_dispetcher_chatdagi_matn_navbatda_bir_marta(monkeypatch):
    """Bolt ipi: chatdagi matn navbatga BIR marta (`meeting.on_text`; yo'riqnoma ham o'sha yerdan - ikki marta emas)
    va Slack'ka murojaatsiz (tarix navbatda o'qiladi). Bot xabari, `subtype` li xabar (tahrir, bot_message) bu yo'lga
    tushmaydi; thread'dagi matn - savol (`meeting.on_message`). Ikkalasiga ham restartda uziladigan kutish
    (`_sleep`): chat xabari bayonnoma ishini boshlasa, vazifa uni kutadi (`meeting._follow_minutes`)."""
    from types import SimpleNamespace

    from app import slack as slack_app
    from app.slack import keep

    jobs = []
    monkeypatch.setattr(slack_app, "_pool", SimpleNamespace(submit=lambda fn, *a, **k: jobs.append((fn, k))))
    client = FakeSlack()
    event = {"type": "message", "channel_type": "im", "channel": "D1", "user": "U1", "ts": "5.1", "text": "Kim?"}
    slack_app._on_message(event, client, {"bot_user_id": BOT_USER})
    assert [(fn, k) for fn, k in jobs if fn is not keep.record] == [
        (meeting.on_text, {"bot_user": BOT_USER, "sleep": slack_app._sleep})]
    assert client.posted == [] and client.history_reads == []

    for extra in ({"bot_id": "B1"}, {"subtype": "message_changed"}, {"subtype": "bot_message", "bot_id": "B1"}):
        jobs.clear()
        slack_app._on_message({**event, **extra}, client, {"bot_user_id": BOT_USER})
        assert [fn for fn, _ in jobs if fn is not keep.record] == [], extra
    jobs.clear()
    slack_app._on_message({**event, "thread_ts": "4.1"}, client, {"bot_user_id": BOT_USER})
    assert [(fn, k) for fn, k in jobs if fn is not keep.record] == [
        (meeting.on_message, {"bot_user": BOT_USER, "sleep": slack_app._sleep})]
    assert client.posted == [] and client.history_reads == []


def test_vazifalar_tugmasi(delivered, _isolated_meetings):
    client, mid, _ = delivered
    _click(client, "barno_tasks", mid, _isolated_meetings)

    assert client.posted[-1]["text"].startswith("*Vazifalar*\n")


def test_shablon_menyusi_yoq_eski_kartadagisi_ochirilgan(delivered, _isolated_meetings):
    """Ega qarori (2026-11-12): «Boshqa shablon bilan xulosa» hozirgi bosqichda kerak emas - yangi kartada menyu
    yo'q, eski kartadagi menyu bosilsa izoh chiqadi va YANGI XULOSA YOZILMAYDI (model chaqirilmaydi)."""
    client, mid, summary = delivered
    assert "barno_template" not in [e["action_id"] for e in elements(summary)]
    before = len(_isolated_meetings.store.summaries(mid))
    _click(client, "barno_template", f"{mid}|minutes", _isolated_meetings, selected=True)

    assert client.posted[-1]["text"] == render.TEMPLATE_OFF
    assert not client.updated
    assert len(_isolated_meetings.store.summaries(mid)) == before


def test_eksport_transkript_va_hisobot(delivered, _isolated_meetings):
    client, mid, _ = delivered
    _click(client, "barno_export", f"{mid}|transcript_txt", _isolated_meetings, selected=True)
    _click(client, "barno_export", f"{mid}|report_docx", _isolated_meetings, selected=True)

    txt, docx = client.uploaded
    assert txt["filename"].endswith(".txt") and "Assalomu alaykum".encode() in txt["file"]
    assert docx["filename"].endswith(".docx") and docx["file"][:2] == b"PK"
    assert all(u["channel"] == "D1" and "thread_ts" not in u for u in client.uploaded)


def test_eksport_ruxsat_yoq(delivered, _isolated_meetings):
    from slack_sdk.errors import SlackApiError

    client, mid, _ = delivered
    client.upload_error = SlackApiError("missing_scope", {"ok": False, "error": "missing_scope"})
    _click(client, "barno_export", f"{mid}|transcript_srt", _isolated_meetings, selected=True)

    assert "files:write" in client.posted[-1]["text"]


def test_eski_kartadagi_boshqa_tilda_qayta_ogirish(delivered, _isolated_meetings):
    """2026-11-12 dan til audio yuklanganda so'raladi - yangi kartada qayta o'girish tugmasi yo'q, lekin ESKI
    kartalardagi tugma ishlayveradi."""
    client, mid, _ = delivered
    before = len(client.posted)
    _click(client, "barno_relang_ru", f"{mid}|ru", _isolated_meetings)

    assert client.posted[before]["text"].startswith("⏳ Audio rus tilida")
    assert client.updated[-1]["text"] == "✅ Audio rus tilida qayta o'girildi."
    # Rus tili - Router orqali (yig'ilish quvurining o'z qoidasi), yangi transkript chatga.
    assert [c["language"] for c in _isolated_meetings.router.calls] == ["ru"]
    assert "Добрый день" in shown(client.posted[before + 1])
    ids = [e["action_id"] for e in elements(card(client))]
    assert not any(i.startswith("barno_relang") for i in ids)


# --- 📄 Bayonnoma --------------------------------------------------------------------------------


def _fake_view(**extra):
    view = {"id": "ab" * 16, "meetingId": "m", "language": "uz-cyrl", "status": "ready", "stale": False,
            "agendaCount": 2, "sectionCount": 2, "itemCount": 5,
            "notes": ["Muddat <aniq> emas", "Mas'ul aytilmagan"], "warnings": [], "error": None}
    view.update(extra)
    return view


def _fake_export(fail_fmt: str | None = None):
    from app.services.meetings import export

    calls = []

    def export_file(user, meeting_id, minutes_id, fmt):
        calls.append((meeting_id, minutes_id, fmt))
        if fmt == fail_fmt:
            raise meeting.MeetingProblem(409, "not_ready", "Bayonnoma hali tayyor emas")
        media, ext = minutes.FORMATS[fmt]
        return fmt.encode(), media, export.content_disposition(*export.file_names("Баённома - Haftalik", 1762150000, ext))

    return export_file, calls


from app.services.meetings import minutes  # noqa: E402 - bayonnoma testlari uchun


def test_bayonnoma_tugmasi_kartada(delivered):
    _, mid, summary = delivered
    ids = [e["action_id"] for e in elements(summary)]
    assert ids[:3] == ["barno_download", "barno_tasks", "barno_minutes"]
    assert [e for e in elements(summary) if e["action_id"] == "barno_minutes"][0]["value"] == mid


def test_bayonnoma_til_menyusi(delivered, _isolated_meetings):
    client, mid, _ = delivered
    _click(client, "barno_minutes", mid, _isolated_meetings)

    menu = client.posted[-1]
    assert menu["text"] == render.MINUTES_PROMPT and menu["channel"] == "D1"
    buttons = elements(menu)
    # Har tugmaning o'z id si - Slack bitta blokda takror `action_id` ni rad etadi.
    assert [b["action_id"] for b in buttons] == [f"barno_minutes_lang_{lang}" for lang in
                                                 ["uz-cyrl", "uz-latn", "ru", "en"]]
    assert sorted(b["value"] for b in buttons) == sorted(f"{mid}|{lang}" for lang in minutes.LANGS)
    # O'zbek yig'ilish -> tavsiya kirill: birinchi va `primary`; qolganlarida uslub yo'q.
    assert buttons[0]["value"] == f"{mid}|uz-cyrl" and buttons[0]["style"] == "primary"
    assert buttons[0]["text"]["text"] == minutes.LANG_TITLES["uz-cyrl"]
    assert all("style" not in b for b in buttons[1:])
    actions = [b for b in menu["blocks"] if b["type"] == "actions"][0]
    assert actions["block_id"] == render.mark(mid, "minutes") and render.marked(menu) == mid


def test_bayonnoma_tanlangan_tilda_word_va_pdf(delivered, _isolated_meetings, monkeypatch):
    client, mid, _ = delivered
    generated = []

    def generate(user, meeting_id, lang, **kwargs):
        generated.append((meeting_id, lang))
        return _fake_view(warnings=["ungrounded_name:Karimov", "script_mismatch"])

    export_file, exported = _fake_export()
    monkeypatch.setattr(minutes, "generate", generate)
    monkeypatch.setattr(minutes, "export_file", export_file)
    before = len(client.posted)
    _click(client, "barno_minutes_lang", f"{mid}|uz-cyrl", _isolated_meetings)

    holder = client.posted[before]
    assert holder["text"] == f"⏳ Bayonnoma ({minutes.LANG_TITLES['uz-cyrl']}) tayyorlanmoqda… 1-3 daqiqa."
    assert generated == [(mid, "uz-cyrl")]
    assert exported == [(mid, "ab" * 16, "docx"), (mid, "ab" * 16, "pdf")]
    docx, pdf = client.uploaded
    assert docx["file"] == b"docx" and docx["filename"].endswith(".docx")
    assert pdf["file"] == b"pdf" and pdf["filename"].endswith(".pdf")
    # Nom `Content-Disposition` dagi haqiqiy (`filename*=`) nom - kirill sarlavha bilan.
    assert docx["filename"].startswith("Баённома - Haftalik") and docx["title"] == docx["filename"]
    assert all(u["channel"] == "D1" and "thread_ts" not in u for u in client.uploaded)
    [update] = client.updated
    assert update["ts"] == holder["ts"]
    text = update["text"]
    assert text.startswith(f"✅ *Bayonnoma tayyor* ({minutes.LANG_TITLES['uz-cyrl']}): 2 bo'lim, 5 band.")
    assert "«________»" in text
    assert "*Aniqlashtirish kerak:*\n• Muddat &lt;aniq&gt; emas\n• Mas'ul aytilmagan" in text
    assert "Transkriptda bo'lmagan ismlar «________» bilan almashtirildi: Karimov" in text
    assert "kirill/lotin" in text
    assert len(client.posted) == before + 1


def test_bayonnoma_thread_ichida(delivered, _isolated_meetings, monkeypatch):
    client, mid, summary = delivered
    export_file, _ = _fake_export()
    monkeypatch.setattr(minutes, "generate", lambda *a, **k: _fake_view(notes=[]))
    monkeypatch.setattr(minutes, "export_file", export_file)
    body = {"actions": [{"action_id": "barno_minutes_lang", "value": f"{mid}|en"}],
            "channel": {"id": "D1"}, "message": {"thread_ts": summary["ts"]}}
    meeting.on_action(client, body, sleep=drive(_isolated_meetings))

    assert client.posted[-1]["thread_ts"] == summary["ts"]
    assert all(u["thread_ts"] == summary["ts"] for u in client.uploaded)
    assert "Aniqlashtirish" not in client.updated[-1]["text"]
    assert client.updated[-1]["text"].startswith("✅ *Bayonnoma tayyor* (English)")


def test_bayonnoma_notogri_til_jim(delivered, _isolated_meetings, monkeypatch):
    client, mid, _ = delivered
    monkeypatch.setattr(minutes, "generate", lambda *a, **k: pytest.fail("model chaqirilmasligi kerak"))
    before = len(client.posted)
    _click(client, "barno_minutes_lang", f"{mid}|de", _isolated_meetings)

    assert len(client.posted) == before and client.updated == [] and client.uploaded == []


def test_bayonnoma_yozilmadi(delivered, _isolated_meetings, monkeypatch):
    client, mid, _ = delivered

    def generate(user, meeting_id, lang, **kwargs):
        raise meeting.MeetingProblem(503, "llm_not_configured",
                                     "Bayonnoma uchun model sozlanmagan (CLAUDE_API_KEY <...>)")

    monkeypatch.setattr(minutes, "generate", generate)
    _click(client, "barno_minutes_lang", f"{mid}|ru", _isolated_meetings)

    assert client.posted[-1]["text"].startswith("⏳ Bayonnoma (Русский)")
    [update] = client.updated
    assert update["text"] == "Bayonnoma yozilmadi: Bayonnoma uchun model sozlanmagan (CLAUDE_API_KEY &lt;...&gt;)"
    assert client.uploaded == []
    # Xato xabarida yig'ilish belgisi (`doc:ru`): uning thread'idagi javob shu yozuv chatiga boradi ("jim" emas).
    assert render.marked_tag(update) == (mid, "doc:ru")


def test_bayonnoma_fayl_ruxsati_yoq(delivered, _isolated_meetings, monkeypatch):
    from slack_sdk.errors import SlackApiError

    client, mid, _ = delivered
    export_file, exported = _fake_export()
    monkeypatch.setattr(minutes, "generate", lambda *a, **k: _fake_view())
    monkeypatch.setattr(minutes, "export_file", export_file)
    client.upload_error = SlackApiError("missing_scope", {"ok": False, "error": "missing_scope"})
    _click(client, "barno_minutes_lang", f"{mid}|uz-latn", _isolated_meetings)

    # Yo'riqnoma "⏳" o'rniga (odam kutib qolmasin); ikkinchi fayl urinilmaydi.
    [update] = client.updated
    assert "files:write" in update["text"] and update["ts"] == client.posted[-1]["ts"]
    assert [fmt for *_, fmt in exported] == ["docx"] and client.uploaded == []


def test_bayonnoma_sozlanmagan_model_haqiqiy_quvurda(delivered, _isolated_meetings):
    """Soxtasiz: testda Claude kaliti bo'sh (`_claude_key_off`) - xizmat 503 beradi, Slack esa
    sababni "⏳" o'rniga yozadi."""
    client, mid, _ = delivered
    _click(client, "barno_minutes_lang", f"{mid}|uz-cyrl", _isolated_meetings)

    assert client.updated[-1]["text"].startswith("Bayonnoma yozilmadi: ")
    assert "CLAUDE_API_KEY" in client.updated[-1]["text"] and client.uploaded == []


# TODO(bayonnoma): 2026-11-04 holatida `minutes/render.py` hali stub (`NotImplementedError`) - shu
# test faqat shu sababdan yiqiladi (Slack qismi `test_bayonnoma_tanlangan_tilda_word_va_pdf` da yashil).
def test_bayonnoma_haqiqiy_quvur_fakellm(delivered, _isolated_meetings, monkeypatch):
    """Oxirigacha: `MEETINGS_MINUTES_CHAIN=ollama` -> `rt.llm` (FakeLLM, `auto_reply` op
    `meeting_minutes`) -> validate -> compose -> render -> Word va PDF fayllar Slack'ga.

    E'TIBOR: `minutes/compose.py` va `minutes/render.py` boshqa agentlar tomonidan parallel
    yozilmoqda - ular hali `NotImplementedError` bersa bu test o'sha sabab bilan yiqiladi
    (Slack qismi emas). Modullar tayyor bo'lgach test o'z-o'zidan yashil bo'lishi kerak."""
    from app.core.config import settings

    client, mid, _ = delivered
    monkeypatch.setattr(settings, "meetings_minutes_chain", "ollama", raising=False)
    _click(client, "barno_minutes_lang", f"{mid}|uz-cyrl", _isolated_meetings)

    assert [c["op"] for c in _isolated_meetings.llm.calls if c["op"] == "meeting_minutes"] == ["meeting_minutes"]
    docx, pdf = client.uploaded
    assert docx["filename"].endswith(".docx") and docx["file"][:2] == b"PK"
    assert pdf["filename"].endswith(".pdf") and pdf["file"][:5] == b"%PDF-"
    assert client.updated[-1]["text"].startswith("✅ *Bayonnoma tayyor* (Ўзбек (кирилл))")
    # Ikkinchi bosish - tayyor hujjat qaytadi, model qayta chaqirilmaydi.
    _click(client, "barno_minutes_lang", f"{mid}|uz-cyrl", _isolated_meetings)
    assert len([c for c in _isolated_meetings.llm.calls if c["op"] == "meeting_minutes"]) == 1
    assert len(client.uploaded) == 4


# --- 📄 Bayonnoma chatda: ko'rsatma (yozishdan oldin) va o'zgartirish (yozilgandan keyin) ---------------------


@pytest.fixture
def minutes_chain(_isolated_meetings, monkeypatch):
    """Bayonnoma modeli - FakeLLM (`MEETINGS_MINUTES_CHAIN=ollama`; `auto_reply`: yangi hujjat - `minutes_reply`,
    tahrir - `revision_reply`: `TITLE=` / `NOOP` ...), chatdan boshlangan ish (`minutes.start` / `revise`) shu ipda
    (`minutes.runner`). Qaytaradi: runtime."""
    monkeypatch.setattr(settings, "meetings_minutes_chain", "ollama", raising=False)
    monkeypatch.setattr(minutes, "runner", lambda job: job())
    return _isolated_meetings


def _minutes_ops(rt) -> list[str]:
    """Bayonnoma model chaqiruvlari (FakeLLM): `meeting_minutes` - yangi hujjat, `meeting_minutes_revise` - tahrir."""
    return [c["op"] for c in rt.llm.calls if c["op"].startswith("meeting_minutes")]


def _language(client, rt, mid: str, lang: str, message: dict) -> dict:
    """Odam (U1) bayonnoma til menyusidagi tugmani bosdi (`message` - tugmali xabar) -> "⏳" o'rnidagi natija."""
    _press(client, rt, {"action_id": f"barno_minutes_lang_{lang}", "value": f"{mid}|{lang}"}, message)
    return client.updated[-1]


def _spy_chat(monkeypatch) -> list[dict]:
    """`service.chat_send` chaqiruvlari (yig'ilish, matn va kalit so'zli argumentlar); haqiqiysi ham chaqiriladi."""
    calls: list[dict] = []
    real = service.chat_send

    def chat_send(user, meeting_id, message, language, **kwargs):
        calls.append({"meeting": meeting_id, "message": message, **kwargs})
        return real(user, meeting_id, message, language, **kwargs)

    monkeypatch.setattr(service, "chat_send", chat_send)
    return calls


def test_bayonnoma_chatda_eslatmalar_va_belgilar():
    """Odam bayonnomani chatda boshqarishini qayerdan biladi: kartadagi eslatma, «🎙 Plaud» yo'riqnomasi, menyu va
    natija ostidagi eslatma. Belgilar: natija (`doc:<til>`) chatdagi keyingi matnni oladi (`LATEST_TAGS`), menyu
    (`minutes`) - yo'q."""
    assert render.LATEST_TAGS == ("", "chat", "doc:uz-latn", "doc:uz-cyrl", "doc:ru", "doc:en")
    assert "📄 Bayonnoma uchun ko'rsatma va tayyor bayonnomadagi o'zgartirishlarni" in render.CHAT_HINT
    assert home.PROMPT.index("yangi versiyasini yuboradi") < home.PROMPT.index("Oldingi yozuv haqida")
    assert "bayonnoma ko'rsatmalarini" in render.CHAT_RESET_DONE and "saqlanib qoladi" in render.CHAT_RESET_DONE
    assert render.CHAT_PENDING.endswith("yoki bayonnoma uchun ko'rsatma yozing.")
    mid = "a" * 32
    hint = render.minutes_hint(mid, "ru")
    assert hint == {"type": "context", "block_id": f"barno:{mid}:doc:ru",
                    "elements": [{"type": "mrkdwn", "text": render.MINUTES_EDIT_HINT}]}
    assert render.marked_tag({"blocks": [{"type": "section"}, hint]}) == (mid, "doc:ru")
    assert render.marked_tag({"blocks": render.minutes_menu(mid, "uz-cyrl")}) == (mid, "minutes")
    assert render.marked_tag({"blocks": render.minutes_menu(mid, "uz-cyrl")}, tags=render.LATEST_TAGS) is None
    assert (render.doc_lang("doc:ru"), render.doc_lang("doc:de"), render.doc_lang("chat"), render.doc_lang(None)) == (
        "ru", None, None, None)

    # Chat javobi ostidagi qator: ko'rsatma - eslab qolindi (jami nechta); ish boshlanmagan - sababi; boshlangan ish
    # (yiqilgan bo'lsa ham) - bo'sh: natija alohida xabarda.
    assert render.minutes_turn_note(None) == ""
    assert render.minutes_turn_note({"action": "note", "notes": 3}) == "\n\n" + render.MINUTES_NOTE_SAVED.format(n=3)
    assert render.minutes_turn_note({"action": "note", "notes": None}) == "\n\n" + render.MINUTES_NOTE_SAVED.format(n=1)
    assert "(jami 1 ta)" in render.MINUTES_NOTE_SAVED.format(n=1)
    error = {"code": "rate_limited", "message": "So'rovlar <ko'p>"}
    assert render.minutes_turn_note({"action": "revise", "id": None, "error": error}) == (
        "\n\n⚠ Bayonnoma ishi boshlanmadi: So'rovlar &lt;ko'p&gt;")
    assert render.minutes_turn_note({"action": "revise", "id": "x" * 32, "error": error}) == ""
    assert render.minutes_turn_note({"action": "create", "id": "x" * 32, "error": None}) == ""


def test_natija_matni_versiya_ozgarish_va_ogohlantirishlar():
    """`render.minutes_result`: tahrir - "tahrirlandi (…, N-versiya)", so'rov (bir qator, escape) va o'zgarishlar;
    ko'rsatmalar qo'llangan tahrir - "yangilandi" (o'zgarishsiz bo'lsa shuni aytadi); ega aytgan sarlavha qiymatlari
    Word'dagi bo'sh joylar ro'yxatidan chiqadi; ko'rsatmali asl hujjat - nechtasi hisobga olingani; yangi
    ogohlantirishlar odam tilida. Yangi kalitlarsiz (eski ko'rinish) - matn avvalgidek."""
    none = {"changed": [], "added": [], "removed": []}
    unchanged = {"items": none, "agenda": none, "header": [], "other": []}
    base = _fake_view(notes=[], sectionCount=2, itemCount=3)
    edited = render.minutes_result({**base, "kind": "revise", "version": 3,
                                    "request": "3-bandda  muddat\n1-dekabr <tez>",
                                    "changes": {**unchanged, "items": {**none, "changed": [3], "added": [8]},
                                                "header": ["chair"]}}, "uz-latn")
    assert edited == ("✅ *Bayonnoma tahrirlandi* (O'zbek (lotin), 3-versiya): 2 bo'lim, 3 band. Loyiha - Word "
                      "faylidagi «________» joylarini to'ldiring (bank nomi, rais, qatnashuvchilar, №, sana).\n\n"
                      "So'rov: «3-bandda muddat 1-dekabr &lt;tez&gt;»\n\n"
                      "*O'zgarishlar:* 3-band o'zgardi; 8-band qo'shildi; rais yangilandi.")
    applied = render.minutes_result({**base, "kind": "revise", "version": 2, "changes": unchanged,
                                     "header": {"organization": "Bank", "chair": "A.Karimov"}}, "uz-cyrl")
    assert applied == ("✅ *Bayonnoma yangilandi* (Ўзбек (кирилл), 2-versiya): ko'rsatmalaringiz qo'llandi - 2 bo'lim, "
                       "3 band. Loyiha - Word faylidagi «________» joylarini to'ldiring (qatnashuvchilar, №, sana).\n\n"
                       "Ko'rsatmalar bayonnomada allaqachon aks etgan - matn o'zgarmadi.")
    fresh = render.minutes_result({**base, "kind": "generate", "version": 1, "notesApplied": 2,
                                   "header": {"organization": "Bank", "chair": "A.Karimov", "attendees": ["X"]},
                                   "warnings": ["header_dropped:city", "header_dropped:attendees",
                                                "header_dropped:city", "superseded_revisions:2",
                                                "guidance_truncated:3"]}, "ru")
    assert fresh.split("\n\n") == [
        "✅ *Bayonnoma tayyor* (Русский): 2 bo'lim, 3 band. Loyiha - Word faylidagi «________» joylarini to'ldiring "
        "(№, sana). Ko'rsatmalaringiz hisobga olindi (2 ta).",
        "Ko'rsatmada aniq aytilmagan sarlavha qiymatlari bo'sh qoldirildi: shahar, qatnashchilar.",
        "⚠ Matn tahrirlangani uchun bayonnoma yangidan yozildi - avvalgi 2 ta o'zgartirish kiritilmagan, kerak bo'lsa "
        "qayta yozing.",
        "⚠ Ko'rsatmalar juda ko'p - eng eskilaridan 3 tasi hisobga olinmadi."]
    assert render.minutes_result(base, "en") == (
        "✅ *Bayonnoma tayyor* (English): 2 bo'lim, 3 band. Loyiha - Word faylidagi «________» joylarini to'ldiring "
        "(bank nomi, rais, qatnashuvchilar, №, sana).")


def test_natija_doc_belgisi(delivered, _isolated_meetings, monkeypatch):
    """Bayonnoma natijasi ostida tahrir eslatmasi - `doc:<til>` belgili kontekst bloki: shu xabar thread'idagi va
    chatdagi keyingi matn o'sha til hujjati bo'yicha. Xabar matni (bildirishnoma) va xabarlar soni o'zgarmaydi."""
    client, mid, _ = delivered
    export_file, _ = _fake_export()
    monkeypatch.setattr(minutes, "generate", lambda *a, **k: _fake_view())
    monkeypatch.setattr(minutes, "export_file", export_file)
    before = len(client.posted)
    _click(client, "barno_minutes_lang", f"{mid}|uz-cyrl", _isolated_meetings)

    [update] = client.updated
    assert update["text"].startswith("✅ *Bayonnoma tayyor* (Ўзбек (кирилл)): 2 bo'lim, 5 band. Loyiha - ")
    assert update["blocks"][:-1] == render.sections(update["text"])
    assert update["blocks"][-1] == render.minutes_hint(mid, "uz-cyrl")
    assert render.marked_tag(update) == (mid, "doc:uz-cyrl") == render.marked_tag(update, tags=render.LATEST_TAGS)
    assert render.MINUTES_EDIT_HINT in shown(update) and len(client.posted) == before + 1


def test_natijadan_keyin_chatdagi_matn_shu_yozuvga(users_file, monkeypatch, _isolated_meetings, claude):
    """Eski yozuv kartasidan bayonnoma: til menyusi nomzod emas, lekin chatga tushgan NATIJA - nomzod (`doc:<til>`):
    keyingi chatdagi matn o'sha yozuvga va o'sha til hujjatiga (`minutes_lang`) - «3-bandni o'zgartir» shu hujjatning
    tahriri bo'ladi. Undan keyingi matn - oxirgi chat javobining yozuviga (hujjat tilini server o'zi tanlaydi)."""
    setup(monkeypatch, users_file)
    rt = _isolated_meetings
    client = FakeSlack(files={"F1": AUDIO, "F2": AUDIO2})
    first = _send(client, rt)
    old_card = card(client)
    second = _send(client, rt, AUDIO2)
    export_file, _ = _fake_export()
    monkeypatch.setattr(minutes, "generate", lambda *a, **k: _fake_view(language="ru"))
    monkeypatch.setattr(minutes, "export_file", export_file)
    sent = _spy_chat(monkeypatch)

    _press(client, rt, {"action_id": "barno_minutes", "value": first}, {"ts": old_card["ts"]})
    menu = client.posted[-1]
    _top(client, "Asosiy qarorlar nima edi?")
    assert (sent[-1]["meeting"], sent[-1]["minutes_lang"]) == (second, None)          # menyu - nomzod emas

    result = _language(client, rt, first, "ru", {"ts": menu["ts"]})
    assert "thread_ts" not in client.posted[-1] and render.marked_tag(result) == (first, "doc:ru")
    _top(client, "3-bandda muddat 1-dekabr bo'lsin")
    answer = client.updated[-1]
    assert answer["text"].startswith("📼 «Slack: ovoz.aac» bo'yicha:\n") and render.marked(answer) == first
    call = sent[-1]
    assert (call["meeting"], call["minutes_lang"], call["intent"], call["asker"], call["client_id"]) == (
        first, "ru", None, "slack:U1", None)
    _top(client, "Yana nima o'zgardi?")
    assert (sent[-1]["meeting"], sent[-1]["minutes_lang"]) == (first, None)


def test_natija_thread_tahrir_oxirigacha(delivered, claude, minutes_chain):
    """Oxirigacha (FakeLLM - pulsiz): ikki tilda hujjat; KIRILL natijaning thread'ida «o'zgartir» -> chat modeli
    tahrir deb tushunadi (til aytilmagan - natija belgisidan, `minutes_lang`; eng yangi rus hujjati emas) -> javob,
    "⏳ ... tahrirlanmoqda", yangi Word va PDF shu thread'da, "⏳" o'rnida "✅ Bayonnoma tahrirlandi (…, 2-versiya)"
    so'rov va o'zgarishlar bilan. O'zgarmagan so'rov - yangi versiya ham, fayl ham yo'q, sababi aytiladi."""
    client, mid, summary = delivered
    rt = minutes_chain
    cyrl = _language(client, rt, mid, "uz-cyrl", {"ts": summary["ts"]})
    assert cyrl["text"].startswith("✅ *Bayonnoma tayyor* (Ўзбек (кирилл)): 2 bo'lim, 3 band.")
    assert _language(client, rt, mid, "ru", {"ts": summary["ts"]})["text"].startswith("✅ *Bayonnoma tayyor* (Русский)")
    assert len(client.uploaded) == 4 and _minutes_ops(rt) == ["meeting_minutes"] * 2
    thread = client.thread_under(cyrl)

    posted, updated = len(client.posted), len(client.updated)
    claude.script = [chat_reply("revise", instruction="Sarlavhani «Yangi sarlavha» qilish")]
    _reply(client, thread, "TITLE=Yangi sarlavha")

    holder, waiting = client.posted[posted:]
    assert (holder["text"], holder["thread_ts"]) == ("⏳ Javob tayyorlanmoqda…", thread)
    assert (waiting["text"], waiting["thread_ts"]) == ("⏳ Bayonnoma (Ўзбек (кирилл)) tahrirlanmoqda… 1-3 daqiqa.",
                                                       thread)
    answer, done = client.updated[updated:]
    assert answer["ts"] == holder["ts"] and answer["text"].startswith(CHAT_ACTION_ANSWER)
    assert answer["blocks"][-1] == render.chat_actions(mid)
    docx, pdf = client.uploaded[4:]
    assert docx["thread_ts"] == pdf["thread_ts"] == thread
    assert "(2-таҳрир)" in docx["filename"] and docx["filename"].endswith(".docx") and pdf["filename"].endswith(".pdf")
    assert done["ts"] == waiting["ts"]
    assert done["text"].startswith("✅ *Bayonnoma tahrirlandi* (Ўзбек (кирилл), 2-versiya): 2 bo'lim, 3 band.")
    assert "\n\nSo'rov: «TITLE=Yangi sarlavha»\n\n*O'zgarishlar:* sarlavha o'zgardi." in done["text"]
    assert done["blocks"][-1] == render.minutes_hint(mid, "uz-cyrl")
    assert _minutes_ops(rt) == ["meeting_minutes"] * 2 + ["meeting_minutes_revise"]
    system = "\n".join(block["text"] for block in claude.chats()[-1]["system"])
    assert "the current document: Uzbek (Cyrillic) (uz-cyrl), version 1" in system
    cyrl_row, _, revision = rt.store.minutes_rows(mid)
    assert (revision["language"], revision["parent_id"], revision["revision"], revision["status"]) == (
        "uz-cyrl", cyrl_row["id"], 1, "ready")
    [turn] = rt.store.chat_turns(mid, asker="slack:U1")
    assert (turn["kind"], turn["minutes_id"]) == ("revise", revision["id"])

    # O'zgarishsiz so'rov (NOOP): yangi versiya ham, fayl ham yo'q - "⏳" o'rnida sababi.
    posted, uploaded = len(client.posted), len(client.uploaded)
    claude.script = [chat_reply("revise", instruction="Hech narsani o'zgartirmaslik")]
    _reply(client, thread, "NOOP")
    _, waiting = client.posted[posted:]
    failed = client.updated[-1]
    assert failed["ts"] == waiting["ts"] and len(client.uploaded) == uploaded
    # Xato xabarida ham yig'ilish belgisi (`doc:<til>`): uning thread'idagi javob (aniqroq so'rov) shu hujjatga boradi.
    assert render.marked_tag(failed) == (mid, "doc:uz-cyrl")
    assert failed["text"] == ("Bayonnoma tahrirlanmadi: Bayonnomada o'zgarish bo'lmadi - nimani o'zgartirish "
                              "kerakligini aniqroq yozing (masalan: «3-bandda muddat - 1-dekabr»)")


def test_menyu_threadi_korsatma(delivered, claude, minutes_chain):
    """Yozishdan OLDIN: til menyusining thread'idagi javob - bayonnoma uchun ko'rsatma (aniq kirish: chat modelisiz va
    bepul), javob ostida "eslab qolindi (jami n ta)". Keyin menyuda til tanlansa (menyu endi thread boshi - natija
    baribir chatning o'ziga) hujjat shu ko'rsatmalar bilan yoziladi: OWNER INSTRUCTIONS, rais sarlavhada - Word'dagi
    bo'sh joylar kamaydi."""
    client, mid, summary = delivered
    rt = minutes_chain
    _press(client, rt, {"action_id": "barno_minutes", "value": mid}, {"ts": summary["ts"]})
    menu = client.posted[-1]
    assert menu["text"] == render.MINUTES_PROMPT and "shu xabarga thread'da yozing" in render.MINUTES_PROMPT
    thread = client.thread_under(menu)
    _reply(client, thread, "CHAIR=Alisher Karimov")

    answer = client.updated[-1]
    assert claude.chats() == []                                          # aniq ko'rsatma - chat modelisiz
    assert answer["text"] == f"{CANNED['note']['uz']}\n\n{render.MINUTES_NOTE_SAVED.format(n=1)}"
    assert answer["blocks"][-1] == render.chat_actions(mid)
    [turn] = rt.store.chat_turns(mid, asker="slack:U1")
    assert (turn["kind"], turn["question"], turn["model"]) == ("note", "CHAIR=Alisher Karimov", None)
    _reply(client, thread, "Kredit masalalariga e'tibor bering")
    assert client.updated[-1]["text"].endswith(render.MINUTES_NOTE_SAVED.format(n=2)) and claude.chats() == []

    done = _language(client, rt, mid, "uz-cyrl", {"ts": menu["ts"], "thread_ts": menu["ts"]})
    [call] = [c for c in rt.llm.calls if c["op"] == "meeting_minutes"]
    assert "OWNER INSTRUCTIONS" in call["user"] and "1. CHAIR=Alisher Karimov" in call["user"]
    assert "2. Kredit masalalariga e'tibor bering" in call["user"]
    assert "thread_ts" not in client.posted[-1] and all("thread_ts" not in u for u in client.uploaded)
    assert done["text"].startswith(
        "✅ *Bayonnoma tayyor* (Ўзбек (кирилл)): 2 bo'lim, 3 band. Loyiha - Word faylidagi «________» joylarini "
        "to'ldiring (bank nomi, qatnashuvchilar, №, sana). Ko'rsatmalaringiz hisobga olindi (2 ta).")


def test_minutes_doc_asker(delivered, _isolated_meetings, monkeypatch):
    """Til tugmasi hujjatni BOSGAN odam nomidan so'raydi (`asker` - uning ko'rsatmalari qo'llanadi; umumiy hisobda
    `slack:<user id>`) va dispetcherning kutishi bilan (`sleep`). Kutish tugab ham hujjat yozilmoqda bo'lsa - fayl
    emas, "hali tayyorlanmoqda"."""
    client, mid, _ = delivered
    seen = []

    def generate(user, meeting_id, lang, **kwargs):
        seen.append(kwargs)
        return _fake_view(status="running")

    monkeypatch.setattr(minutes, "generate", generate)
    monkeypatch.setattr(minutes, "export_file", lambda *a, **k: pytest.fail("fayl yuborilmasligi kerak"))
    sleep = drive(_isolated_meetings)
    meeting.on_action(client, {"actions": [{"action_id": "barno_minutes_lang_ru", "value": f"{mid}|ru"}],
                               "channel": {"id": "D1"}, "user": {"id": "U1"}, "message": {}}, sleep=sleep)
    assert seen == [{"asker": "slack:U1", "sleep": sleep}]
    [update] = client.updated
    assert update["text"] == render.MINUTES_STILL_RUNNING and client.uploaded == []


def test_client_msg_id_takror(delivered, claude, minutes_chain):
    """Slack hodisani qayta yuborsa (o'sha `client_msg_id`): navbat ham, bayonnoma ishi ham bitta - chat modeli ham,
    bayonnoma modeli ham qayta chaqirilmaydi. Kalit Slack'niki; kalitsiz xabarda kalit yo'q (`ts` emas)."""
    client, mid, thread = _thread(delivered)
    rt = minutes_chain
    event = client.say("D1", "Bayonnomani tayyorla ACTION=create", thread=thread,
                       client_msg_id="9f1c2d3e-4b5a-6789-abcd-ef0123456789")
    meeting.on_message(client, event, bot_user=BOT_USER)
    meeting.on_message(client, dict(event), bot_user=BOT_USER)

    [turn] = rt.store.chat_turns(mid, asker="slack:U1")
    assert (turn["kind"], turn["client_id"]) == ("create", "slack-9f1c2d3e-4b5a-6789-abcd-ef0123456789")
    assert len(rt.store.minutes_rows(mid)) == 1 and _minutes_ops(rt) == ["meeting_minutes"]
    assert len(claude.chats()) == 1
    # Fayllar ham bir marta (Word + PDF): takror hodisa natijani qayta kuzatmaydi (`_first_follow`).
    assert len(client.uploaded) == 2
    assert meeting._client_id({"client_msg_id": "<a b>/" + "x" * 80}) == "slack-ab" + "x" * 56
    assert meeting._client_id({"ts": "1.2"}) is None and meeting._client_id({"client_msg_id": "@@"}) is None


def test_ish_boshlanmadi_ogohlantirish(delivered, claude, _isolated_meetings):
    """Chat modeli «tayyorla» dedi, lekin ish boshlanmadi (bayonnoma modeli sozlanmagan - testda Claude kaliti bo'sh):
    navbat saqlanadi, javob ostida sabab (`render.MINUTES_NOT_STARTED`); "⏳ Bayonnoma" ham, fayl ham yo'q."""
    client, mid, thread = _thread(delivered)
    claude.script = [chat_reply("create")]
    posted = len(client.posted)
    _ask(client, thread, "Bayonnomani tayyorlab ber")

    assert len(client.posted) == posted + 1 and client.uploaded == []
    [answer] = client.updated
    assert answer["text"].startswith(CANNED["not_started"]["uz"])
    assert "\n\n⚠ Bayonnoma ishi boshlanmadi: Bayonnoma uchun model sozlanmagan" in answer["text"]
    assert answer["blocks"][-1] == render.chat_actions(mid)
    [turn] = _isolated_meetings.store.chat_turns(mid, asker="slack:U1")
    assert turn["kind"] == "create" and turn["minutes_id"] is None


def test_chatdan_boshlangan_ish_kutiladi(delivered, claude, minutes_chain, monkeypatch):
    """Chatdan boshlangan ish fon ipida (navbat): javobdan keyin "⏳ Bayonnoma ... tayyorlanmoqda", ish kutiladi
    (`minutes.wait`; `sleep` navbatni yuritadi), so'ng fayllar va "⏳" o'rnida natija. Kutish tugab ham yozilmoqda
    bo'lsa - fayl emas, `render.MINUTES_STILL_RUNNING` (tayyori til tugmasidan bepul qayta yuboriladi)."""
    client, mid, thread = _thread(delivered)
    queue: list = []
    monkeypatch.setattr(minutes, "runner", queue.append)

    def drain(_sec: float) -> None:
        while queue:
            queue.pop(0)()

    posted = len(client.posted)
    meeting.on_message(client, client.say("D1", "Bayonnomani tayyorla ACTION=create", thread=thread),
                       bot_user=BOT_USER, sleep=drain)
    _, waiting = client.posted[posted:]
    assert (waiting["text"], waiting["thread_ts"]) == ("⏳ Bayonnoma (Ўзбек (кирилл)) tayyorlanmoqda… 1-3 daqiqa.",
                                                       thread)
    done = client.updated[-1]
    assert done["ts"] == waiting["ts"] and done["text"].startswith("✅ *Bayonnoma tayyor* (Ўзбек (кирилл))")
    assert len(client.uploaded) == 2 and queue == []

    real_wait = minutes.wait
    monkeypatch.setattr(minutes, "wait", lambda *a, **k: real_wait(*a, **{**k, "timeout": 6.0}))
    claude.script = [chat_reply("revise", instruction="Sarlavhani «Boshqa» qilish")]
    meeting.on_message(client, client.say("D1", "TITLE=Boshqa", thread=thread), bot_user=BOT_USER,
                       sleep=lambda _sec: None)
    assert client.posted[-1]["text"] == "⏳ Bayonnoma (Ўзбек (кирилл)) tahrirlanmoqda… 1-3 daqiqa."
    assert client.updated[-1]["text"] == render.MINUTES_STILL_RUNNING
    assert len(client.uploaded) == 2 and len(queue) == 1
