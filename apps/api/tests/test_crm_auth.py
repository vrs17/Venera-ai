"""CRM sessiyasi: login -> refresh -> access_token, va xatolar.

CRM ning O'ZI chaqirilmaydi: u ichki tarmoqda va CI da yo'q. Almashtirish
nuqtasi `urllib.request.urlopen` - ya'ni faqat TRANSPORT soxta, ustidagi
hamma mantiq (rotatsiya, zahira oynasi, halokatli kodlar, tanaffus,
sirni yashirish, atomik saqlash) haqiqiy kod bo'lib qoladi.
"""

from __future__ import annotations

import io
import json
import logging
import stat
import threading
import time
import urllib.error
import urllib.request

import pytest

from app.services.integrations.crm_auth import CrmAuth, _safe

BASE = "http://crm.test"
ACCESS = "eyJhbGciOiJSUzI1NiIs.access-1.sig"
REFRESH = "eyJhbGciOiJIUzUxMiIs.refresh-1.sig"


class FakeCrm:
    """`/api/auth/*` kontraktini taqlid qiladi."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.serial = 0
        #: Keyingi javob o'rniga shu status qaytariladi (bir marta).
        self.fail_once: tuple[int, dict] | None = None
        #: Har doim shu status (o'chirilmaguncha).
        self.fail_always: tuple[int, dict] | None = None
        #: `refresh` ga 400 beradi - bekor qilingan token holati.
        self.refresh_dead = False

    def __call__(self, request, timeout=None):
        path = "/" + request.full_url.split("://", 1)[1].split("/", 1)[1]
        body = json.loads(request.data) if request.data else {}
        self.calls.append((path, body))

        failure = self.fail_always
        if self.fail_once is not None:
            failure, self.fail_once = self.fail_once, None
        if failure:
            raise _http_error(path, failure[0], failure[1])

        if path == "/api/auth/logout":
            return _Response(b"")
        if path == "/api/auth/refresh" and self.refresh_dead:
            raise _http_error(path, 400, {"error": {"code": "AUTH_FAILED",
                                                    "message": "refresh rejected"}})
        self.serial += 1
        return _Response(json.dumps({
            "data": {
                "access_token": f"{ACCESS}-{self.serial}",
                "refresh_token": f"{REFRESH}-{self.serial}",
                "expires_in": 300,
                "refresh_expires_in": 0,
                "token_type": "Bearer",
            },
            "timestamp": "2026-09-14T11:04:22.118",
        }).encode())

    def paths(self) -> list[str]:
        return [path for path, _ in self.calls]


class _Response:
    def __init__(self, raw: bytes) -> None:
        self._raw = raw

    def read(self) -> bytes:
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None


def _http_error(path: str, code: int, payload: dict) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        f"{BASE}{path}", code, "error", {},
        io.BytesIO(json.dumps(payload).encode()),
    )


@pytest.fixture
def crm(tmp_path, monkeypatch):
    fake = FakeCrm()
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    auth = CrmAuth(BASE, "crm-ai-agent", "parol", tmp_path / "crm" / "refresh_token")
    return auth, fake


# --- oddiy yo'l -------------------------------------------------------------


def test_birinchi_chaqiruv_login_qiladi(crm):
    auth, fake = crm
    assert auth.token() == f"{ACCESS}-1"
    assert fake.paths() == ["/api/auth/login"]
    assert fake.calls[0][1] == {"username": "crm-ai-agent", "password": "parol"}


def test_refresh_token_saqlanadi_va_600(crm):
    auth, fake = crm
    auth.token()
    assert auth.store.read_text().strip() == f"{REFRESH}-1"
    mode = stat.S_IMODE(auth.store.stat().st_mode)
    assert mode == 0o600, f"refresh_token huquqi {oct(mode)} - bu DOIMIY kredensial"


def test_ikkinchi_chaqiruv_keshdan(crm):
    """Har savolda yangi token so'ralsa, `/api/auth/*` uchun 30/daqiqa
    chegarasini o'zimiz yeb qo'yardik."""
    auth, fake = crm
    first = auth.token()
    assert auth.token() == first
    assert len(fake.calls) == 1


def test_zahira_oynasida_refresh_qiladi(crm, monkeypatch):
    """Muddati 90 sekundan kam qolganda YANGILANADI.

    Nega 90: savol-javob 45 sekundgacha cho'zilishi mumkin, ya'ni token
    so'rov boshida yaroqli bo'lishi yetarli emas - u javob oxirigacha
    yaroqli turishi kerak.
    """
    auth, fake = crm
    auth.token()
    # Vaqtni 300 - 60 = 240 sekundga suramiz: zahira oynasi ichida.
    base = time.monotonic()
    monkeypatch.setattr(time, "monotonic", lambda: base + 240.0)
    assert auth.token() == f"{ACCESS}-2"
    assert fake.paths() == ["/api/auth/login", "/api/auth/refresh"]
    # ROTATSIYA: yangi refresh_token saqlangan bo'lishi SHART, aks holda
    # keyingi yangilash 400 olib, har safar paroldan login qilardi.
    assert auth.store.read_text().strip() == f"{REFRESH}-2"
    assert fake.calls[1][1] == {"refresh_token": f"{REFRESH}-1"}


def test_saqlangan_token_bilan_login_qilmaydi(tmp_path, monkeypatch):
    """Qayta ishga tushirilgandan keyin parolga QAYTILMAYDI."""
    fake = FakeCrm()
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    store = tmp_path / "refresh_token"
    store.write_text(f"{REFRESH}-saqlangan\n")
    auth = CrmAuth(BASE, "crm-ai-agent", "parol", store)
    auth.token()
    assert fake.paths() == ["/api/auth/refresh"]


def test_bekor_qilingan_refresh_login_ga_tushadi(tmp_path, monkeypatch):
    """30 kun ishlatilmagan yoki bekor qilingan token - KUTILADIGAN holat."""
    fake = FakeCrm()
    fake.refresh_dead = True
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    store = tmp_path / "refresh_token"
    store.write_text("eskirgan\n")
    auth = CrmAuth(BASE, "crm-ai-agent", "parol", store)
    assert auth.token() == f"{ACCESS}-1"
    assert fake.paths() == ["/api/auth/refresh", "/api/auth/login"]


# --- xatolar ---------------------------------------------------------------


@pytest.mark.parametrize("code", ["USER_NOT_PROVISIONED", "ACCOUNT_DISABLED"])
def test_403_halokatli_qayta_urinilmaydi(crm, code):
    """403 - Keycloak token BERDI, CRM esa hisobni rad etdi. Yana login
    qilsak yana yaroqli token va yana o'sha 403 - cheksiz. Odam kerak."""
    auth, fake = crm
    fake.fail_always = (403, {"error": {"code": code, "message": "rad etildi",
                                        "status": 403, "correlationId": "abc"}})
    assert auth.token() == ""
    assert len(fake.calls) == 1
    # Ikkinchi savol yana urinmasligi KERAK.
    assert auth.token() == ""
    assert len(fake.calls) == 1
    assert code in (auth.warning() or "")
    assert auth.status()["fatal"] == code


