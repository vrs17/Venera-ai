"""Slack ilovasi (`app/slack/`): qaysi xabar audio deb olinadi va audio -> transkript va
"Qisqa xulosa" -> chat.

Slack ham, GAPI ham, model ham soxta (`slack_fakes.py`, `meetings_fakes.py`): hech bir test
tarmoqqa chiqmaydi. Fon ishchisi yo'q - kutish (`sleep`) o'rniga navbat qo'lda yuritiladi.
"""

from __future__ import annotations

import urllib.request

from pathlib import Path

import pytest

from app.core.config import settings
from app.slack import meeting, render, transcribe
from slack_fakes import AUDIO, FakeSlack, card, choose_language, drive, elements, question_of, setup, shown


@pytest.fixture
def slack(users_file, monkeypatch):
    return setup(monkeypatch, users_file)


def _meetings(rt):
    return rt.store.list_meetings(1, limit=10, offset=0)


def test_faqat_shaxsiy_xabardagi_audio_olinadi():
    dm = {"channel_type": "im", "subtype": "file_share", "files": [AUDIO, {"id": "F2", "mimetype": "image/png"}]}
    assert [f["id"] for f in transcribe.audio_files(dm)] == ["F1"]
    clip = {"id": "F3", "subtype": "slack_audio", "mimetype": "video/webm"}
    assert transcribe.audio_files({"channel_type": "im", "files": [clip]}) == [clip]
    assert transcribe.audio_files({**dm, "channel_type": "channel"}) == []
    assert transcribe.audio_files({**dm, "bot_id": "B1"}) == []
    assert transcribe.audio_files({**dm, "subtype": "message_changed"}) == []
    assert transcribe.audio_files({"channel_type": "im", "text": "salom"}) == []


def test_audio_chatda_faqat_qisqa_xulosa_transkript_tugmada(slack, _isolated_meetings):
    """Ega talabi (2026-11-11): transkript matni chatga YOZILMAYDI - uzun matn chatni tushunarsiz
    qilardi. Chatda faqat "Qisqa xulosa"; transkript - birinchi tugmada (fayl, `test_slack_meeting`)."""
    client = FakeSlack()
    meeting.handle(client, "D1", None, [AUDIO], sleep=drive(_isolated_meetings))

    assert slack == [AUDIO["url_private_download"]]
    rows, total = _meetings(_isolated_meetings)
    assert total == 1 and rows[0]["title"] == "Slack: ovoz.aac"
    mid = rows[0]["id"]
    assert all("thread_ts" not in m for m in client.posted)
    # Chatda natija qoladi - faqat "Qisqa xulosa"; jarayon xabari o'chirilgan.
    [summary] = client.visible()
    assert summary is card(client) and render.marked(summary) == mid
    assert not any("Assalomu alaykum" in shown(m) or "Assalomu alaykum" in m["text"] for m in client.posted)
    assert shown(summary).startswith("Qisqa xulosa\n*")
    # Ega tartibi (2026-11-12): «📥 Yuklab olish» (transkript), «✅ Vazifalar», «📄 Bayonnoma», «Eksport» (xulosa,
    # hisobot). Qayta o'girish tugmalari yo'q - til audio yuklanganda so'raladi; «Boshqa shablon bilan xulosa» ham
    # yo'q (ega qarori 2026-11-12).
    ids = [e["action_id"] for e in elements(summary)]
    assert ids == ["barno_download", "barno_tasks", "barno_minutes", "barno_export"]
    labels = [(e.get("placeholder") or e["text"])["text"] for e in elements(summary)]
    assert labels == ["📥 Yuklab olish", "✅ Vazifalar", "📄 Bayonnoma", "Eksport"]
    download, export = elements(summary)[0], elements(summary)[-1]
    assert [(o["text"]["text"], o["value"]) for o in download["options"]] == [
        ("Transkript (TXT)", f"{mid}|transcript_txt"), ("Transkript (SRT)", f"{mid}|transcript_srt")]
    assert [o["value"].split("|")[1] for o in export["options"]] == ["summary_md", "report_docx", "report_pdf"]
    assert elements(summary)[2]["value"] == mid


