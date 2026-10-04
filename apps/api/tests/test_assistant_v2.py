"""Yordamchining ikki dvigateli (v1 / v2), qonunchilik manbalari va navbat.

Yuqoridagi jamoaning o'zgarishlar xati (2026-10-02) bo'yicha:

  * dvigatel KANAL bo'yicha (`core/engines.py`): web `v2`, `.env` dagi
    istisno bilan mini app / bot `v1`, bo'sh qiymat - versiyasiz yo'l;
  * `done.engine` savol iziga yoziladi (javob bergan dvigatel ustun);
  * `kind: "law"` manbasi o'zgarishsiz o'tadi, faqat xavfli `url` tozalanadi;
    bot uni "LEX.UZ · qonunchilik" havolasi bilan ko'rsatadi;
  * NAVBAT (xat, 6-bo'lim): 29-sentabrdagi "bir soat 503" ning sababi -
    yopilmay tashlab ketilgan oqim joyni abadiy egallagani. Endi joy uch
    yo'ldan qaytadi va navbat to'lganda o'zini davolaydi;
  * ochilmagan savolning ichki sababi alohida: `queue_full` (BIZNING navbat),
    `upstream_unreachable`, `upstream_busy` - foydalanuvchiga esa bir xil
    "xizmat band".

Tarmoqqa chiqilmaydi: yordamchi, Telegram, CRM - soxta (`build_opener`).
"""

from __future__ import annotations

import gc
import io
import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request

import pytest

from app.bot import render
from app.core import engines
from app.core.config import settings
from app.schemas.auth import AuthUser
from app.schemas.chat import StreamRequest
from app.services import analytics
from app.services.integrations import assistant as assistant_mod
from app.services.integrations.assistant import (
    AnswerStream,
    AssistantClient,
    AssistantError,
    _SlotPool,
    safe_source_url,
    stream_path,
)

BASE = "http://assistant.test"
STREAM_PATH = re.compile(r"/api/(v[12]/)?chat/stream")
BUSY_TEXT = "Savol-javob xizmati band, biroz kutib qayta urinib ko'ring"
LEX = "https://www.lex.uz/uz/docs/6257288#6261538"
LAW_TITLE = ("Mehnat kodeksi, 160-modda — Mehnat shartnomasini xodimning tashabbusiga "
             "ko‘ra bekor qilish")


def frame(**kw) -> bytes:
    return json.dumps(kw, ensure_ascii=False).encode("utf-8") + b"\n"


def frames_of(stream) -> list[dict]:
    return [json.loads(line) for line in stream.frames]


class _Ndjson:
    def __init__(self, lines, on_read=None) -> None:
        self._lines = list(lines)
        self.headers = {"X-Request-Id": "served-v2"}
        self.status = 200
        self.closed = False
        self._on_read = on_read

    def readline(self, limit: int = -1) -> bytes:
        if self._on_read is not None:
            self._on_read()
        return self._lines.pop(0) if self._lines else b""

    def read(self, size: int = -1) -> bytes:
        return self._lines.pop(0) if self._lines else b""

    def close(self) -> None:
        self.closed = True


class Upstream:
    """Soxta yordamchi: qaysi yo'l ochilgani, tanasi va xato holatlari."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        #: `done` ga qo'shiladigan `engine` - `None` bo'lsa yo'lning o'zidan
        #: (versiyasiz yo'lda yo'q), `""` bo'lsa umuman qo'shilmaydi.
        self.done_engine: str | None = None
        self.sources: list[dict] = [{"kind": "doc", "doc_id": "HR_045", "title": "Ichki tartib",
                                     "page": 4, "citation_index": 1}]
        self.error: BaseException | None = None
        self.on_read = None

    def open(self, request, timeout=None):
        parts = urllib.parse.urlsplit(request.full_url)
        body = json.loads(request.data) if request.data else None
        self.calls.append({"path": parts.path, "body": body})
        if self.error is not None:
            raise self.error
        if not STREAM_PATH.fullmatch(parts.path):
            raise AssertionError(f"kutilmagan yo'l: {parts.path}")
        version = parts.path.split("/")[2] if parts.path.count("/") == 4 else None
        engine = version if self.done_engine is None else (self.done_engine or None)
        done = {"type": "done", "route": "rules", "request_id": "r-1"}
        if engine:
            done["engine"] = engine
        return _Ndjson([frame(type="stage", text="Qidirilmoqda"),
                        frame(type="sources", items=self.sources),
                        frame(type="token", text="Javob [1]."), frame(**done)],
                       on_read=self.on_read)

    def stream_calls(self) -> list[dict]:
        return [c for c in self.calls if STREAM_PATH.fullmatch(c["path"])]


@pytest.fixture
def upstream(monkeypatch):
    fake = Upstream()

    class Opener:
        def open(self, request, timeout=None):
            return fake.open(request, timeout)

    monkeypatch.setattr(urllib.request, "build_opener", lambda *a, **kw: Opener())
    return fake


class Clock:
    """Soxta monoton soat - navbatning eskirish chegaralarini kutmasdan sinash uchun."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def make_client(**kw) -> AssistantClient:
    kw.setdefault("timeout", 5)
    kw.setdefault("max_concurrent", 2)
    return AssistantClient(BASE, "venera", "sir", **kw)


