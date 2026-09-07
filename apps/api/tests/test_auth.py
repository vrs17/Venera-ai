"""Autentifikatsiya."""

from __future__ import annotations

import pytest

from app.core.security import create_token, hash_password, verify_password
from tests.conftest import ADMIN, USER


# --- parol xeshi -------------------------------------------------------------

def test_parol_xeshi_ozini_tekshiradi():
    digest = hash_password("maxfiy")
    assert verify_password("maxfiy", digest)
    assert not verify_password("boshqa", digest)


def test_xesh_har_safar_boshqacha():
    """Tasodifiy salt - bir xil parol ikki xil xesh beradi."""
    assert hash_password("bir xil") != hash_password("bir xil")


@pytest.mark.parametrize("buzuq", ["", "salom", "pbkdf2$xato", "md5$1$a$b", None])
def test_buzuq_xesh_yiqitmaydi(buzuq):
    assert verify_password("parol", buzuq) is False


def test_parol_ochiq_saqlanmaydi():
    """Xesh ichida parolning o'zi BO'LMASLIGI shart."""
    assert "juda-maxfiy-parol" not in hash_password("juda-maxfiy-parol")


# --- login -------------------------------------------------------------------

def test_login_token_va_foydalanuvchi_qaytaradi(client):
    response = client.post("/api/v1/auth/login", json=ADMIN)
    assert response.status_code == 200

    body = response.json()
    assert body["tokenType"] == "Bearer"
    assert body["token"]
    assert body["expiresAt"]
    assert body["user"]["email"] == ADMIN["email"]
    assert body["user"]["roles"] == ["ADMIN", "RAG_ADMIN"]


def test_login_javobida_parol_xeshi_yoq(client):
    """Xesh tashqariga CHIQMASLIGI shart."""
    body = client.post("/api/v1/auth/login", json=ADMIN).json()
    assert "password" not in str(body).lower() or "pbkdf2" not in str(body)


def test_notogri_parol_401(client):
    response = client.post(
        "/api/v1/auth/login", json={**ADMIN, "password": "xato"})
    assert response.status_code == 401


def test_notogri_email_401(client):
    response = client.post(
        "/api/v1/auth/login", json={"email": "yoq@venera.uz", "password": "x"})
    assert response.status_code == 401


def test_xato_xabari_qaysi_maydon_notogriligini_AYTMAYDI(client):
    """Aks holda qaysi emaillar ro'yxatda borligini aniqlash mumkin bo'lardi."""
    yoq = client.post(
        "/api/v1/auth/login", json={"email": "yoq@venera.uz", "password": "x"}).json()
    bor = client.post(
        "/api/v1/auth/login", json={**ADMIN, "password": "xato"}).json()
    assert yoq["message"] == bor["message"]


def test_email_registri_ahamiyatsiz(client):
    response = client.post(
        "/api/v1/auth/login", json={**ADMIN, "email": ADMIN["email"].upper()})
    assert response.status_code == 200


# --- /me ---------------------------------------------------------------------

def test_me_foydalanuvchini_qaytaradi(client, auth):
    response = client.get("/api/v1/auth/me", headers=auth)
    assert response.status_code == 200
    assert response.json()["email"] == ADMIN["email"]


def test_me_tokensiz_401(client):
    assert client.get("/api/v1/auth/me").status_code == 401


@pytest.mark.parametrize("header", [
    "",                       # bo'sh
    "Bearer",                 # tokensiz
    "Bearer   ",              # bo'shliq
    "Basic abc",              # boshqa sxema
    "Bearer buzuq.token.xxx",  # buzuq JWT
])
def test_notogri_sarlavha_401(client, header):
    response = client.get("/api/v1/auth/me", headers={"Authorization": header})
    assert response.status_code == 401


def test_boshqa_kalit_bilan_imzolangan_token_rad_etiladi(client):
    """Kalitni bilmasdan token yasab bo'lmaydi."""
    from app.core.config import settings

    original, settings.secret_key = settings.secret_key, "boshqa-kalit"
    soxta, _ = create_token(ADMIN["email"])
    settings.secret_key = original

    response = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {soxta}"})
    assert response.status_code == 401


def test_ochirilgan_foydalanuvchi_tokeni_ishlamaydi(client):
    """Token haqiqiy, lekin foydalanuvchi endi ro'yxatda yo'q."""
    soxta, _ = create_token("ochirilgan@venera.uz")
    response = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {soxta}"})
    assert response.status_code == 401


# --- logout ------------------------------------------------------------------

def test_logout(client, auth):
    response = client.post("/api/v1/auth/logout", headers=auth)
    assert response.status_code == 200
    assert response.json()["status"] == "OK"


def test_logout_tokensiz_401(client):
    assert client.post("/api/v1/auth/logout").status_code == 401


# --- hali bajarilmagan -------------------------------------------------------

@pytest.mark.parametrize("path", ["/api/v1/auth/signup", "/api/v1/auth/change-password"])
def test_bajarilmagan_endpointlar_501_va_tushunarli_xabar(client, path):
    """501 "yo'q" dan aniqroq: endpoint bor, lekin hali qilinmagan."""
    response = client.post(path, json={})
    assert response.status_code == 501
    assert response.json()["message"]


# --- rollar ------------------------------------------------------------------

def test_har_foydalanuvchi_oz_rollarini_oladi(client):
    body = client.post("/api/v1/auth/login", json=USER).json()
    assert body["user"]["roles"] == ["USER"]
    assert body["user"]["actorId"] == 2
