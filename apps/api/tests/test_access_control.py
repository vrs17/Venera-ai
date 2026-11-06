"""Kirish nazorati: rollar (`require_roles`), samarali rollar, `admin_logins`,
bloklash, sessiya versiyasi (`ver`), kirish hodisalari.

`api/deps.py`, `core/security.py`, `api/v1/auth.py`, `services/admin_users.py`,
bot (`bot/runner.py`). Hammasi OFLAYN: Keycloak/HRM/CRM - `test_sso_login.py`
dagi soxta tarmoq, Telegram va yuqoridagi xizmat - `test_telegram_bot.py`
dagi soxtalar. Analitika ombori har testda vaqtinchalik (`conftest.py`).
"""

from __future__ import annotations

import time

import jwt
import pytest

from app.core.config import settings
from app.core.security import create_token, verify_claims
from app.schemas.auth import AuthUser
from app.services import admin_users, analytics
from app.services.analytics import get_db
from app.services.identities import IdentityStore
from app.services.users import UserStore
from tests.conftest import ADMIN, USER
from tests.sso_fake import LOGIN, callback, hub, net, sso_login, start  # noqa: F401 - fiksturalar
from tests.test_connectors import CRM, HRM

ADMIN_ACTOR = AuthUser(actorId=1, email=ADMIN["email"], fullName="Administrator",
                       roles=["ADMIN", "RAG_ADMIN"])
BLOCKED_LOGIN = "Hisob bloklangan. Administratorga murojaat qiling."


def _login(client, creds: dict):
    return client.post("/api/v1/auth/login", json=creds)


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _token(client, creds: dict) -> str:
    response = _login(client, creds)
    assert response.status_code == 200, response.text
    return response.json()["token"]


def _me(client, token: str):
    return client.get("/api/v1/auth/me", headers=_bearer(token))


def _stores(users_file) -> tuple[IdentityStore, UserStore]:
    from app.api.deps import get_identity_store

    return get_identity_store(), UserStore.from_file(users_file)


def _auth_events() -> list[dict]:
    analytics.flush()
    return get_db().rows("SELECT * FROM auth_events ORDER BY id")


@pytest.fixture
def bootstrap(monkeypatch):
    """`admin_logins` ni vaqtincha qo'yish."""

    def set_logins(value: str) -> None:
        monkeypatch.setattr(settings, "admin_logins", value, raising=False)

    return set_logins


# --- token versiyasi -----------------------------------------------------------------


def test_token_ver_claim_bilan():
    token, _ = create_token("a@b.uz", version=3)
    claims = verify_claims(token)
    assert (claims.subject, claims.version) == ("a@b.uz", 3)


def test_ver_siz_eski_token_nol_versiya(client):
    """O'zgarishdan OLDIN berilgan tokenlarda `ver` yo'q - ular uzilmasligi kerak."""
    now = int(time.time())
    old = jwt.encode({"sub": ADMIN["email"], "iat": now, "exp": now + 600},
                     settings.secret_key, algorithm="HS256")
    assert verify_claims(old).version == 0
    assert _me(client, old).status_code == 200


@pytest.mark.parametrize("ver", ["1", 1.5, True, None, [1]])
def test_ver_butun_son_bolmasa_rad(client, ver):
    now = int(time.time())
    forged = jwt.encode({"sub": ADMIN["email"], "iat": now, "exp": now + 600, "ver": ver},
                        settings.secret_key, algorithm="HS256")
    assert verify_claims(forged) is None
    assert _me(client, forged).status_code == 401


# --- require_roles ------------------------------------------------------------------


def test_oddiy_xodim_admin_bolimiga_403(client, auth):
    user = _token(client, USER)
    response = client.get("/api/v1/admin/users", headers=_bearer(user))
    assert response.status_code == 403
    assert response.json()["message"] == "Bu bo'lim uchun ruxsat yo'q"
    assert response.json()["error"] == "Forbidden"
    assert client.get("/api/v1/admin/users", headers=auth).status_code == 200


def test_tokensiz_admin_bolimi_401(client):
    assert client.get("/api/v1/admin/users").status_code == 401


def test_batafsil_holat_faqat_admin(client, auth):
    user = _token(client, USER)
    assert client.get("/api/health/detail", headers=_bearer(user)).status_code == 403
    assert client.get("/api/health/detail", headers=auth).status_code == 200


def test_rol_registrga_sezgir(client):
    """Keycloak'dagi boshqa ilovaning `admin` roli Venera ADMIN ini bermaydi."""
    with get_db().transaction() as conn:
        conn.execute("INSERT INTO user_admin (actor_id, roles) VALUES (2, '[\"admin\"]')")
    token = _token(client, USER)
    assert _me(client, token).json()["roles"] == ["admin"]
    assert client.get("/api/v1/admin/users", headers=_bearer(token)).status_code == 403


