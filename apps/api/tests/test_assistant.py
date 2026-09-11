"""HR Assistant integratsiyasi: NDJSON oqimi, havolalar va xatolar.

Yuqoridagi xizmatning O'ZI chaqirilmaydi: u ichki tarmoqda va CI da yo'q.
Almashtirish nuqtasi `build_opener` - ya'ni faqat TRANSPORT soxta, ustidagi
hamma mantiq (kadrlarni tekshirish, havolalarni qayta yozish, sirni
yashirish, navbat chegarasi, xatoni foydalanuvchi xabariga o'girish)
haqiqiy kod bo'lib qoladi.
"""

from __future__ import annotations

import http.client
import io
import json
import urllib.error
import urllib.request

import pytest

from app.services.integrations import assistant as mod
from app.services.integrations.assistant import (
    AssistantClient,
    AssistantError,
    _filename,
    token_seconds_left,
    token_warning,
)

BASE = "http://assistant.test"
SECRET = "super-secret-value"


def frame(**kw) -> bytes:
    return json.dumps(kw, ensure_ascii=False).encode("utf-8") + b"\n"


DEFAULT_FRAMES = [
    frame(type="stage", stage="retrieval", text="Hujjatlar qidirilmoqda"),
    frame(type="sources", sources=[
        {"kind": "doc", "doc_id": "policy-7", "title": "Mehnat kodeksi", "page": 12,
         "citation_index": 1},
        {"kind": "hrm", "marker": "[T1]", "tool": "hrm_today_late", "status": "ok"},
    ]),
    frame(type="token", text="Yillik ta'til "),
    frame(type="token", text="21 kalendar kun."),
    frame(type="done", route="both", request_id="rid-777"),
]


class _NdjsonResponse:
    """Qator-qator beradigan javob - haqiqiy chunked NDJSON kabi."""

    def __init__(self, lines, headers=None, cut_after=None, timeout_after=None) -> None:
        self._lines = list(lines)
        self.headers = headers or {}
        self._cut_after = cut_after
        self._timeout_after = timeout_after
        self._served = 0
        self.closed = False

    def readline(self, limit: int = -1) -> bytes:
        if self._timeout_after is not None and self._served >= self._timeout_after:
            raise TimeoutError("read timed out")
        if self._cut_after is not None and self._served >= self._cut_after:
            raise http.client.IncompleteRead(b"", 1)
        if not self._lines:
            return b""
        self._served += 1
        return self._lines.pop(0)

    def read(self, size: int = -1) -> bytes:
        if not self._lines:
            return b""
        return self._lines.pop(0)

    def close(self) -> None:
        self.closed = True


class FakeServer:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.frames = list(DEFAULT_FRAMES)
        self.status: int | None = None
        #: Xizmat 422 da so'rov TANASINI qaytarishi mumkin - unda bizning
        #: sirimiz bo'lishi ehtimoli bor, va u xabarga tushmasligi kerak.
        self.echo_secret = False
        self.cut_after: int | None = None
        self.timeout_after: int | None = None
        self.response_headers: dict[str, str] = {"X-Request-Id": "served-1"}
        self.file_bytes = b"%PDF-1.4 fake"
        self.file_headers = {"Content-Type": "application/pdf",
                             "Content-Disposition": 'attachment; filename="ariza.pdf"'}
        self.last: _NdjsonResponse | None = None

    def open(self, request, timeout=None):
        path = "/" + request.full_url.split("://", 1)[1].split("/", 1)[1]
        self.calls.append({
            "path": path,
            "method": request.get_method(),
            "body": json.loads(request.data) if request.data else None,
            "client_id": request.get_header("X-client-id"),
            "client_secret": request.get_header("X-client-secret"),
            "request_id": request.get_header("X-request-id"),
            "accept": request.get_header("Accept"),
            "encoding": request.get_header("Accept-encoding"),
        })
        if self.status:
            detail = f"body was {{'client_secret': '{SECRET}'}}" if self.echo_secret else "xato"
            raise _http_error(path, self.status, detail)
        if path == "/api/chat/stream":
            self.last = _NdjsonResponse(self.frames, self.response_headers,
                                        cut_after=self.cut_after,
                                        timeout_after=self.timeout_after)
            return self.last
        self.last = _NdjsonResponse([self.file_bytes], self.file_headers)
        return self.last