@pytest.fixture
def api(monkeypatch, upstream, client, tmp_path):
    """Endpoint soxta yordamchi ustida; CRM sessiyasi sozlanmagan, tokenlar bo'sh."""
    import app.api.v1.chat as chat_module
    from app.services.integrations.crm_auth import CrmAuth

    monkeypatch.setattr(chat_module, "_assistant", make_client())
    monkeypatch.setattr(chat_module, "_crm", CrmAuth("", "", "", tmp_path / "crm"))
    monkeypatch.setattr(chat_module, "platform_tokens", dict)
    return client


@pytest.fixture
def db(_isolated_analytics):
    return _isolated_analytics


def rows(db, sql: str, params=()) -> list[dict]:
    assert analytics.flush(5.0)
    return db.rows(sql, params)


def set_engines(monkeypatch, default: str = "v2", by_channel: str = "") -> None:
    monkeypatch.setattr(settings, "hrm_assistant_engine", default)
    monkeypatch.setattr(settings, "hrm_assistant_engine_by_channel", by_channel)


def ask(api, auth, channel: str = "web", **body):
    return api.post("/api/v1/chat/stream", headers={**auth, "X-Venera-Client": channel},
                    json={"question": "Sinov muddati qancha?", **body})


# ================================================================ dvigatel sozlamasi


def test_default_hamma_kanalda_v2():
    assert settings.hrm_assistant_engine == "v2"
    assert {engines.engine_for(c) for c in ("web", "miniapp", "bot", "desktop", "api")} == {"v2"}
    assert engines.pro_available("v2") and not engines.pro_available("v1")
    assert not engines.pro_available("")


def test_kanal_istisnosi_va_yozilishlar(monkeypatch):
    set_engines(monkeypatch, by_channel=" MiniApp = V1 ; tg-bot=legacy ")
    assert engines.engine_for("web") == "v2"
    assert engines.engine_for("miniapp") == "v1"
    # `tg-bot` - `bot` ning taxallusi, `legacy` - versiyasiz yo'l.
    assert engines.engine_for("bot") == ""
    assert engines.config_state()["byChannel"] == {
        "web": "v2", "miniapp": "v1", "bot": "", "desktop": "v2", "api": "v2"}


def test_notogri_sozlama_yiqitmaydi_va_aytiladi(monkeypatch):
    set_engines(monkeypatch, default="v3", by_channel="faks=v1,web=v9,miniapp")
    assert engines.engine_for("web") == engines.DEFAULT_ENGINE == "v2"
    state = engines.config_state()
    assert state["default"] == "v2"
    assert len(state["problems"]) == 4, state["problems"]
    assert any("HRM_ASSISTANT_ENGINE='v3'" in p for p in state["problems"])


def test_oqim_yoli_dvigateldan():
    assert stream_path("v1") == "/api/v1/chat/stream"
    assert stream_path("v2") == "/api/v2/chat/stream"
    assert stream_path("") == "/api/chat/stream"
    with pytest.raises(ValueError):
        stream_path("v3")
    with pytest.raises(ValueError):
        make_client().stream("savol", user_id="venera:1", engine="../../admin")


# ================================================================ kanal -> yo'l