# --- rollar: admin qo'ygan va manba ---------------------------------------------------


def test_rollar_almashtiriladi_va_manbaga_qaytariladi(client, auth):
    user = _token(client, USER)
    assert _me(client, user).json()["roles"] == ["USER"]

    response = client.patch("/api/v1/admin/users/2", headers=auth, json={"roles": ["USER", "rag_admin"]})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["roles"] == ["USER", "RAG_ADMIN"] and body["rolesSource"] == "admin"
    # Sessiya darhol yangi rollarni oladi - qayta kirish shart emas.
    assert _me(client, user).json()["roles"] == ["USER", "RAG_ADMIN"]
    assert _login(client, USER).json()["user"]["roles"] == ["USER", "RAG_ADMIN"]

    # `null` - manba rollariga qaytish ("bo'sh ro'yxat" emas).
    response = client.patch("/api/v1/admin/users/2", headers=auth, json={"roles": None})
    assert response.json()["roles"] == ["USER"] and response.json()["rolesSource"] == "source"
    assert _me(client, user).json()["roles"] == ["USER"]


def test_bosh_rollar_royxati_manbadan_farq_qiladi(client, auth):
    response = client.patch("/api/v1/admin/users/2", headers=auth, json={"roles": []})
    assert response.json()["roles"] == [] and response.json()["rolesSource"] == "admin"
    assert _me(client, _token(client, USER)).json()["roles"] == []


def test_admin_bergan_admin_roli_panelni_ochadi(client, auth):
    client.patch("/api/v1/admin/users/2", headers=auth, json={"roles": ["USER", "ADMIN"]})
    user = _token(client, USER)
    assert client.get("/api/v1/admin/users", headers=_bearer(user)).status_code == 200


# --- admin_logins (zaxira kalit) ------------------------------------------------------


def test_admin_logins_har_doim_admin_va_qulflangan(client, auth, bootstrap):
    bootstrap("Boshqa@x.uz, DEMO@venera.uz")
    user = _token(client, USER)
    assert _me(client, user).json()["roles"] == ["USER", "ADMIN"]
    assert client.get("/api/v1/admin/users", headers=_bearer(user)).status_code == 200

    row = next(i for i in client.get("/api/v1/admin/users", headers=auth).json()["items"]
               if i["actorId"] == 2)
    assert row["rolesLocked"] is True and "ADMIN" in row["roles"]

    # Panel ADMIN ni ololmaydi - rollar almashsa ham ADMIN qoladi.
    response = client.patch("/api/v1/admin/users/2", headers=auth, json={"roles": ["USER"]})
    assert response.status_code == 200 and response.json()["roles"] == ["USER", "ADMIN"]
    # Va bloklay olmaydi.
    response = client.patch("/api/v1/admin/users/2", headers=auth, json={"disabled": True})
    assert response.status_code == 409 and "admin_logins" in response.json()["message"]


def test_admin_logins_royxatga_kirsa_blok_otmaydi(client, auth, bootstrap):
    """Oldin bloklangan odam ro'yxatga qo'shilsa - `.env` orqali qaytib kiradi."""
    assert client.patch("/api/v1/admin/users/2", headers=auth, json={"disabled": True}).status_code == 200
    assert _login(client, USER).status_code == 403
    bootstrap("demo@venera.uz")
    assert _login(client, USER).status_code == 200


def test_admin_logins_sso_login_boyicha_emailning_boshi_emas(bootstrap):
    bootstrap("y.mamajonov")
    sso = AuthUser(actorId=5, email="yusuf@brb-tech.uz", fullName="Y", roles=["employee"])
    assert "ADMIN" in admin_users.effective(sso, login="Y.Mamajonov").roles
    # Emailning `@` gacha qismi SOLISHTIRILMAYDI - Keycloak'da email o'zgartirilishi mumkin.
    fake = AuthUser(actorId=6, email="y.mamajonov@gmail.com", fullName="Z", roles=[])
    assert admin_users.effective(fake).roles == []
    assert admin_users.effective(fake, login="boshqa").roles == []


# --- bloklash ----------------------------------------------------------------------


