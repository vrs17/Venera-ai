"""Testlar uchun umumiy fikstura.

Har test O'Z foydalanuvchilar fayli bilan ishlaydi - shu tufayli testlar
bir-biriga ta'sir qilmaydi va `config/users.yaml` (haqiqiy fayl) o'qilmaydi.
"""

from __future__ import annotations

import pytest
import yaml
from fastapi.testclient import TestClient

from app.api.deps import get_user_store
from app.core.config import settings
from app.core.security import hash_password
from app.main import app
from app.services.users import UserStore

ADMIN = {"email": "admin@venera.uz", "password": "venera2026"}
USER = {"email": "demo@venera.uz", "password": "demo2026"}


@pytest.fixture
def users_file(tmp_path):
    """Ikkita foydalanuvchili vaqtinchalik YAML."""
    path = tmp_path / "users.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "users": [
                    {
                        "actor_id": 1,
                        "email": ADMIN["email"],
                        "full_name": "Administrator",
                        "position": "Tizim administratori",
                        "department": "IT",
                        "roles": ["ADMIN", "RAG_ADMIN"],
                        "password_hash": hash_password(ADMIN["password"]),
                    },
                    {
                        "actor_id": 2,
                        "email": USER["email"],
                        "full_name": "Demo Foydalanuvchi",
                        "roles": ["USER"],
                        "password_hash": hash_password(USER["password"]),
                    },
                ]
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def client(users_file):
    """Sinov klienti - vaqtinchalik foydalanuvchilar fayli bilan."""
    store = UserStore.from_file(users_file)
    app.dependency_overrides[get_user_store] = lambda: store
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def token(client) -> str:
    """Kirgan admin uchun token."""
    response = client.post("/api/v1/auth/login", json=ADMIN)
    assert response.status_code == 200, response.text
    return response.json()["token"]


@pytest.fixture
def auth(token) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _isolated_connectors(tmp_path, monkeypatch):
    """Ulanishlar ombori HAR TESTDA vaqtinchalik va bo'sh.

    Modul darajasidagi `hub` haqiqiy `settings.connectors_file` ni o'qiydi -
    ishlab chiqish mashinasida u yerda ODAMNING JONLI TOKENLARI turadi
    (ulangan CRM). Bir marta shunday bo'ldi: `_live_tokens` testlari
    "umumiy token ketadi" deb kutgan joyda faylda turgan odam tokeni
    ustun kelib, 4 test yiqildi - va bu mashinaga bog'liq edi. Testlar
    hech qachon haqiqiy ma'lumotga tegmasligi kerak.
    """
    from app.api.v1 import connectors as connectors_api
    from app.services.integrations.connectors import (
        ConnectorHub, ConnectorStore, CrmUserAuth, HrmAuth,
    )

    monkeypatch.setattr(connectors_api, "hub", ConnectorHub(
        ConnectorStore(tmp_path / "connectors" / "tokens.json"),
        HrmAuth(""), CrmUserAuth("", "", "", ""),
    ))


@pytest.fixture(autouse=True)
def _default_secret():
    """Testlar default kalit bilan ishlaydi - natija takrorlanadigan bo'lsin."""
    original = settings.secret_key
    settings.secret_key = "test-secret"
    yield
    settings.secret_key = original

@pytest.fixture(autouse=True)
def _stt_provider_pinned(monkeypatch, tmp_path):
    """HAR BIR test uchun: STT tanlovi 1-variantda (ichki Router).

    NEGA AUTOUSE. Tanlov `.env` dan o'qiladi, ya'ni mashinada
    `STT_PROVIDER=gapi` bo'lsa endpoint testlari TASHQI PULLIK xizmatga
    chiqib ketardi - va aynan shunday bo'ldi: kalit qo'yilgan zahoti 13
    test yiqildi, chunki ular soxta Router klientini patch qilib, endpoint
    esa GAPI ni tanlagan edi.

    Test natijasi mashinaning sozlamasiga bog'liq bo'lmasligi kerak, va
    hech bir test hisobdan pul yechmasligi kerak. 2-variantning O'ZI
    `test_gapi_stt.py` da sinaladi - u klientni to'g'ridan-to'g'ri
    quradi va transportni almashtiradi, ya'ni bu kafolatga tegmaydi.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "stt_provider", "router", raising=False)
    monkeypatch.setattr(settings, "stt_wake_provider", "router", raising=False)