def test_jarayon_xabari_bosqichma_bosqich(slack, _isolated_meetings):
    """Ega talabi (2026-11-05): odam audio yuborgach nima bo'layotganini ko'rib turadi - "qabul
    qilindi" va bosqichlar BITTA xabarda joyida yangilanadi (2026-11-11 dan transkript chatda yo'q -
    "matn yuqorida" ham yo'q), natija chiqqach jarayon xabari o'chadi."""
    client = FakeSlack()
    meeting.handle(client, "D1", None, [AUDIO], sleep=drive(_isolated_meetings))

    status, summary = client.posted
    assert status["text"] == ("📎 «ovoz.aac» qabul qilindi. Til: o'zbek.\n\n⏳ Audio yuklanmoqda…\n◻️ Matnga o'girish\n"
                              "◻️ Qisqa xulosa\n\nNatija shu yerga keladi - odatda 1-3 daqiqada.")
    transcribing, waiting = client.updated
    assert transcribing["ts"] == waiting["ts"] == status["ts"]
    assert "\n\n✅ Audio yuklandi (1 daq 4 s)\n⏳ Matnga o'girilmoqda…\n◻️ Qisqa xulosa\n\n" in transcribing["text"]
    assert waiting["text"] == ("📎 «ovoz.aac» qabul qilindi. Til: o'zbek.\n\n✅ Audio yuklandi (1 daq 4 s)\n"
                               "✅ Matnga o'girildi\n⏳ Qisqa xulosa yozilmoqda…\n\n"
                               "Xulosa tayyor bo'lishi bilan shu yerga keladi.")
    assert summary is card(client)
    assert [d["ts"] for d in client.deleted] == [status["ts"]]


def test_dispetcher_avval_tilni_soraydi(slack, _isolated_meetings, monkeypatch):
    """Ega talabi (2026-11-12): audio kelishi bilan - DARHOL, Bolt ipida - "qabul qilindi" va «Audio qaysi tilda?»
    (har faylga o'z savoli). Til tanlanmaguncha hech narsa yuklanmaydi va navbatga ish qo'yilmaydi; tanlangach savol
    xabari joyida jarayon xabariga aylanadi, natija chiqqach o'chadi."""
    from types import SimpleNamespace

    from app import slack as slack_app

    jobs = []
    monkeypatch.setattr(slack_app, "_pool", SimpleNamespace(submit=lambda fn, *a, **k: jobs.append((fn, a, k))))
    second = {**AUDIO, "id": "F2", "name": "ikkinchi.m4a"}
    client = FakeSlack(files={"F1": AUDIO, "F2": second})
    event = {"channel_type": "im", "subtype": "file_share", "channel": "D1", "user": "U1", "ts": "5.1",
             "files": [AUDIO, second]}
    slack_app._on_message(event, client, {"bot_user_id": "UBOT"})

    first_q, second_q = client.posted
    assert first_q["text"] == "📎 «ovoz.aac» qabul qilindi.\n🌐 Audio qaysi tilda? Tanlang - shundan keyin matnga o'giraman."
    assert [b.get("block_id") for b in first_q["blocks"]] == [None, "barno-langs:F1"]
    assert second_q["blocks"][-1]["block_id"] == "barno-langs:F2"
    assert [(e["action_id"], e["text"]["text"], e["value"]) for e in elements(first_q)] == [
        ("barno_lang_uz", "🇺🇿 O'zbek", "F1"), ("barno_lang_ru", "🇷🇺 Rus", "F1"), ("barno_lang_en", "🇬🇧 Ingliz", "F1")]
    assert not [j for j in jobs if j[0] is meeting.on_message] and slack == [] and _meetings(_isolated_meetings)[1] == 0

    choose_language(client, first_q, "ru", _isolated_meetings)
    choose_language(client, second_q, "uz", _isolated_meetings)
    assert any(u["ts"] == first_q["ts"] and u["text"].startswith("📎 «ovoz.aac» qabul qilindi. Til: rus.\n\n")
               for u in client.updated)
    assert {first_q["ts"], second_q["ts"]} <= {d["ts"] for d in client.deleted}
    assert [m["text"] for m in client.visible()] == ["Qisqa xulosa", "Qisqa xulosa"]


