"""Telefoniya: FreePBX natijasi (servis kaliti) va qo'ng'iroq boshlash.

FreePBX o'rnida - shu testning o'zidagi HTTPS server (o'z-o'zidan imzolangan sertifikat): `call-live.php`
kontraktini taqlid qiladi va kelgan so'rovlarni yozib boradi. Haqiqiy FreePBX'ga hech narsa yuborilmaydi.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import ssl
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from app.api.v1 import telephony as telephony_api
from app.api.v1.service_auth import PerMinuteRate
from app.core.config import settings
from app.services.telephony import freepbx, service

KEY = "freepbx-test-key"
HEADERS = {"X-Service-Key": KEY}
RESULT = "/api/v1/telephony/call-result"
CALLS = "/api/v1/telephony/calls"


def _self_signed(folder):
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "freepbx.test")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(days=1))
            .not_valid_after(now + dt.timedelta(days=30)).sign(key, hashes.SHA256()))
    cert_path, key_path = folder / "pbx-cert.pem", folder / "pbx-key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    return cert_path, key_path, hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()


class FakeFreePBX:
    """`call-live.php` taqlidi: `reply` - javob (kod, JSON), `delay` - javobdan oldin kutish."""

    def __init__(self, folder) -> None:
        cert, key, self.fingerprint = _self_signed(folder)
        self.requests: list[dict] = []
        self.reply: tuple[int, dict] = (202, {"status": "accepted", "call_id": None})
        self.delay = 0.0
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 - http.server nomi
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                fake.requests.append({"path": self.path, "auth": self.headers.get("Authorization"),
                                      "body": json.loads(body or b"{}")})
                if fake.delay:
                    time.sleep(fake.delay)
                code, data = fake.reply
                raw = json.dumps(data).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        self.url = f"https://127.0.0.1:{self.server.server_address[1]}/barno-api/call-live.php"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def pbx(tmp_path, monkeypatch):
    fake = FakeFreePBX(tmp_path)
    pairs = [fake.fingerprint[i:i + 2].upper() for i in range(0, 64, 2)]
    for name, value in {
        "telephony_calls_db": tmp_path / "telephony" / "calls.db",
        "telephony_result_service_keys": f"freepbx:{hashlib.sha256(KEY.encode()).hexdigest()}",
        "telephony_enabled": True,
        "telephony_call_live_url": fake.url,
        "telephony_call_live_token": "pbx-secret-token",
        "telephony_call_live_cert_sha256": ":".join(pairs),        # FreePBX admini bergan ko'rinishda
        "telephony_call_live_timeout": 2.0,
        "telephony_calls_per_min": 100,
        "telephony_bridge_dir": "",
    }.items():
        monkeypatch.setattr(settings, name, value)
    service.reset_store()
    monkeypatch.setattr(telephony_api, "_per_admin", PerMinuteRate(lambda: max(1, int(settings.telephony_calls_per_min))))
    yield fake
    fake.close()
    service.reset_store()


def _place(client, auth, phone="+998 90 123 45 67", note="") -> dict:
    response = client.post(CALLS, json={"phone": phone, "note": note}, headers=auth)
    assert response.status_code == 200, response.text
    return response.json()


def _answered(call_id: str, **extra) -> dict:
    return {"call_id": call_id, "event": "answered", "answer_time": 1764140000, "end_time": 1764140075,
            "talk_sec": 75, "gateway_status": "ANSWER", "hangup_cause": 16, "uniqueid": "1764140000.42", **extra}


# ------------------------------------------------------------------------------------------- natija endpoint'i

def test_result_needs_service_key(client, pbx):
    body = _answered(str(uuid.uuid4()))
    assert client.post(RESULT, json=body).status_code == 401
    assert client.post(RESULT, json=body, headers={"X-Service-Key": "wrong"}).status_code == 401


def test_call_goes_out_and_answered_result_is_recorded_once(client, auth, pbx):
    call = _place(client, auth, note="1-sinov")
    assert call["status"] == "queued" and call["phone"] == "901234567" and call["httpStatus"] == 202
    sent = pbx.requests[0]
    assert sent["path"] == "/barno-api/call-live.php"
    assert sent["auth"] == "Bearer pbx-secret-token"
    # FreePBX faqat raqam va call_id ni biladi: izoh, ism va boshqa narsa ketmaydi.
    assert sent["body"] == {"call_id": call["callId"], "phone": "901234567", "metadata": {}}

    first = client.post(RESULT, json=_answered(call["callId"]), headers=HEADERS)
    assert first.status_code == 200 and first.json()["status"] == "recorded"
    again = client.post(RESULT, json=_answered(call["callId"]), headers=HEADERS)
    assert again.status_code == 409 and again.json()["status"] == "duplicate"

    detail = client.get(f"{CALLS}/{call['callId']}", headers=auth).json()
    assert (detail["status"], detail["outcome"], detail["talkSec"]) == ("completed", "talked", 75)
    assert detail["hangupCause"] == "16" and detail["note"] == "1-sinov"
    assert [e["verdict"] for e in detail["events"]] == ["recorded", "duplicate"]


@pytest.mark.parametrize("gateway, outcome", [("CHANUNAVAIL", "gateway_failed"), ("CONGESTION", "gateway_failed"),
                                              ("answer", "talked"), (None, "")])
def test_answered_outcome_follows_gateway_status(client, auth, pbx, gateway, outcome):
    call = _place(client, auth)
    client.post(RESULT, json=_answered(call["callId"], gateway_status=gateway, talk_sec=4), headers=HEADERS)
    detail = client.get(f"{CALLS}/{call['callId']}", headers=auth).json()
    assert (detail["status"], detail["outcome"], detail["gatewayStatus"]) == ("completed", outcome, gateway)


@pytest.mark.parametrize("reason, outcome", [(3, "no_answer"), ("5", "busy"), (8, "congestion"), (1, "rejected"),
                                             (0, "failed"), (99, "failed")])
def test_failed_result_reasons(client, auth, pbx, reason, outcome):
    call = _place(client, auth)
    response = client.post(RESULT, json={"call_id": call["callId"], "event": "failed", "reason": reason,
                                         "uniqueid": "x", "time": 1764140000}, headers=HEADERS)
    assert response.status_code == 200
    detail = client.get(f"{CALLS}/{call['callId']}", headers=auth).json()
    assert (detail["status"], detail["outcome"]) == ("failed", outcome)


def test_unknown_and_broken_results_still_get_2xx(client, auth, pbx):
    stranger = client.post(RESULT, json=_answered(str(uuid.uuid4())), headers=HEADERS)
    assert stranger.status_code == 200 and stranger.json()["status"] == "unknown_call"
    not_uuid = client.post(RESULT, json=_answered("123"), headers=HEADERS)
    assert not_uuid.status_code == 200 and not_uuid.json()["status"] == "unknown_call"
    garbage = client.post(RESULT, content=b"{not json", headers={**HEADERS, "Content-Type": "application/json"})
    assert garbage.status_code == 200 and garbage.json()["status"] == "invalid_payload"
    no_event = client.post(RESULT, json={"call_id": str(uuid.uuid4())}, headers=HEADERS)
    assert no_event.status_code == 200 and no_event.json()["status"] == "invalid_payload"


# ------------------------------------------------------------------------------------------- qo'ng'iroq boshlash

def test_wrong_certificate_never_receives_the_token(client, auth, pbx, monkeypatch):
    monkeypatch.setattr(settings, "telephony_call_live_cert_sha256", "ab" * 32)
    call = _place(client, auth)
    assert (call["status"], call["detail"]) == ("rejected", "cert_mismatch")
    assert pbx.requests == []


def test_freepbx_refusal_is_kept_with_reason(client, auth, pbx):
    pbx.reply = (429, {"error": "barno_max"})
    call = _place(client, auth)
    assert (call["status"], call["httpStatus"], call["detail"]) == ("rejected", 429, "barno_max")


def test_sent_without_answer_is_unknown_and_late_result_wins(client, auth, pbx, monkeypatch):
    monkeypatch.setattr(settings, "telephony_call_live_timeout", 0.5)
    pbx.delay = 1.5
    call = _place(client, auth)
    assert (call["status"], call["detail"]) == ("unknown", "no_response")
    assert len(pbx.requests) == 1
    assert client.post(RESULT, json=_answered(call["callId"]), headers=HEADERS).json()["status"] == "recorded"
    assert client.get(f"{CALLS}/{call['callId']}", headers=auth).json()["status"] == "completed"


def test_no_result_in_time_becomes_unknown_but_is_not_final(client, auth, pbx, monkeypatch):
    call = _place(client, auth)
    later = int(time.time()) + 21 * 60
    monkeypatch.setattr(service, "_now", lambda: later)
    listed = client.get(CALLS, headers=auth).json()
    assert (listed[0]["status"], listed[0]["detail"]) == ("unknown", "no_result")
    response = client.post(RESULT, json={"call_id": call["callId"], "event": "failed", "reason": 3}, headers=HEADERS)
    assert response.json()["status"] == "recorded"
    detail = client.get(f"{CALLS}/{call['callId']}", headers=auth).json()
    assert (detail["status"], detail["outcome"]) == ("failed", "no_answer")


def test_unreachable_freepbx_is_rejected_not_unknown(client, auth, pbx, monkeypatch):
    monkeypatch.setattr(settings, "telephony_call_live_url", "https://127.0.0.1:9/barno-api/call-live.php")
    call = _place(client, auth)
    assert call["status"] == "rejected" and call["detail"].startswith("connect_failed")


@pytest.mark.parametrize("phone, expected", [("901234567", "901234567"), ("998901234567", "901234567"),
                                             ("+998 (90) 123-45-67", "901234567")])
def test_phone_formats(client, auth, pbx, phone, expected):
    assert _place(client, auth, phone=phone)["phone"] == expected


@pytest.mark.parametrize("phone", ["0901234567", "12345678901", "abcdefghij", "+7 912 345 67 89"])
def test_bad_phone_is_422_and_nothing_is_sent(client, auth, pbx, phone):
    assert client.post(CALLS, json={"phone": phone}, headers=auth).status_code == 422
    assert pbx.requests == []


def test_disabled_or_unconfigured_is_503(client, auth, pbx, monkeypatch):
    monkeypatch.setattr(settings, "telephony_enabled", False)
    assert client.post(CALLS, json={"phone": "901234567"}, headers=auth).status_code == 503
    monkeypatch.setattr(settings, "telephony_enabled", True)
    monkeypatch.setattr(settings, "telephony_call_live_token", "")
    assert client.post(CALLS, json={"phone": "901234567"}, headers=auth).status_code == 503
    assert pbx.requests == []


def test_daily_cap_and_per_minute_limit(client, auth, pbx, monkeypatch):
    monkeypatch.setattr(settings, "telephony_daily_cap", 1)
    _place(client, auth)
    assert client.post(CALLS, json={"phone": "901234567"}, headers=auth).status_code == 429
    monkeypatch.setattr(settings, "telephony_daily_cap", 100)
    monkeypatch.setattr(settings, "telephony_calls_per_min", 1)
    monkeypatch.setattr(telephony_api, "_per_admin", PerMinuteRate(lambda: int(settings.telephony_calls_per_min)))
    _place(client, auth)
    assert client.post(CALLS, json={"phone": "901234567"}, headers=auth).status_code == 429
    assert len(pbx.requests) == 2


def test_only_admin_can_place_or_see_calls(client, user_auth, pbx):
    assert client.post(CALLS, json={"phone": "901234567"}, headers=user_auth).status_code == 403
    assert client.get(CALLS, headers=user_auth).status_code == 403
    assert client.get(f"{CALLS}/{uuid.uuid4()}", headers=user_auth).status_code == 403
    assert pbx.requests == []


def test_bridge_record_is_joined(client, auth, pbx, tmp_path, monkeypatch):
    call = _place(client, auth)
    folder = tmp_path / "bridge" / "calls" / "20261126"
    folder.mkdir(parents=True)
    (folder / f"{call['callId']}.json").write_text(json.dumps({
        "callId": call["callId"], "endReason": "agent_ended", "seconds": 78.6,
        "agentReport": {"sessionId": "sess_1", "durationSeconds": 76, "totalCostUsd": 0.1155, "endReason": "agent_ended",
                        "turns": [{"source": "user", "text": "MAXFIY"}]}}), encoding="utf-8")
    monkeypatch.setattr(settings, "telephony_bridge_dir", str(tmp_path / "bridge"))
    detail = client.get(f"{CALLS}/{call['callId']}", headers=auth).json()
    assert detail["bridge"] == {"endReason": "agent_ended", "seconds": 78.6, "sessionId": "sess_1", "agentSeconds": 76,
                                "costUsd": 0.1155, "agentEndReason": "agent_ended"}
    assert "MAXFIY" not in json.dumps(detail)          # suhbat matni bu yerga chiqmaydi


def test_missing_call_is_404(client, auth, pbx):
    assert client.get(f"{CALLS}/{uuid.uuid4()}", headers=auth).status_code == 404


def test_fingerprint_formats():
    digest = "df" * 32
    assert freepbx.normalize_fingerprint(":".join(["DF"] * 32)) == digest
    assert freepbx.normalize_fingerprint(digest.upper()) == digest
    assert freepbx.normalize_fingerprint("DF:AB") == ""
    assert freepbx.place("http://127.0.0.1/x", "t", digest, call_id="c", phone="901234567", timeout=1).detail == "not_configured"


def test_status_for_the_panel(client, auth, user_auth, pbx, monkeypatch):
    status = client.get("/api/v1/telephony/status", headers=auth).json()
    assert status == {"enabled": True, "configured": True, "dailyCap": 20, "used24h": 0}
    _place(client, auth)
    assert client.get("/api/v1/telephony/status", headers=auth).json()["used24h"] == 1
    monkeypatch.setattr(settings, "telephony_call_live_cert_sha256", "")
    assert client.get("/api/v1/telephony/status", headers=auth).json()["configured"] is False
    assert client.get("/api/v1/telephony/status", headers=user_auth).status_code == 403