def _http_error(path: str, code: int, detail: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        f"{BASE}{path}", code, detail, {},
        io.BytesIO(json.dumps({"detail": detail}).encode()),
    )


@pytest.fixture
def server(monkeypatch):
    fake = FakeServer()

    class Opener:
        def open(self, request, timeout=None):
            return fake.open(request, timeout)

    monkeypatch.setattr(urllib.request, "build_opener", lambda *a, **kw: Opener())
    return fake


@pytest.fixture
def assistant(server) -> AssistantClient:
    return AssistantClient(BASE, "venera", SECRET, timeout=5, max_concurrent=2)


def collect(stream) -> list[dict]:
    return [json.loads(line) for line in stream.frames]


# --- so'rov ---------------------------------------------------------------


def test_soro_vni_kredensial_bilan_yuboradi(assistant, server):
    stream = assistant.stream("Ta'til necha kun?", user_id="venera:21", chat_id="c-1")
    collect(stream)

    call = server.calls[0]
    assert call["path"] == "/api/chat/stream"
    assert call["method"] == "POST"
    assert call["client_id"] == "venera"
    assert call["client_secret"] == SECRET
    assert call["body"] == {"question": "Ta'til necha kun?", "user_id": "venera:21",
                            "chat_id": "c-1"}
    assert call["accept"] == "application/x-ndjson"
    # Siqish ATAYLAB so'ralmaydi: gzip kadrlarni buferga to'plab, oqimning
    # ma'nosini yo'q qilardi.
    assert call["encoding"] == "identity"


def test_bosh_maydonlar_yuborilmaydi(assistant, server):
    """`chat_id` bo'sh bo'lsa YUBORILMAYDI - bo'sh satr yuqoridagi xizmatda
    "shu nomli suhbat" bo'lib qolardi va hamma xotirasiz turn bir joyga
    to'planardi."""
    collect(assistant.stream("salom", user_id="venera:1"))
    assert set(server.calls[0]["body"]) == {"question", "user_id"}


def test_hrm_tokeni_tokens_xaritasida_ketadi(assistant, server):
    """`tokens: {"hrm": ...}`, `hrm_token` EMAS - jonli o'lchov: qisqa
    shakl bilan xizmat `auth_missing` qaytaradi, xarita bilan esa to'liq
    javob beradi (bir xil token, 2026-09-11)."""
    collect(assistant.stream("Men bugun kechikdimmi?", user_id="venera:1",
                             hrm_token="hrm-jwt", hrm_employee="Mamajonov"))
    body = server.calls[0]["body"]
    assert body["tokens"] == {"hrm": "hrm-jwt"}
    assert body["hrm_employee"] == "Mamajonov"
    # Buzuq yo'l ustun kelib qolmasligi uchun qisqa shakl YUBORILMAYDI.
    assert "hrm_token" not in body


def test_audit_kaliti_yuboriladi_va_xizmatnikisi_ustun(assistant, server):
    """`X-Request-Id` biz tomonidan yuboriladi, lekin xizmat o'zinikini
    qaytarsa AUDIT kaliti o'shanikisi - ikki tizimda bir kalit bilan
    izlash uchun."""
    stream = assistant.stream("salom", user_id="venera:1")
    assert server.calls[0]["request_id"]
    assert stream.request_id == "served-1"


def test_sozlanmagan_klient_hech_narsa_yubormaydi(server):
    """Kredensialsiz savol TARMOQQA CHIQMAYDI: xizmat 401 qaytarardi va u
    foydalanuvchiga "sessiyangiz tugadi" bo'lib ko'rinardi."""
    blank = AssistantClient(BASE, "", "", timeout=5)
    assert blank.configured is False
    with pytest.raises(AssistantError) as exc:
        blank.stream("salom", user_id="venera:1")
    assert exc.value.status == 501
    assert server.calls == []


@pytest.mark.parametrize("question", ["", "   "])
def test_bosh_savol_rad_etiladi(assistant, server, question):
    with pytest.raises(AssistantError) as exc:
        assistant.stream(question, user_id="venera:1")
    assert exc.value.status == 400
    assert server.calls == []


def test_juda_uzun_savol_yuborilmaydi(assistant, server):
    with pytest.raises(AssistantError) as exc:
        assistant.stream("a" * 50, user_id="venera:1", max_chars=10)
    assert exc.value.status == 400
    assert server.calls == []