def test_429_da_tanaffus(crm):
    """Chegara daqiqa bo'yicha: darhol qayta urinish yana 429 berardi."""
    auth, fake = crm
    # Filtr kontrollerlardan OLDIN turadi va YASSI shakl qaytaradi.
    fake.fail_always = (429, {"error": "RATE_LIMIT_EXCEEDED", "message": "sekin"})
    assert auth.token() == ""
    assert len(fake.calls) == 1
    assert auth.token() == ""
    assert len(fake.calls) == 1, "429 dan keyin darhol qayta urinildi"
    assert "RATE_LIMIT" in (auth.status()["last_error"] or "")


def test_ulanmasa_bosh_qaytaradi_istisno_emas(crm):
    """CRM o'chganda HRM savollari ishlashda davom etishi kerak, shuning
    uchun bu yerdan istisno TASHLANMAYDI."""
    auth, fake = crm

    def boom(request, timeout=None):
        raise urllib.error.URLError("ulanmadi")

    fake.calls.append(("(almashtirildi)", {}))
    import app.services.integrations.crm_auth as mod
    mod.urllib.request.urlopen = boom
    try:
        assert auth.token() == ""
    finally:
        mod.urllib.request.urlopen = fake
    assert "UNREACHABLE" in (auth.status()["last_error"] or "")


def test_sozlanmagan_bolsa_jim(tmp_path):
    """Sozlanmagan holat XATO EMAS: `.env` dagi qo'lda yozilgan
    `crm_token` ishlatiladi."""
    auth = CrmAuth("", "", "", tmp_path / "x")
    assert auth.configured is False
    assert auth.token() == ""
    assert auth.warning() is None
    assert auth.status() == {"configured": False}