def test_web_v2_mini_app_istisnosi_bilan_v1(api, auth, upstream, db, monkeypatch):
    set_engines(monkeypatch, by_channel="miniapp=v1")
    web = ask(api, auth, "web")
    mini = ask(api, auth, "miniapp")
    assert web.status_code == mini.status_code == 200
    assert [c["path"] for c in upstream.stream_calls()] == [
        "/api/v2/chat/stream", "/api/v1/chat/stream"]
    # Kadrlar O'ZGARISHSIZ: `done.engine` brauzerga ham boradi.
    assert json.loads(web.text.splitlines()[-1])["engine"] == "v2"
    engines_of = {r["channel"]: r["engine"] for r in rows(db, "SELECT channel, engine FROM turns")}
    assert engines_of == {"web": "v2", "miniapp": "v1"}


def test_versiyasiz_yol_va_dvigatel_yozilmaydi(api, auth, upstream, db, monkeypatch):
    """Bo'sh `HRM_ASSISTANT_ENGINE` - prod bugungi yo'li (`/api/chat/stream`).
    Javobda `engine` yo'q - izda NULL ("default")."""
    set_engines(monkeypatch, default="")
    response = ask(api, auth)
    assert response.status_code == 200
    assert upstream.stream_calls()[0]["path"] == "/api/chat/stream"
    [turn] = rows(db, "SELECT engine FROM turns")
    assert turn["engine"] is None


def test_done_engine_sorovdan_ustun(api, auth, upstream, db):
    """Xizmat savolni boshqa dvigatelga yo'naltirsa - izda JAVOB BERGANI."""
    upstream.done_engine = "v1"
    response = ask(api, auth)
    assert upstream.stream_calls()[0]["path"] == "/api/v2/chat/stream"
    turn_id = response.headers["x-venera-turn"]
    [turn] = rows(db, "SELECT engine FROM turns WHERE id=?", (turn_id,))
    assert turn["engine"] == "v1"
    [done] = rows(db, "SELECT payload FROM turn_events WHERE turn_id=? AND name='done'",
                  (turn_id,))
    assert json.loads(done["payload"])["engine"] == "v1"
    [opened] = rows(db, "SELECT payload FROM turn_events WHERE turn_id=? AND name="
                        "'assistant.open'", (turn_id,))
    assert json.loads(opened["payload"])["engine"] == "v2"


def test_done_da_engine_bolmasa_soralgani_yoziladi(api, auth, upstream, db):
    upstream.done_engine = ""
    ask(api, auth)
    [turn] = rows(db, "SELECT engine FROM turns")
    assert turn["engine"] == "v2"


def test_bot_kanali_ham_oz_dvigatelida(upstream, monkeypatch, tmp_path):
    import app.api.v1.chat as chat_module
    from app.services.integrations.crm_auth import CrmAuth

    monkeypatch.setattr(chat_module, "_assistant", make_client())
    monkeypatch.setattr(chat_module, "_crm", CrmAuth("", "", "", tmp_path / "crm"))
    monkeypatch.setattr(chat_module, "platform_tokens", dict)
    set_engines(monkeypatch, by_channel="bot=v1")
    from app.bot.runner import Backend

    user = AuthUser(actorId=3, email="bot@venera.uz", fullName="Bot Odam")
    stream = Backend().stream("savol", user, "c-1")
    frames_of(stream)
    assert upstream.stream_calls()[0]["path"] == "/api/v1/chat/stream"
    assert stream.engine == "v1" and Backend().engine() == "v1"


def test_ask_dvigatel_va_pro_qaytaradi(upstream):
    result = make_client().ask("savol", user_id="venera:1", engine="v2")
    assert result["engine"] == "v2" and result["pro"] is None
    assert result["answer"] == "Javob [1]."


# ================================================================ qonunchilik manbasi


LAW = {"kind": "law", "citation_index": 2, "title": LAW_TITLE, "url": LEX, "doc_id": None,
       "page": None, "preview_available": None}


def test_qonun_manbasi_ozgarishsiz_otadi(upstream):
    upstream.sources = [dict(upstream.sources[0]), dict(LAW)]
    sources = frames_of(make_client().stream("savol", user_id="venera:1", engine="v2"))[1]
    doc, law = sources["items"]
    assert law == LAW, "qonun manbasi o'zgarishsiz (hujjat havolasisiz) o'tadi"
    assert "docUrl" not in law
    assert doc["docUrl"] == "/api/v1/chat/doc/HR_045#page=4"