# --- kadrlar --------------------------------------------------------------


def test_kadrlar_otadi(assistant):
    frames = collect(assistant.stream("salom", user_id="venera:1"))
    assert [f["type"] for f in frames] == ["stage", "sources", "token", "token", "done"]
    assert "".join(f["text"] for f in frames if f["type"] == "token") == \
        "Yillik ta'til 21 kalendar kun."


def test_natija_yakunda_yoziladi(assistant):
    stream = assistant.stream("salom", user_id="venera:1")
    collect(stream)
    assert stream.outcome["route"] == "both"
    assert stream.outcome["frames"] == 5


def test_buzuq_qatorlar_tashlanadi(assistant, server):
    """Buzuq kadrni o'zgarmasdan uzatish oson yo'l bo'lardi, lekin unda
    brauzerdagi tahlilchi HAR kadrda xatoga tayyor turishi kerak edi."""
    server.frames = [
        b"not json\n",
        b"[1, 2]\n",                        # obyekt emas
        frame(no_type_field=True),          # `type` yo'q
        frame(type=42),                     # `type` satr emas
        b"\n",
        frame(type="token", text="ok"),
    ]
    frames = collect(assistant.stream("salom", user_id="venera:1"))
    assert frames == [{"type": "token", "text": "ok"}]


def test_notanish_kadr_turi_otadi(assistant, server):
    """Xizmat yangi kadr qo'shsa, Venera'ni qayta yozmasdan ishlashi kerak."""
    server.frames = [frame(type="thinking", text="..."), frame(type="done", route="rules")]
    assert [f["type"] for f in collect(assistant.stream("s", user_id="venera:1"))] == \
        ["thinking", "done"]


def test_oqim_chegarasi(assistant, server, monkeypatch):
    """Cheksiz oqim serverni ham, brauzerni ham qulflab qo'yardi."""
    monkeypatch.setattr(mod, "_MAX_STREAM_BYTES", 200)
    server.frames = [frame(type="token", text="x" * 50) for _ in range(20)]
    frames = collect(assistant.stream("salom", user_id="venera:1"))
    assert 0 < len(frames) < 20


# --- havolalar ------------------------------------------------------------


def test_ariza_havolalari_venera_yoliga_ogiriladi(assistant, server):
    """Havola ICHKI manzilni ko'rsatadi - brauzer unga yetib bormaydi."""
    server.frames = [frame(
        type="artifact", title="Ariza", doc_id="d9",
        docx_url=f"{BASE}/api/hr/artifacts/tok-A1/docx",
        pdf_url="/api/hr/artifacts/tok-A1/pdf",
        preview_url=f"{BASE}/api/hr/artifacts/tok-A1/preview",
    )]
    art = collect(assistant.stream("ariza", user_id="venera:1"))[0]
    assert art["docx_url"] == "/api/v1/chat/artifact/tok-A1/docx"
    assert art["pdf_url"] == "/api/v1/chat/artifact/tok-A1/pdf"
    assert art["preview_url"] == "/api/v1/chat/artifact/tok-A1/preview"
    assert BASE not in json.dumps(art)


def test_ariza_kadri_ichma_ich_bolsa_ham(assistant, server):
    """Xizmat kadrni bir daraja pastga tushirsa havolalar JIMGINA ishlamay
    qo'yardi - shuning uchun ikkala shakl ham qo'llanadi."""
    server.frames = [frame(type="artifact", artifact={
        "title": "Ariza", "docx_url": f"{BASE}/api/hr/artifacts/tok-B2/docx"})]
    art = collect(assistant.stream("ariza", user_id="venera:1"))[0]
    assert art["artifact"]["docx_url"] == "/api/v1/chat/artifact/tok-B2/docx"


def test_tanilmagan_ichki_havola_olib_tashlanadi(assistant, server):
    """Ochilmaydigan havolani ko'rsatishdan ko'ra ko'rsatmaslik yaxshi, va
    ichki topologiya tashqariga chiqmaydi."""
    server.frames = [frame(type="artifact", docx_url=f"{BASE}/some/other/path")]
    art = collect(assistant.stream("ariza", user_id="venera:1"))[0]
    assert art["docx_url"] is None


