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
    body = client.get("/health").json()
    assert body["status"] in ("ok", "degraded")
    assert body["users"] == 2


def test_health_default_kalit_haqida_ogohlantiradi(client):
    """Prod'da kalitni o'zgartirishni unutish - eng ko'p uchraydigan xato."""
    from app.core.config import settings

    original, settings.secret_key = settings.secret_key, "dev-only-insecure-change-me"
    body = client.get("/health").json()
    settings.secret_key = original

    assert body["status"] == "degraded"
    assert any("secret_key" in w for w in body["warnings"])
