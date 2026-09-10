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
def client(server) -> AssistantClient:
    return AssistantClient(BASE, "venera", SECRET, timeout=5, max_concurrent=2)


def collect(stream) -> list[dict]:
    return [json.loads(line) for line in stream.frames]


# --- so'rov ---------------------------------------------------------------


def test_soro_vni_kredensial_bilan_yuboradi(client, server):
    stream = client.stream("Ta'til necha kun?", user_id="venera:21", chat_id="c-1")
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


def test_bosh_maydonlar_yuborilmaydi(client, server):
    """`chat_id` bo'sh bo'lsa YUBORILMAYDI - bo'sh satr yuqoridagi xizmatda
    "shu nomli suhbat" bo'lib qolardi va hamma xotirasiz turn bir joyga
    to'planardi."""
    collect(client.stream("salom", user_id="venera:1"))
    assert set(server.calls[0]["body"]) == {"question", "user_id"}


def test_hrm_tokeni_berilsa_otadi(client, server):
    collect(client.stream("Men bugun kechikdimmi?", user_id="venera:1",
                          hrm_token="hrm-jwt", hrm_employee="Mamajonov"))
    assert server.calls[0]["body"]["hrm_token"] == "hrm-jwt"
    assert server.calls[0]["body"]["hrm_employee"] == "Mamajonov"


def test_audit_kaliti_yuboriladi_va_xizmatnikisi_ustun(client, server):
    """`X-Request-Id` biz tomonidan yuboriladi, lekin xizmat o'zinikini
    qaytarsa AUDIT kaliti o'shanikisi - ikki tizimda bir kalit bilan
    izlash uchun."""
    stream = client.stream("salom", user_id="venera:1")
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
def test_bosh_savol_rad_etiladi(client, server, question):
    with pytest.raises(AssistantError) as exc:
        client.stream(question, user_id="venera:1")
    assert exc.value.status == 400
    assert server.calls == []


def test_juda_uzun_savol_yuborilmaydi(client, server):
    with pytest.raises(AssistantError) as exc:
        client.stream("a" * 50, user_id="venera:1", max_chars=10)
    assert exc.value.status == 400
    assert server.calls == []


# --- kadrlar --------------------------------------------------------------


def test_kadrlar_otadi(client):
    frames = collect(client.stream("salom", user_id="venera:1"))
    assert [f["type"] for f in frames] == ["stage", "sources", "token", "token", "done"]
    assert "".join(f["text"] for f in frames if f["type"] == "token") == \
        "Yillik ta'til 21 kalendar kun."


def test_natija_yakunda_yoziladi(client):
    stream = client.stream("salom", user_id="venera:1")
    collect(stream)
    assert stream.outcome["route"] == "both"
    assert stream.outcome["frames"] == 5


def test_buzuq_qatorlar_tashlanadi(client, server):
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
    frames = collect(client.stream("salom", user_id="venera:1"))
    assert frames == [{"type": "token", "text": "ok"}]


def test_notanish_kadr_turi_otadi(client, server):
    """Xizmat yangi kadr qo'shsa, Venera'ni qayta yozmasdan ishlashi kerak."""
    server.frames = [frame(type="thinking", text="..."), frame(type="done", route="rules")]
    assert [f["type"] for f in collect(client.stream("s", user_id="venera:1"))] == \
        ["thinking", "done"]


def test_oqim_chegarasi(client, server, monkeypatch):
    """Cheksiz oqim serverni ham, brauzerni ham qulflab qo'yardi."""
    monkeypatch.setattr(mod, "_MAX_STREAM_BYTES", 200)
    server.frames = [frame(type="token", text="x" * 50) for _ in range(20)]
    frames = collect(client.stream("salom", user_id="venera:1"))
    assert 0 < len(frames) < 20


# --- havolalar ------------------------------------------------------------


