"""Speko (api.speko.dev) - jonli ovozli agent sessiyalari: «Barno AI» agenti (/barno sahifasidagi Barno).

QANDAY ISHLAYDI. Brauzer Barno API dan sessiya so'raydi (`api/v1/live.py`), biz Speko'da `POST /v1/sessions` bilan
sessiya ochamiz va brauzerga FAQAT qisqa muddatli transport tokeni va manzilini beramiz. Ovoz brauzer bilan
Speko (LiveKit, WebRTC) o'rtasida to'g'ridan-to'g'ri oqadi - bizning server orqali EMAS. Agent sozlamalari
(prompt, ovoz, modellar) Speko panelida: o'zgarsa kodni qayta chiqarish kerak emas.

KALIT. Platforma kaliti (`sk_live_...`; `.env` da tarixiy nom bilan - `SPEKO_AGENT_KEY`) FAQAT shu yerda:
brauzerga, logga va xato matniga chiqmaydi (`_redact`). Brauzerga beriladigan `transportToken` - boshqa narsa:
bitta suhbat uchun, ~15 daqiqa yashaydi.

JONLI TEKSHIRILGAN (2026-11-19). Muvaffaqiyat kodi - `201` (hujjatdagi misol 200 ni kutadi - shuning uchun har
qanday 2xx qabul qilinadi). Javob: `mode`, `runtime`, `transport` (`livekit`), `sessionId`, `transportToken`
(JWT), `transportUrl` (`wss://<loyiha>.livekit.cloud`), `expiresAt`; eski nomlar (`conversationToken`,
`livekitUrl`) ham keladi - zaxira sifatida o'qiladi.

Speko'ga odam haqida HECH NARSA yuborilmaydi (ism, hisob raqami): so'rov tanasi - faqat rejim va agent raqami.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

#: Speko sessiya rejimi: STT -> LLM -> TTS (agentning o'z sozlamasi bilan).
MODE = "cascade"


class SpekoError(Exception):
    """Speko sessiyasi ochilmadi. `status` - BIZNING javobimiz uchun kod (502 - sozlama/kalit, 503 - vaqtincha),
    `upstream` - Speko qaytargan HTTP kodi (tarmoq xatosida `None`)."""

    def __init__(self, message: str, *, status: int = 502, upstream: int | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.upstream = upstream


@dataclass(frozen=True)
class LiveSession:
    session_id: str
    transport: str
    transport_token: str
    transport_url: str
    expires_at: str | None = None


class SpekoClient:
    def __init__(self, base_url: str, api_key: str, *, timeout: float = 15.0) -> None:
        self.base_url = str(base_url or "").rstrip("/")
        self._key = str(api_key or "").strip()
        self.timeout = float(timeout)

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self._key)

    def _redact(self, text: Any) -> str:
        value = str(text or "")
        return value.replace(self._key, "***") if self._key else value

    def create_session(self, agent_id: str) -> LiveSession:
        """`POST /v1/sessions` - shu agent bilan yangi suhbat. Xato - `SpekoError` (kalitsiz matn bilan)."""
        if not self.configured:
            raise SpekoError("Speko sozlanmagan", status=503)
        body = json.dumps({"mode": MODE, "agentId": agent_id}).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/v1/sessions", data=body, method="POST",
            headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json",
                     "Accept": "application/json", "User-Agent": "barno-api"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raise self._from_http(exc) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise SpekoError(f"Speko'ga ulanib bo'lmadi: {self._redact(exc)}", status=503) from None
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise SpekoError("Speko javobi o'qilmadi", status=502) from None
        if not isinstance(data, dict):
            raise SpekoError("Speko javobi kutilgan shaklda emas", status=502)
        token = str(data.get("transportToken") or data.get("conversationToken") or "")
        url = str(data.get("transportUrl") or data.get("livekitUrl") or "")
        if not token or not url:
            raise SpekoError("Speko javobida transport tokeni yoki manzili yo'q", status=502)
        expires = data.get("expiresAt")
        return LiveSession(session_id=str(data.get("sessionId") or ""), transport=str(data.get("transport") or "livekit"),
                           transport_token=token, transport_url=url,
                           expires_at=str(expires) if expires else None)

    def _from_http(self, exc: urllib.error.HTTPError) -> SpekoError:
        """Speko xatosi -> bizning kod: 401/403/404 - BIZNING sozlama (kalit, agent raqami) - 502; 402/429 va 5xx -
        vaqtincha (balans, chegara, nosozlik) - 503. Matn - Speko'ning qisqa izohi, kalitsiz."""
        detail = ""
        try:
            payload = json.loads(exc.read().decode("utf-8", "replace"))
            if isinstance(payload, dict):
                found = payload.get("message") or payload.get("error") or payload.get("detail") or ""
                if isinstance(found, dict):
                    found = found.get("message") or found.get("code") or ""
                detail = str(found)[:200]
        except Exception:  # noqa: BLE001 - xato tanasi JSON bo'lmasligi mumkin
            detail = ""
        code = int(exc.code)
        status = 502 if code in (400, 401, 403, 404, 422) else 503
        return SpekoError(self._redact(f"Speko {code}: {detail}".rstrip(": ")), status=status, upstream=code)