def test_tashqi_havola_saqlanadi(assistant, server):
    """Ichki bo'lmagan havolaga tegilmaydi."""
    server.frames = [frame(type="artifact", docx_url="https://example.org/a.docx")]
    art = collect(assistant.stream("ariza", user_id="venera:1"))[0]
    assert art["docx_url"] == "https://example.org/a.docx"


def test_jonli_kadr_shakli(assistant, server):
    """AYNAN jonli xizmatdan kelgan shakl: iqtiboslar `items` ostida, hujjat
    kaliti `HR_045` - pastki chiziq bilan. Ikkalasi ham dastlabki kodda
    e'tibordan chetda qolgan va natijada manbalar ro'yxati JIMGINA bo'sh
    bo'lardi."""
    server.frames = [frame(type="sources", items=[
        {"kind": "doc", "doc_id": "HR_045", "title": "ichki mehnat tartibi qoidalari",
         "section": "70", "page": 22, "preview_available": True},
    ])]
    items = collect(assistant.stream("salom", user_id="venera:1"))[0]["items"]
    assert items[0]["docUrl"] == "/api/v1/chat/doc/HR_045#page=22"


def test_pastki_chiziqli_hujjat_kaliti_yuklanadi(assistant, server):
    assistant.fetch_doc("HR_045")
    assert server.calls[0]["path"] == "/doc/HR_045"


def test_iqtibos_hujjatiga_havola_qoshiladi(assistant):
    """Bank muhitida majburiy: xodim ASL hujjatni ocha olishi kerak."""
    sources = collect(assistant.stream("salom", user_id="venera:1"))[1]["sources"]
    doc, hrm = sources
    assert doc["docUrl"] == "/api/v1/chat/doc/policy-7#page=12"
    assert doc["doc_id"] == "policy-7"      # xizmatning o'z kaliti saqlanadi
    assert "docUrl" not in hrm              # HRM chaqiruvi hujjat emas


def test_yaroqsiz_hujjat_kaliti_havola_bermaydi(assistant, server):
    server.frames = [frame(type="sources", sources=[
        {"kind": "doc", "doc_id": "../../etc/passwd"},
        {"kind": "doc", "doc_id": ""},
    ])]
    sources = collect(assistant.stream("salom", user_id="venera:1"))[0]["sources"]
    assert all("docUrl" not in item for item in sources)


# --- xatolar --------------------------------------------------------------


def test_401_sozlama_xatosi_sifatida_502_ga_tushadi(assistant, server):
    """401 "bizning kredensial noto'g'ri" degani. Brauzerga 401 qaytarish
    foydalanuvchini mutlaqo joyida bo'lgan sessiyasidan chiqarib
    yuborardi."""
    server.status = 401
    with pytest.raises(AssistantError) as exc:
        assistant.stream("salom", user_id="venera:1")
    assert exc.value.status == 502


@pytest.mark.parametrize("status,expected", [
    (400, 400), (404, 404), (422, 422), (503, 503), (403, 502), (500, 502),
])
def test_status_xaritasi(assistant, server, status, expected):
    server.status = status
    with pytest.raises(AssistantError) as exc:
        assistant.stream("salom", user_id="venera:1")
    assert exc.value.status == expected


def test_sir_xato_matnida_qolmaydi(assistant, server):
    """Xizmat 422 da so'rov tanasini qaytarishi mumkin, va unda sir bo'ladi."""
    server.status = 422
    server.echo_secret = True
    with pytest.raises(AssistantError) as exc:
        assistant.stream("salom", user_id="venera:1")
    assert SECRET not in str(exc.value)
    assert "***" in str(exc.value)


def test_ulanmasa_503(assistant, server, monkeypatch):
    class Dead:
        def open(self, request, timeout=None):
            raise urllib.error.URLError("Connection refused")

    monkeypatch.setattr(urllib.request, "build_opener", lambda *a, **kw: Dead())
    with pytest.raises(AssistantError) as exc:
        assistant.stream("salom", user_id="venera:1")
    assert exc.value.status == 503
    assert exc.value.retryable is True


def test_oqim_ortasida_timeout(assistant, server):
    """Kadrlar orasidagi jimlik - nosozlik. Xato oqim ICHIDA chiqadi."""
    server.timeout_after = 2
    stream = assistant.stream("salom", user_id="venera:1")
    with pytest.raises(AssistantError) as exc:
        collect(stream)
    assert exc.value.status == 504


