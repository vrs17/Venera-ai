"""Qurilma sessiyalari (mobil ilova): ro'yxat, almashtirish, bekor qilish, admin qarorlari (3.2, 29-31)."""

from __future__ import annotations

import hashlib
import os
import stat
import time

from app.core.config import settings
from app.core.security import verify_claims
from app.services import analytics
from app.services.analytics.db import get_db
from app.services.users import UserStore
from meetings_fakes import enable


def _register(client, headers) -> dict:
    response = client.post("/api/v1/auth/devices", headers=headers,
                           json={"deviceName": "SM-S921B", "platform": "android", "appVersion": "1.0.0"})
    assert response.status_code == 201, response.text
    return response.json()


def _session(client, token: str):
    return client.post("/api/v1/auth/devices/session", json={"deviceToken": token})


def _events() -> list[dict]:
    analytics.flush()
    return get_db().rows("SELECT * FROM auth_events WHERE method = 'device' ORDER BY id")


def test_royxat_sessiya_bekor(client, auth, monkeypatch, _isolated_meetings):
    enable(monkeypatch)
    device = _register(client, auth)
    assert len(device["deviceToken"]) == 43 and device["expiresAt"].endswith("Z")
    rows = _isolated_meetings.devices.rows()
    assert rows[0]["token_hash"] == hashlib.sha256(device["deviceToken"].encode()).hexdigest()
    assert device["deviceToken"] not in str(rows)                        # faqat xesh
    assert stat.S_IMODE(os.stat(settings.devices_db).st_mode) == 0o600

    response = _session(client, device["deviceToken"])
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"token", "tokenType", "expiresAt", "passwordChangeRequired", "user"}
    assert body["user"]["actorId"] == 1 and verify_claims(body["token"]).subject == "admin@venera.uz"
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {body['token']}"})
    assert me.status_code == 200
    assert _events()[-1]["ok"] == 1

    assert client.post("/api/v1/auth/devices/revoke", json={"deviceToken": device["deviceToken"]}).json() == \
        {"status": "OK"}
    assert client.post("/api/v1/auth/devices/revoke", json={"deviceToken": device["deviceToken"]}).status_code == 200
    refused = _session(client, device["deviceToken"])
    assert refused.status_code == 401 and _events()[-1]["reason"] == "device_revoked"


def test_nomalum_va_eskirgan_token(client, auth, monkeypatch, _isolated_meetings):
    enable(monkeypatch)
    assert _session(client, "yoq-token").status_code == 401
    assert _events()[-1]["reason"] == "device_unknown"
    device = _register(client, auth)
    _isolated_meetings.devices._connect().execute("UPDATE devices SET expires_at=?", (int(time.time()) - 1,))
    assert _session(client, device["deviceToken"]).status_code == 401
    assert _events()[-1]["reason"] == "device_expired"


def test_sirpanuvchi_muddat(client, auth, monkeypatch, _isolated_meetings):
    enable(monkeypatch)
    device = _register(client, auth)
    store = _isolated_meetings.devices
    store._connect().execute("UPDATE devices SET expires_at=?, last_used_at=?",
                             (int(time.time()) + 100, int(time.time()) - 86400))
    assert _session(client, device["deviceToken"]).status_code == 200
    row = store.rows()[0]
    assert row["expires_at"] >= int(time.time()) + 30 * 86400 - 5


def test_royxat_bayroq_va_ruxsat_ortida(client, auth, user_auth, monkeypatch):
    assert client.post("/api/v1/auth/devices", headers=auth,
                       json={"deviceName": "x", "platform": "android"}).status_code == 404
    enable(monkeypatch)
    assert client.post("/api/v1/auth/devices", headers=user_auth,
                       json={"deviceName": "x", "platform": "android"}).status_code == 403
    assert client.post("/api/v1/auth/devices", json={"deviceName": "x", "platform": "android"}).status_code == 401


def test_bloklangan_403_va_hamma_joydan_chiqarish_401(client, auth, users_file, monkeypatch):
    enable(monkeypatch, logins="demo@venera.uz")
    user_login = client.post("/api/v1/auth/login", json={"username": "demo@venera.uz", "password": "demo2026"})
    user_headers = {"Authorization": f"Bearer {user_login.json()['token']}"}
    device = _register(client, user_headers)
    client.patch("/api/v1/admin/users/2", headers=auth, json={"disabled": True})
    blocked = _session(client, device["deviceToken"])
    assert blocked.status_code == 403 and "bloklangan" in blocked.json()["message"].lower()
    # Blok sessiya versiyasini oshiradi (`admin_users`) - blok olingach ham bu token o'lik.
    client.patch("/api/v1/admin/users/2", headers=auth, json={"disabled": False})
    dead = _session(client, device["deviceToken"])
    assert dead.status_code == 401 and _events()[-1]["reason"] == "device_signed_out"
    # Yangi kirish -> yangi qurilma tokeni; "hamma joydan chiqarish" uni ham o'ldiradi.
    user_login = client.post("/api/v1/auth/login", json={"username": "demo@venera.uz", "password": "demo2026"})
    fresh = _register(client, {"Authorization": f"Bearer {user_login.json()['token']}"})
    assert _session(client, fresh["deviceToken"]).status_code == 200
    assert client.post("/api/v1/admin/users/2/signout", headers=auth).status_code == 200
    signed_out = _session(client, fresh["deviceToken"])
    assert signed_out.status_code == 401 and _events()[-1]["reason"] == "device_signed_out"
    assert _session(client, fresh["deviceToken"]).status_code == 401      # token o'ldi (bekor qilingan)


def test_zahira_hisob_qoidalari(client, auth, users_file, monkeypatch):
    import yaml

    from app.api.deps import get_user_store
    from app.main import app

    enable(monkeypatch)
    device = _register(client, auth)
    monkeypatch.setattr(settings, "local_login_enabled", False)
    assert _session(client, device["deviceToken"]).status_code == 401
    assert _events()[-1]["reason"] == "local_login_disabled"
    monkeypatch.setattr(settings, "local_login_enabled", True)
    raw = yaml.safe_load(users_file.read_text(encoding="utf-8"))
    raw["users"][0]["password_change_required"] = True
    users_file.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    store = UserStore.from_file(users_file)
    app.dependency_overrides[get_user_store] = lambda: store
    assert _session(client, device["deviceToken"]).status_code == 401
    assert _events()[-1]["reason"] == "password_change_required"


def test_urinishlar_chegarasi(client, auth, monkeypatch):
    enable(monkeypatch)
    for _ in range(6):
        assert _session(client, "bir-xil-token").status_code == 401
    limited = _session(client, "bir-xil-token")
    assert limited.status_code == 429 and limited.headers.get("Retry-After")
    assert limited.json()["code"] == "rate_limited"
    assert _session(client, "boshqa-token").json()["code"] == "invalid_device_token"


def test_tozalash_muddati_otganlarni_ochiradi(_isolated_meetings):
    store = _isolated_meetings.devices
    _, token, _ = store.register(1, 0, name="a", platform="android", app_version="1", now=time.time() - 40 * 86400)
    _, keep, _ = store.register(1, 0, name="b", platform="android", app_version="1")
    assert store.purge() == 1
    assert store.lookup(keep)[1] == "ok" and store.lookup(token)[1] == "unknown"
