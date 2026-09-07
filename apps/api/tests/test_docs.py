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

import re

from app.main import _STATIC_DIR, _SWAGGER_FILES


def test_docs_sahifasida_inline_skript_yoq(client):
    """Har bir <script> tashqi faylga ishora qilishi SHART.

    Bu buzilsa sahifa jimgina bo'sh ochiladi - eng yomon xato turi.
    """
    html = client.get("/api/docs").text
    for attrs, inner in re.findall(r"<script\b([^>]*)>([\s\S]*?)</script>", html, re.I):
        assert "src=" in attrs.lower(), (
            "Sahifada INLINE skript bor - CSP `script-src 'self'` uni bloklaydi "
            f"va sahifa BO'SH ochiladi. Blok: {inner.strip()[:80]!r}"
        )
        assert inner.strip() == "", "src bilan birga tana ham bor - tana bajarilmaydi"


def test_docs_faqat_oz_originidan_yuklaydi(client):
    """Tashqi manba (CDN) bo'lmasligi kerak: CSP uni bloklaydi VA internet yo'q."""
    html = client.get("/api/docs").text
    for url in re.findall(r'(?:src|href)\s*=\s*["\']([^"\']+)["\']', html):
        assert url.startswith("/") or url.startswith("data:"), (
            f"Tashqi manba {url!r} - ichki tarmoqda yuklanmaydi va CSP bloklaydi"
        )


def test_docs_ishga_tushirish_skriptiga_ishora_qiladi(client):
    """Bundle yolg'iz o'zi hech narsa chizmaydi - init skript ham kerak."""
    html = client.get("/api/docs").text
    assert "/api/static/swagger-ui-bundle.js" in html
    assert "/api/static/swagger-init.js" in html, (
        "init skript yo'q - SwaggerUIBundle yuklanadi, lekin CHAQIRILMAYDI"
    )


def test_sahifa_korsatgan_fayllar_haqiqatan_beriladi(client):
    """Sahifadagi har bir yo'l 200 qaytarishi va JS/CSS bo'lishi kerak."""
    html = client.get("/api/docs").text
    urls = {u for u in re.findall(r'(?:src|href)\s*=\s*["\'](/[^"\']+)["\']', html)}
    assert urls, "sahifa hech qanday resursga ishora qilmayapti"
    for url in urls:
        response = client.get(url)
        assert response.status_code == 200, f"{url} -> {response.status_code}"
        ctype = response.headers.get("content-type", "")
        assert "text/html" not in ctype, (
            f"{url} HTML qaytardi ({ctype}) - demak SPA yoki xato sahifasi keldi"
        )


def test_swagger_fayllari_diskda_bor(client):
    """Fayllar yo'q bo'lsa sahifa bo'sh emas, ANIQ xato qaytarishi kerak."""
    missing = [f for f in _SWAGGER_FILES if not (_STATIC_DIR / f).exists()]
    if missing:
        response = client.get("/api/docs")
        assert response.status_code == 503, (
            "fayllar yo'q, lekin sahifa 200 qaytardi - foydalanuvchi sababsiz "
            "oq ekran ko'radi"
        )
        for name in missing:
            assert name in response.text
    else:
        assert client.get("/api/docs").status_code == 200


def test_openapi_json_ochiladi(client):
    """Swagger buzilsa ham mashina o'qiydigan hujjat qolishi kerak."""
    data = client.get("/api/openapi.json").json()
    assert data["info"]["title"]
    assert "/api/v1/auth/login" in data["paths"]