def test_oqim_ortasida_uzilish(assistant, server):
    """Ulanish uzilishi ham `AssistantError` bo'lishi SHART: chaqiruvchi
    faqat shu turni kutadi, boshqasi brauzerga kutilmagan uzilish bo'lib
    ko'rinardi."""
    server.cut_after = 2
    stream = assistant.stream("salom", user_id="venera:1")
    with pytest.raises(AssistantError) as exc:
        collect(stream)
    assert exc.value.status == 503


def test_juda_katta_kadr_oqimni_toxtatadi(assistant, server, monkeypatch):
    monkeypatch.setattr(mod, "_MAX_LINE_BYTES", 32)
    server.frames = [frame(type="token", text="x" * 500), frame(type="done", route="rules")]
    assert collect(assistant.stream("salom", user_id="venera:1")) == []


# --- navbat ---------------------------------------------------------------


def test_navbat_chegarasi(assistant, server):
    """Yuqorida bitta LLM turadi. Chegaradan oshsa xizmatga BORMASDAN 503 -
    navbatni boshqa chaqiruvchilar uchun to'ldirib qo'ymaslik uchun."""
    first = assistant.stream("a", user_id="venera:1")
    second = assistant.stream("b", user_id="venera:2")
    with pytest.raises(AssistantError) as exc:
        assistant.stream("c", user_id="venera:3")
    assert exc.value.status == 503
    assert exc.value.retryable is True

    collect(first)
    # Slot oqim TUGAGANDA bo'shaydi - javob kelganda emas.
    assistant.stream("d", user_id="venera:4")
    collect(second)


def test_slot_ochilmagan_oqimdan_keyin_qaytadi(assistant, server):
    """Birinchi nosozlik navbatni abadiy egallab qolmasligi kerak."""
    server.status = 500
    for _ in range(5):
        with pytest.raises(AssistantError):
            assistant.stream("salom", user_id="venera:1")
    server.status = None
    collect(assistant.stream("salom", user_id="venera:1"))


def test_uzilgan_oqim_ham_slotni_qaytaradi(assistant, server):
    server.cut_after = 1
    for _ in range(4):
        with pytest.raises(AssistantError):
            collect(assistant.stream("salom", user_id="venera:1"))
    server.cut_after = None
    collect(assistant.stream("salom", user_id="venera:1"))


def test_javob_yopiladi(assistant, server):
    collect(assistant.stream("salom", user_id="venera:1"))
    assert server.last.closed is True


# --- fayllar --------------------------------------------------------------


def test_ariza_fayli(assistant, server):
    content_type, name, chunks = assistant.fetch_artifact("tok-A1", "docx")
    assert content_type == "application/pdf"
    assert name == "ariza.pdf"
    assert b"".join(chunks) == b"%PDF-1.4 fake"
    assert server.calls[0]["path"] == "/api/hr/artifacts/tok-A1/docx"
    assert server.calls[0]["method"] == "GET"


@pytest.mark.parametrize("kind", ["preview", "docx", "pdf"])
def test_ariza_fayl_turlari(assistant, kind):
    assistant.fetch_artifact("tok-A1", kind)


def test_notogri_fayl_turi(assistant, server):
    with pytest.raises(AssistantError) as exc:
        assistant.fetch_artifact("tok-A1", "exe")
    assert exc.value.status == 400
    assert server.calls == []


@pytest.mark.parametrize("token", ["../../secret", "a b", "tok/../x", ""])
def test_yaroqsiz_fayl_kaliti(assistant, server, token):
    with pytest.raises(AssistantError) as exc:
        assistant.fetch_artifact(token, "docx")
    assert exc.value.status == 400
    assert server.calls == []


@pytest.mark.parametrize("doc_id", ["../../etc/passwd", "a/b", "", "x" * 200])
def test_yaroqsiz_hujjat_kaliti(assistant, server, doc_id):
    with pytest.raises(AssistantError) as exc:
        assistant.fetch_doc(doc_id)
    assert exc.value.status == 400
    assert server.calls == []


def test_hujjat_pdfi(assistant, server):
    assistant.fetch_doc("policy-7")
    assert server.calls[0]["path"] == "/doc/policy-7"


