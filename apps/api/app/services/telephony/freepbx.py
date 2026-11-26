"""FreePBX `call-live.php` klienti: mijozga qo'ng'iroq boshlash so'rovi.

SO'ROV (kontrakt, FreePBX admini bilan kelishilgan):
    POST https://<freepbx>/barno-api/call-live.php
    Authorization: Bearer <token>
    {"call_id": "<uuid>", "phone": "<9 raqam, 0 bilan boshlanmaydi>", "metadata": {}}

JAVOB KODLARI:
    202  qabul qilindi - FreePBX qo'ng'iroq qilmoqda, natija keyin `call-result` ga keladi;
    400  JSON buzilgan;  401  token noto'g'ri;  405  usul noto'g'ri;
    409  bu call_id allaqachon ishlatilgan (qayta urinish YANGI call_id bilan bo'ladi);
    422  raqam yoki call_id noto'g'ri;
    429  chegara: disabled | barno_max | trunk | lock (javobdagi `details` - bizda `detail` ga yoziladi);
    502  FreePBX qo'ng'iroqni boshlay olmadi (originate rad etildi);
    503  not_configured | pbx_unavailable | gateway_unavailable.

SERTIFIKAT. FreePBX'ning HTTPS sertifikati o'z-o'zidan imzolangan, shuning uchun CA zanjiri emas, sertifikat
BARMOQ IZI (SHA-256) tekshiriladi - va bu so'rov YUBORILISHIDAN OLDIN bo'ladi: boshqa server bo'lsa token unga
umuman ketmaydi.

YUBORILDI-YU JAVOB KELMADI. Bu holatda FreePBX qo'ng'iroqni boshlagan bo'lishi MUMKIN. Shuning uchun natija
«rad etildi» emas, «noma'lum» (`sent=True`): qayta urinish bu qo'ng'iroqni ikki marta qilib yuborishi mumkin.
"""

from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import socket
import ssl
from dataclasses import dataclass, field
from urllib.parse import urlsplit

USER_AGENT = "barno-telephony/1"
MAX_BODY = 64 * 1024


@dataclass
class CallLiveResult:
    #: HTTP kodi; 0 - javob olinmadi (ulanib bo'lmadi, sertifikat mos emas yoki javob kelmadi).
    status: int
    #: Sabab: javobdagi `detail`/`error` maydoni yoki bizning xato turimiz (`cert_mismatch`, `no_response`...).
    detail: str = ""
    #: So'rov FreePBX'ga yetib borganmi (token va raqam yuborilganmi).
    sent: bool = False
    body: dict = field(default_factory=dict)


def normalize_fingerprint(value: str) -> str:
    """`AA:BB:...` / `aabb...` -> 64 belgili kichik hex; noto'g'ri bo'lsa bo'sh satr."""
    digest = "".join(ch for ch in (value or "").lower() if ch in "0123456789abcdef")
    return digest if len(digest) == 64 else ""


def _detail(body: dict) -> str:
    """Rad etish sababi. FreePBX: `{"ok": false, "error": "busy", "details": "barno_max"}` - aniq sabab `details` da
    (429: disabled | barno_max | trunk | lock; 422: call_id | phone), qolganida `error` ning o'zi
    (duplicate_call_id, originate_failed, gateway_unavailable, pbx_unavailable, not_configured, unauthorized)."""
    for key in ("details", "error", "detail", "reason", "message"):
        value = body.get(key)
        if isinstance(value, dict):
            value = value.get("code") or value.get("message")
        if value not in (None, ""):
            return str(value)[:80]
    return ""


def place(url: str, token: str, fingerprint: str, *, call_id: str, phone: str, timeout: float) -> CallLiveResult:
    """Qo'ng'iroq so'rovini yuboradi. Istisno ko'tarmaydi: har qanday xato `CallLiveResult` bo'lib qaytadi."""
    parts = urlsplit(url)
    pin = normalize_fingerprint(fingerprint)
    if parts.scheme != "https" or not parts.hostname or not pin or not token:
        return CallLiveResult(0, "not_configured")
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    context = ssl.create_default_context()
    # Zanjir va nom tekshirilmaydi - ular o'rnini quyidagi barmoq izi solishtiruvi bosadi.
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    conn = http.client.HTTPSConnection(parts.hostname, parts.port or 443, timeout=timeout, context=context)
    sent = False
    try:
        try:
            conn.connect()
        except (OSError, ssl.SSLError) as exc:
            return CallLiveResult(0, f"connect_failed:{type(exc).__name__}")
        der = conn.sock.getpeercert(binary_form=True) or b""
        if not hmac.compare_digest(hashlib.sha256(der).hexdigest(), pin):
            return CallLiveResult(0, "cert_mismatch")
        payload = json.dumps({"call_id": call_id, "phone": phone, "metadata": {}}).encode("utf-8")
        try:
            conn.request("POST", path, body=payload, headers={
                "Authorization": f"Bearer {token}", "Content-Type": "application/json",
                "Accept": "application/json", "User-Agent": USER_AGENT})
            sent = True
            response = conn.getresponse()
            raw = response.read(MAX_BODY)
        except (OSError, ssl.SSLError, http.client.HTTPException, socket.timeout) as exc:
            return CallLiveResult(0, "no_response" if sent else f"send_failed:{type(exc).__name__}", sent=sent)
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            body = {}
        if not isinstance(body, dict):
            body = {}
        return CallLiveResult(response.status, _detail(body), sent=True, body=body)
    finally:
        conn.close()
