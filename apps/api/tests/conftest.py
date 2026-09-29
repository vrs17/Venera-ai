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
def client(users_file, monkeypatch):
    """Sinov klienti - vaqtinchalik foydalanuvchilar fayli bilan.

    `main._diagnostics` (`/api/health/detail`) omborni `Depends` orqali
    EMAS, to'g'ridan-to'g'ri chaqiradi - `dependency_overrides` unga
    yetmaydi va u HAQIQIY `config/users.yaml` ni sanardi: test natijasi
    mashinadagi hisoblar soniga bog'liq bo'lib qolgan edi. Shuning uchun
    modul atributi ham shu omborga qaratiladi. `settings.users_file`
    ATAYLAB o'zgartirilmaydi: tashxis uning yonidagi `users.example.yaml`
    ni o'qiydi (namuna parollar tekshiruvi).
    """
    import app.main as main_module

    store = UserStore.from_file(users_file)
    app.dependency_overrides[get_user_store] = lambda: store
    monkeypatch.setattr(main_module, "get_user_store", lambda: store)
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


@pytest.fixture
def user_auth(client) -> dict:
    """Oddiy xodim (faqat USER roli) - admin bo'limlari uni 403 bilan qaytarishi kerak."""
    response = client.post("/api/v1/auth/login", json=USER)
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


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
def _isolated_identities(tmp_path, monkeypatch):
    """SSO hisoblar fayli HAR TESTDA vaqtinchalik va bo'sh.

    `data/identities.json` jonli ma'lumot (ishlab chiqish mashinasida
    odamning haqiqiy Keycloak `sub` i). `get_identity_store` keshlangan -
    kesh testdan oldin va keyin tozalanadi, shunda `Depends` ham,
    to'g'ridan-to'g'ri chaqiruv ham vaqtinchalik faylni oladi.
    """
    from app.api.deps import get_identity_store

    monkeypatch.setattr(settings, "identities_file", tmp_path / "identities.json", raising=False)
    get_identity_store.cache_clear()
    yield
    get_identity_store.cache_clear()


#: `.env` dan o'qiladigan, lekin testlar KODDAGI default'ini kutadigan
#: sozlamalar. Mashinada `HOLD_ENABLED=false` yoki `WAKE_LOG_ENABLED=false`
#: turgani uchun kutish ovozi va uyg'otish jurnali testlari yiqilgan edi -
#: kod emas, mashina sozlamasi sinalayotgan edi. Qolganlari xuddi shu
#: turdagi tuzoq: `LOCAL_LOGIN_ENABLED=false` bo'lsa deyarli hamma test
#: kira olmaydi, `ADMIN_LOGINS` / `SSO_TRUSTED_ROLES` esa rollarni
#: o'zgartiradi. O'zgacha qiymat kerak bo'lgan test uni o'zi qo'yadi.
_CODE_DEFAULTS = ("hold_enabled", "wake_log_enabled", "local_login_enabled",
                  "admin_logins", "sso_trusted_roles")


@pytest.fixture(autouse=True)
def _code_defaults(monkeypatch):
    """HAR TESTDA: `_CODE_DEFAULTS` dagi sozlamalar - `Settings` sinfidagi
    default qiymatda, `.env` dagi qiymatda emas."""
    fields = type(settings).model_fields
    for name in _CODE_DEFAULTS:
        monkeypatch.setattr(settings, name, fields[name].default, raising=False)


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
    # Kutish ovozlarini QIZDIRMASLIK: `startup` hodisasi jonli TTS
    # serveriga chiqib ketardi (12 ta sintez, har test yurishida).
    monkeypatch.setattr(settings, "hold_warm", False, raising=False)
    # Savolni tasniflaydigan model ham TASHQI va PULLIK xizmat. Test
    # natijasi mashinaning `.env` iga bog'liq bo'lmasligi kerak, va hech
    # bir test hisobdan pul yechmasligi kerak - modelning O'ZI
    # `test_hold.py` da soxta transport bilan sinaladi.
    import app.api.v1.chat as chat_module

    monkeypatch.setattr(chat_module._hold_classifier, "_api_key", "", raising=False)
    # Tayyor kutish ovozlari keshi HAR TESTDA bo'sh va vaqtinchalik.
    #
    # Aks holda test natijasi mashinada sintez qilingan ovozlarga bog'liq
    # bo'lardi - va aynan shunday bo'ldi: jonli xizmat 12 ta ovozni
    # yasagandan keyin "ovoz tayyor emas" testi 404 o'rniga 200 oldi.
    from app.services.hold import HoldVoices

    monkeypatch.setattr(chat_module, "_hold_voices",
                        HoldVoices(tmp_path / "hold"), raising=False)


@pytest.fixture(autouse=True)
def _telegram_bot_off(tmp_path, monkeypatch):
    """Telegram bot HAR TESTDA o'chiq, ulanishlar ombori esa vaqtinchalik.

    `TestClient` ilovani ishga tushiradi va `startup` hodisasi botni
    yoqardi - `.env` dagi JONLI token bilan. U holda test yurishi haqiqiy
    odamlarning xabarlarini Telegram'dan olib ("yutib") yuborardi, ya'ni
    ular javobsiz qolardi. Ulanishlar fayli ham jonli ma'lumot.
    """
    import app.bot as bot_module
    from app.services.integrations.telegram import TelegramApi
    from app.services.telegram_links import LinkStore

    monkeypatch.setattr(settings, "telegram_bot_enabled", False, raising=False)
    monkeypatch.setattr(bot_module, "api", TelegramApi(""), raising=False)
    monkeypatch.setattr(bot_module, "links", LinkStore(tmp_path / "telegram" / "links.json"),
                        raising=False)


class _OfflineUpstream:
    """`main._upstream` o'rnida: STT/TTS "sog'lom", tarmoqqa chiqilmaydi."""

    def snapshot(self) -> dict:
        return {"stt": {"status": "ok", "broken": []}, "tts": {"status": "ok"}}


@pytest.fixture(autouse=True)
def _offline_upstream(monkeypatch):
    """`/health`, `/api/health/detail` va `/admin/system` STT/TTS ning
    `/health` iga JONLI tarmoq orqali borardi (`settings.stt_base_url` -
    ichki server). Test natijasi o'sha serverning holatiga bog'liq
    bo'lmasligi va unga so'rov yubormasligi kerak. Tekshiruvning o'zi
    `test_wake.py` da soxta `urlopen` bilan sinaladi."""
    import app.main as main_module

    monkeypatch.setattr(main_module, "_upstream", _OfflineUpstream(), raising=False)


@pytest.fixture(autouse=True)
def _isolated_analytics(tmp_path):
    """Analitika ombori HAR TESTDA vaqtinchalik va bo'sh.

    `current_user` har so'rovda `user_admin` ni o'qiydi (blok, rollar,
    sessiya versiyasi), kirish esa `auth_events` ga yozadi - ya'ni endi
    deyarli HAR test shu omborga tegadi. Jonli `data/analytics/venera.db`
    da haqiqiy savollar va admin qarorlari turadi: test ularni o'qimasligi
    ham, ularga yozmasligi ham kerak.
    """
    from app.services import analytics

    database = analytics.reset_for_tests(tmp_path / "analytics" / "venera.db")
    yield database
    analytics.shutdown()
    database.close_all()
