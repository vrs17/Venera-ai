"""Telegram orqali parolsiz kirish (`POST /telegram/session`) va iqtibos
hujjatining tokensiz havolasi (`POST /chat/doc/{doc_id}/link`).

Ikkalasi ham Mini App uchun va ikkalasi ham CHEGARA haqida: sessiya faqat
Telegram imzosi + MAVJUD ulanish bilan beriladi (ulanishni faqat parol bilan
kirgan odam yaratadi), admin bloki va "hamma joydan chiqarish" bu yo'lda ham
ishlaydi; havola esa faqat bitta hujjat va qisqa muddat uchun.

Hammasi germetik: bot tokeni soxta, Telegram'ga, Keycloak'ka va yordamchi
xizmatga chiqilmaydi.
"""

from __future__ import annotations

import time

import jwt
import pytest

from app.api.v1 import chat as chat_api
from app.api.v1 import telegram as telegram_api
from app.core.config import settings
from app.core.security import verify_claims
from app.services import analytics
from app.services.analytics.db import get_db
from app.services.identities import SsoProfile
from app.services.integrations.assistant import AssistantError
from app.services.telegram_links import LinkStore
from app.services.users import UserStore
from tests.conftest import ADMIN, USER
from tests.test_telegram_bot import BOT_TOKEN, TG_ID, sign_init

SESSION = "/api/v1/telegram/session"
MINIAPP = {"X-Venera-Client": "miniapp"}
LOGIN_FIELDS = {"token", "tokenType", "expiresAt", "passwordChangeRequired", "user"}
GENERIC = "Telegram orqali kirib bo'lmadi - login va parol bilan kiring"


@pytest.fixture
def tg(monkeypatch):
    """Soxta bot tokeni (imzo shu bilan tekshiriladi) va toza chegara."""
    import app.bot as bot_module

    monkeypatch.setattr(settings, "telegram_bot_token", BOT_TOKEN)
    telegram_api._session_limiter.reset()
    yield bot_module.links
    telegram_api._session_limiter.reset()


def _session(client, init: str, headers: dict | None = None):
    return client.post(SESSION, json={"initData": init}, headers=MINIAPP if headers is None else headers)


def _init(tg_id: int = TG_ID, **kw) -> str:
    return sign_init({"id": tg_id, "first_name": "Ali"}, **kw)


def _events() -> list[dict]:
    analytics.flush()
    return get_db().rows("SELECT * FROM auth_events WHERE method = 'telegram' ORDER BY id")


def _me(client, token: str):
    return client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})


# --- muvaffaqiyat ------------------------------------------------------------------------


def test_ulangan_hisob_parolsiz_kiradi(client, tg):
    tg.link(TG_ID, 1, now=time.time() - 3600)
    before = tg.lookup(TG_ID)[0].seen_at

    response = _session(client, _init())
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == LOGIN_FIELDS, "javob /auth/login niki bilan bir xil bo'lishi kerak"
    assert body["tokenType"] == "Bearer" and body["passwordChangeRequired"] is False
    assert body["user"]["actorId"] == 1 and body["user"]["email"] == ADMIN["email"]
    # Samarali rollar - `/auth/login` dagidek.
    assert "ADMIN" in body["user"]["roles"]

    me = _me(client, body["token"])
    assert me.status_code == 200 and me.json()["actorId"] == 1
    # Ulanish muddati yangilandi (bot ham shu odamni taniydi).
    assert tg.lookup(TG_ID)[0].seen_at > before

    [event] = _events()
    assert event["ok"] == 1 and event["actor_id"] == 1 and event["channel"] == "miniapp"
    assert event["login"] == ADMIN["email"] and event["reason"] is None


