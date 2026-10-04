"""Backend tekshiruvida topilgan nosozliklar (2-to'plam) - regressiya testlari.

  1. JIM KESILGAN JAVOB. Yuqoridagi xizmat ulanishni ikki NDJSON kadri
     ORASIDA yopsa, `http.client` ning chunked o'quvchisi `b''` qaytaradi -
     toza EOF bilan bir xil. `done` kadri kelmagan oqim endi XATO
     (`AssistantClient.stream`, `pump`), va `chat.py` uni `stream_broken`
     xato kadri + `done` ga o'giradi. Chegaralarda (kadr/oqim hajmi)
     to'xtash ham chala javob - u ham xato.
  2. SSO IMTIYOZLARI. Keycloak rollari qanday bo'lsa shunday ko'chiriladi;
     realm'dagi `ADMIN` degan rol Venera ADMIN ini (hammaning suhbatlari)
     berib yuborardi. Endi SSO manbasidan ADMIN/RAG_ADMIN default rad
     etiladi (`admin_users._source_roles`), `SSO_TRUSTED_ROLES` bilan
     ataylab yoqiladi. `admin_logins`, `users.yaml` va panel o'zgarmaydi.

Muhitdan mustaqillik (3-band) `conftest.py` da: `_code_defaults` va
`client` fiksturasi - ularning isboti mavjud testlarning o'zi
(`test_hold.py`, `test_wake.py`, `test_chat.py`).

Hammasi OFLAYN: 1-bandning transport testi faqat `127.0.0.1` dagi
vaqtinchalik soketga boradi.
"""

from __future__ import annotations

import json
import re
import socket
import threading

import pytest

from app.core.config import settings
from app.schemas.auth import AuthUser
from app.services import admin_users
from app.services.integrations import assistant as assistant_mod
from app.services.integrations.assistant import AssistantClient, AssistantError
from tests.conftest import ADMIN
from tests.test_capture import (  # noqa: F401 - fiksturalar
    FRAMES, ask_stream, db, events_of, payload, rows, upstream,
)
from tests.test_sso_login import LOGIN, hub, net  # noqa: F401 - fiksturalar


def frame(**kw) -> bytes:
    return json.dumps(kw, ensure_ascii=False).encode("utf-8") + b"\n"


# ============================================================ 1. `done` siz EOF


class _Lines:
    """`http.client` javobi o'rnida: qatorlar, keyin `b''` - aynan chunked
    o'quvchi kadrlar orasida uzilgan ulanishda qaytaradigan narsa."""

    def __init__(self, lines: list[bytes]) -> None:
        self._lines = list(lines)
        self.headers: dict[str, str] = {}
        self.status = 200
        self.closed = False

    def readline(self, limit: int = -1) -> bytes:
        return self._lines.pop(0) if self._lines else b""

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_upstream(monkeypatch):
    """`AssistantClient._open` o'rnida - javob qatorlarini test beradi."""
    served: dict[str, list[bytes]] = {"lines": []}
    opened: list[_Lines] = []

    def open_(self, path, body, **kwargs):
        response = _Lines(served["lines"])
        opened.append(response)
        return response

    monkeypatch.setattr(AssistantClient, "_open", open_)
    served["opened"] = opened        # type: ignore[assignment]
    return served


@pytest.fixture
def assistant() -> AssistantClient:
    return AssistantClient("http://assistant.test", "venera", "sir", timeout=5, max_concurrent=1)


def _drain(stream) -> tuple[list[dict], AssistantError | None]:
    got: list[dict] = []
    try:
        for raw in stream.frames:
            got.append(json.loads(raw))
    except AssistantError as exc:
        return got, exc
    return got, None


def test_done_siz_eof_xato(assistant, fake_upstream):
    """Kadrlar keldi, keyin EOF - `done` yo'q. Ilgari oqim JIM tugardi va
    brauzer yarim javobni to'liq deb ko'rsatardi."""
    fake_upstream["lines"] = [frame(type="stage", text="..."), frame(type="token", text="Yillik ")]
    stream = assistant.stream("salom", user_id="venera:1")
    got, error = _drain(stream)
    # Kelgan kadrlar YO'QOLMAYDI - xato ulardan KEYIN ko'tariladi.
    assert [f["type"] for f in got] == ["stage", "token"]
    assert error is not None
    assert (error.status, error.retryable) == (503, True)
    assert "done" in str(error)
    assert stream.outcome["frames"] == 2
    # Ulanish yopildi va slot qaytdi (`max_concurrent=1`): keyingi savol o'tadi.
    assert fake_upstream["opened"][0].closed
    fake_upstream["lines"] = [frame(type="done", route="rules")]
    assert _drain(assistant.stream("yana", user_id="venera:1"))[1] is None


