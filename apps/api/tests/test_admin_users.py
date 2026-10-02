"""Admin panel: foydalanuvchilar katalogi, varaq, rollar/blok himoyalari,
audit, ulanishni majburan uzish, Telegramni uzish.

`api/v1/admin_users.py`, `services/admin_users.py`. Tarmoqqa chiqilmaydi:
ulanishlar markazi - soxta (`FakeHub`), savollar tarixi esa vaqtinchalik
analitika omboriga `TurnRecorder` bilan yoziladi - `chat.py` yozadigan
AYNI yo'l bilan.
"""

from __future__ import annotations

import time

from datetime import datetime, timezone

import pytest

from app.schemas.auth import AuthUser
from app.services import admin_users, analytics
from app.services.analytics import TurnRecorder, get_db
from app.services.identities import SsoProfile
from app.services.integrations.connectors import ConnectorError
from app.services.users import UserStore
from tests.conftest import USER

# types.ts: AdminUser / AdminUserDetail / AdminConnector / AuditEntry / TurnSummary
ADMIN_USER_FIELDS = {
    "actorId", "name", "login", "email", "department", "position", "source", "roles",
    "rolesSource", "rolesLocked", "disabled", "lastSeenAt", "lastLoginAt", "turns",
    "channels", "reports",
}
DETAIL_FIELDS = ADMIN_USER_FIELDS | {"stats", "connectors", "telegram", "recentTurns", "audit",
                                     "note"}
STATS_FIELDS = {"turns", "errors", "medianTtftMs", "reports", "voiceTurns"}
CONNECTOR_FIELDS = {"platform", "connected", "enabled", "login", "expiresAt", "state"}
AUDIT_FIELDS = {"id", "createdAt", "adminActorId", "adminName", "action", "targetType",
                "targetId", "detail"}
TURN_SUMMARY_FIELDS = {
    "id", "startedAt", "actorId", "userName", "userLogin", "channel", "kind", "inputMode",
    "chatId", "question", "route", "status", "errorCode", "ttftMs", "totalMs", "sourcesCount",
    "toolCalls", "hasProposal", "proposalStatus", "hasArtifact", "reported", "engine",
}

DEMO = AuthUser(actorId=2, email=USER["email"], fullName="Demo Foydalanuvchi", roles=["USER"])
SUB = "6f1a2b3c-0000-4000-8000-00000000abcd"


def _turn(actor, channel="web", *, question="Savol?", answer="Javob.", chat="c-1",
          voice=False, error=False, ttft=True):
    rec = TurnRecorder(actor, channel, "chat", question, chat_id=chat,
                       input_mode="voice" if voice else "text")
    if ttft:
        rec.observe({"type": "token", "text": answer})
    if error:
        rec.observe({"type": "error", "code": "stream_broken", "text": "uzildi"})
    rec.observe({"type": "done", "route": "rules"})
    rec.finish()
    return rec.turn_id


def _flush():
    assert analytics.flush()


def _items(client, auth, **params):
    response = client.get("/api/v1/admin/users", headers=auth, params=params)
    assert response.status_code == 200, response.text
    return {item["actorId"]: item for item in response.json()["items"]}


def _identities():
    from app.api.deps import get_identity_store

    return get_identity_store()


class FakeHub:
    """Ulanishlar markazi o'rnida: holat va uzishni yozib boradi, tarmoqsiz."""

    def __init__(self) -> None:
        self.disconnected: list[tuple[str, str]] = []
        self.forgot: list[str] = []
        self.rows = {
            "hrm": {"id": "hrm", "label": "HRM", "configured": True, "state": "connected",
                    "login": "demo", "enabled": True, "expiresAt": "2026-09-30T00:00:00+00:00"},
            "crm": {"id": "crm", "label": "CRM", "configured": True, "state": "expired",
                    "login": "demo", "enabled": False, "expiresAt": None},
        }

    def status(self, user_id):
        return [dict(self.rows["hrm"]), dict(self.rows["crm"])]

    def disconnect(self, user_id, platform):
        if platform not in self.rows:
            raise ConnectorError("Bunday platforma yo'q", status=404, code="UNKNOWN_PLATFORM")
        self.disconnected.append((user_id, platform))
        self.rows[platform] = {"id": platform, "label": platform.upper(), "configured": True,
                               "state": "disconnected", "login": None, "enabled": False,
                               "expiresAt": None}
        return dict(self.rows[platform])

    def forget_password(self, user_id):
        self.forgot.append(user_id)


@pytest.fixture
def fake_hub(monkeypatch):
    from app.api.v1 import connectors as connectors_api

    hub = FakeHub()
    monkeypatch.setattr(connectors_api, "hub", hub)
    return hub


# --- katalog ---------------------------------------------------------------------------


