"""Slack'dagi audio -> matn: yig'ilishlar quvuri orqali (`services/meetings`).

Qadamlar (yaratish -> yuklash -> yakunlash -> kutish -> txt eksport) Telegram bilan
umumiy - `services/meetings/intake.py`; bu yerda faqat Slack'ka xos qismi: fayl Slack'dan
qanday olinadi va kimning nomidan. Slack'ka nima yozilishi - `meeting.py`.

KIMNING NOMIDAN (`account`). 2026-11-12 dan har kim O'Z Barno hisobini ulaydi («Connect Barno AI
account», `link.py`): audio va savollar o'sha odamning yig'ilishi bo'ladi, limitlar ham shaxsiy.
Ulashdan OLDIN kelgan yozuvlar umumiy `SLACK_ACTOR_ID` hisobida qoladi - ularning kartalari va
thread'lari ishlayveradi (`owner`). Ulash o'chirilgan o'rnatmada (`link.required()` yolg'on) hammasi
eskicha, umumiy hisobda.

BITTA FAYL - BITTA YIG'ILISH (`intake.client_id`): fayl qayta kelsa (Slack hodisani qayta
yubordi, "Qayta urinish" tugmasi, fayl yana ulashildi) - o'sha yig'ilish davom ettiriladi
va GAPI qayta to'lanmaydi. Odamning audio xabari ostidagi thread'dagi savol ham
yig'ilishni shu kalit bilan topadi.

FORMAT. Yig'ilish faqat aac, m4a, mp3 va wav ni qabul qiladi (`service.ACCEPTED_TYPES`),
serverda esa ffmpeg yo'q. Slack'ning o'zida yozilgan ovozli xabar boshqa formatda
bo'lishi mumkin - unda fayl obyektidagi `aac` havolasidan Slack tayyorlagan AAC nusxasi
olinadi. Tur Slack aytgan mimetype bo'yicha emas, faylning birinchi baytlari bo'yicha
aniqlanadi, chunki yig'ilish ham aynan shuni tekshiradi (`audio.sniff`).
"""

from __future__ import annotations

import hashlib
import logging
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

from pathlib import Path
from typing import Any

from ..core import config as _config
from ..core.config import settings
from ..schemas.auth import AuthUser
from ..services import admin_users
from ..services.meetings import audio, intake, service
from ..services.meetings.intake import Problem, poll_interval, wait_transcript  # noqa: F401 - `meeting.py` shu nomlar bilan

log = logging.getLogger(__name__)


def audio_files(event: dict[str, Any]) -> list[dict[str, Any]]:
    """Shaxsiy xabardagi audio fayllar; boshqa hamma narsa (kanal, bot, matn) - bo'sh."""
    if event.get("channel_type") != "im" or event.get("bot_id"):
        return []
    if event.get("subtype") not in (None, "file_share"):
        return []
    return [f for f in event.get("files") or [] if is_audio(f)]


def is_audio(file: dict[str, Any]) -> bool:
    """Slack'da yozilgan ovozli xabar (`slack_audio`) yoki yuklangan audio fayl."""
    return file.get("subtype") == "slack_audio" or str(file.get("mimetype") or "").startswith("audio/")


def client_id(file_id: str) -> str:
    """Slack fayli -> yig'ilish kaliti (`CreateMeetingRequest.clientId`, UUID)."""
    return intake.client_id("slack-file", file_id)


def meeting_of_file(user: AuthUser, file_id: str) -> str | None:
    return intake.meeting_of(user, client_id(file_id))


def account(team: str | None = None, slack_user: str | None = None) -> AuthUser:
    """Shu so'rov KIMNING nomidan - HAR so'rovda qayta tekshiriladi (bot kabi).

    Shaxsiy hisob majburiy bo'lsa (`link.required()`): Slack odamining O'Z hisobi; ulanmagan -
    `link.NotLinked` (chaqiruvchi ulash xabarini yuboradi), bloklangan - `Problem`. Ulangan har bir
    xodimga ochiq (ega qarori 2026-11-12) - `MEETINGS_LOGINS` tekshirilmaydi. Aks holda - umumiy
    `SLACK_ACTOR_ID` hisobi (`shared_account`)."""
    from . import link

    if not _config.meetings_enabled_now():
        raise Problem("Yig'ilishlar bo'limi o'chiq.")
    if link.required():
        return link.person(team, slack_user)
    return shared_account()


def owner(user: AuthUser, meeting_id: str) -> AuthUser:
    """Yig'ilish KIMNIKI: odamning o'ziniki bo'lsa - o'zi; ulashdan OLDINGI yozuv bo'lsa - umumiy
    hisob (eski kartalar va thread'lar ishlayversin). Hech kimniki emas - xizmatning 404 i."""
    from . import link

    try:
        service.detail(user, meeting_id)
        return user
    except service.MeetingProblem as exc:
        if exc.status_code != 404 or not link.required():
            raise
        shared = legacy_account()
        if shared is None or shared.actorId == user.actorId:
            raise
    service.detail(shared, meeting_id)
    return shared


def legacy_account() -> AuthUser | None:
    """Umumiy hisob - faqat ESKI yozuvlarni topish uchun; sozlanmagan yoki yaroqsiz bo'lsa `None`
    (shaxsiy hisobli o'rnatmada u bo'lmasligi ham mumkin)."""
    try:
        return shared_account()
    except Problem:
        return None