def test_done_bilan_tugasa_xato_yoq(assistant, fake_upstream):
    fake_upstream["lines"] = [frame(type="token", text="ok"), frame(type="done", route="rag")]
    stream = assistant.stream("salom", user_id="venera:1")
    got, error = _drain(stream)
    assert error is None
    assert [f["type"] for f in got] == ["token", "done"]
    assert stream.outcome["route"] == "rag"


def test_error_keyin_done_xato_emas(assistant, fake_upstream):
    """Hujjat bo'yicha `error` tokenlar O'RNIGA keladi, keyin `done` - bu
    to'liq oqim (masalan `auth_missing`), uzilish emas."""
    fake_upstream["lines"] = [frame(type="error", code="auth_missing", text="HRM kerak"),
                              frame(type="done", route=None)]
    result = assistant.ask("salom", user_id="venera:1")
    assert result["error"] == {"code": "auth_missing", "text": "HRM kerak"}


def test_error_kadri_done_siz_ham_chala(assistant, fake_upstream):
    """`error` kelgan, lekin `done` yo'q - oqim baribir chala uzilgan."""
    fake_upstream["lines"] = [frame(type="error", code="llm_failed", text="xato")]
    got, error = _drain(assistant.stream("salom", user_id="venera:1"))
    assert [f["type"] for f in got] == ["error"]
    assert error is not None and error.status == 503


def test_bosh_oqim_ham_chala(assistant, fake_upstream):
    """Sarlavhalar keldi-yu, bitta ham kadr kelmadi - bo'sh "javob" emas, xato."""
    fake_upstream["lines"] = []
    got, error = _drain(assistant.stream("salom", user_id="venera:1"))
    assert got == [] and error is not None


def test_oqim_chegarasi_chala_javob(assistant, fake_upstream, monkeypatch):
    """Oqim hajmi chegarasida to'xtash - javob kesildi, ya'ni xato (ilgari
    jim `break` edi)."""
    monkeypatch.setattr(assistant_mod, "_MAX_STREAM_BYTES", 120)
    fake_upstream["lines"] = [frame(type="token", text="x" * 40) for _ in range(10)] + [
        frame(type="done", route="rules")]
    got, error = _drain(assistant.stream("salom", user_id="venera:1"))
    assert 0 < len(got) < 10
    assert error is not None and error.status == 502


def test_kadr_chegarasi_chala_javob(assistant, fake_upstream, monkeypatch):
    monkeypatch.setattr(assistant_mod, "_MAX_LINE_BYTES", 64)
    fake_upstream["lines"] = [frame(type="token", text="a"), frame(type="token", text="x" * 200),
                              frame(type="done", route="rules")]
    got, error = _drain(assistant.stream("salom", user_id="venera:1"))
    assert [f["text"] for f in got] == ["a"]
    assert error is not None and error.status == 502


def test_done_dan_keyingi_chegara_xato_emas(assistant, fake_upstream, monkeypatch):
    """`done` kelgan - javob TO'LIQ. Undan keyingi ortiqcha bayt oqimni
    to'xtatadi, lekin "uzildi" deb xato kadri qo'shmaydi (aks holda brauzer
    `done` dan KEYIN xato olardi)."""
    monkeypatch.setattr(assistant_mod, "_MAX_LINE_BYTES", 64)
    fake_upstream["lines"] = [frame(type="token", text="ok"), frame(type="done", route="rag"),
                              frame(type="token", text="x" * 200)]
    got, error = _drain(assistant.stream("salom", user_id="venera:1"))
    assert error is None
    assert [f["type"] for f in got] == ["token", "done"]


# --- haqiqiy `http.client` bilan: chunked oqim kadrlar orasida uziladi --------------


