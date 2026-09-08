"""Swagger sahifasi qattiq CSP ostida ham ochilishini qo'riqlaydi.

NEGA BU TEST BOR. Sahifa bir marta bo'sh ochilgan: HTTP 200 qaytardi,
`swagger-ui-bundle.js` ham 200 qaytardi, lekin brauzerda OQ EKRAN edi.

Sabab: frontend nginx butun saytga `script-src 'self'` CSP qo'yadi, FastAPI
ning `get_swagger_ui_html()` esa sahifaga INLINE `<script>` yozadi. Brauzer
uni bloklaydi - bundle yuklanadi, lekin uni ISHGA TUSHIRADIGAN kod
bajarilmaydi. `curl` buni HECH QACHON ko'rmaydi, chunki u JS ishlatmaydi.

Shuning uchun bu yerda status kod emas, sahifa TARKIBI tekshiriladi.
"""

from __future__ import annotations

import base64
import re

import pytest

from app.main import _STATIC_DIR, _SWAGGER_FILES

from conftest import ADMIN


def _basic(email: str, password: str) -> dict[str, str]:
    raw = base64.b64encode(f"{email}:{password}".encode()).decode()
    return {"Authorization": f"Basic {raw}"}


@pytest.fixture
def docs_auth() -> dict[str, str]:
    """Hujjat sahifasi endi HTTP Basic talab qiladi."""
    return _basic(ADMIN["email"], ADMIN["password"])


def test_docs_sahifasida_inline_skript_yoq(client, docs_auth):
    """Har bir <script> tashqi faylga ishora qilishi SHART.

    Bu buzilsa sahifa jimgina bo'sh ochiladi - eng yomon xato turi.
    """
    html = client.get("/api/docs", headers=docs_auth).text
    for attrs, inner in re.findall(r"<script\b([^>]*)>([\s\S]*?)</script>", html, re.I):
        assert "src=" in attrs.lower(), (
            "Sahifada INLINE skript bor - CSP `script-src 'self'` uni bloklaydi "
            f"va sahifa BO'SH ochiladi. Blok: {inner.strip()[:80]!r}"
        )
        assert inner.strip() == "", "src bilan birga tana ham bor - tana bajarilmaydi"


def test_docs_faqat_oz_originidan_yuklaydi(client, docs_auth):
    """Tashqi manba (CDN) bo'lmasligi kerak: CSP uni bloklaydi VA internet yo'q."""
    html = client.get("/api/docs", headers=docs_auth).text
    for url in re.findall(r'(?:src|href)\s*=\s*["\']([^"\']+)["\']', html):
        assert url.startswith("/") or url.startswith("data:"), (
            f"Tashqi manba {url!r} - ichki tarmoqda yuklanmaydi va CSP bloklaydi"
        )


def test_docs_ishga_tushirish_skriptiga_ishora_qiladi(client, docs_auth):
    """Bundle yolg'iz o'zi hech narsa chizmaydi - init skript ham kerak."""
    html = client.get("/api/docs", headers=docs_auth).text
    assert "/api/static/swagger-ui-bundle.js" in html
    assert "/api/static/swagger-init.js" in html, (
        "init skript yo'q - SwaggerUIBundle yuklanadi, lekin CHAQIRILMAYDI"
    )


def test_sahifa_korsatgan_fayllar_haqiqatan_beriladi(client, docs_auth):
    """Sahifadagi har bir yo'l 200 qaytarishi va JS/CSS bo'lishi kerak."""
    html = client.get("/api/docs", headers=docs_auth).text
    urls = {u for u in re.findall(r'(?:src|href)\s*=\s*["\'](/[^"\']+)["\']', html)}
    assert urls, "sahifa hech qanday resursga ishora qilmayapti"
    for url in urls:
        response = client.get(url, headers=docs_auth)
        assert response.status_code == 200, f"{url} -> {response.status_code}"
        ctype = response.headers.get("content-type", "")
        assert "text/html" not in ctype, (
            f"{url} HTML qaytardi ({ctype}) - demak SPA yoki xato sahifasi keldi"
        )


def test_swagger_fayllari_diskda_bor(client, docs_auth):
    """Fayllar yo'q bo'lsa sahifa bo'sh emas, ANIQ xato qaytarishi kerak."""
    missing = [f for f in _SWAGGER_FILES if not (_STATIC_DIR / f).exists()]
    if missing:
        response = client.get("/api/docs", headers=docs_auth)
        assert response.status_code == 503, (
            "fayllar yo'q, lekin sahifa 200 qaytardi - foydalanuvchi sababsiz "
            "oq ekran ko'radi"
        )
        for name in missing:
            assert name in response.text
    else:
        assert client.get("/api/docs", headers=docs_auth).status_code == 200


def test_openapi_json_ochiladi(client, docs_auth):
    """Swagger buzilsa ham mashina o'qiydigan hujjat qolishi kerak."""
    data = client.get("/api/openapi.json", headers=docs_auth).json()
    assert data["info"]["title"]
    assert "/api/v1/auth/login" in data["paths"]


# --- hujjat himoyasi ---
#
# Sayt tashqi proksi orqali internetdan ochiq. Himoyasiz `/api/docs` va
# `/api/openapi.json` har kimga butun endpoint ro'yxatini va modellarni
# berardi - ya'ni hujumchiga nimani sinashni aytib berardi.


def test_docs_parolsiz_ochilmaydi(client):
    response = client.get("/api/docs")
    assert response.status_code == 401


def test_openapi_parolsiz_ochilmaydi(client):
    """Sahifani qulflab sxemani ochiq qoldirish ma'nosiz - qimmati shu faylda."""
    assert client.get("/api/openapi.json").status_code == 401


def test_401_brauzer_parol_oynasini_chiqaradi(client):
    """`WWW-Authenticate` bo'lmasa brauzer JSON xato ko'rsatadi, parol so'ramaydi.

    Bu sarlavha bir marta yo'qolgan: xato handler'i `exc.headers` ni
    tashlab yuborardi.
    """
    header = client.get("/api/docs").headers.get("www-authenticate", "")
    assert header.lower().startswith("basic"), f"WWW-Authenticate: {header!r}"


def test_xato_parol_rad_etiladi(client):
    assert client.get("/api/docs", headers=_basic(ADMIN["email"], "yolgon")).status_code == 401


def test_notanish_email_rad_etiladi(client):
    assert client.get("/api/docs", headers=_basic("yoq@venera.uz", "x")).status_code == 401


def test_buzuq_sarlavha_yiqitmaydi(client):
    """Noto'g'ri base64 500 bermasligi kerak."""
    for value in ("Basic ###", "Basic", "Bearer abc", "Basic " + base64.b64encode(b"parolsiz").decode()):
        code = client.get("/api/docs", headers={"Authorization": value}).status_code
        assert code == 401, f"{value!r} -> {code}"


def test_togri_parol_bilan_ochiladi(client, docs_auth):
    assert client.get("/api/docs", headers=docs_auth).status_code == 200
    assert client.get("/api/openapi.json", headers=docs_auth).status_code == 200