def test_fayl_chegarasi(assistant, server, monkeypatch):
    monkeypatch.setattr(mod, "_MAX_FILE_BYTES", 8)
    server.file_bytes = b"x" * 100
    _, _, chunks = assistant.fetch_doc("policy-7")
    assert len(b"".join(chunks)) <= 100      # birinchi bo'lakdan keyin to'xtaydi


@pytest.mark.parametrize("disposition,expected", [
    ('attachment; filename="ariza.docx"', "ariza.docx"),
    ('attachment; filename="ariza\r\n"evil.docx"', "ariza"),
    ("attachment; filename*=UTF-8''ta%27til.pdf", "ta_til.pdf"),
    ("", "policy-7"),
    # Yo'l ajratgichlari YO'QOLADI - nom sarlavhaga qo'yiladi, yo'lga emas.
    ('attachment; filename="../../etc/passwd"', "_.._etc_passwd"),
])
def test_fayl_nomi_tozalanadi(disposition, expected):
    """Nom to'g'ridan-to'g'ri sarlavhaga qo'yilsa, undagi `"` yoki yangi
    qator javob sarlavhasini buzib yuborardi."""
    assert _filename(disposition, "/doc/policy-7") == expected


# --- token holati ---------------------------------------------------------


def _jwt(exp: int | None) -> str:
    """Imzosiz, faqat `exp` bor JWT shakli - `token_seconds_left` imzoni
    tekshirmaydi va tekshirmasligi kerak (HRM ochiq kaliti bizda yo'q)."""
    import base64
    body = {} if exp is None else {"exp": exp}
    raw = base64.urlsafe_b64encode(json.dumps(body).encode()).decode().rstrip("=")
    return f"header.{raw}.signature"


def test_token_muddati_oqiladi():
    import time
    left = token_seconds_left(_jwt(int(time.time()) + 600))
    assert left is not None and 590 < left <= 600


def test_tugagan_token_manfiy_qaytaradi():
    import time
    left = token_seconds_left(_jwt(int(time.time()) - 30))
    assert left is not None and left < 0


@pytest.mark.parametrize("value", ["", "bir.qism", "a.b.c", "not-a-jwt", "a." * 3])
def test_yaroqsiz_token_yiqitmaydi(value):
    """Buzuq token DIAGNOSTIKANI buzmasligi kerak: `/api/health` shu
    funksiyani chaqiradi va u yiqilsa butun holat sahifasi yiqilardi."""
    assert token_seconds_left(value) is None


def test_exp_yoq_bolsa_none():
    assert token_seconds_left(_jwt(None)) is None


def test_ogohlantirish_tugagan_tokenni_aytadi():
    import time
    note = token_warning(_jwt(int(time.time()) - 5))
    assert note and "MUDDATI TUGAGAN" in note


def test_ogohlantirish_umumiy_tokendan_xabar_beradi():
    """Umumiy token - VAQTINCHALIK yechim, va uni unutib qo'yish oson."""
    import time
    note = token_warning(_jwt(int(time.time()) + 3600))
    assert note and "TOKEN EGASI" in note


def test_token_yoq_bolsa_ogohlantirish_yoq():
    assert token_warning("") is None


def test_token_ogohlantirishida_tokenning_ozi_yoq():
    """Xabar `/api/health` javobiga tushadi - monitoring o'qiydi, log'ga
    yoziladi. Token MAZMUNI u yerga hech qachon tushmasligi kerak."""
    import time
    token = _jwt(int(time.time()) + 60)
    note = token_warning(token) or ""
    assert token not in note
    assert token.split(".")[1] not in note


# --- `.env` dan issiq o'qish ----------------------------------------------


def test_env_dan_yangi_token_restartsiz_olinadi(tmp_path, monkeypatch):
    """HRM sessiyasi bir necha daqiqada tugaydi. Sozlama obyekti faylni
    faqat import paytida o'qigan bo'lardi, ya'ni har almashtirishda
    restart kerak bo'lardi - va restart oqib turgan javoblarni kesardi."""
    from app.core import config

    env = tmp_path / ".env"
    env.write_text("SECRET_KEY=x\nhrm_token=birinchi\n")
    monkeypatch.setattr(config, "_ENV_FILE", env)
    monkeypatch.setattr(config, "_token_cache", (None, ""))
    assert config.hrm_token_now() == "birinchi"

    # Yangi qiymat - IMPORTGA TEGILMASDAN ko'rinishi kerak.
    env.write_text("SECRET_KEY=x\nhrm_token=ikkinchi\n")
    import os
    os.utime(env, (0, 0))          # `mtime` albatta boshqa bo'lsin
    assert config.hrm_token_now() == "ikkinchi"


