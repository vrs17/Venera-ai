"""Telegram uchun tokensiz yuklab olish havolasi (`POST .../link`, `GET /file/...`).

Telegram mini app'da faylni Telegram ilovasining O'ZI yuklaydi
(`WebApp.downloadFile`) va u bizning `Authorization` sarlavhamizni yubora
olmaydi. Shuning uchun havola tokensiz ochiladi - va aynan shu sabab bu
testlarning ko'pi CHEGARA haqida: havola faqat bitta fayl, qisqa muddat,
kirish tokeni o'rnida ishlamaydi va aksincha.
"""

from __future__ import annotations

import time

import jwt
import pytest

from app.api.v1 import chat as chat_api
from app.core.config import settings
from app.core.security import create_token
from app.services.integrations.assistant import AssistantError

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
LINK = "/api/v1/chat/artifact/tok-A1/docx/link"


class FakeFiles:
    """Yuqoridagi xizmatning fayl yo'li - so'rovlarni yozib boradi."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.error: AssistantError | None = None

    def fetch_artifact(self, token: str, kind: str):
        self.calls.append((token, kind))
        if self.error:
            raise self.error
        return DOCX, "ariza.docx", iter([b"PK\x03\x04", b"soxta ariza"])


@pytest.fixture
def files(monkeypatch):
    fake = FakeFiles()
    monkeypatch.setattr(chat_api, "_assistant", fake)
    return fake


def _link(client, auth, filename="Ta'til arizasi (shablon)", path=LINK):
    return client.post(path, json={"filename": filename}, headers=auth)


def _signed(**claims) -> str:
    now = int(time.time())
    payload = {"aud": "venera:file", "iat": now, "exp": now + 60,
               "art": "tok-A1", "kind": "docx", "fn": "ariza.docx", "uid": "1"}
    payload.update(claims)
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


# --- havola ------------------------------------------------------------------


def test_havola_sessiyasiz_berilmaydi(client, files):
    assert client.post(LINK, json={}).status_code == 401
    assert files.calls == []


def test_havola_shakli(client, auth, files):
    response = _link(client, auth)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"url", "filename", "expiresIn"}
    assert body["url"].startswith("/api/v1/chat/file/")
    assert body["filename"] == "Ta'til arizasi shablon.docx"
    assert body["expiresIn"] == 600
    assert files.calls == [], "havola berilganda fayl OLINMAYDI"


@pytest.mark.parametrize("requested, saved", [
    ("ariza.exe", "ariza.exe.docx"),          # kengaytma TUR bo'yicha
    ("../../etc/passwd", "etc passwd.docx"),  # yo'l belgilari yo'q
    ('x"y\r\nz', "x y z.docx"),               # sarlavhani buzadigan belgilar
    ("", "hujjat.docx"),
    ("Ariza.DOCX", "Ariza.docx"),
])
def test_nom_tozalanadi(client, auth, files, requested, saved):
    assert _link(client, auth, requested).json()["filename"] == saved


@pytest.mark.parametrize("path", [
    "/api/v1/chat/artifact/tok-A1/preview/link",   # ko'rinish - fayl emas
    "/api/v1/chat/artifact/tok-A1/exe/link",
    "/api/v1/chat/artifact/a%20b/docx/link",        # yaroqsiz kalit
])
def test_notogri_tur_yoki_kalit(client, auth, files, path):
    assert _link(client, auth, path=path).status_code == 400


# --- havola bo'yicha fayl ----------------------------------------------------


def test_havola_boyicha_fayl_tokensiz(client, auth, files):
    url = _link(client, auth).json()["url"]
    response = client.get(url)                     # Authorization YO'Q
    assert response.status_code == 200
    assert response.content == b"PK\x03\x04soxta ariza"
    assert files.calls == [("tok-A1", "docx")]
    disposition = response.headers["content-disposition"]
    assert disposition.startswith('attachment; filename="Ta\'til arizasi shablon.docx"')
    assert "filename*=UTF-8''Ta%27til%20arizasi%20shablon.docx" in disposition
    # Telegram hujjati talabi: Telegram Web faylni `fetch` bilan oladi.
    assert response.headers["access-control-allow-origin"] == "https://web.telegram.org"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"


def test_head_ham_ishlaydi(client, auth, files):
    """Ba'zi yuklab olgichlar avval hajm va nomni so'raydi."""
    url = _link(client, auth).json()["url"]
    response = client.head(url)
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]


def test_kirillcha_nom_500_bermaydi(client, auth, files):
    """Sarlavhalar latin-1 da ketadi: faqat `filename="..."` bo'lsa kirill
    harfli nom javobni yiqitardi."""
    url = _link(client, auth, "Отпуск ариза").json()["url"]
    response = client.get(url)
    assert response.status_code == 200
    assert 'filename="hujjat.docx"' in response.headers["content-disposition"]
    assert "filename*=UTF-8''%D0%9E" in response.headers["content-disposition"]


def test_buzilgan_imzo_404(client, auth, files):
    url = _link(client, auth).json()["url"]
    tampered = url[:-3] + ("AAA" if not url.endswith("AAA") else "BBB")
    assert client.get(tampered).status_code == 404
    assert files.calls == []


def test_muddati_otgan_havola_410(client, files):
    expired = _signed(exp=int(time.time()) - 5)
    response = client.get(f"/api/v1/chat/file/{expired}")
    assert response.status_code == 410
    assert "muddati" in response.json()["message"]
    assert files.calls == []


def test_boshqa_kalit_bilan_imzolangan_404(client, files):
    forged = jwt.encode({"aud": "venera:file", "exp": int(time.time()) + 60,
                         "art": "tok-A1", "kind": "docx"}, "boshqa-sir", algorithm="HS256")
    assert client.get(f"/api/v1/chat/file/{forged}").status_code == 404
    assert files.calls == []


def test_kirish_tokeni_havola_ornida_ishlamaydi(client, files):
    """Sessiya tokeni `aud` siz - havola sifatida rad etiladi."""
    access, _ = create_token("admin@venera.uz")
    assert client.get(f"/api/v1/chat/file/{access}").status_code == 404
    assert files.calls == []


def test_havola_kirish_tokeni_ornida_ishlamaydi(client, auth, files):
    """Havola tokeni bilan API'ga kirib bo'lmaydi - `verify_token` `aud` li
    tokenni rad etadi."""
    signed = _link(client, auth).json()["url"].rsplit("/", 1)[1]
    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {signed}"})
    assert response.status_code == 401


def test_preview_imzosi_ham_fayl_bermaydi(client, files):
    """Qo'lda imzolangan `preview` (masalan eski yoki kelajakdagi tur) - rad."""
    assert client.get(f"/api/v1/chat/file/{_signed(kind='preview')}").status_code == 404
    assert files.calls == []


def test_xizmat_xatosi_ichki_manzilni_ochmaydi(client, auth, files):
    url = _link(client, auth).json()["url"]
    files.error = AssistantError("Assistant 404: http://10.10.50.4:8100/api/hr/artifacts yo'q", status=404)
    response = client.get(url)
    assert response.status_code == 404
    assert "10.10.50" not in response.text
    assert response.json()["message"] == "So'ralgan hujjat topilmadi"