def test_sso_hisob_keycloak_sub_bilan(client, tg, users_file):
    """SSO bilan kirgan odam (`identities.json`) - token `sub` i Keycloak `sub`."""
    from app.api.deps import get_identity_store

    sub = "0f6c1d1e-aaaa-bbbb-cccc-1234567890ab"
    who = get_identity_store().upsert(
        SsoProfile(subject=sub, username="y.m", email="y.m@brb.uz", full_name="Y M"),
        legacy=UserStore.from_file(users_file))
    tg.link(TG_ID, who.actor_id)

    response = _session(client, _init())
    assert response.status_code == 200, response.text
    token = response.json()["token"]
    assert verify_claims(token).subject == sub
    assert _me(client, token).json()["actorId"] == who.actor_id
    assert _events()[-1]["login"] == "y.m"


def test_sarlavhasiz_sorov_ham_miniapp_kanali(client, tg):
    """`initData` faqat Mini App ichida bo'ladi - sarlavha yo'q bo'lsa ham."""
    tg.link(TG_ID, 1)
    assert _session(client, _init(), headers={}).status_code == 200
    assert _events()[-1]["channel"] == "miniapp"


# --- rad etish ----------------------------------------------------------------------------


def test_ulanmagan_telegram_401(client, tg):
    response = _session(client, _init())
    assert response.status_code == 401
    assert response.json()["message"] == GENERIC
    [event] = _events()
    assert event["ok"] == 0 and event["reason"] == "tg_not_linked"
    assert event["login"] == f"tg:{TG_ID}" and event["actor_id"] is None


def test_muddati_otgan_ulanish_401(client, tg):
    tg.link(TG_ID, 1, now=time.time() - (settings.telegram_link_days + 1) * 86400)
    response = _session(client, _init())
    assert response.status_code == 401 and response.json()["message"] == GENERIC
    assert _events()[-1]["reason"] == "tg_link_expired"
    # Muddati o'tgan ulanish TIRILMAYDI - yana parol bilan kirish kerak.
    assert tg.lookup(TG_ID) == (None, "expired")


def test_boshqa_telegram_hisobining_ulanishi_ishlamaydi(client, tg):
    tg.link(TG_ID + 1, 1)                          # boshqa odamning Telegrami
    assert _session(client, _init()).status_code == 401


@pytest.mark.parametrize("init", [
    pytest.param(lambda: sign_init({"id": TG_ID}, token="999:boshqa-bot"), id="boshqa-bot"),
    pytest.param(lambda: _init().replace("Ali", "Vali"), id="buzilgan"),
    pytest.param(lambda: _init().split("&hash=")[0], id="imzosiz"),
    pytest.param(lambda: _init() + "&user=%7B%22id%22%3A1%7D", id="takroriy-maydon"),
    pytest.param(lambda: sign_init({"id": TG_ID, "is_bot": True}), id="bot"),
])
def test_soxta_imzo_401(client, tg, init):
    tg.link(TG_ID, 1)
    response = _session(client, init())
    assert response.status_code == 401 and response.json()["message"] == GENERIC
    event = _events()[-1]
    assert event["ok"] == 0 and event["reason"] == "tg_invalid" and event["login"] is None


def test_eski_initdata_sessiya_bermaydi_ulash_esa_qabul_qiladi(client, tg, auth):
    """Sessiya oynasi QISQA (600 s), ulashniki - 1 kun: bir kunlik satr parolsiz
    kirish kaliti bo'lib qolmasin."""
    tg.link(TG_ID, 1)
    old = _init(auth_date=int(time.time()) - telegram_api._SESSION_MAX_AGE - 60)
    response = _session(client, old)
    assert response.status_code == 401 and response.json()["message"] == GENERIC
    assert _events()[-1]["reason"] == "tg_stale"
    assert client.post("/api/v1/telegram/link", headers=auth, json={"initData": old}).status_code == 200