def test_bloklash_kirish_403_token_401_blok_ochilsa_eski_token_olik(client, auth):
    old = _token(client, USER)
    response = client.patch("/api/v1/admin/users/2", headers=auth, json={"disabled": True})
    assert response.status_code == 200 and response.json()["disabled"] is True

    me = _me(client, old)
    assert me.status_code == 401 and me.json()["message"] == "Hisob bloklangan"
    login = _login(client, USER)
    assert login.status_code == 403 and login.json()["message"] == BLOCKED_LOGIN
    # Parol NOTO'G'RI bo'lsa - blok haqida aytilmaydi (hisob borligi oshkor bo'lmasin).
    wrong = _login(client, {**USER, "password": "xato"})
    assert wrong.status_code == 401 and wrong.json()["message"] == "Login yoki parol noto'g'ri"

    assert client.patch("/api/v1/admin/users/2", headers=auth, json={"disabled": False}).status_code == 200
    # Bloklash versiyani oshirgan edi - eski token blok olingach ham TIRILMAYDI.
    me = _me(client, old)
    assert me.status_code == 401 and me.json()["message"] == "Sessiya yakunlangan"
    fresh = _token(client, USER)
    assert _me(client, fresh).status_code == 200


def test_kirish_hodisalari_parolsiz(client, auth):
    client.patch("/api/v1/admin/users/2", headers=auth, json={"disabled": True})
    _login(client, USER)                                   # bloklangan
    _login(client, {"email": "Yoq@Venera.uz", "password": "maxfiy-parol-123"})
    events = _auth_events()
    ok = [e for e in events if e["ok"]]
    assert ok and ok[0]["actor_id"] == 1 and ok[0]["method"] == "local"
    assert ok[0]["login"] == ADMIN["email"]
    blocked = [e for e in events if e["reason"] == "blocked"]
    assert len(blocked) == 1 and blocked[0]["actor_id"] == 2 and blocked[0]["ok"] == 0
    bad = [e for e in events if e["reason"] == "bad_credentials"]
    assert len(bad) == 1 and bad[0]["login"] == "yoq@venera.uz" and bad[0]["actor_id"] is None
    # Parol HECH QAYERDA yo'q.
    dump = repr(events)
    for secret in (USER["password"], ADMIN["password"], "maxfiy-parol-123"):
        assert secret not in dump


def test_kirish_hodisasi_kanal_sarlavhadan(client):
    client.post("/api/v1/auth/login", json=USER, headers={"X-Venera-Client": "miniapp"})
    assert _auth_events()[-1]["channel"] == "miniapp"


# --- hamma sessiyalardan chiqarish -------------------------------------------------------


def test_signout_eski_token_olik_yangi_kirish_ishlaydi(client, auth):
    import app.bot as bot_module

    old = _token(client, USER)
    bot_module.links.link(700001, 2)
    bot_module.links.link(700002, 2)
    bot_module.links.link(700003, 1)

    response = client.post("/api/v1/admin/users/2/signout", headers=auth)
    assert response.status_code == 200 and response.json() == {"tokenVersion": 1}
    me = _me(client, old)
    assert me.status_code == 401 and me.json()["message"] == "Sessiya yakunlangan"
    # Qayta kirish - yangi versiya bilan token, ishlaydi.
    fresh = _token(client, USER)
    assert verify_claims(fresh).version == 1 and _me(client, fresh).status_code == 200
    # Telegram bot ulanishlari ham uzildi - faqat shu odamniki.
    assert bot_module.links.by_actor(2) == []
    assert [link.tg_id for link in bot_module.links.by_actor(1)] == [700003]
    # Boshqa odamning sessiyasiga tegilmadi.
    assert _me(client, auth["Authorization"].split()[1]).status_code == 200

    entry = admin_users.audit_entries(target_type="user", target_id=2)[0]
    assert entry["action"] == "user.signout" and entry["adminActorId"] == 1
    assert entry["detail"] == {"tokenVersion": 1, "telegramLinks": 2}


def test_ozini_signout_qilish_mumkin(client, auth):
    assert client.post("/api/v1/admin/users/1/signout", headers=auth).status_code == 200
    assert client.get("/api/v1/auth/me", headers=auth).status_code == 401


# --- SSO bilan bloklangan odam ---------------------------------------------------------


def test_sso_bloklangan_odam_kira_olmaydi(client, hub, net, users_file):
    first = sso_login(client, net)
    actor = first["user"]["actorId"]
    identities, users = _stores(users_file)
    seen_before = identities.by_actor_id(actor).last_login_at
    admin_users.update_user(ADMIN_ACTOR, actor, identities, users, disabled=True)

    net.calls.clear()
    code, state = start(client, net)
    location, query = callback(client, code, state)
    # Keycloak "ha" dedi, Barno sessiya bermadi: kirish sahifasiga sabab bilan.
    assert query["sso_error"] == "blocked" and "sso" not in query, location
    assert f"{HRM}/api/authenticate" not in net.urls()
    # Bloklangan urinish "oxirgi kirish" bo'lib ko'rinmaydi.
    assert identities.by_actor_id(actor).last_login_at == seen_before
    # Avvalgi SSO tokeni ham o'ldi.
    me = _me(client, first["token"])
    assert me.status_code == 401 and me.json()["message"] == "Hisob bloklangan"
    events = _auth_events()
    assert [(e["ok"], e["method"], e["reason"]) for e in events] == [
        (1, "sso", None), (0, "sso", "blocked")]


