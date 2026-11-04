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
from slack_fakes import AUDIO, FakeSlack, card, drive, elements, setup, shown


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


def test_audio_transkript_va_qisqa_xulosa_chatning_ozida(slack, _isolated_meetings):
    client = FakeSlack()
    meeting.handle(client, "D1", None, [AUDIO], sleep=drive(_isolated_meetings))

    assert slack == [AUDIO["url_private_download"]]
    rows, total = _meetings(_isolated_meetings)
    assert total == 1 and rows[0]["title"] == "Slack: ovoz.aac"
    mid = rows[0]["id"]
    assert all("thread_ts" not in m for m in client.posted)
    first = client.posted[0]
    assert "Assalomu alaykum, bugun hisobot bo'yicha yig'ildik" in shown(first)
    assert "[00:" not in shown(first)
    assert render.marked(first) == mid
    summary = card(client)
    assert summary is client.posted[-1] and render.marked(summary) == mid
    assert shown(summary).startswith("Qisqa xulosa\n*")
    ids = [e["action_id"] for e in elements(summary)]
    assert ids == ["barno_tasks", "barno_template", "barno_export", "barno_relang_ru", "barno_relang_en"]
    assert all("confirm" in e for e in elements(summary) if e["action_id"].startswith("barno_relang"))


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
    assert sum("Assalomu alaykum" in shown(m) for m in client.posted) == 2


def test_slack_ovozli_xabari_aac_nusxasidan_olinadi(slack, _isolated_meetings):
    clip = {"id": "F3", "subtype": "slack_audio", "mimetype": "audio/webm", "created": 1762150000,
            "url_private_download": "https://files.slack.com/files-pri/T1-F3/download/clip.webm",
            "aac": "https://files.slack.com/files-tmb/T1-F3-ab/clip.aac"}
    client = FakeSlack()
    meeting.handle(client, "D1", None, [clip], sleep=drive(_isolated_meetings))

    assert slack == [clip["aac"]]
    assert "Assalomu alaykum" in shown(client.posted[0])


def test_toliq_obyekt_files_info_dan(slack, _isolated_meetings):
    client = FakeSlack(files={"F1": AUDIO})
    stub = {"id": "F1", "mimetype": "audio/aac", "file_access": "check_file_info"}
    meeting.handle(client, "D1", None, [stub], sleep=drive(_isolated_meetings))

    assert slack == [AUDIO["url_private_download"]]
    assert "Assalomu alaykum" in shown(client.posted[0])


def test_mos_kelmaydigan_format_tugmasiz(slack, monkeypatch):
    webm = b"\x1aE\xdf\xa3" + b"\0" * 60

    def download(url, dest, limit):
        dest.write_bytes(webm)
        return len(webm), "0" * 64, webm[:16]

    monkeypatch.setattr(transcribe, "download", download)
    client = FakeSlack()
    meeting.handle(client, "D1", None, [{"id": "F4", "mimetype": "audio/webm",
                                         "url_private_download": "https://files.slack.com/x"}])

    assert client.posted[0]["text"] == ("Matnga o'girib bo'lmadi: Bu audio formati qo'llab-quvvatlanmaydi "
                                        "(mp3, m4a, aac, wav).")
    assert elements(client.posted[0]) == []


def test_yuklab_bolmasa_qayta_urinish_tugmasi(slack, monkeypatch, _isolated_meetings):
    real = transcribe.download

    def broken(url, dest, limit):
        raise transcribe.Problem("Slack'dan faylni yuklab bo'lmadi.", retry=True)

    monkeypatch.setattr(transcribe, "download", broken)
    client = FakeSlack(files={"F1": AUDIO})
    meeting.handle(client, "D1", None, [AUDIO])
    [retry] = elements(client.posted[0])
    assert (retry["action_id"], retry["value"]) == ("barno_retry", "f:F1")

    monkeypatch.setattr(transcribe, "download", real)
    meeting.on_action(client, {"actions": [retry], "channel": {"id": "D1"}, "message": {}},
                      sleep=drive(_isolated_meetings))
    assert "Assalomu alaykum" in shown(client.posted[1])
    assert render.marked(card(client)) == _meetings(_isolated_meetings)[0][0]["id"]


def test_kunlik_limit_tugasa_yozuv_ochiriladi(slack, monkeypatch, _isolated_meetings):
    monkeypatch.setattr(settings, "meetings_user_daily_minutes", 0, raising=False)
    client = FakeSlack()
    meeting.handle(client, "D1", None, [AUDIO], sleep=drive(_isolated_meetings))

    assert "limiti tugagan" in client.posted[0]["text"]
    assert elements(client.posted[0]) == []
    assert _meetings(_isolated_meetings)[1] == 0


def test_hisob_sozlanmagan(slack, monkeypatch):
    monkeypatch.setattr(settings, "slack_actor_id", "", raising=False)
    client = FakeSlack()
    meeting.handle(client, "D1", None, [AUDIO])
    monkeypatch.setattr(settings, "slack_actor_id", "admin", raising=False)
    meeting.handle(client, "D1", None, [AUDIO])

    assert slack == []
    assert "SLACK_ACTOR_ID" in client.posted[0]["text"]
    assert "raqam bo'lishi kerak" in client.posted[1]["text"]


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