def test_ariza_havolalari_venera_yoliga_ogiriladi(client, server):
    """Havola ICHKI manzilni ko'rsatadi - brauzer unga yetib bormaydi."""
    server.frames = [frame(
        type="artifact", title="Ariza", doc_id="d9",
        docx_url=f"{BASE}/api/hr/artifacts/tok-A1/docx",
        pdf_url="/api/hr/artifacts/tok-A1/pdf",
        preview_url=f"{BASE}/api/hr/artifacts/tok-A1/preview",
    )]
    art = collect(client.stream("ariza", user_id="venera:1"))[0]
    assert art["docx_url"] == "/api/v1/chat/artifact/tok-A1/docx"
    assert art["pdf_url"] == "/api/v1/chat/artifact/tok-A1/pdf"
    assert art["preview_url"] == "/api/v1/chat/artifact/tok-A1/preview"
    assert BASE not in json.dumps(art)


def test_ariza_kadri_ichma_ich_bolsa_ham(client, server):
    """Xizmat kadrni bir daraja pastga tushirsa havolalar JIMGINA ishlamay
    qo'yardi - shuning uchun ikkala shakl ham qo'llanadi."""
    server.frames = [frame(type="artifact", artifact={
        "title": "Ariza", "docx_url": f"{BASE}/api/hr/artifacts/tok-B2/docx"})]
    art = collect(client.stream("ariza", user_id="venera:1"))[0]
    assert art["artifact"]["docx_url"] == "/api/v1/chat/artifact/tok-B2/docx"


def test_tanilmagan_ichki_havola_olib_tashlanadi(client, server):
    """Ochilmaydigan havolani ko'rsatishdan ko'ra ko'rsatmaslik yaxshi, va
    ichki topologiya tashqariga chiqmaydi."""
    server.frames = [frame(type="artifact", docx_url=f"{BASE}/some/other/path")]
    art = collect(client.stream("ariza", user_id="venera:1"))[0]
    assert art["docx_url"] is None


def test_tashqi_havola_saqlanadi(client, server):
    """Ichki bo'lmagan havolaga tegilmaydi."""
    server.frames = [frame(type="artifact", docx_url="https://example.org/a.docx")]
    art = collect(client.stream("ariza", user_id="venera:1"))[0]
    assert art["docx_url"] == "https://example.org/a.docx"


def test_jonli_kadr_shakli(client, server):
    """AYNAN jonli xizmatdan kelgan shakl: iqtiboslar `items` ostida, hujjat
    kaliti `HR_045` - pastki chiziq bilan. Ikkalasi ham dastlabki kodda
    e'tibordan chetda qolgan va natijada manbalar ro'yxati JIMGINA bo'sh
    bo'lardi."""
    server.frames = [frame(type="sources", items=[
        {"kind": "doc", "doc_id": "HR_045", "title": "ichki mehnat tartibi qoidalari",
         "section": "70", "page": 22, "preview_available": True},
    ])]
    items = collect(client.stream("salom", user_id="venera:1"))[0]["items"]
    assert items[0]["docUrl"] == "/api/v1/chat/doc/HR_045#page=22"


def test_pastki_chiziqli_hujjat_kaliti_yuklanadi(client, server):
    client.fetch_doc("HR_045")
    assert server.calls[0]["path"] == "/doc/HR_045"


def test_iqtibos_hujjatiga_havola_qoshiladi(client):
    """Bank muhitida majburiy: xodim ASL hujjatni ocha olishi kerak."""
    sources = collect(client.stream("salom", user_id="venera:1"))[1]["sources"]
    doc, hrm = sources
    assert doc["docUrl"] == "/api/v1/chat/doc/policy-7#page=12"
    assert doc["doc_id"] == "policy-7"      # xizmatning o'z kaliti saqlanadi
    assert "docUrl" not in hrm              # HRM chaqiruvi hujjat emas


