"""CRM sessiyasini O'ZI boshqaradi: login -> refresh -> yaroqli access_token.

NEGA KERAK. CRM ning `access_token` i 300 SEKUND yashaydi (Keycloak shunday
stamp qiladi, CRM uni uzaytira olmaydi - o'lchangan: `exp - iat` = 300).
Ilgari bu token `.env` ga QO'LDA yozilardi, va u amalda ishlamasdi: odam
tokenni nusxalab, faylga yopishtirib, saqlab bo'lguncha muddati tugardi.
Jonli holat: `crm_token MUDDATI TUGAGAN (461 s oldin)`.

To'g'ri yechim CRM tomonida berildi (hujjat, 2026-09-14): bir marta login
qilinadi, keyin `refresh_token` bilan yashaladi. `refresh_token` ning
`exp` i YO'Q (`typ=Offline`), ya'ni u 30 kun ishlatilmasa bekor bo'ladi -
boshqa hech qachon.

SHAKLI:

    login (bir marta)  ->  refresh (~4 daqiqada)  ->  access_token
                              ^                            |
                              +--- rotatsiya: yangisi saqlanadi

`refresh_token` DOIMIY KREDENSIAL - paroldan farqi yo'q. Uni qo'lga
kiritgan odam cheksiz muddat agent nomidan token yasay oladi. Shuning
uchun:

  * `data/` ichida, 600 huquq bilan, atomik yoziladi (`data/` gitignore'da);
  * HECH QACHON jurnalga, xato matniga yoki `/api/health` ga tushmaydi -
    faqat uzunligi va muddati ko'rsatiladi;
  * o'g'irlansa `POST /api/auth/logout` uni darhol bekor qiladi.

YANGILASH TIMER BILAN EMAS, KERAK BO'LGANDA. Hujjat "timer bilan ~4
daqiqada, YOKI 401 da dangasa - ikkisini birga qilmang" deydi. Bizda 401
ni KO'RISH imkoni yo'q: CRM ga biz emas, yuqoridagi yordamchi xizmat
murojaat qiladi, va u bizga faqat `auth_expired` deb aytadi. Shuning
uchun tokenni so'rov oldidan tekshiramiz va muddati 90 sekundan kam
qolgan bo'lsa yangilaymiz - 401 ning o'rnini shu zahira bosadi. Timer
bo'lmagani yana bir foyda beradi: hech kim savol bermayotganda token
behuda yangilanmaydi (sutkada 360 marta refresh - `/api/auth/*` uchun
30/daqiqa chegarasi bo'lgan xizmatda keraksiz shovqin).
"""

from __future__ import annotations

import json
import logging
import os
import re
import stat
import tempfile
import threading
import time
import urllib.error
import urllib.request

from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: `access_token` ning muddati shundan kam qolganda yangilanadi.
#:
#: 90 s ATAYLAB katta: savol-javob 45 sekundgacha cho'zilishi mumkin
#: (o'lchangan: "qoidalar + jonli" savol p90 = 38.7 s), ya'ni token
#: so'rov BOSHIDA yaroqli bo'lishi yetarli emas - u javob oxirigacha
#: yaroqli turishi kerak.
_MARGIN = 90.0

#: Muvaffaqiyatsiz urinishdan keyingi tanaffus. `/api/auth/*` uchun
#: chegara: bir IP dan 30 so'rov/daqiqa. Har savolda qayta urinsak,
#: CRM o'chganda o'zimiz 429 ga kirib qolardik.
_RETRY_PAUSE = 20.0
#: 429 dan keyin - chegara daqiqa bo'yicha hisoblanadi.
_RATE_PAUSE = 65.0

#: Bu kodlarda QAYTA URINISH BEFOYDA: Keycloak token beradi, CRM esa
#: hisobni rad etadi. Yana login qilsak yana yaroqli token va yana
#: o'sha 403 - cheksiz. Odam aralashishi kerak.
_FATAL_CODES = {"USER_NOT_PROVISIONED", "ACCOUNT_DISABLED"}

#: JWT ga o'xshagan har qanday bo'lak - jurnalga va xabarga tushmasin.
_JWT_LIKE = re.compile(r"eyJ[A-Za-z0-9_-]{8,}(?:\.[A-Za-z0-9_-]+){0,2}")