def test_env_ozgarmasa_diskka_borilmaydi(tmp_path, monkeypatch):
    from app.core import config

    env = tmp_path / ".env"
    env.write_text("hrm_token=qiymat\n")
    monkeypatch.setattr(config, "_ENV_FILE", env)
    monkeypatch.setattr(config, "_token_cache", (None, ""))
    assert config.hrm_token_now() == "qiymat"

    reads = []
    original = config._read_env_value
    monkeypatch.setattr(config, "_read_env_value",
                        lambda *a, **kw: (reads.append(1), original(*a, **kw))[1])
    for _ in range(5):
        config.hrm_token_now()
    assert reads == [], "fayl o'zgarmagan, lekin qayta o'qilgan"


def test_fayl_oqilmasa_eski_qiymat_qoladi(tmp_path, monkeypatch):
    """Tahrirlash o'rtasida qolgan yoki o'chib ketgan fayl tufayli ishlab
    turgan chat to'xtab qolmasligi kerak."""
    from app.core import config

    env = tmp_path / ".env"
    env.write_text("hrm_token=ishlaydi\n")
    monkeypatch.setattr(config, "_ENV_FILE", env)
    monkeypatch.setattr(config, "_token_cache", (None, ""))
    assert config.hrm_token_now() == "ishlaydi"

    env.unlink()
    assert config.hrm_token_now() == "ishlaydi"


def test_kalit_olib_tashlansa_bosh_qaytadi(tmp_path, monkeypatch):
    """Fayl O'QILDI, lekin kalit yo'q - bu "token olib tashlandi" degani."""
    from app.core import config

    env = tmp_path / ".env"
    env.write_text("hrm_token=bor\n")
    monkeypatch.setattr(config, "_ENV_FILE", env)
    monkeypatch.setattr(config, "_token_cache", (None, ""))
    assert config.hrm_token_now() == "bor"

    env.write_text("SECRET_KEY=x\n")
    import os
    os.utime(env, (0, 0))
    assert config.hrm_token_now() == ""


@pytest.mark.parametrize("line,expected", [
    ("hrm_token=oddiy", "oddiy"),
    ("HRM_TOKEN=katta_harf", "katta_harf"),
    ('hrm_token="qo`shtirnoqda"', "qo`shtirnoqda"),
    ("hrm_token='bir tirnoqda'", "bir tirnoqda"),
    ("  hrm_token = bosh joylar  ", "bosh joylar"),
    ("# hrm_token=izohda\nhrm_token=haqiqiy", "haqiqiy"),
    ("hrm_token=birinchi\nhrm_token=oxirgi", "oxirgi"),
])
def test_env_qatori_turli_shaklda(tmp_path, line, expected):
    """`.env` ni odam qo'lda tahrirlaydi, ya'ni shakl har xil bo'ladi.
    Registr va qo'shtirnoq `pydantic-settings` da ham shunday ishlanadi."""
    from app.core.config import _read_env_value

    env = tmp_path / ".env"
    env.write_text(line + "\n")
    assert _read_env_value(env, "hrm_token") == expected


# --- yig'ib olish ---------------------------------------------------------


def test_ask_javobni_yigadi(assistant):
    result = assistant.ask("Ta'til necha kun?", user_id="venera:1")
    assert result["answer"] == "Yillik ta'til 21 kalendar kun."
    assert result["route"] == "both"
    assert result["requestId"] == "served-1"
    assert len(result["sources"]) == 2
    assert result["stages"] == ["Hujjatlar qidirilmoqda"]
    assert result["error"] is None


# --- endpoint: kimlik va sozlamadagi token ---------------------------------


@pytest.fixture
def api(monkeypatch, assistant, client):
    """Endpoint soxta transport ustida: `/chat/stream` ning O'ZI tekshiriladi.
    `client` - conftest'dagi HTTP klienti, `assistant` - shu fayldagi
    integratsiya klienti."""
    import app.api.v1.chat as module
    monkeypatch.setattr(module, "_assistant", assistant)
    return module, client


