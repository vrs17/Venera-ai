"""Slack ilovasi (`app/slack/meeting.py`): transkriptdan keyingi imkoniyatlar - thread'dagi
savol, vazifalar, boshqa shablon bilan xulosa, eksport, boshqa tilda qayta o'girish.

Hammasi soxta (`slack_fakes.py`, `meetings_fakes.py`): tarmoq ham, pul ham yo'q.
"""

from __future__ import annotations

import pytest

from app.services.meetings import templates
from app.slack import meeting, render
from slack_fakes import AUDIO, BOT_USER, FakeSlack, as_parent, card, drive, elements, setup, shown


@pytest.fixture
def delivered(users_file, monkeypatch, _isolated_meetings):
    """Audio o'girilgan: (Slack, yig'ilish id, "Qisqa xulosa" xabari)."""
    setup(monkeypatch, users_file)
    client = FakeSlack(files={"F1": AUDIO})
    meeting.handle(client, "D1", None, [AUDIO], sleep=drive(_isolated_meetings))
    summary = card(client)
    return client, render.marked(summary), summary


def _click(client, element, value, rt, *, selected=False):
    action = {"action_id": element, **({"selected_option": {"value": value}} if selected else {"value": value})}
    meeting.on_action(client, {"actions": [action], "channel": {"id": "D1"}, "message": {}}, sleep=drive(rt))


def _ask(client, thread, text="Kim hisobot yuboradi?"):
    event = {"channel_type": "im", "channel": "D1", "user": "U1", "text": text, "ts": "200.1", "thread_ts": thread}
    assert meeting.wants(event)
    meeting.on_message(client, event, bot_user=BOT_USER)


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


def test_vazifalar_tugmasi(delivered, _isolated_meetings):
    client, mid, _ = delivered
    _click(client, "barno_tasks", mid, _isolated_meetings)

    assert client.posted[-1]["text"].startswith("*Vazifalar*\n")


def test_boshqa_shablon_bilan_xulosa(delivered, _isolated_meetings):
    client, mid, summary = delivered
    title = {t["id"]: t["title"] for t in templates.catalog("uz")}["minutes"]
    options = [e for e in elements(summary) if e["action_id"] == "barno_template"][0]["options"]
    assert f"{mid}|minutes" in [o["value"] for o in options]
    assert f"{mid}|auto" not in [o["value"] for o in options]
    _click(client, "barno_template", f"{mid}|minutes", _isolated_meetings, selected=True)

    assert client.posted[-1]["text"].startswith("⏳")
    assert client.updated[-1]["text"].startswith(f"*Xulosa: {title}*")


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


def test_boshqa_tilda_qayta_ogirish(delivered, _isolated_meetings):
    client, mid, _ = delivered
    before = len(client.posted)
    _click(client, "barno_relang_ru", f"{mid}|ru", _isolated_meetings)

    assert client.posted[before]["text"].startswith("⏳ Audio rus tilida")
    assert client.updated[-1]["text"] == "✅ Audio rus tilida qayta o'girildi."
    # Rus tili - Router orqali (yig'ilish quvurining o'z qoidasi), yangi transkript chatga.
    assert [c["language"] for c in _isolated_meetings.router.calls] == ["ru"]
    assert "Добрый день" in shown(client.posted[before + 1])
    ids = [e["action_id"] for e in elements(card(client))]
    assert ids[-2:] == ["barno_relang_uz", "barno_relang_en"]
