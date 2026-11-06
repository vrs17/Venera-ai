"""Telegram "📲 Ilovani yuklab olish" (`app/bot/mobile_app.py`): tugma -> 10.10.50.4 dagi APK API
(`/latest`, `/download`) -> Android APK botning o'zidan, versiya izohi bilan.

APK API ham, Telegram ham soxta (`FakeApi`, `test_telegram_bot.FakeTelegram`): hech bir test
tarmoqqa chiqmaydi.
"""

from __future__ import annotations

import hashlib
import json
import urllib.error

import pytest

from app.bot import briefs, plaud
from app.bot.mobile_app import BTN_APP, MAX_SEND, MobileApp
from app.bot.runner import VeneraBot
from app.core.security import hash_password
from app.services import archive
from app.services.integrations.telegram import TelegramError
from app.services.telegram_links import LinkStore
from app.services.users import StoredUser, UserStore
from test_telegram_bot import TG_ID, FakeBackend, FakeTelegram, text_update

OTHER_TG = 5550002
APK = b"PK\x03\x04" + b"barno" * 1000
RETRY = "birozdan keyin qayta urinib ko'ring."


class FakeApi:
    """10.10.50.4 dagi "Barno AI APK" API o'rnida: `/latest` va `/download`."""

    def __init__(self) -> None:
        self.data, self.version, self.code = APK, "1.3.5", 10
        self.size: int | None = None              # `/latest` aytadigan hajm (None - haqiqiysi)
        self.down = False
        self.calls: list[str] = []

    def __call__(self, url: str, timeout: float) -> bytes:
        self.calls.append(url)
        if self.down:
            raise urllib.error.URLError("connection refused")
        if url.endswith("/latest"):
            arm64 = {"version": self.version, "versionCode": self.code,
                     "file": f"barno-ai-{self.version}-vc{self.code}-arm64.apk",
                     "size": len(self.data) if self.size is None else self.size,
                     "sha256": hashlib.sha256(self.data).hexdigest()}
            return json.dumps({"app": "Barno AI", "package": "uz.brbtech.venera.meetings",
                               "variants": {"arm64": arm64, "universal": {**arm64, "size": 108276812}}}).encode()
        assert url.endswith("/download?variant=arm64")
        return self.data


@pytest.fixture
def world(tmp_path):
    users = UserStore({
        "a@b.uz": StoredUser(actor_id=1, email="a@b.uz", full_name="Ali Valiyev", password_hash=hash_password("x")),
    })
    tg = FakeTelegram()
    links = LinkStore(tmp_path / "links.json")
    links.link(TG_ID, 1)
    api = FakeApi()
    app = MobileApp(tg, "http://10.10.50.4:8097/", inline=True, fetch=api)
    bot = VeneraBot(tg, links, users=lambda: users, backend=FakeBackend(), webapp_url="https://llm.brb-tech.uz/tg/",
                    inline=True, typing_every=None, mobile_app=app)
    return bot, tg, api, app