def test_endpoint_kimlikni_tokendan_oladi(api, auth, server):
    """`user_id` SO'ROV TANASIDAN emas, sessiyadan. Aks holda klient o'zini
    boshqa xodim deb tanishtirib, o'sha odamning suhbat tarixiga kirardi -
    xizmatda xotira `(user_id, chat_id)` bo'yicha saqlanadi."""
    _, app_client = api
    response = app_client.post("/api/v1/chat/stream", headers=auth,
                               json={"question": "salom", "chatId": "c-9",
                                     "user_id": "boshqa-odam"})
    assert response.status_code == 200
    body = server.calls[0]["body"]
    assert body["user_id"] == "venera:1"        # admin fikstura actor_id
    assert body["chat_id"] == "c-9"
    assert "boshqa-odam" not in json.dumps(body)


def test_endpoint_hrm_tokenini_har_sorovda_oqiydi(api, auth, server, monkeypatch):
    """Token `.env` dan HAR SO'ROVDA olinadi, `settings` dan emas: HRM
    sessiyasi bir necha daqiqada tugaydi va yangi qiymat uchun restart
    kerak bo'lsa, restart oqib turgan javoblarni kesib yuborardi."""
    module, app_client = api
    tokens = iter(["birinchi-jwt", "ikkinchi-jwt"])
    monkeypatch.setattr(module, "hrm_token_now", lambda: next(tokens))

    app_client.post("/api/v1/chat/stream", headers=auth, json={"question": "salom"})
    app_client.post("/api/v1/chat/stream", headers=auth, json={"question": "salom"})

    assert server.calls[0]["body"]["tokens"] == {"hrm": "birinchi-jwt"}
    assert server.calls[1]["body"]["tokens"] == {"hrm": "ikkinchi-jwt"}


def test_endpoint_token_bosh_bolsa_yubormaydi(api, auth, server, monkeypatch):
    """Bo'sh satr YUBORILMAYDI: xizmat uni yaroqsiz sessiya deb qabul qilib,
    hujjatlar bo'yicha savolni ham buzishi mumkin edi."""
    module, app_client = api
    monkeypatch.setattr(module, "hrm_token_now", lambda: "")
    app_client.post("/api/v1/chat/stream", headers=auth, json={"question": "salom"})
    assert "tokens" not in server.calls[0]["body"]
    assert "hrm_token" not in server.calls[0]["body"]


def test_endpoint_kadrlarni_ozgartirmasdan_uzatadi(api, auth):
    module, app_client = api
    response = app_client.post("/api/v1/chat/stream", headers=auth,
                               json={"question": "salom"})
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-venera-request-id"] == "served-1"
    kinds = [json.loads(line)["type"] for line in response.text.splitlines() if line.strip()]
    assert kinds == ["stage", "sources", "token", "token", "done"]


def test_endpoint_tokensiz_rad_etiladi(api):
    _, app_client = api
    assert app_client.post("/api/v1/chat/stream", json={"question": "salom"}).status_code == 401


def test_endpoint_sozlanmagan_xizmat_haqida_aytadi(api, auth, monkeypatch):
    """Kredensial bo'lmasa foydalanuvchi TUSHUNARLI xabar olishi kerak -
    xizmatning 401 i esa "sessiyangiz tugadi" bo'lib ko'rinardi."""
    module, app_client = api
    monkeypatch.setattr(module._assistant, "client_id", "")
    response = app_client.post("/api/v1/chat/stream", headers=auth,
                               json={"question": "salom"})
    assert response.status_code == 501
    assert response.json()["message"] == "Savol-javob xizmati hali sozlanmagan"


def test_ask_xato_kadrini_qaytaradi(assistant, server):
    """`auth_missing` - HRM tokeni yo'q. Bu XATO EMAS, holat: hujjatlar
    bo'yicha savollar ishlaydi, jonli HRM ma'lumoti esa yo'q."""
    server.frames = [
        frame(type="error", code="auth_missing", text="HRM sessiyasi kerak"),
        frame(type="done", route=None),
    ]
    result = assistant.ask("Bugun kechikdimmi?", user_id="venera:1")
    assert result["error"] == {"code": "auth_missing", "text": "HRM sessiyasi kerak"}
    assert result["answer"] == ""