def test_tanlangan_tilda_ogiriladi(slack, _isolated_meetings):
    """Tanlangan til yig'ilishga yoziladi va o'girish o'sha tilda (rus - Router orqali, quvurning o'z qoidasi)."""
    client = FakeSlack(files={"F1": AUDIO})
    meeting.acknowledge(client, client.say("D1", files=[AUDIO]))
    choose_language(client, question_of(client, "F1"), "ru", _isolated_meetings)

    [row] = _meetings(_isolated_meetings)[0]
    assert row["language"] == "ru"
    assert [c["language"] for c in _isolated_meetings.router.calls] == ["ru"]
    assert render.marked(card(client)) == row["id"] and client.visible() == [card(client)]


def test_til_tugmasi_takror_va_yaroqsiz_qiymat(slack, _isolated_meetings):
    """Tugma ikki marta (yoki ikkinchi til) bosilsa - audio hali ishlanayotgan bo'lsa ikkinchisi e'tiborsiz; noma'lum
    til yoki fayl id'si - jim."""
    client = FakeSlack(files={"F1": AUDIO})
    meeting.acknowledge(client, client.say("D1", files=[AUDIO]))
    question = question_of(client, "F1")
    meeting._started.add("F1")                                  # birinchi bosish hali ishlanyapti
    try:
        choose_language(client, question, "en", _isolated_meetings)
    finally:
        meeting._started.discard("F1")
    meeting.start(client, "D1", None, "F1", "de", ref=question["ts"])
    meeting.start(client, "D1", None, "../x", "uz", ref=question["ts"])
    assert slack == [] and client.updated == [] and _meetings(_isolated_meetings)[1] == 0


def test_thread_ichidagi_audio_javobi_osha_threadda(slack, _isolated_meetings):
    client = FakeSlack()
    meeting.handle(client, "D1", "111.222", [AUDIO], sleep=drive(_isolated_meetings))

    assert client.posted and all(m["thread_ts"] == "111.222" for m in client.posted)


def test_bir_fayl_bir_yigilish_gapi_qayta_tolanmaydi(slack, _isolated_meetings):
    client = FakeSlack()
    for _ in range(2):
        meeting.handle(client, "D1", None, [AUDIO], sleep=drive(_isolated_meetings))

    assert slack == [AUDIO["url_private_download"]]
    assert len(_isolated_meetings.gapi.submits) == 1
    assert _meetings(_isolated_meetings)[1] == 1
    assert sum(m["text"] == "Qisqa xulosa" for m in client.posted) == 2


def test_slack_ovozli_xabari_aac_nusxasidan_olinadi(slack, _isolated_meetings):
    clip = {"id": "F3", "subtype": "slack_audio", "mimetype": "audio/webm", "created": 1762150000,
            "url_private_download": "https://files.slack.com/files-pri/T1-F3/download/clip.webm",
            "aac": "https://files.slack.com/files-tmb/T1-F3-ab/clip.aac"}
    client = FakeSlack()
    meeting.handle(client, "D1", None, [clip], sleep=drive(_isolated_meetings))

    assert slack == [clip["aac"]]
    assert client.posted[0]["text"].startswith("🎙 Ovozli xabaringiz qabul qilindi. Til: o'zbek.\n\n⏳ Audio yuklanmoqda…")
    assert client.visible() == [card(client)]


def test_toliq_obyekt_files_info_dan(slack, _isolated_meetings):
    client = FakeSlack(files={"F1": AUDIO})
    stub = {"id": "F1", "mimetype": "audio/aac", "file_access": "check_file_info"}
    meeting.handle(client, "D1", None, [stub], sleep=drive(_isolated_meetings))

    assert slack == [AUDIO["url_private_download"]]
    assert client.visible() == [card(client)]


def test_mos_kelmaydigan_format_tugmasiz(slack, monkeypatch):
    webm = b"\x1aE\xdf\xa3" + b"\0" * 60

    def download(url, dest, limit):
        dest.write_bytes(webm)
        return len(webm), "0" * 64, webm[:16]

    monkeypatch.setattr(transcribe, "download", download)
    client = FakeSlack()
    meeting.handle(client, "D1", None, [{"id": "F4", "mimetype": "audio/webm",
                                         "url_private_download": "https://files.slack.com/x"}])

    [failed] = client.visible()
    assert failed["text"] == "Matnga o'girib bo'lmadi: Bu audio formati qo'llab-quvvatlanmaydi (mp3, m4a, aac, wav)."
    assert elements(failed) == []
    assert [d["ts"] for d in client.deleted] == [client.posted[0]["ts"]]      # "⏳" xabari o'chdi
    # Xato xabarida yig'ilish belgisi yo'q (thread'idagi javob hech qaysi yozuvga bog'lanmaydi).
    assert render.marked(failed) is None and "block_id" not in failed["blocks"][0]