def test_sso_kirish_javobida_samarali_rollar(client, hub, net, bootstrap):
    bootstrap("y.mamajonov")
    body = sso_login(client, net, roles=["employee"])
    assert body["user"]["roles"] == ["EMPLOYEE", "ADMIN"]
    assert _me(client, body["token"]).json()["roles"] == ["EMPLOYEE", "ADMIN"]


# --- Telegram bot ---------------------------------------------------------------------


def test_bot_bloklangan_odamni_xushmuomala_rad_etadi_ulanishni_uzmaydi(tmp_path):
    from app.bot.runner import VeneraBot
    from app.core.security import hash_password
    from app.services.telegram_links import LinkStore
    from app.services.users import StoredUser
    from tests.test_telegram_bot import TG_ID, FakeBackend, FakeTelegram, text_update

    users = UserStore({"a@b.uz": StoredUser(actor_id=1, email="a@b.uz", full_name="Ali",
                                            password_hash=hash_password("x"), roles=["USER"])})
    identities = IdentityStore(tmp_path / "identities.json")
    tg, links, backend = FakeTelegram(), LinkStore(tmp_path / "links.json"), FakeBackend()
    bot = VeneraBot(tg, links, users=lambda: users, backend=backend,
                    webapp_url="https://x.test/tg/", inline=True, typing_every=None)
    links.link(TG_ID, 1)
    admin = AuthUser(actorId=99, email="boss@x.uz", fullName="Boss", roles=["ADMIN"])
    admin_users.update_user(admin, 1, identities, users, disabled=True)

    bot.handle_update(text_update("salom"))
    assert backend.questions == []
    assert tg.texts() == ["Hisobingiz bloklangan. Administratorga murojaat qiling."]
    link, state = links.lookup(TG_ID)
    assert state == "linked" and link.actor_id == 1          # ulanish JOYIDA

    admin_users.update_user(admin, 1, identities, users, disabled=False)
    bot.handle_update(text_update("savol", message_id=11))
    assert [q[0] for q in backend.questions] == ["savol"]


def test_bot_samarali_rollarni_oladi(tmp_path):
    from app.bot.runner import VeneraBot
    from app.core.security import hash_password
    from app.services.telegram_links import LinkStore
    from app.services.users import StoredUser
    from tests.test_telegram_bot import TG_ID, FakeBackend, FakeTelegram, text_update

    users = UserStore({"a@b.uz": StoredUser(actor_id=1, email="a@b.uz", full_name="Ali",
                                            password_hash=hash_password("x"), roles=["USER"])})
    seen: list[list[str]] = []

    class Backend(FakeBackend):
        def stream(self, question, user, chat_id):
            seen.append(list(user.roles))
            return super().stream(question, user, chat_id)

    tg, links = FakeTelegram(), LinkStore(tmp_path / "links.json")
    bot = VeneraBot(tg, links, users=lambda: users, backend=Backend(),
                    webapp_url="https://x.test/tg/", inline=True, typing_every=None)
    links.link(TG_ID, 1)
    with get_db().transaction() as conn:
        conn.execute("INSERT INTO user_admin (actor_id, roles) VALUES (1, '[\"USER\",\"RAG_ADMIN\"]')")
    bot.handle_update(text_update("savol"))
    assert seen == [["USER", "RAG_ADMIN"]]


# --- ombor nosoz bo'lsa ------------------------------------------------------------------


def test_ombor_oqilmasa_hamma_chiqib_ketmaydi(client, auth, monkeypatch):
    """`user_admin` o'qilmasa - sukut holati: sessiya ishlaydi (jurnalga yoziladi)."""
    import sqlite3

    def broken(*args, **kwargs):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(type(get_db()), "row", broken)
    assert client.get("/api/v1/auth/me", headers=auth).status_code == 200
    # Avval "hamma joydan chiqarilgan" odamning yangi tokeni (`ver` > 0) ham -
    # sukut holatidagi 0 versiya bilan solishtirilmaydi.
    later, _ = create_token(ADMIN["email"], version=3)
    assert _me(client, later).status_code == 200