class CrmAuthError(Exception):
    """`code` - CRM ning mashina o'qiydigan kaliti (bo'lsa)."""

    def __init__(self, message: str, *, status: int = 0, code: str = "",
                 fatal: bool = False, rate_limited: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.fatal = fatal
        self.rate_limited = rate_limited


def _safe(text: str) -> str:
    """Matndan JWT ga o'xshagan bo'laklarni olib tashlaydi.

    HAR BIR jurnal qatori va xato xabari shu yerdan o'tadi. CRM 400 da
    so'rov tanasini qaytarishi mumkin, va o'sha tanada bizning
    `refresh_token` imiz bo'lardi - hujjat uni "paroldan farqi yo'q"
    deb ataydi, ya'ni uning jurnalga tushishi sirning oshkor bo'lishi.
    """
    return _JWT_LIKE.sub("<token>", text or "")


class CrmAuth:
    """CRM uchun yaroqli `access_token` beradi va uni o'zi yangilab turadi.

    IP SO'ROV EMAS. Bu obyekt CRM ning faqat `/api/auth/*` yo'llariga
    boradi. CRM ning ma'lumot endpointlariga biz umuman murojaat
    qilmaymiz - tokenni yuqoridagi yordamchi xizmatga beramiz, CRM ga
    o'sha boradi.
    """

    def __init__(self, base_url: str, username: str, password: str,
                 store: Path, *, timeout: float = 10.0) -> None:
        # SXEMA QO'SHILADI, agar yozilmagan bo'lsa. `.env` ga `https://`
        # siz `crm.brb-tech.uz` yozish juda oson xato, va uning natijasi
        # tushunarsiz bo'lardi: `urllib` "unknown url type" deb yiqilib,
        # sabab manzilda emas, boshqa joyda izlanardi. CRM faqat TLS da
        # javob beradi (jonli tekshirilgan: `http://` ulanmaydi), shuning
        # uchun default `https`.
        base = (base_url or "").strip().rstrip("/")
        if base and "://" not in base:
            base = f"https://{base}"
        self.base_url = base
        self.username = username or ""
        self._password = password or ""
        self.store = Path(store)
        self.timeout = timeout

        # Bitta qulf: bir vaqtda kelgan bir necha savol BITTA yangilashni
        # bo'lishadi. Aks holda har biri alohida refresh yuborib,
        # rotatsiya tufayli bir-birining tokenini bekor qilardi.
        self._lock = threading.Lock()
        self._access = ""
        #: `time.monotonic()` bo'yicha - tizim soati o'zgarsa ham to'g'ri.
        self._expires_at = 0.0
        self._fatal_code = ""
        self._last_error = ""
        self._next_try = 0.0
        self._logins = 0
        self._refreshes = 0

    # --- tashqi yuz -------------------------------------------------------

    @property
    def configured(self) -> bool:
        """Sozlanganmi. Sozlanmagan bo'lsa `token()` bo'sh satr qaytaradi
        va `.env` dagi qo'lda yozilgan `crm_token` ishlatiladi."""
        return bool(self.base_url and self.username and self._password)

    def token(self) -> str:
        """Yaroqli `access_token`, yoki bo'sh satr.

        BO'SH SATR XATO EMAS: CRM savoli u holda yuqoridagi xizmatdan
        `auth_missing` oladi va foydalanuvchi "CRM tizimiga kiring"
        degan tushunarli xabarni ko'radi. HRM savollari esa ishlashda
        davom etadi - shuning uchun bu yerdan ISTISNO TASHLANMAYDI.
        """
        if not self.configured:
            return ""
        if self._fresh():
            return self._access
        with self._lock:
            # Ikkinchi tekshiruv: qulf kutilayotganda boshqa ip allaqachon
            # yangilab bo'lgan bo'lishi mumkin.
            if self._fresh():
                return self._access
            if self._fatal_code:
                return ""
            if time.monotonic() < self._next_try:
                # Tanaffus davom etyapti. Eski token hali yaroqli bo'lsa
                # (faqat zahira oynasiga kirgan bo'lsa) undan foydalanamiz.
                return self._access if self._valid() else ""
            try:
                self._renew()
            except CrmAuthError as exc:
                self._note(exc)
                return self._access if self._valid() else ""
            return self._access

    def status(self) -> dict[str, Any]:
        """`/api/health` uchun. TOKEN QIYMATI YO'Q - faqat holat."""
        if not self.configured:
            return {"configured": False}
        left = self._expires_at - time.monotonic()
        return {
            "configured": True,
            "has_token": bool(self._access),
            "expires_in": int(left) if self._access else 0,
            "stored_refresh": self.store.exists(),
            "logins": self._logins,
            "refreshes": self._refreshes,
            "fatal": self._fatal_code or None,
            "last_error": self._last_error or None,
        }

    def warning(self) -> str | None:
        """Bir qatorli ogohlantirish yoki `None`."""
        if not self.configured:
            return None
        if self._fatal_code:
            return (f"CRM hisobi RAD ETILDI ({self._fatal_code}) - qayta urinish "
                    "befoyda, CRM administratori aralashishi kerak; jonli CRM "
                    "savollari ishlamaydi")
        if self._last_error and not self._access:
            return f"CRM sessiyasi olinmadi ({self._last_error}) - jonli CRM savollari ishlamaydi"
        return None

    def logout(self) -> bool:
        """Saqlangan `refresh_token` ni CRM da BEKOR qiladi va o'chiradi.

        O'chirish tugmasi: token o'g'irlangan deb hisoblasa, shu chaqiruv
        uni darhol yaroqsiz qiladi.
        """
        saved = self._load()
        self._access = ""
        self._expires_at = 0.0
        ok = True
        if saved:
            try:
                self._post("/api/auth/logout", {"refresh_token": saved})
            except CrmAuthError as exc:
                log.warning("CRM logout: %s", _safe(str(exc)))
                ok = False
        self.store.unlink(missing_ok=True)
        return ok

    # --- ichki ------------------------------------------------------------

    def _valid(self) -> bool:
        return bool(self._access) and time.monotonic() < self._expires_at

    def _fresh(self) -> bool:
        """Token bor va zahira oynasiga hali kirmagan."""
        return bool(self._access) and time.monotonic() < self._expires_at - _MARGIN

    def _note(self, exc: CrmAuthError) -> None:
        """Xatoni eslab qoladi va keyingi urinish vaqtini belgilaydi."""
        self._last_error = _safe(f"{exc.code or exc.status or '?'}: {exc}")[:200]
        if exc.fatal:
            self._fatal_code = exc.code
            log.error("CRM hisobi rad etildi (%s) - qayta urinilmaydi", exc.code)
            return
        pause = _RATE_PAUSE if exc.rate_limited else _RETRY_PAUSE
        self._next_try = time.monotonic() + pause
        log.warning("CRM sessiyasi olinmadi (%s), %.0f s tanaffus",
                    _safe(str(exc)), pause)

    def _renew(self) -> None:
        """`refresh` ni sinaydi, bo'lmasa `login` qiladi."""
        saved = self._load()
        if saved:
            try:
                self._apply(self._post("/api/auth/refresh", {"refresh_token": saved}),
                            how="refresh")
                return
            except CrmAuthError as exc:
                if exc.fatal:
                    raise
                # 400 = token bekor qilingan yoki 30 kun ishlatilmagan.
                # Bu KUTILADIGAN holat, xato emas: paroldan qaytadan
                # boshlaymiz. Boshqa xatolarda ham login sinaladi -
                # eng yomoni yana xato bo'ladi va tanaffus qo'yiladi.
                log.info("CRM refresh ishlamadi (%s) - login qilinadi",
                         _safe(str(exc)))
                self.store.unlink(missing_ok=True)
        self._apply(self._post("/api/auth/login",
                               {"username": self.username, "password": self._password}),
                    how="login")

    def _apply(self, data: dict[str, Any], *, how: str) -> None:
        access = str(data.get("access_token") or "")
        refresh = str(data.get("refresh_token") or "")
        if not access:
            raise CrmAuthError("javobda access_token yo'q", code="BAD_RESPONSE")
        # `expires_in` ga ISHONAMIZ, lekin ko'r-ko'rona emas: yo'q yoki
        # aqldan tashqari bo'lsa hujjatdagi 300 s olinadi.
        try:
            ttl = float(data.get("expires_in") or 0)
        except (TypeError, ValueError):
            ttl = 0.0
        if not 30.0 <= ttl <= 3600.0:
            ttl = 300.0
        self._access = access
        self._expires_at = time.monotonic() + ttl
        self._last_error = ""
        if how == "login":
            self._logins += 1
        else:
            self._refreshes += 1
        # ROTATSIYA: CRM har refresh'da YANGI refresh_token beradi va
        # eskisi bekor bo'ladi. Saqlamasak keyingi yangilash 400 olib,
        # har safar paroldan login qilishga tushib qolardi.
        if refresh:
            self._save(refresh)
        log.info("CRM sessiyasi yangilandi (%s): access %.0f s, refresh %s",
                 how, ttl, "saqlandi" if refresh else "kelmadi")

    # --- transport --------------------------------------------------------

    def _post(self, path: str, body: dict[str, str]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raise self._from_http(exc) from None
        except (urllib.error.URLError, OSError) as exc:
            raise CrmAuthError(f"CRM ga ulanib bo'lmadi: {exc}", code="UNREACHABLE") from exc
        if not raw:
            return {}
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise CrmAuthError(f"CRM javobi o'qilmadi: {exc}", code="BAD_RESPONSE") from exc
        # Tokenlar `data` ichida keladi. Tur tekshiruvi MAJBURIY: 200 bilan
        # `null` yoki satr kelsa keyingi `.get()` AttributeError berardi va
        # butun savol 500 ga aylanardi.
        if not isinstance(payload, dict):
            raise CrmAuthError("CRM javobi obyekt emas", code="BAD_RESPONSE")
        data = payload.get("data")
        return data if isinstance(data, dict) else payload

    def _from_http(self, exc: urllib.error.HTTPError) -> CrmAuthError:
        """HTTP xatosini kodli `CrmAuthError` ga o'giradi.

        IKKI SHAKL bor va ikkisi ham qo'llaniladi (hujjat: "parse
        defensively"): kodli xatolar `{"error": {"code": ...}}` bo'lib
        keladi, 429 esa kontrollerlardan OLDINGI filtrdan chiqadi va
        yassi `{"error": "RATE_LIMIT_EXCEEDED", ...}` beradi.
        """
        status = exc.code
        code, message = "", ""
        try:
            payload = json.loads(exc.read().decode("utf-8", "replace"))
        except Exception:
            payload = None
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                code = str(error.get("code") or "")
                message = str(error.get("message") or "")
            elif isinstance(error, str):
                code = error
                message = str(payload.get("message") or "")
        if not code:
            code = {401: "UNAUTHORIZED", 403: "FORBIDDEN",
                    400: "AUTH_FAILED", 429: "RATE_LIMIT_EXCEEDED"}.get(status, f"HTTP_{status}")
        return CrmAuthError(
            _safe(message or f"CRM {status}"),
            status=status,
            code=code,
            fatal=code in _FATAL_CODES,
            rate_limited=status == 429 or code == "RATE_LIMIT_EXCEEDED",
        )

    # --- saqlash ----------------------------------------------------------

    def _load(self) -> str:
        try:
            return self.store.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def _save(self, refresh: str) -> None:
        """ATOMIK va 600 huquq bilan.

        Atomik: yarim yozilgan fayl "refresh_token yo'qoldi" degani bo'lardi
        va tizim paroldan qaytadan login qilishga tushardi. Huquq
        ALMASHTIRISHDAN OLDIN qo'yiladi - aks holda fayl bir lahza
        kengroq huquq bilan o'z joyida turardi.
        """
        try:
            self.store.parent.mkdir(parents=True, exist_ok=True)
            handle = tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=self.store.parent,
                prefix=".crm.", suffix=".tmp", delete=False,
            )
            try:
                with handle:
                    handle.write(refresh + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.chmod(handle.name, stat.S_IRUSR | stat.S_IWUSR)
                os.replace(handle.name, self.store)
            except BaseException:
                Path(handle.name).unlink(missing_ok=True)
                raise
        except OSError as exc:
            # Saqlanmasa ham ishlashda davom etamiz: joriy `access_token`
            # qo'lda, va keyingi yangilash paroldan login bo'ladi.
            log.warning("CRM refresh_token saqlanmadi: %s", exc)