def test_yuklab_bolmasa_qayta_urinish_tugmasi(slack, monkeypatch, _isolated_meetings):
    real = transcribe.download

    def broken(url, dest, limit):
        raise transcribe.Problem("Slack'dan faylni yuklab bo'lmadi.", retry=True)

    monkeypatch.setattr(transcribe, "download", broken)
    client = FakeSlack(files={"F1": AUDIO})
    meeting.acknowledge(client, client.say("D1", files=[AUDIO]))
    choose_language(client, question_of(client, "F1"), "en", _isolated_meetings)
    [failed] = client.visible()
    [retry] = elements(failed)
    # "Qayta urinish" tanlangan tilni eslab qoladi.
    assert (retry["action_id"], retry["value"]) == ("barno_retry", "f:F1:en")

    monkeypatch.setattr(transcribe, "download", real)
    meeting.on_action(client, {"actions": [retry], "channel": {"id": "D1"}, "message": {}},
                      sleep=drive(_isolated_meetings))
    assert client.visible()[1] is card(client)
    [row] = _meetings(_isolated_meetings)[0]
    assert render.marked(card(client)) == row["id"] and row["language"] == "en"

    # Tilsiz eski tugma (2026-11-12 gacha) - o'zbek.
    meeting.retry(client, "D1", None, transcribe.account(), "f:F1", sleep=drive(_isolated_meetings))
    assert client.posted[-1] is card(client)


def test_kunlik_limit_tugasa_yozuv_ochiriladi(slack, monkeypatch, _isolated_meetings):
    monkeypatch.setattr(settings, "meetings_user_daily_minutes", 0, raising=False)
    client = FakeSlack()
    meeting.handle(client, "D1", None, [AUDIO], sleep=drive(_isolated_meetings))

    [failed] = client.visible()
    assert "limiti tugagan" in failed["text"] and elements(failed) == []
    assert _meetings(_isolated_meetings)[1] == 0


def test_hisob_sozlanmagan(slack, monkeypatch):
    monkeypatch.setattr(settings, "slack_actor_id", "", raising=False)
    client = FakeSlack()
    meeting.handle(client, "D1", None, [AUDIO])
    monkeypatch.setattr(settings, "slack_actor_id", "admin", raising=False)
    meeting.handle(client, "D1", None, [AUDIO])

    assert slack == []
    first, second = client.visible()
    assert "SLACK_ACTOR_ID" in first["text"]
    assert "raqam bo'lishi kerak" in second["text"]


def test_token_faqat_slack_xostiga():
    with pytest.raises(transcribe.Problem):
        transcribe.download("https://example.com/f", Path("unused"), 10)
    handler = transcribe._SlackOnly()
    request = urllib.request.Request("https://files.slack.com/a", headers={"Authorization": "Bearer x"})
    assert handler.redirect_request(request, None, 302, "Found", {}, "https://cdn.example.com/a") is None
    assert handler.redirect_request(request, None, 302, "Found", {}, "https://files.slack.com/b") is not None


def test_matn_bolaklari_belgilar_va_markdown():
    assert render.split("a" * 10 + "\n" + "b" * 10, limit=15) == ["a" * 10, "b" * 10]
    assert render.split("x" * 40, limit=15) == ["x" * 15, "x" * 15, "x" * 10]
    assert render.escape("<@U1> & <!here>") == "&lt;@U1&gt; &amp; &lt;!here&gt;"
    md = "**Maqsad:** x\n- a\n## **Sarlavha**\n| A | B |\n|---|---|\n| 1 | 2 |"
    assert render.mrkdwn(md) == "*Maqsad:* x\n• a\n*Sarlavha*\nA · B\n1 · 2"


def test_thread_bolmasa_xabar_chatning_ozida():
    client = FakeSlack()
    meeting.post(client, "D1", None, "matn")
    assert "thread_ts" not in client.posted[0] and client.posted[0]["text"] == "matn"