def test_royxat_uch_manba_va_shakl(client, auth, users_file):
    _turn(DEMO, "web")
    _turn(DEMO, "bot", chat="tg-1")
    _turn({"actorId": 77, "fullName": "Ketgan Xodim", "email": "ketgan@venera.uz"}, "miniapp")
    _identities().upsert(SsoProfile(subject=SUB, username="y.m", email="y.m@brb.uz",
                                    full_name="Yusuf M", roles=("employee",)),
                         legacy=UserStore.from_file(users_file))
    _flush()

    items = _items(client, auth)
    assert set(items) == {1, 2, 3, 77}
    for item in items.values():
        assert set(item) == ADMIN_USER_FIELDS
    assert items[1]["source"] == "local" and items[1]["roles"] == ["ADMIN", "RAG_ADMIN"]
    assert items[1]["department"] == "IT" and items[1]["lastLoginAt"]     # `auth` kirgan
    assert (items[2]["turns"], items[2]["channels"]) == (2, ["web", "bot"])
    assert items[2]["lastSeenAt"].endswith("Z")
    assert (items[3]["source"], items[3]["login"], items[3]["roles"]) == ("sso", "y.m", ["employee"])
    assert (items[77]["source"], items[77]["name"], items[77]["login"]) == (
        "telemetry", "Ketgan Xodim", "ketgan@venera.uz")
    # Tartib - oxirgi faollik bo'yicha: savol bergan odamlar oldinda.
    order = [i["actorId"] for i in client.get("/api/v1/admin/users", headers=auth).json()["items"]]
    assert order[:2] == [77, 2]


def test_eski_hisob_sso_bilan_kirsa_both(client, auth, users_file):
    _identities().upsert(SsoProfile(subject=SUB, username="demo", email=USER["email"],
                                    full_name="Demo SSO", roles=("employee",)),
                         legacy=UserStore.from_file(users_file))
    item = _items(client, auth)[2]
    # Ikkala manbada - ism va rollar SSO dan (kirishning asosiy yo'li).
    assert (item["source"], item["name"], item["login"], item["roles"]) == (
        "both", "Demo SSO", "demo", ["employee"])


def test_filtrlar(client, auth):
    _turn(DEMO, "bot")
    _flush()
    assert set(_items(client, auth, q="demo")) == {2}
    assert set(_items(client, auth, q="tizim administratori")) == {1}
    assert set(_items(client, auth, q="2")) == {2}
    assert set(_items(client, auth, role="rag_admin")) == {1}
    assert set(_items(client, auth, channel="bot")) == {2}
    assert set(_items(client, auth, channel="web")) == set()
    client.patch("/api/v1/admin/users/2", headers=auth, json={"disabled": True})
    assert set(_items(client, auth, status="blocked")) == {2}
    assert set(_items(client, auth, status="active")) == {1}


def test_oraliq_statistikaga_tasir_qiladi(client, auth):
    _turn(DEMO)
    _flush()
    old = time.time() - 30 * 86400
    with get_db().transaction() as conn:
        conn.execute("UPDATE turns SET started_at = ?", (old,))
    assert _items(client, auth)[2]["turns"] == 0                     # sukut: oxirgi 7 kun
    since = datetime.fromtimestamp(time.time() - 60 * 86400, timezone.utc).strftime("%Y-%m-%d")
    assert _items(client, auth, **{"from": since})[2]["turns"] == 1
    assert _items(client, auth)[2]["lastSeenAt"]                     # oxirgi faollik oraliqsiz


@pytest.mark.parametrize("params", [{"from": "kecha"}, {"from": "2026-09-10", "to": "2026-09-01"},
                                    {"status": "yoq"}, {"channel": "fax"}])
def test_notogri_parametr_422(client, auth, params):
    assert client.get("/api/v1/admin/users", headers=auth, params=params).status_code == 422


# --- varaq ------------------------------------------------------------------------------


def test_varaq_statistika_ulanishlar_telegram_savollar(client, auth, fake_hub):
    import app.bot as bot_module

    _turn(DEMO, "web")
    _turn(DEMO, "web", voice=True)
    _turn(DEMO, "miniapp", error=True, ttft=False)
    _flush()
    bot_module.links.link(800001, 2)
    bot_module.links.link(800002, 2)
    client.patch("/api/v1/admin/users/2", headers=auth, json={"note": "  sinov izohi  "})

    response = client.get("/api/v1/admin/users/2", headers=auth)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == DETAIL_FIELDS
    assert set(body["stats"]) == STATS_FIELDS
    assert body["stats"]["turns"] == 3 and body["stats"]["errors"] == 1
    assert body["stats"]["voiceTurns"] == 1 and isinstance(body["stats"]["medianTtftMs"], int)
    assert [set(c) for c in body["connectors"]] == [CONNECTOR_FIELDS, CONNECTOR_FIELDS]
    hrm, crm = body["connectors"]
    assert (hrm["platform"], hrm["connected"], hrm["state"]) == ("hrm", True, "connected")
    assert (crm["platform"], crm["connected"], crm["state"]) == ("crm", False, "expired")
    assert body["telegram"]["links"] == 2 and body["telegram"]["lastSeenAt"]
    assert len(body["recentTurns"]) == 3
    assert all(set(t) == TURN_SUMMARY_FIELDS for t in body["recentTurns"])
    assert body["recentTurns"][0]["channel"] == "miniapp"                 # yangisi birinchi
    assert body["note"] == "sinov izohi"
    assert [set(a) for a in body["audit"]] == [AUDIT_FIELDS]
    assert body["audit"][0]["action"] == "user.note"
    # Varaqda token yoki parol YO'Q.
    assert "token" not in response.text.lower().replace("tokenversion", "")