@pytest.mark.parametrize(("url", "expected"), [
    (LEX, LEX),
    # LEX.UZ shifrsiz - https ga ko'tariladi.
    ("http://lex.uz/docs/6257288", "https://lex.uz/docs/6257288"),
    ("javascript:alert(document.cookie)", None),
    ("JavaScript:alert(1)", None),
    ("data:text/html;base64,PHNjcmlwdD4=", None),
    ("vbscript:msgbox(1)", None),
    ("http://evil.example/lex.uz", None),
    ("//evil.example/x", None),
    ("https://www.lex.uz@evil.example/", None),
    ("https://lex.uz/a\nb", None),
    ("https:///lex", None),
    ("", None),
    (None, None),
    (42, None),
])
def test_xavfli_havola_tozalanadi(upstream, url, expected):
    law = {**LAW, "url": url}
    upstream.sources = [law]
    [item] = frames_of(make_client().stream("savol", user_id="venera:1", engine="v2"))[1]["items"]
    assert item["url"] == expected
    # Manbaning o'zi qoladi - faqat havola yo'q.
    assert (item["kind"], item["title"]) == ("law", LAW_TITLE)


def test_boshqa_https_domen_otadi_lekin_jurnalga_yoziladi(caplog):
    with caplog.at_level(logging.WARNING, logger=assistant_mod.__name__):
        assert safe_source_url("https://norma.uz/modda/160") == "https://norma.uz/modda/160"
    assert "LEX.UZ emas: norma.uz" in caplog.text
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=assistant_mod.__name__):
        assert safe_source_url(LEX) == LEX
    assert caplog.text == ""


def test_qonun_manbasi_doc_id_bilan_kelsa_ham_korsatkichga_bormaydi(upstream):
    upstream.sources = [{**LAW, "doc_id": "HR_045", "docUrl": "/api/v1/chat/doc/HR_045"}]
    [item] = frames_of(make_client().stream("savol", user_id="venera:1", engine="v2"))[1]["items"]
    assert "docUrl" not in item


def test_qonun_manbasi_izga_yoziladi(api, auth, upstream, db):
    upstream.sources = [dict(upstream.sources[0]), dict(LAW)]
    response = ask(api, auth)
    turn_id = response.headers["x-venera-turn"]
    sources = rows(db, "SELECT kind, ref, title, citation FROM turn_sources WHERE turn_id=? "
                       "ORDER BY idx", (turn_id,))
    assert sources[1] == {"kind": "law", "ref": LEX, "title": LAW_TITLE, "citation": 2}
    [turn] = rows(db, "SELECT sources_count, tool_calls FROM turns WHERE id=?", (turn_id,))
    assert (turn["sources_count"], turn["tool_calls"]) == (2, 0)


# ================================================================ bot: qonun havolasi


def test_bot_qonun_manbasini_havola_bilan_korsatadi():
    docs = [{"kind": "doc", "doc_id": "HR_045", "title": "Ichki tartib", "page": 4,
             "citation_index": 1}, dict(LAW)]
    block = render.sources_block(docs)
    assert "[1] Ichki tartib, 4-bet" in block
    assert (f'[2] LEX.UZ · qonunchilik: <a href="{LEX}">{LAW_TITLE}</a>') in block
    # Hujjat ko'ruvchisi tugmasi FAQAT hujjatga - qonun moddasiga yo'q.
    buttons = render.doc_buttons(docs)
    assert buttons == {"inline_keyboard": [[{"text": "📄 Hujjatni ochish", "callback_data": "d:HR_045"}]]}
    # Telegram belgilashni rad etsa - teglarsiz, lekin manzil ko'rinib turadi.
    assert f"{LAW_TITLE} ({LEX})" in render.plain(block)
    # Xabarlarga bo'linganda teg butun qoladi.
    [chunk] = render.pack([block])
    assert chunk.count("<a href=") == chunk.count("</a>") == 1