def test_yaroqsiz_hujjat_kaliti_havola_bermaydi(client, server):
    server.frames = [frame(type="sources", sources=[
        {"kind": "doc", "doc_id": "../../etc/passwd"},
        {"kind": "doc", "doc_id": ""},
    ])]
    sources = collect(client.stream("salom", user_id="venera:1"))[0]["sources"]
    assert all("docUrl" not in item for item in sources)


# --- xatolar --------------------------------------------------------------


def test_401_sozlama_xatosi_sifatida_502_ga_tushadi(client, server):
    """401 "bizning kredensial noto'g'ri" degani. Brauzerga 401 qaytarish
    foydalanuvchini mutlaqo joyida bo'lgan sessiyasidan chiqarib
    yuborardi."""
    server.status = 401
    with pytest.raises(AssistantError) as exc:
        client.stream("salom", user_id="venera:1")
    assert exc.value.status == 502


@pytest.mark.parametrize("status,expected", [
    (400, 400), (404, 404), (422, 422), (503, 503), (403, 502), (500, 502),
])
def test_status_xaritasi(client, server, status, expected):
    server.status = status
    with pytest.raises(AssistantError) as exc:
        client.stream("salom", user_id="venera:1")
    assert exc.value.status == expected


def test_sir_xato_matnida_qolmaydi(client, server):
    """Xizmat 422 da so'rov tanasini qaytarishi mumkin, va unda sir bo'ladi."""
    server.status = 422
    server.echo_secret = True
    with pytest.raises(AssistantError) as exc:
        client.stream("salom", user_id="venera:1")
    assert SECRET not in str(exc.value)
    assert "***" in str(exc.value)


def test_ulanmasa_503(client, server, monkeypatch):
    class Dead:
        def open(self, request, timeout=None):
            raise urllib.error.URLError("Connection refused")

    monkeypatch.setattr(urllib.request, "build_opener", lambda *a, **kw: Dead())
    with pytest.raises(AssistantError) as exc:
        client.stream("salom", user_id="venera:1")
    assert exc.value.status == 503
    assert exc.value.retryable is True


def test_oqim_ortasida_timeout(client, server):
    """Kadrlar orasidagi jimlik - nosozlik. Xato oqim ICHIDA chiqadi."""
    server.timeout_after = 2
    stream = client.stream("salom", user_id="venera:1")
    with pytest.raises(AssistantError) as exc:
        collect(stream)
    assert exc.value.status == 504


def test_oqim_ortasida_uzilish(client, server):
    """Ulanish uzilishi ham `AssistantError` bo'lishi SHART: chaqiruvchi
    faqat shu turni kutadi, boshqasi brauzerga kutilmagan uzilish bo'lib
    ko'rinardi."""
    server.cut_after = 2
    stream = client.stream("salom", user_id="venera:1")
    with pytest.raises(AssistantError) as exc:
        collect(stream)
    assert exc.value.status == 503


def test_juda_katta_kadr_oqimni_toxtatadi(client, server, monkeypatch):
    monkeypatch.setattr(mod, "_MAX_LINE_BYTES", 32)
    server.frames = [frame(type="token", text="x" * 500), frame(type="done", route="rules")]
    assert collect(client.stream("salom", user_id="venera:1")) == []


# --- navbat ---------------------------------------------------------------


def test_navbat_chegarasi(client, server):
    """Yuqorida bitta LLM turadi. Chegaradan oshsa xizmatga BORMASDAN 503 -
    navbatni boshqa chaqiruvchilar uchun to'ldirib qo'ymaslik uchun."""
    first = client.stream("a", user_id="venera:1")
    second = client.stream("b", user_id="venera:2")
    with pytest.raises(AssistantError) as exc:
        client.stream("c", user_id="venera:3")
    assert exc.value.status == 503
    assert exc.value.retryable is True

    collect(first)
    # Slot oqim TUGAGANDA bo'shaydi - javob kelganda emas.
    client.stream("d", user_id="venera:4")
    collect(second)


