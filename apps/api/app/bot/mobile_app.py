"""Telegram'da "📲 Ilovani yuklab olish" - Barno AI mobil ilovasi (hozircha Android APK).

Ega talabi (2026-11-06): botda ilovani saqlab olish tugmasi - hozircha faqat Android, iOS keyinroq
qo'shiladi. Tugma pastdagi doimiy klaviaturada, "🎙 Plaud" yonida; faqat ulangan xodimlarga.

APK QAYERDAN. 10.10.50.4 (build serveri) dagi ichki "Barno AI APK" API (`settings.mobile_apk_api`):
`/latest` - oxirgi versiya (har variantning `versionCode`, hajmi, sha256), `/download?variant=` -
faylning o'zi. API'ga faqat shu server (10.10.50.8) kira oladi, telefonlar emas - shuning uchun fayl
odamga havola bilan emas, botning o'zidan keladi. Yuklangan fayl hajm va sha256 bilan tekshiriladi.

QAYSI VARIANT. `arm64` (~40 MB, 64-bit Android - hozirgi telefonlarning deyarli hammasi): Telegram
boti 50 MB dan katta fayl yubora olmaydi, `universal` (~105 MB) sig'maydi.

BIR MARTA YUKLANADI. Telegram yuborilgan faylga `file_id` beradi: shu versiya keyingi odamlarga qayta
yuklanmasdan, darhol yuboriladi; `versionCode` oshsa - yangisi yuklanadi. Xotirada: restartdan keyin
birinchi so'rov faylni qayta yuklaydi. Yuklash (bir necha soniya) paytida odam "⏳" xabarini ko'radi.

ARXIV (ega talabi, 2026-11-05). APK ning o'zi har yuborishda arxivga ko'chirilmaydi (40 MB x har
odam) - kimga qaysi versiya yuborilgani qatori yoziladi (nomi, hajmi, sha256).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import urllib.error
import urllib.request

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from ..schemas.auth import AuthUser
from ..services import archive
from ..services.integrations.telegram import TelegramApi, TelegramError
from .render import esc

log = logging.getLogger(__name__)

BTN_APP = "📲 Ilovani yuklab olish"
#: Telegram'da yuboriladigan variant (yuqoridagi izoh).
VARIANT = "arm64"
#: Telegram Bot API: bot yuboradigan fayl chegarasi.
MAX_SEND = 50 * 1024 * 1024
APK_TYPE = "application/vnd.android.package-archive"
#: 40 MB ni Telegram'ga yuklash sekin tarmoqda bir daqiqadan oshishi mumkin.
UPLOAD_TIMEOUT = 300.0
#: Fayl nomi tarmoqdan keladi - kutilmagan shaklda bo'lsa versiyadan yasaladi.
_NAME = re.compile(r"[\w.\-]{1,100}\.apk")
_RETRY = "birozdan keyin qayta urinib ko'ring."

#: (manzil, timeout) -> javob tanasi.
Fetch = Callable[[str, float], bytes]


class AppProblem(Exception):
    """Odamga botda ko'rsatiladigan sabab."""