@pytest.mark.parametrize("url", ["javascript:alert(1)", 'https://lex.uz/"><b>x', None])
def test_bot_xavfli_qonun_havolasi_matn_bolib_qoladi(url):
    line = render.law_line({**LAW, "url": url}, 1)
    if url and url.startswith("https://"):
        # Qo'shtirnoq atributdan chiqa olmaydi - escape qilingan.
        assert '"><b>' not in line and "&quot;" in line
    else:
        assert "<a " not in line and line.startswith("[2] LEX.UZ · qonunchilik: ")


def test_bot_qonun_manbasi_nomsiz_bolsa_yorliq_havola():
    line = render.law_line({"kind": "law", "url": LEX}, 0)
    assert line == f'[1] <a href="{LEX}">LEX.UZ · qonunchilik</a>'


def test_bot_javobida_qonun_havolasi(tmp_path):
    from test_telegram_bot import TG_ID, FakeBackend, FakeTelegram, _frames, text_update

    from app.bot.runner import VeneraBot
    from app.core.security import hash_password
    from app.services.telegram_links import LinkStore
    from app.services.users import StoredUser, UserStore

    users = UserStore({"a@b.uz": StoredUser(actor_id=1, email="a@b.uz", full_name="Ali Valiyev",
                                            password_hash=hash_password("x"))})
    tg, links, backend = FakeTelegram(), LinkStore(tmp_path / "links.json"), FakeBackend()
    bot = VeneraBot(tg, links, users=lambda: users, backend=backend,
                    webapp_url="https://llm.test/tg/", inline=True, typing_every=None)
    links.link(TG_ID, 1)
    backend.frames = _frames(
        {"type": "sources", "items": [
            {"kind": "doc", "doc_id": "HR_045", "title": "Ichki tartib", "citation_index": 1},
            dict(LAW)]},
        {"type": "token", "text": "Ogohlantirish kerak [1] [2]."},
        {"type": "done", "route": "rules", "engine": "v2"})
    bot.handle_update(text_update("shartnomani bekor qilsam?"))
    answer = tg.sent()[-1]
    assert f'<a href="{LEX}">' in answer["text"] and "LEX.UZ · qonunchilik" in answer["text"]
    datas = [b["callback_data"] for row in answer["reply_markup"]["inline_keyboard"] for b in row]
    # "⚑" (`r:`) - javob haqida xabar berish; hujjat tugmasi (`d:`) faqat hujjatga.
    assert [d for d in datas if not d.startswith("r:")] == ["d:HR_045"], \
        "qonun moddasi /doc ga yo'naltirilmaydi"


# ================================================================ navbat: oqib ketgan joy


def test_boshlanmagan_oqimlar_tashlansa_keyingisi_joy_oladi(upstream):
    """REGRESSIYA (29-sentabr): oqim ochiladi, lekin hech o'qilmaydi va
    tashlanadi (brauzer tanadan oldin uzildi). Ilgari har biri joyni abadiy
    egallardi - `max_concurrent` tadan keyin har savol 503 edi."""
    client = make_client(max_concurrent=2)
    for _ in range(5):
        dropped = [client.stream("savol", user_id="venera:1", engine="v2") for _ in range(2)]
        assert client.busy() == 2
        del dropped
        gc.collect()
        assert client.busy() == 0
    assert frames_of(client.stream("savol", user_id="venera:1", engine="v2"))[-1]["type"] == "done"
    assert client.busy() == 0
    assert len(upstream.stream_calls()) == 11


def test_close_boshlanmagan_oqim_joyini_darhol_qaytaradi(upstream):
    client = make_client(max_concurrent=1)
    stream = client.stream("savol", user_id="venera:1", engine="v2")
    assert client.busy() == 1
    stream.close()
    assert client.busy() == 0
    stream.close()                                   # idempotent
    other = client.stream("savol", user_id="venera:1", engine="v2")
    stream.close()                                   # kech chaqiruv boshqaning joyiga tegmaydi
    assert client.busy() == 1
    frames_of(other)
    assert client.busy() == 0


def test_soxta_oqimda_close_xato_bermaydi():
    AnswerStream(request_id="r", frames=iter([b"{}\n"])).close()