def shared_account() -> AuthUser:
    """`SLACK_ACTOR_ID` hisobi - HAR so'rovda qayta tekshiriladi (bot kabi): hisob
    o'chirilsa, bloklansa yoki bo'limga ruxsati olinsa, darhol to'xtaydi."""
    from ..api.deps import get_directory
    from ..api.v1.meetings import meetings_allowed

    if not _config.meetings_enabled_now():
        raise Problem("Yig'ilishlar bo'limi o'chiq.")
    actor_id = str(settings.slack_actor_id or "").strip()
    if not actor_id:
        raise Problem("Slack uchun Venera hisobi sozlanmagan (SLACK_ACTOR_ID).")
    if not actor_id.isdigit():
        raise Problem("SLACK_ACTOR_ID raqam bo'lishi kerak.")
    stored = get_directory().by_actor_id(int(actor_id))
    if stored is None:
        raise Problem("Slack uchun belgilangan Venera hisobi topilmadi.")
    login = getattr(stored, "username", None)
    verdict = admin_users.access(stored.to_public(), login=login)
    if verdict.blocked or not meetings_allowed(verdict.user, login):
        raise Problem("Slack uchun belgilangan hisobga yig'ilishlar bo'limi ochiq emas.")
    return verdict.user


def ingest(client: Any, user: AuthUser, file: dict[str, Any], *, language: str = intake.LANGUAGE) -> str:
    """Fayl -> yig'ilish id. Yangi bo'lsa yaratib yuklaydi (`language` - odam tanlagan audio tili); oldin kelgan
    bo'lsa davom ettiradi: yarim yuklangani - qolgan joyidan, xato bergani - `service.retry` bilan."""
    if file.get("file_access") == "check_file_info":
        # Hodisada faylning to'liq obyekti yo'q (masalan Slack Connect) - so'rab olinadi.
        file = client.files_info(file=file["id"])["file"]
    meeting_id = meeting_of_file(user, file["id"])
    if meeting_id is not None and intake.resume(user, meeting_id):
        return meeting_id
    name = file.get("title") or file.get("name") or "audio"
    with tempfile.TemporaryDirectory(prefix="slack-audio-") as tmp:
        path, size, sha, kind = fetch(file, Path(tmp))
        log.info("Slack audio (%s): %s, %d bayt", file.get("id"), kind, size)
        # Kanal `api`: `core/channels.py` ro'yxatida Slack yo'q - Plaud filtri uchun manba alohida (`origin`).
        return intake.upload(user, client_id(file["id"]), path, size, sha, kind, title=f"Slack: {name}",
                             recorded_at=float(file.get("created") or time.time()), channel="api",
                             origin="slack", language=language)


def fetch(file: dict[str, Any], folder: Path) -> tuple[Path, int, str, str]:
    """Faylni yuklab oladi va yig'ilish qabul qiladigan nusxasini tanlaydi:
    (yo'l, hajm, sha256, tur)."""
    urls = [file.get("url_private_download") or file.get("url_private"), file.get("aac")]
    if audio.canonical_type(file.get("mimetype")) not in service.ACCEPTED_TYPES:
        # Masalan Slack'da yozilgan ovozli xabar: asl nusxa yaroqsizligi aniq - avval
        # Slack'ning AAC nusxasi.
        urls.reverse()
    limit = service.max_upload_bytes()
    for n, url in enumerate(u for u in urls if u):
        path = folder / f"audio-{n}"
        size, sha, head = download(url, path, limit)
        kind = next((t for t in service.ACCEPTED_TYPES if audio.sniff(head, t)), None)
        if kind is not None:
            return path, size, sha, kind
    log.info("Slack audio (%s): mos format yo'q (%s)", file.get("id"), file.get("mimetype"))
    raise Problem("Bu audio formati qo'llab-quvvatlanmaydi (mp3, m4a, aac, wav).")


def download(url: str, dest: Path, limit: int) -> tuple[int, str, bytes]:
    """Slack faylini `dest` ga yozadi: (hajm, sha256, birinchi 16 bayt).

    Bot tokeni FAQAT Slack xostiga yuboriladi: boshqa xostga yo'naltirilsa so'rov
    to'xtaydi (`_SlackOnly`).
    """
    if not _slack_url(url):
        raise Problem("Slack fayl manzili kutilmagan.")
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {settings.slack_bot_token}"})
    digest, size, head = hashlib.sha256(), 0, b""
    try:
        with _opener().open(request, timeout=60) as resp, open(dest, "wb") as fh:
            if "text/html" in (resp.headers.get("Content-Type") or ""):
                # Ruxsat yetmasa Slack fayl o'rniga KIRISH SAHIFASINI qaytaradi (200 bilan).
                raise Problem("Slack faylni bermadi - ilovada `files:read` ruxsati bormi?", retry=True)
            while block := resp.read(256 * 1024):
                size += len(block)
                if size > limit:
                    raise Problem("Fayl juda katta.")
                head += block[:16 - len(head)]
                digest.update(block)
                fh.write(block)
    except urllib.error.HTTPError as exc:
        raise Problem(f"Slack faylni bermadi (HTTP {exc.code}).", retry=True) from None
    except (urllib.error.URLError, OSError) as exc:
        log.warning("Slack faylini yuklab bo'lmadi: %s", exc)
        raise Problem("Slack'dan faylni yuklab bo'lmadi.", retry=True) from None
    return size, digest.hexdigest(), head


def _slack_url(url: str) -> bool:
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and (host == "slack.com" or host.endswith(".slack.com"))


class _SlackOnly(urllib.request.HTTPRedirectHandler):
    """Yo'naltirish faqat Slack xostiga: urllib `Authorization` sarlavhasini yangi
    manzilga ham ko'chiradi, ya'ni token begona xostga ketib qolardi."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _slack_url(newurl):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener() -> urllib.request.OpenerDirector:
    from . import SSL

    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=SSL), _SlackOnly())