def _chunked_server(chunks: list[bytes], *, finish: bool) -> tuple[str, threading.Thread]:
    """Bitta so'rovga chunked NDJSON beradigan server (127.0.0.1, tasodifiy
    port). `finish=False` - oxirgi `0\\r\\n\\r\\n` bo'lagisiz, ulanish shunchaki
    yopiladi: aynan `mock:cut` stsenariysi va jonli proksi uzilishi."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    srv.settimeout(10)
    port = srv.getsockname()[1]

    def run() -> None:
        try:
            conn, _ = srv.accept()
        except OSError:
            srv.close()
            return
        with conn:
            conn.settimeout(10)
            data = b""
            while b"\r\n\r\n" not in data:
                part = conn.recv(65536)
                if not part:
                    break
                data += part
            head, _, body = data.partition(b"\r\n\r\n")
            match = re.search(rb"(?i)content-length:\s*(\d+)", head)
            length = int(match.group(1)) if match else 0
            while len(body) < length:
                part = conn.recv(65536)
                if not part:
                    break
                body += part
            conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/x-ndjson\r\n"
                         b"Transfer-Encoding: chunked\r\n\r\n")
            for chunk in chunks:
                conn.sendall(b"%x\r\n%s\r\n" % (len(chunk), chunk))
            if finish:
                conn.sendall(b"0\r\n\r\n")
        srv.close()

    thread = threading.Thread(target=run, name="chunked-test-server", daemon=True)
    thread.start()
    return f"http://127.0.0.1:{port}", thread


def test_haqiqiy_chunked_uzilish_xato_beradi():
    """Nosozlikning ASL sababi transportda: `http.client` kadrlar orasidagi
    uzilishni xato EMAS, `b''` qilib beradi. Soxta javob buni ko'rsatmaydi -
    shuning uchun haqiqiy soket va haqiqiy `urllib`."""
    base, thread = _chunked_server([frame(type="stage", text="..."),
                                    frame(type="token", text="Yarim ")], finish=False)
    client = AssistantClient(base, "venera", "sir", timeout=5)
    got, error = _drain(client.stream("salom", user_id="venera:1"))
    thread.join(5)
    assert [f["type"] for f in got] == ["stage", "token"]
    assert error is not None and (error.status, error.retryable) == (503, True)


def test_haqiqiy_chunked_toliq_oqim_xatosiz():
    base, thread = _chunked_server([frame(type="token", text="ok"),
                                    frame(type="done", route="rag")], finish=True)
    client = AssistantClient(base, "venera", "sir", timeout=5)
    got, error = _drain(client.stream("salom", user_id="venera:1"))
    thread.join(5)
    assert error is None
    assert [f["type"] for f in got] == ["token", "done"]


# --- endpoint: brauzer chala javobni XATO bilan oladi, iz `error` ------------------


def test_endpoint_done_siz_oqim_stream_broken(client, auth, upstream, db):
    upstream.frames = FRAMES[:-1]          # `done` siz - ulanish kadrlar orasida yopildi
    response = ask_stream(client, auth)
    assert response.status_code == 200
    lines = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    assert [f["type"] for f in lines] == ["stage", "sources", "token", "token", "error", "done"]
    assert lines[-2]["code"] == "stream_broken"
    turn_id = response.headers["x-venera-turn"]
    [turn] = rows(db, "SELECT * FROM turns WHERE id=?", (turn_id,))
    assert (turn["status"], turn["error_code"]) == ("error", "stream_broken")
    broken = [e for e in events_of(db, turn_id) if e["name"] == "assistant.broken"]
    assert broken and "done" in payload(broken[0])["error"]
    [call] = rows(db, "SELECT * FROM api_calls WHERE service='assistant'")
    assert call["status"] == "error"


def test_endpoint_toliq_oqim_ok(client, auth, upstream, db):
    """Nazorat: `done` bilan tugagan oqimga xato kadri QO'SHILMAYDI."""
    response = ask_stream(client, auth)
    kinds = [json.loads(line)["type"] for line in response.text.splitlines() if line.strip()]
    assert kinds == ["stage", "sources", "token", "token", "done"]
    [turn] = rows(db, "SELECT status FROM turns WHERE id=?", (response.headers["x-venera-turn"],))
    assert turn["status"] == "ok"


# ============================================================ 2. SSO imtiyozlari


def _sso_login(client, net, roles: list[str]) -> dict:
    net.roles = [*roles, "employee", "offline_access"]
    response = client.post("/api/v1/auth/login", json=LOGIN)
    assert response.status_code == 200, response.text
    return response.json()


def _bearer(body: dict) -> dict:
    return {"Authorization": f"Bearer {body['token']}"}


def test_keycloak_admin_roli_venera_admin_bermaydi(client, hub, net):
    """Realm'da `ADMIN` / `RAG_ADMIN` degan rol - Venera imtiyozi EMAS."""
    body = _sso_login(client, net, ["ADMIN", "RAG_ADMIN"])
    assert "ADMIN" not in body["user"]["roles"]
    assert "RAG_ADMIN" not in body["user"]["roles"]
    # Imtiyozsiz rollar joyida - ular faqat kimligini ko'rsatadi.
    assert body["user"]["roles"] == ["employee", "crm-user"]
    headers = _bearer(body)
    assert client.get("/api/v1/auth/me", headers=headers).json()["roles"] == ["employee", "crm-user"]
    assert client.get("/api/v1/admin/users", headers=headers).status_code == 403
    assert client.get("/api/health/detail", headers=headers).status_code == 403


