"""Bayonnoma xizmati (`services/meetings/minutes/__init__.py`): yaratish, takror, chegara, xatolar, eksport.

Model - `FakeLLM` (`MEETINGS_MINUTES_CHAIN=ollama`, `auto_reply` op `meeting_minutes`); yig'ilish Slack
yo'li bilan tayyorlanadi (`slack_fakes.setup`, admin hisobi). Tarmoqqa chiqilmaydi.
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.services.meetings import minutes, service
from app.services.meetings.errors import MeetingProblem
from app.services.meetings.store import jdump, jload
from app.slack import meeting, render, transcribe
from slack_fakes import AUDIO, FakeSlack, card, drive, setup


@pytest.fixture
def ready(users_file, monkeypatch, _isolated_meetings):
    """(hisob, transkripti tayyor yig'ilish id, runtime) - bayonnoma zanjiri FakeLLM."""
    setup(monkeypatch, users_file)
    client = FakeSlack(files={"F1": AUDIO})
    meeting.handle(client, "D1", None, [AUDIO], sleep=drive(_isolated_meetings))
    monkeypatch.setattr(settings, "meetings_minutes_chain", "ollama", raising=False)
    return transcribe.account(), render.marked(card(client)), _isolated_meetings


def _minutes_calls(rt) -> int:
    return len([c for c in rt.llm.calls if c["op"] == "meeting_minutes"])


def test_yaratish_takror_va_eksport(ready):
    user, mid, rt = ready
    view = minutes.generate(user, mid, "uz-cyrl")
    assert view["status"] == "ready" and view["provider"] == "ollama" and view["language"] == "uz-cyrl"
    assert (view["agendaCount"], view["sectionCount"], view["itemCount"]) == (2, 2, 3)
    assert view["stale"] is False and view["error"] is None and _minutes_calls(rt) == 1
    # Xuddi shu til - tayyori, model qayta chaqirilmaydi; boshqa yozuv shakli - yo'q.
    assert minutes.generate(user, mid, "UZ_CYRL")["id"] == view["id"] and _minutes_calls(rt) == 1
    assert minutes.latest(user, mid, "uz-cyrl")["id"] == view["id"] and minutes.latest(user, mid, "ru") is None
    assert minutes.generate(user, mid, "uz-cyrl", force=True)["id"] != view["id"] and _minutes_calls(rt) == 2
    assert len(minutes.listing(user, mid)["items"]) == 2
    # Eksport: Word, PDF, Markdown - fayl nomida hujjat so'zi va sana.
    docx, media, disposition = minutes.export_file(user, mid, view["id"], "docx")
    assert docx[:2] == b"PK" and media.startswith("application/vnd.openxmlformats") and "docx" in disposition
    assert "%D0%91%D0%B0%D1%91%D0%BD%D0%BD%D0%BE%D0%BC%D0%B0" in disposition      # "Баённома" (UTF-8 foiz bilan)
    pdf, media, _ = minutes.export_file(user, mid, view["id"], "pdf")
    assert pdf[:5] == b"%PDF-" and media == "application/pdf"
    md, media, _ = minutes.export_file(user, mid, view["id"], "md")
    assert "ҚАРОР ҚИЛАДИ:" in md.decode("utf-8") and media.startswith("text/markdown")
    full = minutes.get(user, mid, view["id"])
    assert full["content"]["language"] == "uz-cyrl" and full["content"]["version"] == minutes.prompt.MINUTES_VERSION
    with pytest.raises(MeetingProblem) as bad:
        minutes.export_file(user, mid, view["id"], "txt")
    assert bad.value.status_code == 400
    with pytest.raises(MeetingProblem) as bad:
        minutes.generate(user, mid, "de")
    assert bad.value.code == "invalid_language"


def test_model_sozlanmagan_va_chegara(ready, monkeypatch):
    user, mid, rt = ready
    monkeypatch.setattr(settings, "meetings_minutes_chain", "claude", raising=False)   # rt.claude yo'q
    with pytest.raises(MeetingProblem) as bad:
        minutes.generate(user, mid, "ru")
    assert bad.value.status_code == 503 and bad.value.code == "llm_not_configured"
    monkeypatch.setattr(settings, "meetings_minutes_chain", "ollama", raising=False)
    monkeypatch.setattr(settings, "meetings_minutes_per_hour", 1, raising=False)
    minutes.generate(user, mid, "ru")
    # Tayyori chegarani yemaydi; yangi til - yeydi.
    minutes.generate(user, mid, "ru")
    with pytest.raises(MeetingProblem) as bad:
        minutes.generate(user, mid, "en")
    assert bad.value.status_code == 429


def test_kutilmagan_xato_qator_failed(ready, monkeypatch):
    user, mid, rt = ready
    monkeypatch.setattr(minutes.prompt, "build", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(MeetingProblem) as bad:
        minutes.generate(user, mid, "en")
    assert bad.value.status_code == 500
    [row] = rt.store.minutes_rows(mid)
    assert row["status"] == "failed" and row["error_code"] == "internal" and row["error"] == "RuntimeError"
    assert minutes.listing(user, mid)["items"][0]["error"] == {"code": "internal", "message": "RuntimeError"}


def test_model_yaroqsiz_javob_502(ready):
    user, mid, rt = ready
    rt.llm.script["meeting_minutes"] = ["bu JSON emas"]
    with pytest.raises(MeetingProblem) as bad:
        minutes.generate(user, mid, "en")
    assert bad.value.status_code == 502 and bad.value.code == "llm_failed"
    assert rt.store.minutes_rows(mid)[-1]["status"] == "failed"


def test_izohlarda_spiker_tokeni_korinmaydi(ready):
    # Birinchi jonli sinov (2026-11-05): izohdagi "[S3] ва [S4]" Slack/Telegram xabariga xom tushgan edi.
    user, mid, rt = ready
    view = minutes.generate(user, mid, "uz-cyrl")
    content = jload(rt.store.minutes_row(mid, view["id"])["content_json"])
    content["notes"] = ["[S1] нинг лавозими аниқлаштирилсин.", "[S9] 03:10 да эшитилмади."]
    rt.store.update_minutes(view["id"], content_json=jdump(content))
    service.rename_speaker(user, mid, "S1", "Aziz Karimov")
    expected = ["Aziz Karimov нинг лавозими аниқлаштирилсин.", "9-иштирокчи 03:10 да эшитилмади."]
    assert minutes.latest(user, mid, "uz-cyrl")["notes"] == expected
    assert minutes.get(user, mid, view["id"])["notes"] == expected
    md = minutes.export_file(user, mid, view["id"], "md")[0].decode("utf-8")
    assert "Aziz Karimov нинг лавозими аниқлаштирилсин." in md and "[S" not in md