def test_tugma_apk_yuboradi_keyingisi_qayta_yuklanmaydi(world):
    bot, tg, api, app = world
    bot.handle_update(text_update(BTN_APP))

    [doc] = tg.sent("send_document")
    assert doc["filename"] == "barno-ai-1.3.5-vc10-arm64.apk" and doc["size"] == len(APK)
    assert doc["content_type"] == "application/vnd.android.package-archive" and doc["timeout"] == 300.0
    assert doc["caption"].startswith("📲 <b>Barno AI</b> 1.3.5 - Android ilovasi\n\n")
    assert api.calls == ["http://10.10.50.4:8097/latest", "http://10.10.50.4:8097/download?variant=arm64"]
    # Yuklash paytida "⏳" xabari - fayl ketgach o'chadi.
    holder = next(kw for kw in tg.sent() if kw["text"] == "⏳ Barno AI 1.3.5 (Android) tayyorlanmoqda…")
    assert ("delete_message", {"chat_id": TG_ID, "message_id": holder["message_id"]}) in tg.calls
    assert bot.backend.questions == []                                    # HR yordamchisiga ketmadi

    # Shu versiya keyingi safar - Telegram'dagi fayl (`file_id`) bilan, qayta yuklanmaydi.
    bot.handle_update(text_update(BTN_APP, message_id=11))
    [again] = tg.sent("send_document_id")
    assert again["file_id"] == app._cached[1] and again["caption"] == doc["caption"]
    assert len(tg.sent("send_document")) == 1 and api.calls[-1].endswith("/latest")

    # Yangi versiya (versionCode oshdi) - yangisi yuklanadi.
    api.data, api.version, api.code = APK + b"!", "1.3.6", 11
    bot.handle_update(text_update(BTN_APP, message_id=12))
    assert tg.sent("send_document")[-1]["filename"] == "barno-ai-1.3.6-vc11-arm64.apk"

    # Arxivda - kimga qaysi versiya ketgani; APK ning o'zi har safar ko'chirilmaydi.
    rows = archive.get().rows(channel="telegram")
    assert [json.loads(r["meta"])["versionCode"] for r in rows] == [10, 10, 11]
    assert all((r["direction"], r["kind"], r["file_path"], r["actor_id"]) == ("out", "document", None, 1) for r in rows)
    assert rows[0]["file_name"] == "barno-ai-1.3.5-vc10-arm64.apk" and rows[0]["size"] == len(APK)


def test_api_ishlamasa_fayl_buzuq_yoki_katta_bolsa_sabab(world):
    bot, tg, api, app = world
    api.down = True
    bot.handle_update(text_update(BTN_APP))
    assert tg.texts()[-1] == f"📲 Ilovani hozir olib bo'lmadi - {RETRY}"

    api.down, api.size = False, len(APK) + 1                              # sha256/hajm mos emas
    bot.handle_update(text_update(BTN_APP, message_id=11))
    assert tg.texts()[-1] == f"📲 Ilova fayli tekshiruvdan o'tmadi - {RETRY}"

    api.size = MAX_SEND + 1                                               # Telegram chegarasidan katta
    bot.handle_update(text_update(BTN_APP, message_id=12))
    assert "50 MB" in tg.texts()[-1] and api.calls[-1].endswith("/latest")

    assert tg.sent("send_document") == [] and archive.get().rows(channel="telegram") == []


def test_telegram_xatosi_va_yaroqsiz_file_id(world, monkeypatch):
    bot, tg, api, app = world
    real = tg.send_document

    def too_big(*args, **kwargs):
        raise TelegramError("sendDocument: 413", code=413, description="Request Entity Too Large")

    monkeypatch.setattr(tg, "send_document", too_big)
    bot.handle_update(text_update(BTN_APP))
    assert tg.texts()[-1] == f"📲 Ilovani yuborib bo'lmadi - {RETRY}" and app._cached is None

    monkeypatch.setattr(tg, "send_document", real)
    bot.handle_update(text_update(BTN_APP, message_id=11))
    assert app._cached is not None

    def wrong_id(*args, **kwargs):
        raise TelegramError("sendDocument: 400", code=400, description="Bad Request: wrong file identifier")

    monkeypatch.setattr(tg, "send_document_id", wrong_id)
    bot.handle_update(text_update(BTN_APP, message_id=12))                # fayl qaytadan yuklanadi
    assert len(tg.sent("send_document")) == 2


def test_ulanmagan_odamga_yoq_ochiq_bolmasa_aytadi_va_klaviaturada(world):
    bot, tg, api, app = world
    bot.handle_update(text_update(BTN_APP, tg_id=OTHER_TG))
    assert tg.sent("send_document") == [] and api.calls == []

    bot.mobile_app = None
    bot.handle_update(text_update(BTN_APP))
    assert tg.texts()[-1] == "📲 Ilovani yuklab olish hozir o'chiq." and bot.backend.questions == []

    row = [{"text": plaud.BTN_PLAUD}, {"text": BTN_APP}]                  # pastdagi klaviaturada, Plaud yonida
    assert plaud.KEYBOARD["keyboard"] == [row]
    assert row in briefs.REPLY_KEYBOARD["keyboard"] and row in briefs.REPLY_KEYBOARD_ADMIN["keyboard"]