def test_bloklangan_hisob_403(client, tg, auth):
    tg.link(TG_ID, 2)
    client.patch("/api/v1/admin/users/2", headers=auth, json={"disabled": True})
    response = _session(client, _init())
    assert response.status_code == 403
    assert "bloklangan" in response.json()["message"].lower()
    event = _events()[-1]
    assert event["ok"] == 0 and event["reason"] == "blocked" and event["actor_id"] == 2
    # Blok ulanishni UZMAYDI (bot kabi): blok olib tashlansa davom etadi.
    client.patch("/api/v1/admin/users/2", headers=auth, json={"disabled": False})
    assert _session(client, _init()).status_code == 200


def test_hisob_ochirilgan_401(client, tg):
    tg.link(TG_ID, 77)                              # hech qayerda yo'q
    response = _session(client, _init())
    assert response.status_code == 401
    event = _events()[-1]
    assert event["reason"] == "tg_unknown_actor" and event["actor_id"] == 77


def test_zahira_kirish_ochiq_bolmasa_parolsiz_ham_yoq(client, tg, monkeypatch):
    """`users.yaml` hisobi: `/auth/login` uni qabul qilmasa - Telegram ham."""
    tg.link(TG_ID, 2)
    monkeypatch.setattr(settings, "local_login_enabled", False)
    response = _session(client, _init())
    assert response.status_code == 401
    assert _events()[-1]["reason"] == "local_login_disabled"


def test_parol_almashtirish_talab_qilinsa_yoq(client, tg, users_file):
    import yaml

    raw = yaml.safe_load(users_file.read_text(encoding="utf-8"))
    raw["users"][1]["password_change_required"] = True
    users_file.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    from app.api.deps import get_user_store
    from app.main import app

    store = UserStore.from_file(users_file)
    app.dependency_overrides[get_user_store] = lambda: store
    tg.link(TG_ID, 2)
    response = _session(client, _init())
    assert response.status_code == 401
    assert _events()[-1]["reason"] == "password_change_required"


def test_sessiya_versiyasi_hurmat_qilinadi(client, tg, auth):
    """"Hamma joydan chiqarish": eski token o'ladi, Telegram ulanishi uziladi
    (ya'ni parolsiz qaytib bo'lmaydi). Qayta ulangandan keyingi token - YANGI
    versiya bilan, ya'ni ishlaydi."""
    tg.link(TG_ID, 2)
    first = _session(client, _init()).json()["token"]
    assert verify_claims(first).version == 0

    assert client.post("/api/v1/admin/users/2/signout", headers=auth).status_code == 200
    assert _me(client, first).status_code == 401
    assert _session(client, _init()).status_code == 401

    tg.link(TG_ID, 2)                               # odam parol bilan qayta kirdi
    second = _session(client, _init()).json()["token"]
    assert verify_claims(second).version == 1
    assert _me(client, second).status_code == 200


def test_tekshiruvdan_keyin_uzilgan_ulanish_tirilmaydi(client, tg, monkeypatch):
    """Tekshiruv va yangilash orasida odam chiqdi (yoki admin chiqardi)."""
    tg.link(TG_ID, 1)
    original = LinkStore.touch

    def unlink_then_touch(self, tg_id, actor_id, **kw):
        self.unlink(tg_id)
        return original(self, tg_id, actor_id, **kw)

    monkeypatch.setattr(LinkStore, "touch", unlink_then_touch)
    response = _session(client, _init())
    assert response.status_code == 401
    assert tg.lookup(TG_ID) == (None, "none"), "uzilgan ulanish qayta yaratilmasligi kerak"
    assert not any(e["ok"] for e in _events())