def test_tsiklda_qolgan_oqimlar_navbat_toliganda_yigiladi(upstream):
    """Oqim yetib bo'lmaydigan TSIKLDA qolgan (masalan uzilgan klient
    istisnosining traceback'i ushlab turibdi) va avtomatik yig'ish hali
    kelmagan. Navbat to'lganda klient o'zi yig'adi - joy halol qaytadi."""
    client = make_client(max_concurrent=2)
    gc.collect()
    gc.disable()
    try:
        for _ in range(2):
            holder: dict = {"stream": client.stream("savol", user_id="venera:1", engine="v2")}
            holder["self"] = holder                  # tsikl: refcount uni hech qachon bo'shatmaydi
            del holder
        assert client.busy() == 2
        stream = client.stream("savol", user_id="venera:1", engine="v2")
        assert client.busy() == 1
        frames_of(stream)
    finally:
        gc.enable()
    assert client.busy() == 0
    assert client.slots_state()["reclaimed"] == 0, "yig'ish halol qaytardi - majburlash kerak emas"


def test_ushlanib_qolgan_eskirgan_joy_qaytarib_olinadi(upstream, caplog):
    """Eng yomon holat: oqim obyekti TIRIK (kimdir ushlab turibdi) va hech
    o'qilmaydi. Na `finally`, na yig'ish yordam beradi - navbat uni `timeout`
    + zahiradan keyin "tashlab ketilgan" deb qaytarib oladi, ERROR bilan."""
    clock = Clock()
    client = make_client(max_concurrent=2, clock=clock)
    stuck = [client.stream("savol", user_id="venera:1", engine="v2") for _ in range(2)]
    with pytest.raises(AssistantError) as info:
        client.stream("savol", user_id="venera:1", engine="v2")
    assert (info.value.status, info.value.reason) == (503, "queue_full")
    calls = len(upstream.calls)

    clock.now += client.timeout + assistant_mod._LEASE_GRACE + 1
    with caplog.at_level(logging.ERROR, logger=assistant_mod.__name__):
        fresh = client.stream("savol", user_id="venera:1", engine="v2")
    assert "2 ta oqib ketgan joy qaytarib olindi" in caplog.text
    assert client.slots_state()["reclaimed"] == 2
    assert len(upstream.calls) == calls + 1
    # Eski oqimlar keyin yopilsa - yangi savolning joyiga TEGMAYDI.
    for stream in stuck:
        stream.close()
    assert client.busy() == 1
    frames_of(fresh)
    assert client.busy() == 0


def test_oqilayotgan_oqim_qaytarib_olinmaydi(upstream):
    """Tirik (o'qilayotgan) oqim jim chegaraga yetmagan - navbat uni tegmaydi
    va to'la navbat halol `queue_full` beradi."""
    clock = Clock()
    client = make_client(max_concurrent=1, clock=clock)
    upstream.on_read = lambda: setattr(clock, "now", clock.now + 30)
    live = client.stream("savol", user_id="venera:1", engine="v2")
    iterator = iter(live.frames)
    next(iterator)                                   # o'qildi - "tirik"
    clock.now += client.timeout + assistant_mod._LEASE_GRACE - 1
    with pytest.raises(AssistantError) as info:
        client.stream("savol", user_id="venera:1", engine="v2")
    assert info.value.reason == "queue_full"
    assert client.slots_state()["reclaimed"] == 0
    live.close()
    assert client.busy() == 0


def test_qari_ijara_ham_qaytariladi():
    """Doim "tirik" ko'ringan, lekin umri `max_age` dan oshgan joy (oqim muddati
    chegaralangan - bunday joy tirik bo'lishi mumkin emas)."""
    clock = Clock()
    pool = _SlotPool(1, idle_after=10, max_age=100, clock=clock)
    lease = pool.acquire()
    for _ in range(11):                              # 99 s: hali chegarada
        clock.now += 9
        lease.touch()
    assert pool.acquire() is None
    clock.now += 9                                   # 108 s > max_age
    lease.touch()
    assert pool.acquire() is not None
    assert pool.reclaimed == 1
    assert lease.release() is False, "qaytarib olingan ijara ikkinchi marta bo'shatilmaydi"
    assert pool.busy() == 1


def test_oqim_muddati_oshsa_uziladi(upstream):
    clock = Clock()
    client = make_client(clock=clock, max_stream_seconds=60)
    upstream.on_read = lambda: setattr(clock, "now", clock.now + 25)
    stream = client.stream("savol", user_id="venera:1", engine="v2")
    with pytest.raises(AssistantError) as info:
        frames_of(stream)
    assert (info.value.status, info.value.reason) == (504, "stream_deadline")
    assert client.busy() == 0