def test_varaq_yoq_odam_404(client, auth):
    response = client.get("/api/v1/admin/users/4242", headers=auth)
    assert response.status_code == 404 and response.json()["message"] == "Foydalanuvchi topilmadi"


# --- o'zgartirish va himoyalar ----------------------------------------------------------


def test_nomalum_rol_422_manbadagi_rol_qabul(client, auth, users_file):
    response = client.patch("/api/v1/admin/users/2", headers=auth, json={"roles": ["SUPERUSER"]})
    assert response.status_code == 422 and "SUPERUSER" in response.json()["message"]
    _identities().upsert(SsoProfile(subject=SUB, username="y.m", email="y.m@brb.uz",
                                    roles=("employee",)), legacy=UserStore.from_file(users_file))
    # Manbada (Keycloak) BOR rol - qabul qilinadi, asl yozilishida.
    response = client.patch("/api/v1/admin/users/2", headers=auth, json={"roles": ["EMPLOYEE", "user"]})
    assert response.status_code == 200 and response.json()["roles"] == ["employee", "USER"]


def test_ozidan_admin_olish_va_ozini_bloklash_409(client, auth):
    response = client.patch("/api/v1/admin/users/1", headers=auth, json={"roles": ["RAG_ADMIN"]})
    assert response.status_code == 409 and "O'zingizdan" in response.json()["message"]
    response = client.patch("/api/v1/admin/users/1", headers=auth, json={"disabled": True})
    assert response.status_code == 409 and "O'zingizni" in response.json()["message"]
    # O'z rollarini ADMIN ni saqlab o'zgartirish - mumkin.
    response = client.patch("/api/v1/admin/users/1", headers=auth, json={"roles": ["ADMIN"]})
    assert response.status_code == 200 and response.json()["roles"] == ["ADMIN"]
    assert admin_users.audit_entries(target_type="user", target_id=1)[0]["action"] == "user.roles"


def test_oxirgi_admin_pasaytirilmaydi_va_bloklanmaydi(users_file):
    """Katalogdagi YAGONA faol ADMIN - 1. Amal qiluvchi (99) katalogda yo'q
    (masalan boshqa yo'l bilan admin bo'lgan) - himoya baribir ishlaydi."""
    identities, users = _identities(), UserStore.from_file(users_file)
    boss = AuthUser(actorId=99, email="boss@x.uz", fullName="Boss", roles=["ADMIN"])
    for change in ({"roles": ["USER"]}, {"disabled": True}):
        with pytest.raises(admin_users.AdminError) as info:
            admin_users.update_user(boss, 1, identities, users, **change)
        assert info.value.status == 409 and info.value.code == "LAST_ADMIN"
    assert admin_users.state(1).roles is None and not admin_users.state(1).disabled
    assert admin_users.audit_entries() == []

    # Ikkinchi admin paydo bo'lsa - birinchisini pasaytirish mumkin.
    admin_users.update_user(boss, 2, identities, users, roles=["USER", "ADMIN"])
    item = admin_users.update_user(boss, 1, identities, users, roles=["RAG_ADMIN"])
    assert item["roles"] == ["RAG_ADMIN"]
    # Endi 2 - yagona admin: uni bloklab bo'lmaydi.
    with pytest.raises(admin_users.AdminError):
        admin_users.update_user(boss, 2, identities, users, disabled=True)