class MobileApp:
    def __init__(self, api: TelegramApi, base_url: str, *, inline: bool = False, fetch: Fetch | None = None) -> None:
        self.api = api
        self.base_url = base_url.strip().rstrip("/")
        self._fetch = fetch or _fetch
        #: Bitta yuklash: bir vaqtda bosganlar o'sha faylni kutadi, keyin `file_id` bilan oladi.
        self._lock = threading.Lock()
        #: (versionCode, Telegram `file_id`) - oxirgi yuklangan APK.
        self._cached: tuple[int, str] | None = None
        self._pool = None if inline else ThreadPoolExecutor(max_workers=2, thread_name_prefix="tg-app")

    def on_button(self, chat_id: int, user: AuthUser) -> None:
        """Tugma: APK o'z ipida yuboriladi - yuklash botning navbatini band qilmasin."""
        if self._pool is None:
            self._deliver(chat_id, user)
            return
        try:
            self._pool.submit(self._deliver, chat_id, user)
        except RuntimeError:
            pass  # to'xtatilmoqda

    def stop(self) -> None:
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)

    def _deliver(self, chat_id: int, user: AuthUser) -> None:
        try:
            info = self._latest()
            self._send(chat_id, info)
        except AppProblem as exc:
            self._say(chat_id, f"📲 {esc(str(exc))}")
            return
        except Exception:  # noqa: BLE001 - odam javobsiz qolmasin
            log.exception("Telegram ilova (%s): kutilmagan xato", user.actorId)
            self._say(chat_id, f"📲 Ilovani yuborib bo'lmadi - {_RETRY}")
            return
        log.info("Telegram ilova (%s): Android %s (vc%d) yuborildi", user.actorId, info["version"],
                 info["versionCode"])
        archive.record("telegram", "out", "document", chat=chat_id, actor=user.actorId, name=info["file"],
                       mime=APK_TYPE, size=info["size"],
                       meta={"app": "android", "version": info["version"], "versionCode": info["versionCode"],
                             "sha256": info["sha256"]})

    def _latest(self) -> dict[str, Any]:
        """`/latest` -> `VARIANT` ning versiyasi, `versionCode`, fayl nomi, hajmi va sha256."""
        if not self.base_url:
            raise AppProblem("Ilovani yuklab olish hozir o'chiq.")
        try:
            variant = json.loads(self._fetch(f"{self.base_url}/latest", 15.0))["variants"][VARIANT]
            info = {"version": str(variant["version"]), "versionCode": int(variant["versionCode"]),
                    "file": str(variant["file"]), "size": int(variant["size"]),
                    "sha256": str(variant["sha256"]).lower()}
        except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError) as exc:
            log.warning("Telegram ilova: APK API javob bermadi (%s)", type(exc).__name__)
            raise AppProblem(f"Ilovani hozir olib bo'lmadi - {_RETRY}") from None
        if info["size"] > MAX_SEND:
            raise AppProblem("Ilova fayli Telegram chegarasidan (50 MB) katta - bot uni yubora olmaydi.")
        if not _NAME.fullmatch(info["file"]):
            info["file"] = f"barno-ai-{re.sub(r'[^0-9A-Za-z.]', '', info['version']) or 'android'}.apk"
        return info

    def _send(self, chat_id: int, info: dict[str, Any]) -> None:
        """Oxirgi APK shu chatga: shu versiyaning `file_id` si bo'lsa - darhol, bo'lmasa yuklab olib,
        tekshirib, Telegram'ga yuklab."""
        caption = caption_of(info)
        with self._lock:
            cached = self._cached
            if cached is not None and cached[0] == info["versionCode"]:
                try:
                    self.api.send_document_id(chat_id, cached[1], caption=caption)
                    return
                except TelegramError as exc:
                    if exc.code != 400:
                        log.warning("Telegram ilova: APK yuborilmadi: %s", exc)
                        raise AppProblem(f"Ilovani yuborib bo'lmadi - {_RETRY}") from None
                    # `file_id` yaroqsiz bo'lib qolgan - fayl qaytadan yuklanadi.
                    log.warning("Telegram ilova: saqlangan fayl rad etildi (%s)", exc)
                    self._cached = None
            holder = self._say(chat_id, f"⏳ Barno AI {esc(info['version'])} (Android) tayyorlanmoqda…")
            try:
                data = self._download(info)
                sent = self.api.send_document(chat_id, info["file"], data, APK_TYPE, caption=caption,
                                              timeout=UPLOAD_TIMEOUT)
            except TelegramError as exc:
                log.warning("Telegram ilova: APK yuborilmadi: %s", exc)
                raise AppProblem(f"Ilovani yuborib bo'lmadi - {_RETRY}") from None
            finally:
                self._delete(chat_id, holder)
            document = sent.get("document") if isinstance(sent, dict) else None
            if isinstance(document, dict) and document.get("file_id"):
                self._cached = (info["versionCode"], str(document["file_id"]))

    def _download(self, info: dict[str, Any]) -> bytes:
        try:
            data = self._fetch(f"{self.base_url}/download?variant={VARIANT}", 120.0)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            log.warning("Telegram ilova: APK yuklab olinmadi (%s)", type(exc).__name__)
            raise AppProblem(f"Ilovani hozir olib bo'lmadi - {_RETRY}") from None
        if len(data) != info["size"] or hashlib.sha256(data).hexdigest() != info["sha256"]:
            # Build serverda aynan shu orada yangi versiya chiqqan bo'lishi ham mumkin.
            log.warning("Telegram ilova: APK hajmi yoki sha256 /latest ga mos emas")
            raise AppProblem(f"Ilova fayli tekshiruvdan o'tmadi - {_RETRY}")
        return data

    def _say(self, chat_id: int, text: str) -> int | None:
        try:
            sent = self.api.send_message(chat_id, text)
        except TelegramError as exc:
            log.warning("Telegram ilova: xabar yuborilmadi: %s", exc)
            return None
        message_id = sent.get("message_id") if isinstance(sent, dict) else None
        return message_id if isinstance(message_id, int) else None

    def _delete(self, chat_id: int, message_id: int | None) -> None:
        if message_id is None:
            return
        try:
            self.api.delete_message(chat_id, message_id)
        except TelegramError as exc:
            log.debug("Telegram ilova: xabar o'chirilmadi: %s", exc)


def caption_of(info: dict[str, Any]) -> str:
    # Play Protect qatori (2026-11-09, ega so'rovi "Play Protect bloklamasin"): 1.3.6 dan ilovada
    # Accessibility yo'q - qattiq blok tushmaydi; Play'dan tashqaridagi har ilovaga chiqadigan YUMSHOQ
    # ogohlantirishda odam "OK" ni bossa "App not installed" bo'lardi - yo'lini shu yerda aytamiz.
    return (f"📲 <b>Barno AI</b> {esc(info['version'])} - Android ilovasi\n\n"
            "O'rnatish: faylni oching; telefon so'rasa, «Noma'lum manbalardan o'rnatish»ga ruxsat bering. "
            "Play Protect ogohlantirsa: «Batafsil» → «Baribir o'rnatish». "
            "Kirish - HRM/CRM login va parolingiz bilan.")


def _fetch(url: str, timeout: float) -> bytes:
    """Ichki API dan GET. Proksisiz (manzil ichki tarmoqda); javob `MAX_SEND` dan katta bo'lsa -
    xato, xotira to'lmasin."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=timeout) as resp:
        data = resp.read(MAX_SEND + 1)
    if len(data) > MAX_SEND:
        raise ValueError("javob juda katta")
    return data