def test_javobda_access_token_bolmasa(crm, monkeypatch):
    auth, fake = crm

    def empty(request, timeout=None):
        return _Response(json.dumps({"data": {"refresh_token": "r"}}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", empty)
    assert auth.token() == ""
    assert "BAD_RESPONSE" in (auth.status()["last_error"] or "")


# --- sir oshkor bo'lmasligi ------------------------------------------------


def test_token_jurnalga_tushmaydi(crm, caplog):
    """`refresh_token` DOIMIY kredensial - paroldan farqi yo'q."""
    auth, fake = crm
    with caplog.at_level(logging.DEBUG):
        auth.token()
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert f"{REFRESH}-1" not in text
    assert f"{ACCESS}-1" not in text
    assert "parol" not in text


def test_xato_matnidan_token_ochiriladi(crm):
    """CRM 400 da so'rov tanasini qaytarishi mumkin - va o'sha tanada
    bizning refresh_token imiz bo'lardi."""
    auth, fake = crm
    fake.fail_always = (400, {"error": {"code": "AUTH_FAILED",
                                        "message": f"body was {REFRESH}-1"}})
    auth.token()
    last = auth.status()["last_error"] or ""
    assert f"{REFRESH}-1" not in last
    assert "<token>" in last


def test_holat_token_qiymatini_bermaydi(crm):
    auth, fake = crm
    auth.token()
    blob = json.dumps(auth.status())
    assert ACCESS not in blob and REFRESH not in blob
    assert auth.status()["has_token"] is True


def test_safe_jwt_ni_yashiradi():
    assert _safe("oldin eyJabcdefghij.klm.nop keyin") == "oldin <token> keyin"
    assert _safe("") == ""


# --- parallel ish ----------------------------------------------------------


def test_bir_vaqtda_kelgan_sorovlar_bitta_login_qiladi(crm):
    """Rotatsiya tufayli ikkita parallel refresh bir-birining tokenini
    bekor qilardi - va har savolda paroldan login qilishga tushardik."""
    auth, fake = crm
    seen: list[str] = []
    ready = threading.Barrier(8)

    def worker():
        ready.wait()
        seen.append(auth.token())

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(set(seen)) == 1, "ishchilar har xil token oldi"
    assert len(fake.calls) == 1, f"{len(fake.calls)} marta login qilindi"


# --- o'chirish tugmasi -----------------------------------------------------


def test_logout_bekor_qiladi_va_ochiradi(crm):
    auth, fake = crm
    auth.token()
    assert auth.store.exists()
    assert auth.logout() is True
    assert fake.paths()[-1] == "/api/auth/logout"
    assert fake.calls[-1][1] == {"refresh_token": f"{REFRESH}-1"}
    assert not auth.store.exists()
    assert auth.status()["has_token"] is False


def test_rad_etilgan_parolda_tanaffus_ikki_baravar_oshadi(crm, monkeypatch):
    """Noto'g'ri parol o'zi tuzalmaydi: har savolda login qilsak har savol 0.1-0.5 s
    yo'qotardi va Keycloak hisobni bloklashi mumkin edi. Tanaffus 20, 40, 80 ... s,
    30 daqiqagacha; muvaffaqiyatli login hisobni nolga qaytaradi."""
    auth, fake = crm
    now = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    fake.fail_always = (400, {"error": {"code": "AUTH_FAILED", "message": "Authentication failed"}})

    gaps = []
    for _ in range(9):
        calls = len(fake.calls)
        assert auth.token() == ""
        assert len(fake.calls) == calls + 1
        # Tanaffus ichida qayta urinilmaydi.
        assert auth.token() == "" and len(fake.calls) == calls + 1
        gaps.append(round(auth._next_try - now[0]))
        now[0] = auth._next_try + 0.1
    assert gaps == [20, 40, 80, 160, 320, 640, 1280, 1800, 1800]
    assert auth.status()["auth_failures"] == 9

    # Parol tuzatildi: keyingi urinish o'tadi va hisob nolga qaytadi.
    fake.fail_always = None
    assert auth.token().startswith(ACCESS)
    assert auth.status()["auth_failures"] == 0


def test_tarmoq_xatosida_tanaffus_oshmaydi(crm, monkeypatch):
    """Ikki baravar faqat rad etilgan parolda: CRM vaqtincha o'chsa 20 s qoladi."""
    auth, fake = crm
    now = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    fake.fail_always = (503, {"error": {"code": "UNAVAILABLE", "message": "down"}})
    for _ in range(3):
        auth.token()
        assert round(auth._next_try - now[0]) == 20
        now[0] = auth._next_try + 0.1
    assert auth.status()["auth_failures"] == 0