def test_keycloak_admin_roli_ishonilsa_admin(client, hub, net, monkeypatch):
    """`SSO_TRUSTED_ROLES=ADMIN` - Keycloak rollari Venera uchun ataylab
    boshqariladi. Ro'yxatda yo'q RAG_ADMIN baribir suziladi."""
    monkeypatch.setattr(settings, "sso_trusted_roles", "admin")     # registr muhim emas
    body = _sso_login(client, net, ["ADMIN", "RAG_ADMIN"])
    assert "ADMIN" in body["user"]["roles"]
    assert "RAG_ADMIN" not in body["user"]["roles"]
    assert client.get("/api/v1/admin/users", headers=_bearer(body)).status_code == 200


def test_users_yaml_admin_ishlayveradi(client, auth):
    """Zahira hisob (`users.yaml`) - bizning manbamiz, suzilmaydi."""
    me = client.get("/api/v1/auth/me", headers=auth).json()
    assert me["email"] == ADMIN["email"]
    assert me["roles"] == ["ADMIN", "RAG_ADMIN"]
    assert client.get("/api/v1/admin/users", headers=auth).status_code == 200


def test_panel_override_sso_hisobga_admin_beradi(client, hub, net, auth):
    """Admin panel qarori - imtiyozning qonuniy yo'li; SSO hisobiga ham ishlaydi."""
    body = _sso_login(client, net, ["ADMIN"])
    headers = _bearer(body)
    actor = body["user"]["actorId"]
    assert client.get("/api/v1/admin/users", headers=headers).status_code == 403

    # Panelda ham Keycloak ADMIN i ko'rinmaydi - sessiyadagi bilan bir xil.
    items = {i["actorId"]: i for i in client.get("/api/v1/admin/users", headers=auth).json()["items"]}
    assert "ADMIN" not in items[actor]["roles"]
    assert items[actor]["rolesSource"] == "source"

    response = client.patch(f"/api/v1/admin/users/{actor}", headers=auth,
                            json={"roles": ["employee", "ADMIN"]})
    assert response.status_code == 200, response.text
    assert response.json()["roles"] == ["employee", "ADMIN"]
    # Rollar har so'rovda qayta hisoblanadi - o'sha token bilan darhol.
    assert client.get("/api/v1/admin/users", headers=headers).status_code == 200


def test_admin_logins_sso_hisobga_admin_beradi(client, hub, net, monkeypatch):
    """`.env` dagi zaxira kalit - SSO hisobi LOGINI bilan, o'zgarmagan."""
    monkeypatch.setattr(settings, "admin_logins", LOGIN["username"])
    body = _sso_login(client, net, [])
    assert "ADMIN" in body["user"]["roles"]
    assert client.get("/api/v1/admin/users", headers=_bearer(body)).status_code == 200


def test_keycloak_admin_oxirgi_admin_hisobiga_kirmaydi():
    """"Oxirgi admin" himoyasi ham SESSIYA bilan bir xil qoidada sanaydi:
    Keycloak ADMIN i bor SSO hisobi faol admin EMAS. Aks holda yagona haqiqiy
    admin o'zini "sen oxirgisi emassan" deb pasaytira olardi."""
    st = admin_users.AdminState(actor_id=7)
    sso = admin_users.Person(actor_id=7, sso=True, sso_login="kc.user", source_roles=["ADMIN"])
    local = admin_users.Person(actor_id=8, local=True, email="it@x.uz", source_roles=["ADMIN"])
    assert admin_users._is_active_admin(sso, st) is False
    assert admin_users._is_active_admin(local, admin_users.AdminState(actor_id=8)) is True


def test_effective_manba_login_boyicha():
    """`login is not None` - SSO (bot ham shu yo'l bilan chaqiradi)."""
    user = AuthUser(actorId=5, email="x@brb.uz", fullName="X", roles=["ADMIN", "USER"])
    st = admin_users.AdminState(actor_id=5)
    assert admin_users.effective(user, login="x", admin_state=st).roles == ["USER"]
    assert admin_users.effective(user, login="", admin_state=st).roles == ["USER"]
    assert admin_users.effective(user, login=None, admin_state=st).roles == ["ADMIN", "USER"]