# --- endpoint: tashlab ketilgan javob tanasi -----------------------------------------------


class _Request:
    headers = {"X-Venera-Client": "web"}


USER = AuthUser(actorId=7, email="uzilgan@venera.uz", fullName="Uzilgan Xodim")


@pytest.fixture
def captured(monkeypatch, upstream, tmp_path):
    """Endpointni HTTP'siz chaqirish: javob tanasi (generator) qo'lda boshqariladi."""
    import app.api.v1.chat as chat_module
    from app.services.integrations.crm_auth import CrmAuth

    got: dict = {}

    class Capture:
        def __init__(self, content, media_type=None, headers=None) -> None:
            got["content"], got["headers"] = content, headers

    monkeypatch.setattr(chat_module, "StreamingResponse", Capture)
    monkeypatch.setattr(chat_module, "_assistant", make_client(max_concurrent=2))
    monkeypatch.setattr(chat_module, "_crm", CrmAuth("", "", "", tmp_path / "crm"))
    monkeypatch.setattr(chat_module, "platform_tokens", dict)
    return chat_module, got


def test_endpoint_tanasi_boshlanmagan_javoblar_navbatni_toldirmaydi(captured, db):
    chat_module, got = captured
    for _ in range(chat_module._assistant.max_concurrent + 3):
        chat_module.stream(StreamRequest(question="salom"), _Request(), user=USER)
        got.clear()                                  # brauzer tanadan OLDIN uzildi
        gc.collect()
    assert chat_module._assistant.busy() == 0
    chat_module.stream(StreamRequest(question="salom"), _Request(), user=USER)
    assert json.loads(list(got["content"])[-1])["type"] == "done"
    assert chat_module._assistant.busy() == 0
    statuses = [r["status"] for r in rows(db, "SELECT status FROM turns ORDER BY started_at")]
    assert statuses == ["cancelled"] * 5 + ["ok"]


def test_endpoint_tsikldagi_javob_tanasi_ham_qaytadi(captured):
    chat_module, got = captured
    gc.collect()
    gc.disable()
    try:
        for _ in range(chat_module._assistant.max_concurrent):
            chat_module.stream(StreamRequest(question="salom"), _Request(), user=USER)
            holder = {"body": got.pop("content")}
            holder["self"] = holder
            del holder
        assert chat_module._assistant.busy() == 2
        # Navbat to'la - lekin savol 503 OLMAYDI: yig'ish tashlangan oqimlarni yopadi.
        chat_module.stream(StreamRequest(question="salom"), _Request(), user=USER)
        list(got["content"])
    finally:
        gc.enable()
    assert chat_module._assistant.busy() == 0


def test_endpoint_uzilgan_klient_joyni_qaytaradi(captured):
    chat_module, got = captured
    chat_module.stream(StreamRequest(question="salom"), _Request(), user=USER)
    body = got["content"]
    next(body)
    body.close()
    assert chat_module._assistant.busy() == 0


# ================================================================ ochilmagan savol sababi


def test_bizning_navbat_toliq_yuqoriga_bormaydi(api, auth, upstream, db, monkeypatch, caplog):
    import app.api.v1.chat as chat_module

    monkeypatch.setattr(chat_module, "_assistant", make_client(max_concurrent=1))
    held = chat_module._assistant.stream("band", user_id="venera:9", engine="v2")
    opened = len(upstream.calls)
    with caplog.at_level(logging.WARNING):
        response = ask(api, auth)
    assert response.status_code == 503
    assert response.json()["message"] == BUSY_TEXT
    assert len(upstream.calls) == opened, "yuqoridagi xizmatga BORILMAGAN"
    [turn] = rows(db, "SELECT error_code, http_status, status, engine FROM turns")
    assert turn == {"error_code": "queue_full", "http_status": 503, "status": "error",
                    "engine": "v2"}
    assert "[queue_full]" in caplog.text
    held.close()