def test_bot_sozlanmagan_501(client, monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    assert _session(client, "a=b").status_code == 501


def test_chegara_telegram_hisobi_boyicha(client, tg):
    limit = telegram_api._session_limiter.limit
    for _ in range(limit):
        assert _session(client, _init()).status_code == 401
    response = _session(client, _init())
    assert response.status_code == 429
    assert int(response.headers["retry-after"]) >= 1
    # Chegaradan oshganlar jurnalni to'ldirmaydi.
    assert len(_events()) == limit
    # Boshqa Telegram hisobi - o'z chegarasi.
    assert _session(client, _init(TG_ID + 1)).status_code == 401


def test_sorov_shakli(client, tg):
    assert client.post(SESSION, json={}).status_code == 422
    assert client.post(SESSION, json={"initData": ""}).status_code == 422
    assert client.post(SESSION, json={"initData": "x" * 9000}).status_code == 422


# --- ulanishni yangilash (`LinkStore.touch`) ----------------------------------------------


def test_touch_faqat_tirik_va_oz_ulanishini(tmp_path):
    store = LinkStore(tmp_path / "links.json", ttl_days=30)
    assert store.touch(TG_ID, 1) is False
    assert store.lookup(TG_ID) == (None, "none"), "yo'q ulanish yaratilmaydi"

    store.link(TG_ID, 2, now=1000.0)
    assert store.touch(TG_ID, 1, now=2000.0) is False, "boshqa odamniki"
    assert store.lookup(TG_ID, now=2000.0)[0].seen_at == 1000.0

    assert store.touch(TG_ID, 2, now=2000.0) is True
    assert store.lookup(TG_ID, now=2000.0)[0].seen_at == 2000.0

    late = 2000.0 + 31 * 86400
    assert store.touch(TG_ID, 2, now=late) is False, "muddati o'tgan tirilmaydi"
    assert store.lookup(TG_ID, now=late) == (None, "expired")


# --- iqtibos hujjati havolasi ---------------------------------------------------------------

PDF = b"%PDF-1.7\n%soxta hujjat\n"


class FakeDocs:
    """Yuqoridagi xizmatning hujjat yo'li - so'rovlarni yozib boradi."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.content_type = "application/pdf"
        self.error: AssistantError | None = None

    def fetch_doc(self, doc_id: str):
        self.calls.append(doc_id)
        if self.error:
            raise self.error
        return self.content_type, "HR_045.pdf", iter([PDF[:8], PDF[8:]])


@pytest.fixture
def docs(monkeypatch):
    fake = FakeDocs()
    monkeypatch.setattr(chat_api, "_assistant", fake)
    return fake


def _doc_link(client, auth, doc_id="HR_045", filename="ichki mehnat tartibi qoidalari"):
    return client.post(f"/api/v1/chat/doc/{doc_id}/link", json={"filename": filename},
                       headers={**auth, **MINIAPP})


def _claims(url: str) -> dict:
    return jwt.decode(url.rsplit("/", 1)[1], settings.secret_key, algorithms=["HS256"],
                      audience="venera:file")


def test_hujjat_havolasi_shakli(client, auth, docs):
    response = _doc_link(client, auth)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"url", "filename", "expiresIn"}
    assert body["url"].startswith("/api/v1/chat/file/")
    assert body["filename"] == "ichki mehnat tartibi qoidalari.pdf"
    assert body["expiresIn"] == 600
    assert docs.calls == [], "havola berilganda hujjat OLINMAYDI"
    claims = _claims(body["url"])
    assert claims["kind"] == "doc" and claims["doc"] == "HR_045"
    assert claims["uid"] == 1 and claims["ch"] == "miniapp"
    assert claims["exp"] - claims["iat"] == 600


def test_hujjat_havolasi_sessiyasiz_berilmaydi(client, docs):
    assert client.post("/api/v1/chat/doc/HR_045/link", json={}).status_code == 401


def test_hujjat_havola_orqali_tokensiz_ochiladi(client, auth, docs):
    url = _doc_link(client, auth).json()["url"]
    response = client.get(url)                      # Authorization YO'Q
    assert response.status_code == 200
    assert response.content == PDF
    assert docs.calls == ["HR_045"]
    disposition = response.headers["content-disposition"]
    # PDF - brauzer o'zi ko'rsatadi (tashqi brauzerda o'qiladi, yuklanmaydi).
    assert disposition.startswith('inline; filename="ichki mehnat tartibi qoidalari.pdf"')
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["access-control-allow-origin"] == "https://web.telegram.org"


def test_pdf_bolmasa_attachment(client, auth, docs):
    """Xizmat boshqa tur bersa (masalan HTML) - Venera originida sahifa bo'lib ochilmaydi."""
    docs.content_type = "text/html; charset=utf-8"
    response = client.get(_doc_link(client, auth).json()["url"])
    assert response.headers["content-disposition"].startswith("attachment;")


def test_hujjat_havolasi_bosh_nom_bilan(client, auth, docs):
    response = client.post("/api/v1/chat/doc/HR_045/link", headers=auth)
    assert response.status_code == 200 and response.json()["filename"] == "hujjat.pdf"


@pytest.mark.parametrize("doc_id", ["a%20b", "a$b", "a,b"])
def test_yaroqsiz_hujjat_kaliti_400(client, auth, docs, doc_id):
    assert _doc_link(client, auth, doc_id=doc_id).status_code == 400
    assert docs.calls == []


def test_juda_uzun_hujjat_kaliti(client, auth, docs):
    assert _doc_link(client, auth, doc_id="a" * 129).status_code == 422


def test_hujjat_topilmasa_ichki_manzil_ochilmaydi(client, auth, docs):
    url = _doc_link(client, auth).json()["url"]
    docs.error = AssistantError("Assistant 404: http://10.10.50.4:8100/doc/HR_045 yo'q", status=404)
    response = client.get(url)
    assert response.status_code == 404
    assert "10.10.50" not in response.text


def test_muddati_otgan_hujjat_havolasi_410(client, docs):
    now = int(time.time())
    expired = jwt.encode({"aud": "venera:file", "iat": now - 700, "exp": now - 100,
                          "kind": "doc", "doc": "HR_045", "uid": 1},
                         settings.secret_key, algorithm="HS256")
    assert client.get(f"/api/v1/chat/file/{expired}").status_code == 410
    assert docs.calls == []


@pytest.mark.parametrize("claims", [
    {"kind": "doc", "art": "tok-A1"},              # ariza imzosi hujjat sifatida
    {"kind": "doc", "doc": "../etc/passwd"},       # yaroqsiz kalit
    {"kind": "docx", "doc": "HR_045"},             # hujjat imzosi ariza sifatida
])
def test_havola_turlari_aralashmaydi(client, docs, claims):
    now = int(time.time())
    signed = jwt.encode({"aud": "venera:file", "iat": now, "exp": now + 60, **claims},
                        settings.secret_key, algorithm="HS256")
    assert client.get(f"/api/v1/chat/file/{signed}").status_code == 404
    assert docs.calls == []


def test_hujjat_havolasi_kirish_tokeni_ornida_ishlamaydi(client, auth, docs):
    signed = _doc_link(client, auth).json()["url"].rsplit("/", 1)[1]
    assert _me(client, signed).status_code == 401


def test_bot_uchun_umumiy_imzolovchi():
    """Bot ("Hujjatni ochish") ham shu funksiyadan imzolaydi - kanal va muddat bilan."""
    link = chat_api.doc_link("HR_045", 2, "Mehnat kodeksi", channel="bot", ttl=3600)
    assert link.filename == "Mehnat kodeksi.pdf" and link.expiresIn == 3600
    claims = _claims(link.url)
    assert claims["ch"] == "bot" and claims["uid"] == 2 and claims["exp"] - claims["iat"] == 3600
    with pytest.raises(ValueError):
        chat_api.doc_link("a/b", 2)


def test_parol_jurnalga_tushmaydi(client, tg):
    """Bu yo'lda parol umuman yo'q - lekin `initData` ham jurnalga tushmasin."""
    tg.link(TG_ID, 1)
    init = _init()
    _session(client, init)
    dump = repr(_events())
    assert init not in dump and USER["password"] not in dump
