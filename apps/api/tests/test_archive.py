"""Arxiv (`services/archive.py`), Telegram fayllari (`bot/media.py`) va Slack xabarlari (`slack/keep.py`).

Ega talabi (2026-11-05): Telegram va Slack'dan kelgan har qanday ma'lumot saqlansin. Arxiv har testda
vaqtinchalik papkada (`conftest._isolated_archive`). Tarmoqqa chiqilmaydi.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat

from types import SimpleNamespace

import app.slack as slack_app
from app.bot import media
from app.core.config import settings
from app.services import archive
from app.slack import keep, meeting, transcribe
from slack_fakes import FakeSlack


def mode(path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


class Api:
    """Telegram Bot API ning `getFile` va yuklab olish qismi."""

    def __init__(self, files: dict[str, bytes] | None = None, *, fail: bool = False) -> None:
        self.files = files or {}
        self.fail = fail
        self.asked: list[str] = []

    def get_file(self, file_id):
        self.asked.append(file_id)
        if self.fail:
            raise RuntimeError("tarmoq")
        return {"file_path": f"f/{file_id}"}

    def download(self, file_path, *, limit):
        return self.files[file_path]


# --- arxiv ombori -----------------------------------------------------------------------------------


def test_matn_va_fayl_yoziladi_huquqlar_600():
    store = archive.get()
    assert store.root == settings.archive_dir                     # conftest: har testda vaqtinchalik
    text_id = archive.record("slack", "in", "text", chat="D1", user="U1", message="1.2", text="salom",
                             now=1762300000)
    file_id = archive.record("telegram", "out", "document", chat=42, actor=1, data=b"%PDF-1", name="Баённома.pdf",
                             mime="application/pdf", meta={"meeting": "m1"}, now=1762300000)
    text, file = store.rows()
    assert text["id"] == text_id and (text["kind"], text["text"], text["file_path"]) == ("text", "salom", None)
    assert (text["chat_id"], text["user_id"], text["message_id"], text["status"]) == ("D1", "U1", "1.2", "ok")
    assert file["id"] == file_id and file["file_path"] == f"files/2025/11/{file_id}.pdf"
    path = store.root / file["file_path"]
    assert path.read_bytes() == b"%PDF-1" and file["size"] == 6
    assert file["sha256"] == hashlib.sha256(b"%PDF-1").hexdigest()
    assert (file["chat_id"], file["actor_id"], json.loads(file["meta"])) == ("42", 1, {"meeting": "m1"})
    # Shaxsiy ma'lumot: fayl va indeks faqat egasiga, papkalar 700.
    assert mode(path) == 0o600 and mode(store.db_path) == 0o600
    assert {mode(store.root), mode(store.root / "files"), mode(path.parent.parent), mode(path.parent)} == {0o700}


def test_katta_fayl_yozilmaydi_xato_otilmaydi(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "archive_max_file_mb", 1)
    big = archive.record("slack", "in", "file", data=b"x" * (1024 * 1024 + 1), name="katta.zip")
    [row] = archive.get().rows()
    assert row["id"] == big and (row["status"], row["size"], row["file_path"]) == ("too_large", 1024 * 1024 + 1, None)
    assert not (archive.get().root / "files").exists()
    # Arxivga yozib bo'lmasa ham xato otilmaydi - javob va fayl yuborish davom etadi.
    (tmp_path / "fayl").write_text("papka emas")
    monkeypatch.setattr(settings, "archive_dir", tmp_path / "fayl")
    assert archive.record("slack", "in", "text", text="salom") is None


def test_kengaytma_nomdan_yoki_turdan():
    assert archive._ext("hisobot.PDF", "") == ".pdf" and archive._ext("a.tar.gz", "") == ".gz"
    assert archive._ext("rasm", "image/png") == ".png" and archive._ext("rasm", "") == ".bin"
    # Nom faylning nomiga ta'sir qilmaydi (id), kengaytma - faqat harf va raqam.
    assert archive._ext("../../etc/passwd", "") == ".bin" and archive._ext("x.verylongext1", "") == ".bin"


# --- Telegram fayllari ------------------------------------------------------------------------------


def test_telegram_fayli_yuklanadi_izoh_niqoblanadi():
    api = Api({"f/big": b"JPEG"})
    msg = {"message_id": 7, "date": 1762300000, "chat": {"id": -100}, "from": {"id": 5},
           "caption": "tel +998901234567", "photo": [{"file_id": "small", "file_size": 1},
                                                     {"file_id": "big", "file_size": 4}]}
    assert media.file_of({"message_id": 1, "text": "salom"}) is None
    assert media.file_of({"message_id": 1, "sticker": {"file_id": "s"}}) is None      # umumiy to'plamdan
    item = media.keep(api, msg, channel="telegram_group")
    [row] = archive.get().rows()
    assert row["id"] == item and api.asked == ["big"]                                  # eng katta o'lcham
    assert (row["channel"], row["kind"], row["file_name"], row["mime"]) == ("telegram_group", "photo", "photo-7.jpg",
                                                                            "image/jpeg")
    assert (archive.get().root / row["file_path"]).read_bytes() == b"JPEG"
    assert "+998901234567" not in row["text"]
    assert (row["chat_id"], row["user_id"], row["message_id"], json.loads(row["meta"])) == (
        "-100", "5", "7", {"date": 1762300000})


def test_telegram_katta_yoki_yuklanmagan_fayl_qatori_qoladi():
    api = Api()
    media.keep(api, {"message_id": 8, "chat": {"id": 1}, "video": {"file_id": "v", "file_size": 21 * 1024 * 1024}},
               channel="telegram")
    media.keep(Api(fail=True), {"message_id": 9, "chat": {"id": 1},
                                "voice": {"file_id": "o", "file_size": 3, "duration": 2}}, channel="telegram")
    big, failed = archive.get().rows()
    assert (big["kind"], big["status"], big["file_path"], big["size"]) == ("video", "too_large", None, 21 * 1024 * 1024)
    assert api.asked == []                                       # 20 MB dan kattasini Telegram baribir bermaydi
    assert (failed["kind"], failed["status"], json.loads(failed["meta"])) == ("voice", "failed", {"duration": 2})


# --- Slack ------------------------------------------------------------------------------------------


def test_slack_matn_niqoblanadi_fayl_yuklanadi_audio_yoq(monkeypatch):
    def download(url, dest, limit):
        assert url == "https://files.slack.com/x.pdf"
        dest.write_bytes(b"%PDF")
        return 4, "sha", b"%PDF"

    monkeypatch.setattr(transcribe, "download", download)
    event = {"channel_type": "im", "user": "U1", "channel": "D1", "ts": "1.2", "subtype": "file_share",
             "text": "karta 8600 1234 5678 9012 ni tekshiring",
             "files": [{"id": "F1", "name": "x.pdf", "mimetype": "application/pdf", "size": 4,
                        "url_private_download": "https://files.slack.com/x.pdf"},
                       {"id": "F2", "name": "yozuv.m4a", "mimetype": "audio/mp4", "size": 9}]}
    assert keep.wants(event) and not keep.wants({**event, "bot_id": "B1"})
    assert not keep.wants({**event, "channel_type": "channel"}) and not keep.wants({**event, "subtype": "message_changed"})
    keep.record(event)
    text, file = archive.get().rows(channel="slack")                # audio - yig'ilish bo'ladi, bu yerda yo'q
    assert (text["kind"], text["user_id"], text["chat_id"]) == ("text", "U1", "D1")
    assert "8600 1234 5678 9012" not in text["text"] and "tekshiring" in text["text"]
    assert (file["kind"], file["file_name"], json.loads(file["meta"])) == ("file", "x.pdf", {"file": "F1"})
    assert (archive.get().root / file["file_path"]).read_bytes() == b"%PDF"
    # Thread'dagi xabar - thread bilan; yuklab bo'lmagan fayl - `failed`, xato otilmaydi.
    monkeypatch.setattr(transcribe, "download", lambda *a: (_ for _ in ()).throw(transcribe.Problem("yo'q")))
    keep.record({**event, "ts": "1.3", "thread_ts": "1.2", "text": "savol", "files": event["files"][:1]})
    reply, broken = archive.get().rows(channel="slack")[2:]
    assert json.loads(reply["meta"]) == {"thread": "1.2"} and broken["status"] == "failed"


def test_slack_yuborilgan_fayl_arxivga():
    client = FakeSlack()
    meeting.upload(client, "D1", "1.5", b"PK-docx", "Баённома.docx")
    assert client.uploaded[0]["filename"] == "Баённома.docx"
    [row] = archive.get().rows(channel="slack")
    assert (row["direction"], row["kind"], row["chat_id"], row["file_name"]) == ("out", "document", "D1", "Баённома.docx")
    assert json.loads(row["meta"]) == {"thread": "1.5"} and row["file_path"].endswith(".docx")


def test_slack_dispetcher_arxivni_navbatga_qoyadi(monkeypatch):
    submitted = []
    monkeypatch.setattr(slack_app, "_pool", SimpleNamespace(submit=lambda fn, *a, **k: submitted.append(fn.__name__)))
    slack_app._on_message({"channel_type": "im", "user": "U1", "channel": "D1", "ts": "1.1", "text": "salom"},
                          client=None, context={})
    assert submitted == ["record", "on_text"]                    # arxiv + odatdagi yo'riqnoma
    submitted.clear()
    slack_app._on_message({"channel_type": "im", "bot_id": "B1", "channel": "D1", "ts": "1.2", "text": "javob"},
                          client=None, context={})
    assert "record" not in submitted                              # botning o'z xabari arxivga emas