@pytest.mark.parametrize(("error", "code"), [
    (urllib.error.URLError(ConnectionRefusedError(111, "Connection refused")),
     "upstream_unreachable"),
    (urllib.error.URLError("timed out"), "upstream_unreachable"),
    (ConnectionResetError(104, "reset"), "upstream_unreachable"),
    (urllib.error.HTTPError(f"{BASE}/api/v2/chat/stream", 503, "busy", {},
                            io.BytesIO(b'{"detail":"LLM navbati"}')), "upstream_busy"),
    (urllib.error.HTTPError(f"{BASE}/api/v2/chat/stream", 500, "xato", {},
                            io.BytesIO(b'{"detail":"x"}')), "open_failed"),
])
def test_ochilmagan_savol_sababi_alohida(api, auth, upstream, db, error, code, caplog):
    upstream.error = error
    with caplog.at_level(logging.WARNING):
        response = ask(api, auth)
    [turn] = rows(db, "SELECT error_code, http_status FROM turns")
    assert turn["error_code"] == code
    if code != "open_failed":
        # Foydalanuvchiga bir xil "band" - sababni faqat admin ko'radi.
        assert (response.status_code, response.json()["message"]) == (503, BUSY_TEXT)
        assert f"[{code}]" in caplog.text
    else:
        assert response.status_code == 502
    # Har holatda joy qaytdi.
    import app.api.v1.chat as chat_module

    assert chat_module._assistant.busy() == 0


def test_bot_ham_sababni_yozadi(tmp_path, db):
    from test_telegram_bot import TG_ID, FakeBackend, FakeTelegram, text_update

    from app.bot.runner import VeneraBot
    from app.core.security import hash_password
    from app.services.telegram_links import LinkStore
    from app.services.users import StoredUser, UserStore

    users = UserStore({"a@b.uz": StoredUser(actor_id=1, email="a@b.uz", full_name="Ali Valiyev",
                                            password_hash=hash_password("x"))})
    tg, links, backend = FakeTelegram(), LinkStore(tmp_path / "links.json"), FakeBackend()
    bot = VeneraBot(tg, links, users=lambda: users, backend=backend,
                    webapp_url="https://llm.test/tg/", inline=True, typing_every=None)
    links.link(TG_ID, 1)
    backend.open_error = AssistantError("navbat to'la", status=503, reason="queue_full")
    bot.handle_update(text_update("savol"))
    assert tg.texts()[-1] == "⚠️ " + BUSY_TEXT
    [turn] = rows(db, "SELECT error_code, channel FROM turns")
    assert (turn["error_code"], turn["channel"]) == ("queue_full", "bot")


# ================================================================ tashxis


def test_health_detail_dvigatel_va_navbatni_korsatadi(client, auth, monkeypatch):
    set_engines(monkeypatch, by_channel="miniapp=v1,faks=v2")
    body = client.get("/api/health/detail", headers=auth).json()
    assistant = body["assistant"]
    assert assistant["engine"]["default"] == "v2"
    assert assistant["engine"]["byChannel"]["miniapp"] == "v1"
    assert set(assistant["slots"]) == {"busy", "limit", "oldestSec", "idlestSec", "reclaimed"}
    # Noto'g'ri yozuv - ogohlantirishda, server esa ishlaydi.
    assert any("faks=v2" in w for w in body["warnings"])
    # Ochiq holatda hech biri yo'q.
    assert "assistant" not in client.get("/api/health").json()


# ================================================================ Mini App


def test_mini_app_qonun_manbasini_tashqi_havola_qiladi():
    """`apps/tg/app.js`: qonun moddasi - Telegram'ning tashqi brauzerida
    (`openLink`), zaxira - `noopener` bilan yangi oyna; faqat `https`.
    Hujjat ko'ruvchisiga (`/chat/doc`) yo'naltirilmaydi. "Pro" yo'q."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[3] / "apps" / "tg" / "app.js").read_text(
        encoding="utf-8")
    assert "const LAW_LABEL = 'LEX.UZ · qonunchilik';" in src
    assert "tg.openLink(url);" in src
    assert "window.open(url, '_blank', 'noopener,noreferrer')" in src
    assert "u.protocol !== 'https:'" in src
    assert "link.rel = 'noopener noreferrer';" in src
    # Sarlavha MATN bo'lib qo'yiladi - HTML sifatida emas.
    assert "link.textContent = s.title || LAW_LABEL;" in src
    body = src[src.index("async function streamAsk"):]
    body = body[:body.index("});")]
    assert "mode" not in body, "Mini App 'Pro' yubormaydi"
