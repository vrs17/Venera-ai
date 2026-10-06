"""Telegram Bot API klienti va mini app `initData` tekshiruvi.

NEGA STDLIB `urllib`. Loyihadagi boshqa klientlar kabi (`stt.py`,
`assistant.py`): `httpx` faqat test bog'liqligi, ishlab chiqarish uchun
yangi paket qo'shilmaydi. Bu modul BLOKLAYDI - chaqiruvchi bot iplari.

TOKEN SIR. U manzilning O'ZIDA turadi (`/bot<token>/method`), ya'ni har
qanday tarmoq xatosi matnida paydo bo'lishi mumkin. Shuning uchun bu yerdan
chiqadigan HAR BIR xato matni `_redact` dan o'tadi - jurnalga ham, `/api/
health/detail` ga ham token tushmaydi.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from collections.abc import Mapping
from socket import timeout as socket_timeout
from typing import Any

from ..analytics.meter import begin, current

log = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"

#: Hisobga FAQAT XATOSI yoziladigan usullar. `getUpdates` - 25 soniyalik uzun
#: so'rov, kuniga ~3500 marta: har birini yozish xizmat statistikasini
#: (p50 = 25 s) ma'nosiz qilardi. `sendChatAction` ("yozmoqda...") javob
#: davomida har 4.5 s da ketadi - u ham shovqin. Ularning XATOSI esa muhim
#: (409 - botni boshqa jarayon o'qiyapti, 401 - token bekor qilingan).
_QUIET_OK = frozenset({"getUpdates", "sendChatAction"})

#: 429 da Telegram aytgan kutish shundan uzun bo'lsa QAYTA URINILMAYDI -
#: xabar kechikib kelgandan ko'ra xato jurnalda qolgani yaxshi.
_MAX_RETRY_AFTER = 30

#: Yuklab olinadigan fayl uchun zaxira chegara. Asosiysi chaqiruvchida
#: (`limit`), bu faqat noto'g'ri chaqiruvdan himoya. Bot API o'zi ham 20 MB
#: dan kattasini bermaydi.
_MAX_DOWNLOAD = 20 * 1024 * 1024


class TelegramError(Exception):
    """Bot API xatosi. `code` - Telegram'ning `error_code` i (tarmoq xatosida
    0), `description` - uning matni (TOKENSIZ)."""

    def __init__(self, message: str, *, code: int = 0, description: str = "",
                 retry_after: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.description = description
        self.retry_after = retry_after

    @property
    def not_modified(self) -> bool:
        """Tahrirlangan matn avvalgisi bilan bir xil - xato emas."""
        return self.code == 400 and "not modified" in self.description.lower()

    @property
    def bad_markup(self) -> bool:
        """HTML belgilash buzuq - oddiy matn bilan qayta yuborish kerak."""
        return self.code == 400 and "parse entities" in self.description.lower()


class TelegramApi:
    """Bot API ustidagi yupqa qatlam: bitta `call` va kerakli usullar."""

    def __init__(self, token: str, *, base_url: str = TELEGRAM_API, timeout: float = 30.0) -> None:
        self.token = (token or "").strip()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.token)

    # --- past qatlam ---------------------------------------------------------

    def call(self, method: str, params: Mapping[str, Any] | None = None, *,
             timeout: float | None = None) -> Any:
        """Usulni chaqiradi va `result` ni qaytaradi.

        429 (chegaradan oshildi) BIR MARTA qayta uriniladi - Telegram aytgan
        vaqt qisqa bo'lsa. Qolgan xatolar `TelegramError`.
        """
        body = json.dumps(dict(params or {}), ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json; charset=utf-8"}
        for attempt in (1, 2):
            try:
                return self._send(method, body, headers, timeout)
            except TelegramError as exc:
                wait = exc.retry_after
                if attempt == 1 and exc.code == 429 and wait is not None and wait <= _MAX_RETRY_AFTER:
                    time.sleep(max(1, wait))
                    continue
                raise
        raise AssertionError("yetib kelmaydi")  # pragma: no cover

    def upload(self, method: str, fields: Mapping[str, Any], *, file_field: str,
               filename: str, content: bytes, content_type: str) -> Any:
        """Fayl bilan chaqiruv (`multipart/form-data`) - masalan `sendDocument`."""
        boundary = f"----venera{uuid.uuid4().hex}"
        parts: list[bytes] = []
        for name, value in fields.items():
            if value is None:
                continue
            text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
                + text.encode("utf-8") + b"\r\n"
            )
        # Nom sarlavhaga tushadi: qo'shtirnoq va qator uzilishi sarlavhani
        # buzardi. Telegram UTF-8 nomni to'g'ri ko'rsatadi.
        safe = re.sub(r'["\r\n\\]+', " ", filename).strip() or "hujjat"
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; '
            f'filename="{safe}"\r\nContent-Type: {content_type}\r\n\r\n'.encode("utf-8")
            + content + b"\r\n"
        )
        parts.append(f"--{boundary}--\r\n".encode())
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
        return self._send(method, b"".join(parts), headers, max(self.timeout, 60.0))

    def download(self, file_path: str, *, limit: int) -> bytes:
        """`getFile` bergan yo'l bo'yicha fayl. `limit` dan katta bo'lsa xato."""
        limit = min(limit, _MAX_DOWNLOAD)
        path = urllib.parse.quote(file_path, safe="/")
        request = urllib.request.Request(f"{self.base_url}/file/bot{self.token}/{path}")
        # Hisob: ovozli xabar fayli (`bytes`). Manzilda token bor - xato
        # matni `_redact` dan o'tadi.
        call = begin("telegram", "file", channel=current().channel or "bot")
        try:
            with urllib.request.urlopen(request, timeout=max(self.timeout, 60.0)) as response:
                data = response.read(limit + 1)
        except urllib.error.HTTPError as exc:
            error = TelegramError(self._redact(f"fayl olinmadi: HTTP {exc.code}"), code=exc.code)
            call.end("error", http_status=exc.code, error=error)
            raise error from exc
        except (urllib.error.URLError, TimeoutError, socket_timeout, OSError) as exc:
            error = TelegramError(self._redact(f"fayl olinmadi: {exc}"))
            call.end("error", error=error)
            raise error from exc
        call.end("ok", http_status=200, units={"bytes": len(data)})
        if len(data) > limit:
            raise TelegramError(f"fayl juda katta (> {limit} bayt)", code=413)
        return data

    def _send(self, method: str, body: bytes, headers: dict[str, str],
              timeout: float | None) -> Any:
        """Bitta chaqiruv - hisob bilan (`api_calls`, xizmat `telegram`).

        Kanal kontekstdan (bot ishlovchisi `bot` qo'yadi); yo'q bo'lsa ham
        `bot` - Bot API ga faqat bot murojaat qiladi. Xato matnida token
        yo'q: `_redact` dan o'tgan.
        """
        call = begin("telegram", method, units={"bytes": len(body)},
                     channel=current().channel or "bot")
        try:
            result = self._send_raw(method, body, headers, timeout)
        except TelegramError as exc:
            call.end("error", http_status=exc.code if 100 <= exc.code <= 599 else None,
                     error=exc)
            raise
        except BaseException as exc:
            call.end("error", error=self._redact(str(exc)) or type(exc).__name__)
            raise
        if method not in _QUIET_OK:
            call.end("ok", http_status=200)
        return result

    def _send_raw(self, method: str, body: bytes, headers: dict[str, str],
                  timeout: float | None) -> Any:
        request = urllib.request.Request(
            f"{self.base_url}/bot{self.token}/{method}", data=body, headers=headers, method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raw = b""
            try:
                raw = exc.read()
            except Exception:  # noqa: BLE001 - tana bo'lmasa ham status bor
                pass
            payload = _json(raw)
            params = payload.get("parameters") if isinstance(payload.get("parameters"), dict) else {}
            description = self._redact(str(payload.get("description") or exc.reason or ""))
            raise TelegramError(
                f"{method}: {exc.code} {description}".strip(),
                code=int(payload.get("error_code") or exc.code),
                description=description,
                retry_after=_int(params.get("retry_after")),
            ) from exc
        except (urllib.error.URLError, TimeoutError, socket_timeout, OSError) as exc:
            raise TelegramError(self._redact(f"{method}: tarmoq xatosi: {exc}")) from exc
        payload = _json(raw)
        if not payload.get("ok"):
            description = self._redact(str(payload.get("description") or "javob tushunarsiz"))
            raise TelegramError(f"{method}: {description}", code=int(payload.get("error_code") or 0),
                                description=description)
        return payload.get("result")

    def _redact(self, text: str) -> str:
        return text.replace(self.token, "***") if self.token else text

    # --- usullar ---------------------------------------------------------------

    def get_me(self) -> dict[str, Any]:
        return self.call("getMe")

    def get_updates(self, offset: int | None, *, timeout: int = 25) -> list[dict[str, Any]]:
        """Uzun so'rov (long polling). HTTP kutishi Telegram kutishidan UZUN
        bo'lishi shart - aks holda har bo'sh so'rov "timeout" xatosi bo'lardi."""
        # `edited_message` - guruh xulosasi tahrirlangan matnni ko'rsin
        # (`app/bot/groups.py`); shaxsiy chatda tahrir e'tiborsiz.
        params: dict[str, Any] = {"timeout": timeout,
                                  "allowed_updates": ["message", "edited_message", "callback_query"]}
        if offset is not None:
            params["offset"] = offset
        result = self.call("getUpdates", params, timeout=timeout + 15)
        return result if isinstance(result, list) else []

    def send_message(self, chat_id: int, text: str, *, html: bool = True,
                     reply_markup: Mapping[str, Any] | None = None,
                     reply_to: int | None = None, thread_id: int | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"chat_id": chat_id, "text": text,
                                  "link_preview_options": {"is_disabled": True}}
        if thread_id is not None:
            # Forum guruhidagi mavzu - javob o'sha mavzuga tushsin.
            params["message_thread_id"] = thread_id
        if html:
            params["parse_mode"] = "HTML"
        if reply_markup:
            params["reply_markup"] = reply_markup
        if reply_to:
            # Asl xabar o'chirilgan bo'lsa ham javob ketaversin.
            params["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
        return self.call("sendMessage", params)

    def edit_message_text(self, chat_id: int, message_id: int, text: str, *, html: bool = True,
                          reply_markup: Mapping[str, Any] | None = None) -> Any:
        params: dict[str, Any] = {"chat_id": chat_id, "message_id": message_id, "text": text,
                                  "link_preview_options": {"is_disabled": True}}
        if html:
            params["parse_mode"] = "HTML"
        if reply_markup:
            params["reply_markup"] = reply_markup
        return self.call("editMessageText", params)

    def edit_reply_markup(self, chat_id: int, message_id: int,
                          reply_markup: Mapping[str, Any] | None = None) -> Any:
        """Tugmalarni almashtiradi; `None` - tugmalar olib tashlanadi."""
        return self.call("editMessageReplyMarkup", {
            "chat_id": chat_id, "message_id": message_id,
            "reply_markup": dict(reply_markup or {"inline_keyboard": []}),
        })

    def delete_message(self, chat_id: int, message_id: int) -> Any:
        return self.call("deleteMessage", {"chat_id": chat_id, "message_id": message_id})

    def send_chat_action(self, chat_id: int, action: str = "typing", *,
                         thread_id: int | None = None) -> Any:
        params: dict[str, Any] = {"chat_id": chat_id, "action": action}
        if thread_id is not None:
            params["message_thread_id"] = thread_id
        return self.call("sendChatAction", params)

    def answer_callback(self, callback_id: str, text: str = "", *, alert: bool = False) -> Any:
        params: dict[str, Any] = {"callback_query_id": callback_id}
        if text:
            params["text"] = text[:200]
            params["show_alert"] = alert
        return self.call("answerCallbackQuery", params)

    def get_file(self, file_id: str) -> dict[str, Any]:
        return self.call("getFile", {"file_id": file_id})

    def send_document(self, chat_id: int, filename: str, content: bytes, content_type: str, *,
                      caption: str | None = None,
                      reply_markup: Mapping[str, Any] | None = None) -> Any:
        fields: dict[str, Any] = {"chat_id": str(chat_id)}
        if caption:
            fields["caption"] = caption
            fields["parse_mode"] = "HTML"
        if reply_markup:
            fields["reply_markup"] = dict(reply_markup)
        return self.upload("sendDocument", fields, file_field="document", filename=filename,
                           content=content, content_type=content_type)

    def set_webhook(self, url: str, *, secret: str, allowed_updates: list[str]) -> Any:
        """Telegram xabarlarni shu manzilga YUBORADI. `secret` har so'rovning
        `X-Telegram-Bot-Api-Secret-Token` sarlavhasida keladi - endpoint uni
        tekshiradi. Kutilayotgan xabarlar TASHLANMAYDI."""
        return self.call("setWebhook", {"url": url, "secret_token": secret,
                                        "allowed_updates": allowed_updates,
                                        "drop_pending_updates": False})

    def get_webhook_info(self) -> dict[str, Any]:
        result = self.call("getWebhookInfo")
        return result if isinstance(result, dict) else {}

    def delete_webhook(self) -> Any:
        return self.call("deleteWebhook", {"drop_pending_updates": False})

    def get_my_commands(self, *, scope: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        """`scope` - masalan `{"type": "chat", "chat_id": ...}` (bitta guruh
        menyusi); yo'q bo'lsa - umumiy menyu."""
        result = self.call("getMyCommands", {"scope": dict(scope)} if scope else None)
        return result if isinstance(result, list) else []

    def set_my_commands(self, commands: list[dict[str, str]], *,
                        scope: Mapping[str, Any] | None = None) -> Any:
        params: dict[str, Any] = {"commands": commands}
        if scope:
            params["scope"] = dict(scope)
        return self.call("setMyCommands", params)


def webhook_secret(bot_token: str, secret_key: str) -> str:
    """Webhook sarlavhasi uchun sir - `SECRET_KEY` va bot tokenidan HMAC.

    Saqlanmaydi va qayta ishga tushganda o'zgarmaydi; kalit almashsa sir ham
    almashadi va bot ishga tushganda webhook yangi sir bilan qayta o'rnatiladi.
    Telegram ruxsat bergan belgilar: `A-Z a-z 0-9 _ -` - hex mos keladi.
    """
    if not bot_token or not secret_key:
        return ""
    return hmac.new(secret_key.encode("utf-8"), b"venera-telegram-webhook:" + bot_token.encode("utf-8"),
                    hashlib.sha256).hexdigest()


def _json(raw: bytes) -> dict[str, Any]:
    try:
        parsed = json.loads(raw.decode("utf-8")) if raw else {}
    except (ValueError, UnicodeDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# --- mini app `initData` ----------------------------------------------------
#
# Telegram mini app ochilganda sahifaga `initData` beradi: kim ochgani
# (`user`), qachon (`auth_date`) va shularning IMZOSI (`hash`). Imzo BOT
# TOKENI bilan qo'yiladi, ya'ni uni faqat Telegram yasay oladi. Hisobni
# ulash shunga tayanadi: Venera sessiyasi "bu kim" ekanini, imzo esa "bu
# Telegram hisobi aynan o'sha odamning qo'lida" ekanini isbotlaydi.
#
# Algoritm - rasmiy hujjatdan: `hash` dan boshqa hamma maydon nomi bo'yicha
# saralanadi, `kalit=qiymat` qatorlari `\n` bilan ulanadi; kalit =
# HMAC-SHA256("WebAppData", bot_token), imzo = HMAC-SHA256(kalit, satr).

#: `initData` odatda 300-700 belgi. Undan kattasi - xato yoki suiiste'mol.
_INIT_MAX_LEN = 8192


class InitDataError(Exception):
    """`initData` qabul qilinmadi. `stale` - imzo to'g'ri, lekin eskirgan
    (odamga "ilovani qayta oching" deyish kerak, "soxta" emas)."""

    def __init__(self, message: str, *, stale: bool = False) -> None:
        super().__init__(message)
        self.stale = stale


def verify_init_data(init_data: str, bot_token: str, *, max_age: int,
                     now: float | None = None) -> dict[str, Any]:
    """Imzolangan `initData` -> `user` obyekti (kamida butun `id` bilan)."""
    if not bot_token:
        raise InitDataError("bot tokeni sozlanmagan")
    if not init_data or len(init_data) > _INIT_MAX_LEN:
        raise InitDataError("initData bo'sh yoki juda uzun")
    try:
        pairs = urllib.parse.parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
    except ValueError as exc:
        raise InitDataError("initData shakli buzilgan") from exc
    data: dict[str, str] = {}
    for key, value in pairs:
        if key in data:
            # Takroriy maydon: qaysi biri imzolanganini taxmin qilish kerak
            # bo'lardi - rad etamiz.
            raise InitDataError("initData da takroriy maydon")
        data[key] = value
    received = data.pop("hash", "")
    if not re.fullmatch(r"[0-9a-f]{64}", received):
        raise InitDataError("initData imzosi yo'q")
    check = "\n".join(f"{key}={data[key]}" for key in sorted(data))
    secret = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    expected = hmac.new(secret, check.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        raise InitDataError("initData imzosi mos emas")
    # Imzo to'g'ri - endi mazmun.
    auth_date = _int(data.get("auth_date"))
    if auth_date is None:
        raise InitDataError("initData da auth_date yo'q")
    age = (time.time() if now is None else now) - auth_date
    if age > max_age:
        raise InitDataError("initData eskirgan", stale=True)
    if age < -300:
        raise InitDataError("initData vaqti kelajakda")
    try:
        user = json.loads(data.get("user") or "null")
    except ValueError as exc:
        raise InitDataError("initData da user o'qilmadi") from exc
    if not isinstance(user, dict) or not isinstance(user.get("id"), int) or user.get("is_bot"):
        raise InitDataError("initData da foydalanuvchi yo'q")
    return user