def test_audit_yozuvlari_va_takroriy_patch_audit_yozmaydi(client, auth):
    client.patch("/api/v1/admin/users/2", headers=auth, json={"roles": ["USER", "RAG_ADMIN"]})
    client.patch("/api/v1/admin/users/2", headers=auth, json={"disabled": True})
    client.patch("/api/v1/admin/users/2", headers=auth, json={"disabled": True})   # o'zgarishsiz
    client.patch("/api/v1/admin/users/2", headers=auth, json={"disabled": False, "note": "ok"})
    client.patch("/api/v1/admin/users/2", headers=auth, json={})                   # bo'sh
    entries = admin_users.audit_entries(target_type="user", target_id=2)
    assert [e["action"] for e in entries] == ["user.note", "user.unblock", "user.block", "user.roles"]
    roles = entries[-1]
    assert roles["detail"] == {"from": ["USER"], "to": ["USER", "RAG_ADMIN"],
                               "override": ["USER", "RAG_ADMIN"]}
    assert roles["adminActorId"] == 1 and roles["adminName"] == "Administrator"
    assert roles["targetType"] == "user" and roles["targetId"] == "2"
    assert entries[2]["detail"] == {"tokenVersion": 1}
    assert entries[0]["detail"] == {"chars": 2, "preview": "ok"}


def test_bloklash_hrm_parolini_xotiradan_ochiradi(client, auth, fake_hub):
    client.patch("/api/v1/admin/users/2", headers=auth, json={"disabled": True})
    assert fake_hub.forgot == ["2"]


def test_patch_tanasi_tekshiriladi(client, auth):
    assert client.patch("/api/v1/admin/users/2", headers=auth,
                        json={"note": "x" * 501}).status_code == 422
    assert client.patch("/api/v1/admin/users/2", headers=auth,
                        json={"roles": ["USER"] * 21}).status_code == 422
    assert client.patch("/api/v1/admin/users/4242", headers=auth,
                        json={"disabled": True}).status_code == 404


# --- ulanish va Telegram ----------------------------------------------------------------


def test_ulanishni_majburan_uzish(client, auth, fake_hub):
    response = client.delete("/api/v1/admin/users/2/connectors/crm", headers=auth)
    assert response.status_code == 200, response.text
    assert set(response.json()) == CONNECTOR_FIELDS
    assert (response.json()["platform"], response.json()["state"]) == ("crm", "disconnected")
    assert fake_hub.disconnected == [("2", "crm")]
    entry = admin_users.audit_entries(target_type="user", target_id=2)[0]
    assert entry["action"] == "user.connector.disconnect"
    assert entry["detail"] == {"platform": "crm", "state": "expired"}

    assert client.delete("/api/v1/admin/users/2/connectors/xyz", headers=auth).status_code == 404
    assert client.delete("/api/v1/admin/users/4242/connectors/crm", headers=auth).status_code == 404
    assert fake_hub.disconnected == [("2", "crm")]


def test_ulanishni_uzish_haqiqiy_markaz_bilan(client, auth):
    """conftest'dagi haqiqiy `ConnectorHub` (sozlanmagan, tarmoqsiz) - saqlangan
    yozuv o'chadi."""
    from app.api.v1 import connectors as connectors_api

    connectors_api.hub.store.set("2", "hrm", {"login": "demo", "token": "t", "expires_at": 1e12,
                                             "enabled": True})
    response = client.delete("/api/v1/admin/users/2/connectors/hrm", headers=auth)
    assert response.status_code == 200 and response.json()["state"] == "disconnected"
    assert connectors_api.hub.store.get("2") == {}


def test_telegramni_uzish_faqat_shu_odamniki(client, auth):
    import app.bot as bot_module

    bot_module.links.link(900001, 2)
    bot_module.links.link(900002, 2)
    bot_module.links.link(900003, 1)
    response = client.delete("/api/v1/admin/users/2/telegram", headers=auth)
    assert response.status_code == 200 and response.json() == {"unlinked": 2}
    assert bot_module.links.by_actor(2) == [] and len(bot_module.links.by_actor(1)) == 1
    entry = admin_users.audit_entries(target_type="user", target_id=2)[0]
    assert (entry["action"], entry["detail"]) == ("user.telegram.unlink", {"links": 2})
    # Takror - 0, xato emas.
    assert client.delete("/api/v1/admin/users/2/telegram", headers=auth).json() == {"unlinked": 0}


# --- huquq ------------------------------------------------------------------------------


@pytest.mark.parametrize("method,path,body", [
    ("GET", "/api/v1/admin/users", None),
    ("GET", "/api/v1/admin/users/1", None),
    ("PATCH", "/api/v1/admin/users/1", {"roles": ["USER"]}),
    ("POST", "/api/v1/admin/users/1/signout", None),
    ("DELETE", "/api/v1/admin/users/1/connectors/crm", None),
    ("DELETE", "/api/v1/admin/users/1/telegram", None),
])
def test_oddiy_xodimga_hammasi_403(client, method, path, body):
    token = client.post("/api/v1/auth/login", json=USER).json()["token"]
    response = client.request(method, path, headers={"Authorization": f"Bearer {token}"},
                              json=body)
    assert response.status_code == 403
    # Hech narsa o'zgarmadi.
    assert admin_users.state(1).roles is None and admin_users.audit_entries() == []