def test_slot_ochilmagan_oqimdan_keyin_qaytadi(client, server):
    """Birinchi nosozlik navbatni abadiy egallab qolmasligi kerak."""
    server.status = 500
    for _ in range(5):
        with pytest.raises(AssistantError):
            client.stream("salom", user_id="venera:1")
    server.status = None
    collect(client.stream("salom", user_id="venera:1"))


def test_uzilgan_oqim_ham_slotni_qaytaradi(client, server):
    server.cut_after = 1
    for _ in range(4):
        with pytest.raises(AssistantError):
            collect(client.stream("salom", user_id="venera:1"))
    server.cut_after = None
    collect(client.stream("salom", user_id="venera:1"))


def test_javob_yopiladi(client, server):
    collect(client.stream("salom", user_id="venera:1"))
    assert server.last.closed is True


# --- fayllar --------------------------------------------------------------


def test_ariza_fayli(client, server):
    content_type, name, chunks = client.fetch_artifact("tok-A1", "docx")
    assert content_type == "application/pdf"
    assert name == "ariza.pdf"
    assert b"".join(chunks) == b"%PDF-1.4 fake"
    assert server.calls[0]["path"] == "/api/hr/artifacts/tok-A1/docx"
    assert server.calls[0]["method"] == "GET"


@pytest.mark.parametrize("kind", ["preview", "docx", "pdf"])
def test_ariza_fayl_turlari(client, kind):
    client.fetch_artifact("tok-A1", kind)


def test_notogri_fayl_turi(client, server):
    with pytest.raises(AssistantError) as exc:
        client.fetch_artifact("tok-A1", "exe")
    assert exc.value.status == 400
    assert server.calls == []


@pytest.mark.parametrize("token", ["../../secret", "a b", "tok/../x", ""])
def test_yaroqsiz_fayl_kaliti(client, server, token):
    with pytest.raises(AssistantError) as exc:
        client.fetch_artifact(token, "docx")
    assert exc.value.status == 400
    assert server.calls == []


@pytest.mark.parametrize("doc_id", ["../../etc/passwd", "a/b", "", "x" * 200])
def test_yaroqsiz_hujjat_kaliti(client, server, doc_id):
    with pytest.raises(AssistantError) as exc:
        client.fetch_doc(doc_id)
    assert exc.value.status == 400
    assert server.calls == []


def test_hujjat_pdfi(client, server):
    client.fetch_doc("policy-7")
    assert server.calls[0]["path"] == "/doc/policy-7"


def test_fayl_chegarasi(client, server, monkeypatch):
    monkeypatch.setattr(mod, "_MAX_FILE_BYTES", 8)
    server.file_bytes = b"x" * 100
    _, _, chunks = client.fetch_doc("policy-7")
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


# --- yig'ib olish ---------------------------------------------------------


def test_ask_javobni_yigadi(client):
    result = client.ask("Ta'til necha kun?", user_id="venera:1")
    assert result["answer"] == "Yillik ta'til 21 kalendar kun."
    assert result["route"] == "both"
    assert result["requestId"] == "served-1"
    assert len(result["sources"]) == 2
    assert result["stages"] == ["Hujjatlar qidirilmoqda"]
    assert result["error"] is None


def test_ask_xato_kadrini_qaytaradi(client, server):
    """`auth_missing` - HRM tokeni yo'q. Bu XATO EMAS, holat: hujjatlar
    bo'yicha savollar ishlaydi, jonli HRM ma'lumoti esa yo'q."""
    server.frames = [
        frame(type="error", code="auth_missing", text="HRM sessiyasi kerak"),
        frame(type="done", route=None),
    ]
    result = client.ask("Bugun kechikdimmi?", user_id="venera:1")
    assert result["error"] == {"code": "auth_missing", "text": "HRM sessiyasi kerak"}
    assert result["answer"] == ""
