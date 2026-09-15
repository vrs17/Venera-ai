"""Chat quvuri."""

from __future__ import annotations

import pytest


def ask(client, auth, question: str):
    return client.post("/api/v1/chat/ask", json={"question": question}, headers=auth)


def test_tokensiz_401(client):
    response = client.post("/api/v1/chat/ask", json={"question": "salom"})
    assert response.status_code == 401


def test_savol_javob_qaytaradi(client, auth):
    body = ask(client, auth, "Ta'til qancha qoldi?").json()
    assert body["answer"], "javob bo'sh"
    # Hali hech qanday tizim ulanmagan - foydalanuvchi buni TUSHUNARLI
    # shaklda bilishi kerak, "undefined" yoki bo'sh ekran emas.
    assert body["finalStatus"] == "RAG_DOMAIN_NOT_READY"


def test_bosh_savol_guard_tomonidan_toxtatiladi(client, auth):
    body = ask(client, auth, "   ").json()
    assert body["finalStatus"] == "STOP_UNSAFE"
    assert body["guard"]["safe"] is False
    # Quvur to'xtagach keyingi bosqichlar BAJARILMAYDI - frontend ularni
    # "o'tkazib yuborilgan" deb ko'rsatadi.
    assert body["intent"] is None
    assert body["orchestrator"] is None


def test_bosqichlar_tartibi_saqlanadi(client, auth):
    body = ask(client, auth, "savol").json()
    assert body["guard"]["safe"] is True
    assert body["intent"] is not None
    assert body["orchestrator"] is not None
    assert body["access"] is not None


def test_yonaltirish_yoq_bolsa_access_otkazib_yuboriladi(client, auth):
    """Hali modul yo'q - huquq tekshirish ma'nosiz."""
    body = ask(client, auth, "savol").json()
    assert body["orchestrator"]["requiresAccessCheck"] is False
    assert body["access"]["decision"] == "SKIP"


@pytest.mark.parametrize("question", [
    "a" * 5000,               # juda uzun
    "!@#$%^&*()",             # faqat belgilar
    "😀 emoji",
    "<script>alert(1)</script>",
    "'; DROP TABLE users; --",
])
def test_notogri_kirish_yiqitmaydi(client, auth, question):
    assert ask(client, auth, question).status_code == 200


def test_savol_maydoni_yoq_bolsa_422(client, auth):
    response = client.post("/api/v1/chat/ask", json={}, headers=auth)
    assert response.status_code == 422
    assert response.json()["message"]


def test_health(client):
    """OCHIQ holat ATAYLAB minimal: faqat tiriklik va versiya."""
    body = client.get("/health").json()
    assert body["status"] in ("ok", "degraded")
    assert set(body) == {"status", "version"}, f"ochiq holatda ortiqcha maydon: {set(body)}"


def test_ochiq_holat_tashxis_bermaydi(client):
    """Bu yo'l nginx orqali TASHQARIGA ochiq.

    Ilgari u butun tashxisni qaytarardi: `crm_session` (CRM hisobi
    sozlanganmi va Keycloak ning xom xatosi), `warnings` (qaysi token
    tugagani, namuna parollari qaysi hisoblarda), `users`, `upstream`.
    Ismini aytmagan odam uchun bu razvedka edi.
    """
    body = client.get("/api/health").json()
    for leak in ("warnings", "users", "upstream", "crm_session", "tts_slots"):
        assert leak not in body, f"ochiq holat {leak} ni oshkor qildi"


def test_batafsil_holat_sessiya_talab_qiladi(client):
    assert client.get("/api/health/detail").status_code == 401


def test_batafsil_holat_sessiya_bilan_ishlaydi(client, auth):
    body = client.get("/api/health/detail", headers=auth).json()
    assert body["users"] == 2
    assert "warnings" in body and "crm_session" in body


def test_health_default_kalit_haqida_ogohlantiradi(client):
    """Prod'da kalitni o'zgartirishni unutish - eng ko'p uchraydigan xato."""
    from app.core.config import settings
    from app.core.security import create_token

    original, settings.secret_key = settings.secret_key, "dev-only-insecure-change-me"
    try:
        # Token ALMASHTIRILGAN kalit ostida yasaladi: `auth` fiksturasi
        # asl kalit bilan imzolangan va bu blokda yaroqsiz bo'lardi.
        token, _ = create_token("admin@venera.uz")
        headers = {"Authorization": f"Bearer {token}"}
        public = client.get("/health").json()
        body = client.get("/api/health/detail", headers=headers).json()
    finally:
        settings.secret_key = original

    # Ochiq yo'l "e'tibor kerak" deydi, SABABINI aytmaydi.
    assert public["status"] == "degraded"
    assert body["status"] == "degraded"
    assert any("secret_key" in w for w in body["warnings"])
