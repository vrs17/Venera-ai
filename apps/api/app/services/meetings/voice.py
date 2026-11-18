"""Spikerni OVOZIDAN tanish - 1-bosqich: GAPI "ovoz bo'yicha tanish" (`speaker_identification`).

EGA QARORLARI (2026-11-18):
  * Plaud (Telegram, Slack, mobil ilova) yig'ilishida spiker ism-familiyasi bilan chiqsin - 1-bosqichda GAPI orqali.
  * BRB-Tech'da hamma xodim rozi: alohida rozilik so'ralmaydi.
  * Mehmon (va namuna yozmagan xodim) ovozi SAQLANADI va doimiy ID oladi, ismi chiqmaydi: «Noma'lum #12».
  * Xodim ovoz namunasini uchala kanalda yoza oladi; tartib va o'qish matni beriladi (`instructions`).

QANDAY ISHLAYDI
  1. Yig'ilish GAPI ga "ovoz bo'yicha tanish" bilan ketadi (`gapi_stt.meeting_settings(identify=True)`). GAPI har
     spikerning ovoz izini loyihadagi ovozlar bilan solishtiradi: tanish ovoz o'z doimiy raqamini oladi, 10 s dan
     ko'p gapirgan yangi ovoz ro'yxatga olinadi. Natija - `speaker_info[].identity`.
  2. `identify` (transkript saqlanishidan OLDIN, `transcribe._poll`) GAPI ovozini bizning shaxsimizga bog'laydi
     (`voice_links`): xodim - ismi spikerga yoziladi (`name_source='voice'`), mehmon - faqat raqami (`person_id`).
  3. Namuna (`submit`): xodim ~45 s gapiradi. Har GAPI hisobida: sinxron `/transcribe` -> tekshiruv (bitta ovoz,
     kamida `VOICE_SAMPLE_MIN_SPEECH_SEC` nutq, ovoz izi bor) -> ovoz xodimga bog'lanadi. Namuna avval mehmon deb
     saqlangan ovozga mos kelsa - o'sha mehmon xodimga aylanadi va o'tgan yig'ilishlardagi «Noma'lum #N» ham
     ismga almashadi (`_backfill`).

IKKI HISOB. Ovozlar GAPI LOYIHASIDA - har hisobda alohida. Namuna HAR hisobga yoziladi: xodim zaxira hisobga
tushgan yig'ilishda ham tanilsin. Mehmon esa faqat o'zi eshitilgan hisobda ma'lum (zaxirada boshqa raqam
olishi mumkin) - to'liq yechim bitta hisob (GAPI bilan kelishuv).

GAPI DAGI NOM - taxallus: `barno-<shaxs raqami>`, haqiqiy ism EMAS (ism faqat bizda). Nom qo'yilgan ovoz
muddatsiz saqlanadi; nomsiz ovozni GAPI bir yozuvda eshitilgan bo'lsa 30 kundan keyin o'chiradi.

NUSXA OVOZ (jonli muammo, 2026-11-18). GAPI ovozni faqat ikkinchi eng o'xshash ovozdan ANIQ ustun bo'lsa
taniydi. Bitta odamning loyihada ikki ovozi bo'lsa (namunasi alohida, eski yig'ilishdagi ovozi alohida raqam
olgan) - yig'ilishdagi nutqi ikkalasiga deyarli bir xil o'xshaydi, GAPI tanlamaydi va UCHINCHI ovoz ochadi:
odam shundan keyin har yig'ilishda «Noma'lum» bo'lib qoladi. O'lchov: toza maydonda o'z ovozi 0.74-0.91, begona
0.21-0.33 - ya'ni model yaxshi ajratadi, muammo faqat nusxalarda. Yechim - `resolve_meeting` va `sweep`:
  * "FAQAT XODIMLAR" MAYDONI - GAPI `tenant` (`VOICE_STAFF_TENANT`, har hisobda): unda namuna yozgan har xodimning
    bitta ovozi bor (`barno-<shaxs>`), mehmon ham, nusxa ham YO'Q. Loyiha ovozlari bilan hech qachon aralashmaydi.
  * Xodimga bog'lanmagan spikerning nutq parchasi (yig'ilish audiosidan DEKODERSIZ kesiladi, `audio.cut_adts`)
    shu maydonda `enroll: off` bilan qayta solishtiriladi. Mos keldi -> `_adopt`: yig'ilishdagi nutqi xodimning
    loyihadagi ovoziga iz bo'lib qo'shiladi, nusxa ovoz GAPI dan o'chadi, mehmon shaxs xodimga qo'shiladi va
    o'tgan yig'ilishlardagi «Noma'lum #N» ismga almashadi.
  * QACHON: yig'ilishdan keyin (GAPI "yangi ovoz" degan, lekin mavjud ovozga `VOICE_HINT_SCORE` dan ko'p
    o'xshagan spiker; yoki yangi namunalardan beri tekshirilmagan mehmon) va YANGI NAMUNADAN keyin (`sweep` -
    oxirgi 30 kun mehmonlari). Ya'ni xodim namunani yig'ilishdan KEYIN yozsa ham o'sha yig'ilishga ismi qo'yiladi.
  * KUCHAYTIRISH (`_reinforce`): GAPI o'zi tanigan xodimning yig'ilishdagi nutqi ham ovoziga iz bo'lib qo'shiladi
    (`VOICE_PRINTS_MAX` gacha) - bitta o'qilgan namuna boshqa telefon/xonada chegarada qoladi (0.72-0.75).

OVOZ IZI bizda yo'q (GAPI uni hech qachon bermaydi). Namuna AUDIOSI saqlanadi (`<meetings_dir>/voice/`, 700/600):
2-bosqichda (o'z modelimiz) xodimlardan qayta yozdirmaslik uchun. Xodim ovozini o'chirsa - audio ham o'chadi.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ...core.config import settings
from ...schemas.auth import AuthUser
from ..stt import SttError
from . import audio
from .errors import MeetingProblem
from .store import MeetingStore, jdump, new_id, private_file, remove_file

log = logging.getLogger(__name__)

# --- xodimga ko'rsatiladigan matnlar (uchala kanal - shu yerdan) ---------------------------

SAMPLE_TEXT = (
    "Assalomu alaykum. Men BRB-Tech jamoasida ishlayman. Har kuni ertalab hamkasblarim bilan qisqa yig'ilish "
    "o'tkazamiz: kim qaysi vazifa ustida ishlayotganini, qanday muammolar chiqqanini va bugun nimalarni "
    "tugatishimiz kerakligini muhokama qilamiz. Yangi loyihalar bo'yicha takliflarimni ochiq aytaman, savollarga "
    "esa aniq va qisqa javob berishga harakat qilaman. Bizning ishimizda vaqtni to'g'ri taqsimlash, bir-birimizga "
    "yordam berish va mijozlar ishonchini qozonish eng muhim. Bugun ob-havo yaxshi, shuning uchun kayfiyatim ham a'lo."
)
FREE_SPEECH = ("Keyin 10-15 soniya o'z so'zlaringiz bilan gapiring: ismingiz, qaysi bo'limda ishlashingiz va hozir "
               "qanday ish ustida ekaningiz.")
STEPS = (
    "Jim joy tanlang: atrofda musiqa, shovqin va boshqa odamlarning gapi bo'lmasin.",
    "Telefonni og'zingizdan 20-30 sm uzoqda ushlang.",
    "Yig'ilishda qanday gapirsangiz, xuddi shunday odatiy ovozda va tezlikda gapiring. Baqirmang va shivirlamang.",
    "Quyidagi matnni o'qing, taxminan 30 soniya ketadi.",
    FREE_SPEECH,
    "Yozuvni yuboring. Unda faqat sizning ovozingiz bo'lishi, nutq kamida 20 soniya davom etishi va shovqin kam "
    "bo'lishi kerak.",
)
RECOMMENDED_SEC = 45
INTRO = ("🗣 Ovoz namunasi - Plaud yig'ilishlarida ism-familiyangiz avtomatik chiqishi uchun. Bir marta yozasiz, "
         "Telegram, Slack va mobil ilovadagi yig'ilishlarning hammasida ishlaydi.")
OK_TEXT = "✅ Ovozingiz saqlandi. Endi Plaud yig'ilishlarida ism-familiyangiz avtomatik chiqadi."
#: Namunadan keyin o'tgan yig'ilishlardagi «Noma'lum» ham shu xodim bo'lib chiqsa - natija matniga qo'shiladi.
RETRO_TEXT = " O'tgan {n} ta yig'ilishda ham ismingiz qo'yildi."
DELETED_TEXT = "🗑 Ovoz namunangiz o'chirildi. Yig'ilishlarda endi «Noma'lum» deb chiqasiz."
#: Rad etish / xato sababi -> xodimga matn (kod - API javobida `reason`).
REASONS = {
    "too_short": "Nutq juda qisqa chiqdi. Matnni oxirigacha o'qing va yana 10-15 soniya o'zingiz haqingizda "
                 "gapiring (jami ~45 soniya).",
    "many_voices": "Yozuvda bir nechta odamning ovozi bor. Jim joyda, yolg'iz o'zingiz yozing.",
    "no_voiceprint": "Ovoz aniq eshitilmadi. Telefonni og'zingizdan 20-30 sm uzoqda tutib, shovqinsiz joyda "
                     "qayta yozing.",
    "voice_taken": "Bu ovoz boshqa xodimning namunasiga juda o'xshash chiqdi. Administratorga murojaat qiling.",
    "unreadable": "Audio o'qilmadi. Ovozli xabar yoki m4a/mp3 formatida qayta yuboring.",
    "stt_unavailable": "Ovoz xizmati hozir javob bermadi. Birozdan keyin qayta yuboring.",
    "interrupted": "Tekshiruv server qayta ishga tushgani uchun uzildi. Namunani qayta yuboring.",
    "failed": "Namunani saqlab bo'lmadi. Birozdan keyin qayta urinib ko'ring.",
}
#: Ismsiz spiker (mehmon yoki namuna yozmagan xodim) - doimiy raqami bilan.
UNKNOWN = {"uz": "Noma'lum #{n}", "ru": "Неизвестный #{n}", "en": "Unknown #{n}"}

#: Namuna qabul qilinadigan turlar (GAPI ffmpeg o'qiydigan hamma narsani oladi; bular - kanallarimiz beradigani).
ACCEPTED = ("audio/aac", "audio/mp4", "audio/mpeg", "audio/wav", "audio/ogg", "audio/webm")
_EXT = {**audio.EXTENSIONS, "audio/webm": ".webm"}
#: GAPI dagi ovoz nomi - taxallus (haqiqiy ism emas).
PSEUDONYM = "barno-{id}"
_PSEUDONYM = re.compile(r"^barno-(\d+)$")
#: Shuncha vaqtdan eski `processing` namuna - uzilgan (restart), qayta yuborish mumkin.
STALE_SEC = 15 * 60
#: Namuna tekshiruvi fon iplari: GAPI so'rovi ~5-60 s, xodim natijani kutadi - lekin ko'p ip GAPI'ni bosmasin.
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="voice-sample")
_busy_lock = threading.Lock()


def instructions() -> dict[str, Any]:
    """Tartib va o'qish matni - uchala kanal (Telegram, Slack, mobil) SHU yerdan oladi."""
    return {"intro": INTRO, "steps": list(STEPS), "text": SAMPLE_TEXT, "freeSpeech": FREE_SPEECH,
            "recommendedSeconds": RECOMMENDED_SEC, "minSpeechSeconds": settings.voice_sample_min_speech_sec,
            "maxBytes": settings.voice_sample_max_bytes, "acceptedContentTypes": list(ACCEPTED)}


def unknown_label(person_id: Any, lang: str = "uz") -> str:
    return UNKNOWN.get(lang, UNKNOWN["uz"]).format(n=person_id)


def reason_text(reason: str | None) -> str:
    return REASONS.get(reason or "", REASONS["failed"])


# --- ish vaqti ---------------------------------------------------------------------------


def _rt() -> Any:
    from . import runtime

    return runtime()


def _gapi() -> Any:
    rt = _rt()
    return rt.voice_gapi if getattr(rt, "voice_gapi", None) is not None else rt.gapi


def _now() -> int:
    return int(time.time())


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None and str(value).strip() != "" else None
    except (TypeError, ValueError):
        return None


def _num(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _key(identity: dict[str, Any]) -> tuple[str, int | None, str]:
    """GAPI identity -> (bizdagi kalit, ovoz raqami, speaker_id). Kalit - `speaker_id` (API kaliti),
    u yo'q bo'lsa raqam (`n:<raqam>`)."""
    voice_no = _int(identity.get("voice_id"))
    speaker_id = str(identity.get("speaker_id") or "").strip()
    return (speaker_id or (f"n:{voice_no}" if voice_no is not None else "")), voice_no, speaker_id


# --- yig'ilish: GAPI ovozi -> shaxs ------------------------------------------------------


def identify(store: MeetingStore, account: int, speakers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`transcribe.normalize` spikerlari (`identity` bilan) -> shaxs raqami va (xodim bo'lsa) ismi qo'shilgan
    nusxa. Hech qachon xato bermaydi: tanib bo'lmasa spiker avvalgidek (S1, S2...) qoladi."""
    out: list[dict[str, Any]] = []
    for sp in speakers:
        item = {k: v for k, v in sp.items() if k != "identity"}
        identity = sp.get("identity") if isinstance(sp.get("identity"), dict) else {}
        status = str(identity.get("status") or "") or None
        item["voiceStatus"] = status
        item["voiceScore"] = _num(identity.get("score"))
        key, voice_no, speaker_id = _key(identity)
        # Ichki (omborga yozilmaydi): `resolve_meeting` uchun GAPI dagi ovoz kaliti va ikkinchi ovozga o'xshashlik.
        item["_voiceKey"] = speaker_id or None
        item["_runnerUp"] = _num(identity.get("runner_up"))
        if key and status in ("matched", "new"):
            try:
                person = _person_for(store, account, key, voice_no, identity.get("name"))
            except Exception:  # noqa: BLE001 - tanish ixtiyoriy: transkript baribir saqlansin
                log.exception("Ovozdan tanish: shaxs topilmadi (hisob %s)", account)
                person = None
            if person is not None:
                item["personId"] = int(person["id"])
                if person["kind"] == "employee" and person.get("name"):
                    item["name"] = person["name"]
                    item["nameSource"] = "voice"
        out.append(item)
    known = sum(1 for s in out if s.get("nameSource") == "voice")
    if any(s.get("personId") for s in out):
        log.info("Ovozdan tanish (hisob %s): %d spikerdan %d tasi xodim, %d tasi raqamli",
                 account, len(out), known, sum(1 for s in out if s.get("personId")))
    return out


def _person_for(store: MeetingStore, account: int, key: str, voice_no: int | None,
                gapi_name: Any) -> dict[str, Any]:
    now = _now()
    found = store.row("SELECT p.* FROM voice_links l JOIN voice_persons p ON p.id = l.person_id "
                      "WHERE l.account=? AND l.speaker_key=?", (account, key))
    if found is not None:
        store.execute("UPDATE voice_links SET last_seen_at=? WHERE account=? AND speaker_key=?", (now, account, key))
        return found
    with store.transaction() as conn:
        # Bog'lanish yo'q, lekin GAPI dagi nom bizning taxallus (masalan ombor tiklangan) - o'sha shaxs.
        person = None
        match = _PSEUDONYM.match(str(gapi_name or ""))
        if match:
            row = conn.execute("SELECT * FROM voice_persons WHERE id=?", (int(match.group(1)),)).fetchone()
            person = dict(row) if row is not None else None
        if person is None:
            cur = conn.execute("INSERT INTO voice_persons (kind, actor_id, name, created_at, updated_at) "
                               "VALUES ('guest', NULL, NULL, ?, ?)", (now, now))
            person = {"id": cur.lastrowid, "kind": "guest", "actor_id": None, "name": None}
        conn.execute("INSERT OR IGNORE INTO voice_links (account, speaker_key, voice_no, person_id, named, created_at, "
                     "last_seen_at) VALUES (?,?,?,?,?,?,?)",
                     (account, key, voice_no, person["id"], 1 if match else 0, now, now))
    return person


# --- namuna ------------------------------------------------------------------------------


@dataclass
class Check:
    """Namuna natijasini tekshirish: `reason` bo'sh - yaroqli."""

    reason: str | None = None
    speech: float = 0.0
    index: int = 0
    identity: dict[str, Any] = field(default_factory=dict)


def assess(payload: dict[str, Any]) -> Check:
    """GAPI natijasi -> bitta odam, yetarli nutq, ovoz izi bormi. Asosiy spiker - eng ko'p gapirgani."""
    info = [s for s in (payload.get("speaker_info") or []) if isinstance(s, dict)]

    def seconds(s: dict[str, Any]) -> float:
        return _num(s.get("speech_seconds")) or 0.0

    if not info:
        speech = _num(payload.get("speech_seconds")) or 0.0
        if speech < settings.voice_sample_min_speech_sec:
            return Check("too_short", speech)
        return Check("no_voiceprint", speech)
    main = max(info, key=seconds)
    total = sum(seconds(s) for s in info)
    speech = seconds(main)
    index = _int(main.get("index"))
    index = index if index is not None else info.index(main)
    identity = dict(main.get("identity") or {}) if isinstance(main.get("identity"), dict) else {}
    # `voices[]` - zaxira manba: identity'da raqam bo'lmasa.
    for v in payload.get("voices") or []:
        if isinstance(v, dict) and _int(v.get("speaker")) == index:
            identity.setdefault("voice_id", v.get("voice_id"))
            identity.setdefault("status", v.get("status"))
            identity.setdefault("name", v.get("name"))
    others = total - speech
    if speech < settings.voice_sample_min_speech_sec:
        return Check("too_short", speech, index, identity)
    if others >= 3.0 and others > 0.15 * total:
        return Check("many_voices", speech, index, identity)
    if main.get("has_voiceprint") is False and not _key(identity)[0]:
        return Check("no_voiceprint", speech, index, identity)
    return Check(None, speech, index, identity)


class VoiceTaken(Exception):
    """Namuna boshqa XODIMNING ovoziga mos keldi."""


def _content_type(content_type: str | None, data: bytes) -> str:
    kind = audio.canonical_type(content_type)
    if kind in ACCEPTED:
        return kind
    head = data[:16]
    if head[:4] == b"OggS":
        return "audio/ogg"
    if head[:4] == b"\x1aE\xdf\xa3":
        return "audio/webm"
    if head[:4] == b"RIFF":
        return "audio/wav"
    for candidate in ("audio/aac", "audio/mp4", "audio/mpeg"):
        try:
            if audio.sniff(data[:64], candidate):
                return candidate
        except Exception:  # noqa: BLE001
            continue
    return kind


def submit(user: AuthUser, data: bytes, content_type: str | None, channel: str, *,
           on_done: Callable[[dict[str, Any]], None] | None = None, wait: bool = False) -> dict[str, Any]:
    """Namunani qabul qiladi va tekshiruvni fonda boshlaydi -> namuna ko'rinishi (`processing`).
    `on_done(view)` - tekshiruv tugagach (botlar natijani shu bilan yuboradi). `wait` - testlar uchun."""
    if not settings.voice_samples_enabled:
        raise MeetingProblem(503, "voice_disabled", "Ovoz namunasi hozir o'chiq")
    gapi = _gapi()
    if gapi is None or not getattr(gapi, "configured", False):
        raise MeetingProblem(503, "stt_not_configured", "Ovoz xizmati sozlanmagan")
    if not data:
        raise MeetingProblem(400, "empty_audio", "Audio bo'sh")
    if len(data) > int(settings.voice_sample_max_bytes):
        raise MeetingProblem(413, "sample_too_large", "Namuna juda katta - 1 daqiqagacha yozing")
    kind = _content_type(content_type, data)
    if kind not in ACCEPTED:
        raise MeetingProblem(415, "unsupported_type", "Bu audio formati qabul qilinmaydi")
    store = _rt().store
    now = _now()
    with _busy_lock:
        busy = store.row("SELECT id FROM voice_samples WHERE actor_id=? AND status='processing' AND created_at>?",
                         (user.actorId, now - STALE_SEC))
        if busy is not None:
            raise MeetingProblem(409, "sample_busy", "Oldingi namuna hali tekshirilmoqda - natijani kuting")
        sid = new_id()
        path = voice_dir(store, user.actorId) / f"{sid}{_EXT.get(kind, '.bin')}"
        private_file(path)
        path.write_bytes(data)
        store.execute("INSERT INTO voice_samples (id, actor_id, channel, status, content_type, bytes, path, created_at) "
                      "VALUES (?,?,?,'processing',?,?,?,?)", (sid, user.actorId, channel, kind, len(data), str(path), now))
    log.info("Ovoz namunasi %s (%s, %s): %d bayt, %s", sid[:8], user.actorId, channel, len(data), kind)
    name = " ".join(str(user.fullName or "").split())[:60] or None
    if wait:
        _process(user.actorId, name, sid, on_done)
    else:
        _pool.submit(_process, user.actorId, name, sid, on_done)
    return sample_view(store.row("SELECT * FROM voice_samples WHERE id=?", (sid,)))


def voice_dir(store: MeetingStore, actor_id: int) -> Path:
    from .store import _private_dir

    root = store.root / "voice"
    _private_dir(root)
    path = root / str(int(actor_id))
    _private_dir(path)
    return path


def _process(actor_id: int, name: str | None, sid: str, on_done: Callable[[dict[str, Any]], None] | None) -> None:
    store = _rt().store
    gapi = _gapi()
    row = store.row("SELECT * FROM voice_samples WHERE id=?", (sid,))
    if row is None:
        return
    status, reason, speech, person_id = "failed", "failed", None, None
    report: dict[str, Any] = {}
    try:
        data = Path(row["path"]).read_bytes()
        accounts = list(gapi.accounts) or [1]
        # ASOSIY hisob - natija bergan BIRINCHISI: namunani u baholaydi (rad etish shu yerda). Masalan 1-hisob
        # balansi tugagan bo'lsa (kun oxiri) - 2-hisob asosiy bo'ladi, 1-hisobga keyingi namunada yoziladi.
        primary = False
        last_error: SttError | None = None
        before: set[str] = set()
        hint = False
        first = not store.scalar("SELECT COUNT(*) FROM voice_samples WHERE actor_id=? AND status='ok'", (actor_id,), 0)
        for account in accounts:
            try:
                payload, job_id = gapi.transcribe_sample(data, row["content_type"], account=account)
            except SttError as exc:
                last_error = exc
                log.warning("Ovoz namunasi %s: %d-hisobga yozilmadi - %s", sid[:8], account, exc)
                report[str(account)] = {"error": getattr(exc, "gapi_code", "") or "stt"}
                if getattr(exc, "gapi_status", None) == 422 and not primary:
                    raise                                       # audio o'qilmadi - boshqa hisob ham o'qimaydi
                continue
            check = assess(payload)
            if not primary:
                speech = round(check.speech, 1)
                if check.reason:
                    status, reason = "rejected", check.reason
                    report[str(account)] = {"rejected": check.reason, "speech": speech}
                    break
                person_id = employee_id(store, actor_id, name)
                before = _named_meetings(store, person_id)
            elif check.reason:
                report[str(account)] = {"rejected": check.reason}
                continue
            try:
                report[str(account)] = _attach(store, gapi, account, job_id, check, person_id)
            except VoiceTaken:
                if not primary:
                    status, reason = "rejected", "voice_taken"
                    report[str(account)] = {"rejected": "voice_taken"}
                    break
                log.warning("Ovoz namunasi %s: %d-hisobda ovoz boshqa xodimniki", sid[:8], account)
                report[str(account)] = {"rejected": "voice_taken"}
                continue
            primary = True
            hint = hint or _similar_exists(check.identity, first)
            # "Faqat xodimlar" maydoniga ham (nusxa ovozlarni tuzatish shu bilan ishlaydi). Xato namunani buzmaydi.
            try:
                report[str(account)]["staff"] = _staff_add(gapi, account, person_id, data, row["content_type"])
                _staff_forget(account)
            except SttError as exc:
                log.warning("Ovoz namunasi %s: %d-hisobda xodimlar maydoniga yozilmadi - %s", sid[:8], account, exc)
        else:
            if not primary:
                raise last_error or SttError("GAPI hisobi yo'q", status=501)
            status, reason = "ok", None
    except SttError as exc:
        status = "failed"
        reason = "unreadable" if getattr(exc, "gapi_status", None) == 422 else "stt_unavailable"
        log.warning("Ovoz namunasi %s: GAPI xatosi - %s", sid[:8], exc)
    except Exception:  # noqa: BLE001 - namuna yo'qolmasin, odam aniq javob olsin
        log.exception("Ovoz namunasi %s: kutilmagan xato", sid[:8])
        status, reason = "failed", "failed"
    # Namuna vaqti - tekshiruvdan OLDIN: mehmonning `checked_at` i undan keyin bo'ladi, ya'ni shu namunaga
    # nisbatan "tekshirilgan" hisoblanadi (`_stale`) va keyingi yig'ilishda bekorga qayta solishtirilmaydi.
    finished = _now()
    if status == "ok" and person_id is not None:
        # O'TGAN YIG'ILISHLAR. Namuna mehmon ovoziga mos kelgan bo'lsa ism allaqachon ko'chgan (`merge_guest`);
        # GAPI tanlay olmagan bo'lsa (`hint`: mavjud ovozga o'xshash, lekin bog'lanmadi) - oxirgi 30 kun
        # mehmonlari xodimlar maydonida qayta solishtiriladi (`sweep`).
        try:
            _backfill(store, person_id)
            if hint:
                report["sweep"] = sweep(store, gapi, budget=float(settings.voice_sweep_budget_sec),
                                        limit=int(settings.voice_sweep_max), fresh=finished)
            gained = len(_named_meetings(store, person_id) - before)
            if gained:
                report["retro"] = {"meetings": gained}
        except Exception:  # noqa: BLE001 - o'tgan yig'ilishlar qo'shimcha: namunaning o'zi saqlangan
            log.exception("Ovoz namunasi %s: o'tgan yig'ilishlar tekshirilmadi", sid[:8])
    store.execute("UPDATE voice_samples SET status=?, reason=?, speech_sec=?, person_id=?, result_json=?, done_at=? "
                  "WHERE id=?", (status, reason, speech, person_id, jdump(report), finished, sid))
    log.info("Ovoz namunasi %s: %s%s", sid[:8], status, f" ({reason})" if reason else "")
    if on_done is not None:
        try:
            on_done(sample_view(store.row("SELECT * FROM voice_samples WHERE id=?", (sid,))))
        except Exception:  # noqa: BLE001 - kanal xatosi namunani buzmasin
            log.exception("Ovoz namunasi %s: natijani yuborib bo'lmadi", sid[:8])


def employee_id(store: MeetingStore, actor_id: int, name: str | None) -> int:
    """Xodimning shaxs raqami (yo'q bo'lsa yaratiladi). Ism o'zgargan bo'lsa yangilanadi."""
    now = _now()
    row = store.row("SELECT id, name FROM voice_persons WHERE actor_id=?", (actor_id,))
    if row is not None:
        if name and row["name"] != name:
            store.execute("UPDATE voice_persons SET name=?, kind='employee', updated_at=? WHERE id=?",
                          (name, now, row["id"]))
        return int(row["id"])
    cur = store.execute("INSERT INTO voice_persons (kind, actor_id, name, created_at, updated_at) "
                        "VALUES ('employee', ?, ?, ?, ?)", (actor_id, name, now, now))
    return int(cur.lastrowid)


def _attach(store: MeetingStore, gapi: Any, account: int, job_id: str, check: Check, person_id: int) -> dict[str, Any]:
    """Namunaning ovozi -> shu xodim (shu hisobda). `VoiceTaken` - boshqa xodimning ovozi."""
    identity = check.identity
    status = str(identity.get("status") or "")
    key, voice_no, speaker_id = _key(identity)
    now = _now()
    mine = store.rows("SELECT * FROM voice_links WHERE person_id=? AND account=? ORDER BY created_at", (person_id, account))
    own = next((m for m in mine if not str(m["speaker_key"]).startswith("n:")), None)
    if key and status in ("matched", "new"):
        link = store.row("SELECT l.*, p.kind, p.actor_id AS owner FROM voice_links l JOIN voice_persons p "
                         "ON p.id = l.person_id WHERE l.account=? AND l.speaker_key=?", (account, key))
        if link is None:
            match = _PSEUDONYM.match(str(identity.get("name") or ""))
            if match and int(match.group(1)) != person_id:
                other = store.row("SELECT kind FROM voice_persons WHERE id=?", (int(match.group(1)),))
                if other is not None and other["kind"] == "employee":
                    raise VoiceTaken()
        elif int(link["person_id"]) != person_id:
            if link["kind"] == "employee":
                raise VoiceTaken()
            merge_guest(store, int(link["person_id"]), person_id)
        if status == "new" and link is None and own is not None and speaker_id and job_id:
            # Namuna xodimning BOR ovoziga mos kelmay yangi ovoz ochdi - izi bor ovozga qo'shiladi, yangisi o'chadi:
            # bitta xodim - bitta ovoz (loyihada 500 ta chegara).
            gapi.enroll_speaker(own["speaker_key"], job_id, speaker_index=check.index, account=account)
            _quiet(gapi.delete_speaker, speaker_id, account=account)
            return {"voice": own["voice_no"], "action": "added"}
        if link is None:
            store.execute("INSERT OR IGNORE INTO voice_links (account, speaker_key, voice_no, person_id, named, "
                          "created_at, last_seen_at) VALUES (?,?,?,?,0,?,?)",
                          (account, key, voice_no, person_id, now, now))
        if status == "matched" and speaker_id and job_id:
            # Tanish ovozga shu namunaning izi ham (yaxshi yozuv - aniqroq tanish). Chegara (10 ta iz) - jim.
            _quiet(gapi.enroll_speaker, speaker_id, job_id, speaker_index=check.index, account=account)
        if speaker_id:
            _name_voice(store, gapi, account, key, speaker_id, person_id)
        return {"voice": voice_no, "status": status, "action": "linked"}
    # GAPI ovoz ochmadi (masalan bo'sh loyiha: `no_enrolled_voices`) - aniq yo'l: ovoz yaratib, izini qo'shamiz.
    if not job_id:
        raise SttError("GAPI vazifa raqamini bermadi", status=502)
    if own is not None:
        gapi.enroll_speaker(own["speaker_key"], job_id, speaker_index=check.index, account=account)
        return {"voice": own["voice_no"], "action": "added"}
    created = gapi.create_speaker(PSEUDONYM.format(id=person_id), account=account)
    new_key = str(created.get("id") or created.get("speaker_id") or "")
    if not new_key:
        raise SttError("GAPI ovoz raqamini bermadi", status=502)
    gapi.enroll_speaker(new_key, job_id, speaker_index=check.index, account=account)
    number = _int(created.get("number") if created.get("number") is not None else created.get("voice_id"))
    store.execute("INSERT OR REPLACE INTO voice_links (account, speaker_key, voice_no, person_id, named, created_at, "
                  "last_seen_at) VALUES (?,?,?,?,1,?,?)", (account, new_key, number, person_id, now, now))
    return {"voice": number, "action": "created"}


def _name_voice(store: MeetingStore, gapi: Any, account: int, key: str, speaker_id: str, person_id: int) -> None:
    """GAPI dagi ovozga taxallus (`barno-<id>`) - muddatsiz saqlansin. Xato - keyingi namunada qayta."""
    row = store.row("SELECT named FROM voice_links WHERE account=? AND speaker_key=?", (account, key))
    if row is not None and row["named"]:
        return
    try:
        gapi.rename_speaker(speaker_id, PSEUDONYM.format(id=person_id), account=account)
    except SttError as exc:
        log.warning("Ovozga nom qo'yilmadi (hisob %s): %s", account, exc)
        return
    store.execute("UPDATE voice_links SET named=1 WHERE account=? AND speaker_key=?", (account, key))


def _quiet(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
    try:
        fn(*args, **kwargs)
    except SttError as exc:
        log.info("GAPI ovoz amali o'tmadi (%s): %s", getattr(fn, "__name__", "?"), exc)


def merge_guest(store: MeetingStore, guest_id: int, person_id: int) -> None:
    """Mehmon shu xodim bo'lib chiqdi: ovozlari va yig'ilishlardagi raqami xodimga o'tadi."""
    with store.transaction() as conn:
        conn.execute("UPDATE voice_links SET person_id=? WHERE person_id=?", (person_id, guest_id))
        conn.execute("UPDATE speakers SET person_id=? WHERE person_id=?", (person_id, guest_id))
        conn.execute("DELETE FROM voice_persons WHERE id=? AND kind='guest'", (guest_id,))
    log.info("Ovoz: mehmon #%d -> xodim #%d", guest_id, person_id)


def _backfill(store: MeetingStore, person_id: int) -> None:
    """Xodim ismi - shu shaxs eshitilgan hamma yig'ilishga (odam o'zi qo'ygan ismga tegilmaydi)."""
    person = store.row("SELECT name FROM voice_persons WHERE id=?", (person_id,))
    if person is None or not person["name"]:
        return
    cur = store.execute("UPDATE speakers SET name=?, name_source='voice' WHERE person_id=? "
                        "AND (name IS NULL OR name_source='voice')", (person["name"], person_id))
    if cur.rowcount:
        log.info("Ovoz: xodim #%d ismi %d ta spikerga qo'yildi", person_id, cur.rowcount)


def _named_meetings(store: MeetingStore, person_id: int) -> set[str]:
    """Shu xodim OVOZIDAN tanilgan yig'ilishlar."""
    return {str(r["meeting_id"]) for r in store.rows(
        "SELECT DISTINCT meeting_id FROM speakers WHERE person_id=? AND name_source='voice'", (person_id,))}


# --- NUSXA OVOZ: "faqat xodimlar" maydonida qayta solishtirish (modul izohi) -----------------

#: Maydondagi xodimlar ro'yxati shuncha soniya eslab qolinadi (har yig'ilishda GAPI dan so'ralmasin).
_STAFF_TTL = 600.0
_staff_lock = threading.Lock()
_staff_cache: dict[int, tuple[float, frozenset[int]]] = {}
#: Maydonga yozish - navbat bilan: ikki xodim bir vaqtda namuna yuborsa, birining hali taxallus olmagan yangi ovozi
#: ikkinchisining "nomsiz ovozlarni tozalash" qadamida o'chib ketmasin.
_staff_write_lock = threading.Lock()
_sweep_lock = threading.Lock()
#: GAPI natijasi 30 kun saqlanadi - undan eski yig'ilishdan iz qo'shib bo'lmaydi.
_RETRO_DAYS = 30
#: Bitta mehmondan xodim ovoziga qo'shiladigan yig'ilishlar soni (iz chegarasi - 10).
_ADOPT_JOBS = 3
#: Bitta yig'ilishda qayta solishtiriladigan spikerlar chegarasi (GAPI 4 tadan ortiq ovoz ajratmaydi).
_MEETING_PROBES = 4


def _staff_tenant() -> str:
    """"Faqat xodimlar" maydoni nomi; bo'sh - tuzatish o'chiq."""
    if not settings.voice_resolve_enabled:
        return ""
    return str(settings.voice_staff_tenant or "").strip()


def _alias_id(name: Any) -> int | None:
    match = _PSEUDONYM.match(str(name or ""))
    return int(match.group(1)) if match else None


def _similar_exists(identity: dict[str, Any], first: bool) -> bool:
    """Namuna natijasi: loyihada shu odamga O'XSHASH, lekin unga bog'lanmagan ovoz bormi. "Yangi ovoz" bo'lsa -
    eng yaqin ovozga o'xshashlik chegaradan baland. Tanilgan bo'lsa - IKKINCHI izga o'xshashlik, lekin faqat
    BIRINCHI namunada: `runner_up` shu ovozning o'z ikkinchi izi ham bo'lishi mumkin (jonli: 0.913 / 0.875 - bitta
    odamning ikki izi), ya'ni qayta namunada u doim baland va hech narsani bildirmaydi."""
    status = str(identity.get("status") or "")
    floor = float(settings.voice_hint_score)
    if status == "new":
        return (_num(identity.get("score")) or 0.0) >= floor
    if status == "matched":
        return first and (_num(identity.get("runner_up")) or 0.0) >= floor
    return False


def _staff_forget(account: int | None = None) -> None:
    with _staff_lock:
        if account is None:
            _staff_cache.clear()
        else:
            _staff_cache.pop(account, None)


def _staff_add(gapi: Any, account: int, person_id: int, data: bytes, content_type: str) -> str:
    """Xodim namunasi -> "faqat xodimlar" maydonidagi ovozi (`barno-<shaxs>`; yo'q bo'lsa ochiladi).
    `created` | `added` | `conflict` (maydonda boshqa xodimga mos keldi) | `rejected` | `off`. Xato - `SttError`.

    `enroll` - odatiy (`auto`): `off` bilan ishlagan vazifadan iz qo'shib bo'lmaydi (422 `no_voiceprint`, jonli
    tekshirilgan). Shuning uchun GAPI yangi ovozni o'zi ochadi - unga taxallus qo'yiladi; namunadagi ikkinchi
    (qisqa) ovozdan ochilgan nomsiz ovoz esa oxirida o'chiriladi: maydonda FAQAT taxallusli ovozlar qoladi."""
    tenant = _staff_tenant()
    if not tenant:
        return "off"
    with _staff_write_lock:
        return _staff_write(gapi, account, person_id, data, content_type, tenant)


def _staff_write(gapi: Any, account: int, person_id: int, data: bytes, content_type: str, tenant: str) -> str:
    alias = PSEUDONYM.format(id=person_id)
    payload, job_id = gapi.transcribe_sample(data, content_type, account=account, tenant=tenant)
    check = assess(payload)
    if check.reason or not job_id:
        return "rejected"
    status = str(check.identity.get("status") or "")
    _, _, heard = _key(check.identity)                    # GAPI shu vazifada tanigan yoki ochgan ovoz
    voices = gapi.speakers(account=account, tenant=tenant)
    names = {str(v.get("id") or ""): str(v.get("name") or "") for v in voices}
    own = next((key for key, name in names.items() if key and name == alias), None)
    other = _alias_id(names.get(heard) or check.identity.get("name"))
    result = "added"
    if status == "matched" and other is not None and other != person_id:
        result = "conflict"
    elif own is None and heard and other is None:
        gapi.rename_speaker(heard, alias, account=account)
        own, result = heard, "created"
    elif own is None:
        created = gapi.create_speaker(alias, account=account, tenant=tenant)
        own = str(created.get("id") or created.get("speaker_id") or "")
        if not own:
            raise SttError("GAPI ovoz raqamini bermadi", status=502)
        gapi.enroll_speaker(own, job_id, speaker_index=check.index, account=account)
        result = "created"
    else:
        # O'z ovozi bor: shu namunaning izi ham unga (boshqa sharoit - aniqroq tanish). Chegara (10 iz) - jim.
        _quiet(gapi.enroll_speaker, own, job_id, speaker_index=check.index, account=account)
    for key, name in names.items():
        if key and key != own and _alias_id(name) is None:
            _quiet(gapi.delete_speaker, key, account=account)
    return result


def _staff_learn(gapi: Any, account: int, person_id: int, clip: tuple[bytes, str], score: float | None) -> None:
    """Xodim deb topilgan spikerning YIG'ILISHDAGI nutqi maydondagi ovoziga ham iz bo'ladi: maydonda faqat o'qilgan
    namuna bo'lsa boshqa telefon/xonadagi nutq chegarada chiqadi (jonli: 0.721, chegara 0.72) - keyingi safar
    aniqroq tanilsin. Solishtirish vazifasidan (`enroll: off`) iz qo'shib bo'lmaydi, shuning uchun parcha maydonga
    yana bir marta yuboriladi (~40 s). Yaxshi tanilgan (>= 0.85) bo'lsa kerak emas. Xato - jim."""
    if score is not None and score >= 0.85:
        return
    try:
        outcome = _staff_add(gapi, account, person_id, clip[0], clip[1])
    except SttError as exc:
        log.info("Xodimlar maydoni (hisob %s): #%d yig'ilish nutqi qo'shilmadi - %s", account, person_id, exc)
        return
    log.info("Xodimlar maydoni (hisob %s): xodim #%d yig'ilish nutqi - %s", account, person_id, outcome)


def _staff_remove(gapi: Any, person_id: int) -> None:
    """Xodim ovozini o'chirdi - maydondagi ovozi ham (har hisobda). Xato - jim (maydon yordamchi)."""
    tenant = _staff_tenant()
    if not tenant:
        return
    alias = PSEUDONYM.format(id=person_id)
    for account in list(getattr(gapi, "accounts", None) or [1]):
        try:
            for v in gapi.speakers(account=account, tenant=tenant):
                if str(v.get("name") or "") == alias and v.get("id"):
                    gapi.delete_speaker(str(v["id"]), account=account)
        except SttError as exc:
            log.info("Xodimlar maydonidan ovoz o'chmadi (hisob %s): %s", account, exc)
    _staff_forget()


def _staff_people(store: MeetingStore, gapi: Any, account: int) -> frozenset[int]:
    """Shu hisobning maydonida ovozi bor XODIMLAR (shaxs raqamlari). Yetishmayotgani saqlangan namunasidan
    to'ldiriladi (maydon yo'q bo'lsa yoki xodim maydon paydo bo'lishidan oldin yozgan bo'lsa) - maydon o'zi tiklanadi."""
    tenant = _staff_tenant()
    if not tenant:
        return frozenset()
    with _staff_lock:
        cached = _staff_cache.get(account)
        if cached is not None and time.monotonic() - cached[0] < _STAFF_TTL:
            return cached[1]
        have = {pid for v in gapi.speakers(account=account, tenant=tenant)
                if (pid := _alias_id(v.get("name"))) is not None}
        tried: set[int] = set()
        for row in store.rows("SELECT p.id, s.path, s.content_type FROM voice_persons p JOIN voice_samples s "
                              "ON s.actor_id = p.actor_id WHERE p.kind='employee' AND s.status='ok' "
                              "ORDER BY s.created_at DESC, s.rowid DESC"):
            pid = int(row["id"])
            if pid in have or pid in tried:
                continue
            tried.add(pid)
            try:
                outcome = _staff_add(gapi, account, pid, Path(str(row["path"])).read_bytes(), row["content_type"])
            except (OSError, SttError) as exc:
                log.warning("Xodimlar maydoni (hisob %s): #%d namunasi yozilmadi - %s", account, pid, exc)
                continue
            log.info("Xodimlar maydoni (hisob %s): xodim #%d - %s", account, pid, outcome)
            if outcome in ("created", "added"):
                have.add(pid)
        employees = {int(r["id"]) for r in store.rows("SELECT id FROM voice_persons WHERE kind='employee'")}
        people = frozenset(have & employees)
        _staff_cache[account] = (time.monotonic(), people)
        return people


def _ranges(segments: list[dict[str, Any]], label: str) -> list[tuple[float, float]]:
    """Spikerning eng uzun gaplari - jami `VOICE_CLIP_SEC` gacha (uzun gap - toza ovoz: ustma-ust gap kam)."""
    target, floor = float(settings.voice_clip_sec), float(settings.voice_clip_min_sec)
    spans = sorted(((float(s["end"]) - float(s["start"]), float(s["start"]), float(s["end"]))
                    for s in segments if s.get("speaker") == label), reverse=True)
    picked: list[tuple[float, float]] = []
    total = 0.0
    for length, start, end in spans:
        if total >= target or length < 1.0:
            break
        take = min(length - 0.2, target - total)
        if take <= 0.5:
            continue
        picked.append((start + 0.1, start + 0.1 + take))
        total += take
    return picked if total >= floor else []


def _meeting_clip(meeting: dict[str, Any], label: str, segments: list[dict[str, Any]]) -> tuple[bytes, str] | None:
    """Yig'ilish audiosidan shu spikerning nutq parchasi - dekodersiz (AAC/ADTS, m4a, MP3). Bo'lmasa `None`."""
    path = Path(str(meeting.get("audio_path") or ""))
    if meeting.get("audio_deleted_at") or not str(meeting.get("audio_path") or "") or not path.is_file():
        return None
    ranges = _ranges(segments, label)
    if not ranges:
        return None
    kind = audio.canonical_type(meeting.get("content_type"))
    try:
        if kind == "audio/aac":
            data, out = audio.cut_adts(path, ranges), "audio/aac"
        elif kind == "audio/mp4":
            tmp = path.with_name(f"{path.stem}.clip-{new_id()[:8]}.aac")
            try:
                private_file(tmp)
                audio.mp4_to_adts(path, tmp)
                data, out = audio.cut_adts(tmp, ranges), "audio/aac"
            finally:
                remove_file(tmp)
        elif kind == "audio/mpeg":
            data, out = audio.cut_mp3(path, ranges), "audio/mpeg"
        else:
            return None
    except Exception as exc:  # noqa: BLE001 - parcha qo'shimcha: kesilmasa GAPI dagi qisqa parcha sinab ko'riladi
        log.info("Spiker parchasi kesilmadi (%s): %s", path.name, exc)
        return None
    return (data, out) if len(data) >= 4000 else None


def _voice_clip(gapi: Any, account: int, key: Any) -> tuple[bytes, str] | None:
    """Zaxira: GAPI dagi shu ovozning 12 soniyagacha parchasi (audio bizda yo'q yoki kesib bo'lmaydigan tur)."""
    key = str(key or "")
    if not key or key.startswith("n:"):
        return None
    try:
        data = gapi.speaker_clip(key, account=account)
    except SttError:
        return None
    return (data, "audio/wav") if data and len(data) >= 4000 else None


def _probe(store: MeetingStore, gapi: Any, account: int, clip: tuple[bytes, str]) -> tuple[int | None, float | None]:
    """Nutq parchasi -> ("faqat xodimlar" maydonida mos kelgan XODIM, o'xshashlik). `enroll: off` - maydon
    o'zgarmaydi. Qaror GAPI niki (chegara 0.72 va ikkinchi ovozdan ustunlik) - toza maydonda u ishonchli."""
    payload, _ = gapi.transcribe_sample(clip[0], clip[1], account=account, tenant=_staff_tenant(), enroll="off")
    info = [s for s in (payload.get("speaker_info") or []) if isinstance(s, dict)]
    if not info:
        return None, None
    main = max(info, key=lambda s: _num(s.get("speech_seconds")) or 0.0)
    identity = main.get("identity") if isinstance(main.get("identity"), dict) else {}
    score = _num(identity.get("score"))
    if str(identity.get("status") or "") != "matched":
        return None, score
    pid = _alias_id(identity.get("name"))
    if pid is None:
        return None, score
    known = store.row("SELECT id FROM voice_persons WHERE id=? AND kind='employee'", (pid,))
    return (pid if known is not None else None), score


def _adopt(store: MeetingStore, gapi: Any, account: int, employee: int, *, guest: int | None,
           voice_key: str | None, jobs: list[tuple[str, int]]) -> None:
    """Spiker (va uning mehmon ovozi) shu XODIM bo'lib chiqdi: yig'ilishdagi nutqi xodimning loyihadagi ovoziga
    iz bo'ladi, NUSXA ovoz GAPI dan o'chadi (bitta odam - bitta ovoz), mehmon shaxs xodimga qo'shiladi va
    o'tgan yig'ilishlarga ism qo'yiladi."""
    now = _now()
    if guest is not None and store.row("SELECT id FROM voice_persons WHERE id=? AND kind='guest'", (guest,)) is None:
        guest = None                                           # faqat MEHMON shaxs qo'shiladi, xodim - hech qachon
    own = store.row("SELECT speaker_key FROM voice_links WHERE person_id=? AND account=? AND speaker_key NOT LIKE 'n:%' "
                    "ORDER BY created_at LIMIT 1", (employee, account))
    if own is None:
        created = gapi.create_speaker(PSEUDONYM.format(id=employee), account=account)
        own_key = str(created.get("id") or created.get("speaker_id") or "")
        if not own_key:
            raise SttError("GAPI ovoz raqamini bermadi", status=502)
        number = _int(created.get("number") if created.get("number") is not None else created.get("voice_id"))
        store.execute("INSERT OR REPLACE INTO voice_links (account, speaker_key, voice_no, person_id, named, "
                      "created_at, last_seen_at) VALUES (?,?,?,?,1,?,?)", (account, own_key, number, employee, now, now))
    else:
        own_key = str(own["speaker_key"])
    for job_id, raw_index in jobs[:_ADOPT_JOBS]:
        _quiet(gapi.enroll_speaker, own_key, str(job_id), speaker_index=int(raw_index), account=account)
    keys: set[str] = set()
    if guest is not None:
        keys |= {str(r["speaker_key"]) for r in store.rows(
            "SELECT speaker_key FROM voice_links WHERE person_id=? AND account=?", (guest, account))}
    if voice_key:
        holder = store.row("SELECT p.kind FROM voice_links l JOIN voice_persons p ON p.id = l.person_id "
                           "WHERE l.account=? AND l.speaker_key=?", (account, voice_key))
        if holder is None or holder["kind"] == "guest":       # boshqa XODIMNING ovoziga hech qachon tegilmaydi
            keys.add(str(voice_key))
    keys.discard(own_key)
    for key in sorted(keys):
        if key.startswith("n:"):
            continue
        try:
            gapi.delete_speaker(key, account=account)
        except SttError as exc:
            # O'chmadi - bog'lanish pastda xodimga o'tadi: ovoz uning ikkinchi ovozi bo'lib qoladi (ism to'g'ri chiqadi).
            log.warning("Nusxa ovoz GAPI dan o'chmadi (hisob %s): %s", account, exc)
            continue
        store.execute("DELETE FROM voice_links WHERE account=? AND speaker_key=?", (account, key))
    if guest is not None and guest != employee:
        merge_guest(store, guest, employee)
    _backfill(store, employee)


def _stale(store: MeetingStore, guest: Any, fresh: int) -> bool:
    """Mehmon oxirgi namunadan (`fresh`) beri xodimlar maydonida solishtirilmaganmi."""
    row = store.row("SELECT checked_at FROM voice_persons WHERE id=? AND kind='guest'", (guest,))
    return row is not None and (row["checked_at"] is None or int(row["checked_at"]) < fresh)


def _checked(store: MeetingStore, guest: Any) -> None:
    if guest is not None:
        store.execute("UPDATE voice_persons SET checked_at=? WHERE id=? AND kind='guest'", (_now(), guest))


def _fresh(store: MeetingStore) -> int:
    """Oxirgi muvaffaqiyatli namuna vaqti: undan keyin xodimlar maydoni o'zgarmagan."""
    return int(store.scalar("SELECT MAX(done_at) FROM voice_samples WHERE status='ok'", (), 0) or 0)


def resolve_meeting(store: MeetingStore, account: int, meeting: dict[str, Any], speakers: list[dict[str, Any]],
                    segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`identify` dan keyin, transkript saqlanishidan OLDIN: (1) GAPI tanigan xodimning nutqi ovoziga iz bo'lib
    qo'shiladi; (2) xodimga bog'lanmagan, lekin kimningdir NUSXASI bo'lishi mumkin spiker xodimlar maydonida
    qayta solishtiriladi. Hech qachon xato bermaydi - tuzatib bo'lmasa spikerlar o'zgarishsiz qaytadi."""
    if not _staff_tenant() or not meeting.get("stt_job_id"):
        return speakers
    try:
        return _resolve_meeting(store, _gapi(), account, meeting, [dict(sp) for sp in speakers], segments)
    except Exception:  # noqa: BLE001 - tuzatish ixtiyoriy: transkript baribir saqlansin
        log.exception("Ovoz: yig'ilish %s spikerlari qayta solishtirilmadi", meeting.get("id"))
        return speakers


def _resolve_meeting(store: MeetingStore, gapi: Any, account: int, meeting: dict[str, Any],
                     speakers: list[dict[str, Any]], segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    job_id = str(meeting["stt_job_id"])
    employees = {int(r["id"]) for r in store.rows("SELECT id FROM voice_persons WHERE kind='employee'")}
    if not employees:
        return speakers
    _reinforce(gapi, account, job_id, speakers, employees)
    fresh = _fresh(store)
    floor, shortest = float(settings.voice_hint_score), float(settings.voice_clip_min_sec)

    def suspect(sp: dict[str, Any]) -> bool:
        if sp.get("rawIndex") is None or sp.get("personId") in employees or (sp.get("talkSec") or 0.0) < shortest:
            return False
        if sp.get("voiceStatus") == "new":                    # mavjud ovozga o'xshash "yangi" - kimningdir nusxasi
            return (sp.get("voiceScore") or 0.0) >= floor
        if sp.get("voiceStatus") == "matched" and sp.get("personId") is not None:
            return _stale(store, sp["personId"], fresh)       # mehmon - yangi namunalardan beri tekshirilmagan
        return False

    pending = [sp for sp in speakers if suspect(sp)][:_MEETING_PROBES]
    if not pending or not _staff_people(store, gapi, account):
        return speakers
    for sp in pending:
        guest = sp.get("personId")
        clip = _meeting_clip(meeting, sp["id"], segments) or _voice_clip(gapi, account, sp.get("_voiceKey"))
        if clip is None:
            continue
        try:
            found, score = _probe(store, gapi, account, clip)
            if found is None:
                _checked(store, guest)
                continue
            _adopt(store, gapi, account, found, guest=guest, voice_key=sp.get("_voiceKey"),
                   jobs=[(job_id, int(sp["rawIndex"]))])
        except SttError as exc:
            log.warning("Ovoz: yig'ilish %s, %s qayta solishtirilmadi - %s", meeting.get("id"), sp.get("id"), exc)
            continue
        _staff_learn(gapi, account, found, clip, score)
        person = store.row("SELECT name FROM voice_persons WHERE id=?", (found,)) or {}
        sp.update(personId=found, nameSource="voice", voiceStatus="matched",
                  voiceScore=score if score is not None else sp.get("voiceScore"))
        if person.get("name"):
            sp["name"] = person["name"]
        log.info("Ovoz: yig'ilish %s, %s - nusxa ovoz xodim #%d ga birlashtirildi (o'xshashlik %s)",
                 meeting.get("id"), sp.get("id"), found, score)
    return speakers


def _reinforce(gapi: Any, account: int, job_id: str, speakers: list[dict[str, Any]], employees: set[int]) -> None:
    """GAPI o'zi tanigan xodim: shu yig'ilishdagi nutqi ham ovoziga iz bo'lib qo'shiladi (`VOICE_PRINTS_MAX` gacha) -
    faqat ovoz bu sharoitni hali yaxshi bilmasa (< 0.9) va nutq yetarli bo'lsa (20 s). Ishonch - GAPI ning
    "tanildi" qarori (chegara 0.72 va boshqa OVOZDAN ustunlik); `runner_up` ga qaralmaydi - u shu ovozning o'z
    ikkinchi izi ham bo'ladi (jonli: 0.913 / 0.875), ya'ni ikki izli ovozda doim baland."""
    todo = []
    for sp in speakers:
        key, score = str(sp.get("_voiceKey") or ""), sp.get("voiceScore")
        if (sp.get("personId") in employees and sp.get("voiceStatus") == "matched" and key
                and sp.get("rawIndex") is not None and (sp.get("talkSec") or 0.0) >= 20.0
                and score is not None and score < 0.9):
            todo.append(sp)
    if not todo:
        return
    try:
        prints = {str(v.get("id") or ""): _int(v.get("voiceprints")) or 0 for v in gapi.speakers(account=account)}
    except SttError as exc:
        log.info("Ovoz izlari soni olinmadi (hisob %s): %s", account, exc)
        return
    for sp in todo:
        key = str(sp["_voiceKey"])
        if prints.get(key, 0) < int(settings.voice_prints_max):
            _quiet(gapi.enroll_speaker, key, job_id, speaker_index=int(sp["rawIndex"]), account=account)


def sweep(store: MeetingStore | None = None, gapi: Any = None, *, budget: float | None = None,
          limit: int | None = None, fresh: int | None = None, force: bool = False) -> dict[str, int]:
    """Oxirgi 30 kun MEHMONLARI xodimlar maydonida qayta solishtiriladi: namunani yig'ilishdan KEYIN yozgan xodim
    o'sha yig'ilishda ham ismi bilan chiqsin. Yangi namunadan keyin ishlaydi (`_process`); `force` - hammasi
    (qo'lda tuzatish). Bitta vaqtda bitta tekshiruv. -> `{"checked", "adopted"}`."""
    if not _staff_tenant():
        return {"checked": 0, "adopted": 0}
    store = store if store is not None else _rt().store
    gapi = gapi if gapi is not None else _gapi()
    if not _sweep_lock.acquire(blocking=False):
        return {"checked": 0, "adopted": 0, "busy": 1}
    try:
        return _sweep(store, gapi, budget, limit, _fresh(store) if fresh is None else int(fresh), force)
    finally:
        _sweep_lock.release()


def _sweep(store: MeetingStore, gapi: Any, budget: float | None, limit: int | None, fresh: int,
           force: bool) -> dict[str, int]:
    started = time.monotonic()
    rows = store.rows(
        "SELECT s.person_id AS guest, s.meeting_id, s.id AS label, s.raw_index, s.talk_sec, m.stt_job_id, "
        "m.stt_account, m.audio_path, m.content_type, m.audio_deleted_at, m.id AS id "
        "FROM speakers s JOIN meetings m ON m.id = s.meeting_id JOIN voice_persons p ON p.id = s.person_id "
        "WHERE p.kind='guest' AND s.merged_into IS NULL AND s.raw_index IS NOT NULL AND m.stt_engine='gapi' "
        "AND m.stt_job_id IS NOT NULL AND m.created_at > ? ORDER BY m.created_at DESC",
        (_now() - _RETRO_DAYS * 86400,))
    groups: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(int(row["guest"]), []).append(row)
    checked = adopted = 0
    for guest, items in groups.items():
        if (limit is not None and checked >= limit) or (budget is not None and time.monotonic() - started > budget):
            break
        if not force and not _stale(store, guest, fresh):
            continue

        def playable_first(r: dict[str, Any]) -> tuple[int, float]:
            there = bool(r.get("audio_path")) and not r.get("audio_deleted_at") and Path(str(r["audio_path"])).is_file()
            return (1 if there else 0, float(r.get("talk_sec") or 0.0))

        best = max(items, key=playable_first)
        account = int(best.get("stt_account") or 1)
        try:
            if not _staff_people(store, gapi, account):
                continue
            link = store.row("SELECT speaker_key FROM voice_links WHERE person_id=? AND account=? LIMIT 1", (guest, account))
            clip = (_meeting_clip(best, str(best["label"]), store.segments(str(best["meeting_id"])))
                    or _voice_clip(gapi, account, (link or {}).get("speaker_key")))
            if clip is None:
                _checked(store, guest)
                continue
            checked += 1
            found, score = _probe(store, gapi, account, clip)
            if found is None:
                _checked(store, guest)
                continue
            jobs = [(str(r["stt_job_id"]), int(r["raw_index"])) for r in items if int(r.get("stt_account") or 1) == account]
            _adopt(store, gapi, account, found, guest=guest, voice_key=None, jobs=jobs)
        except SttError as exc:
            log.warning("Ovoz: mehmon #%d qayta solishtirilmadi - %s", guest, exc)
            if getattr(exc, "gapi_code", "") == "insufficient_balance":
                break
            continue
        _staff_learn(gapi, account, found, clip, score)
        adopted += 1
        log.info("Ovoz: mehmon #%d - xodim #%d (o'xshashlik %s), o'tgan yig'ilishlarga ism qo'yildi", guest, found, score)
    if checked:
        log.info("Ovoz: %d ta mehmon qayta solishtirildi, %d tasi xodim bo'lib chiqdi", checked, adopted)
    return {"checked": checked, "adopted": adopted}


# --- holat, o'chirish, qamrov ------------------------------------------------------------


def sample_view(row: dict[str, Any] | None) -> dict[str, Any]:
    if row is None:
        raise MeetingProblem(404, "sample_not_found", "Namuna topilmadi")
    status, reason = row["status"], row.get("reason")
    if status == "processing" and int(row["created_at"]) < _now() - STALE_SEC:
        status, reason = "failed", "interrupted"
    message = OK_TEXT if status == "ok" else ("⏳ Namuna tekshirilmoqda…" if status == "processing"
                                             else reason_text(reason))
    if status == "ok":
        gained = _retro_of(row)
        if gained:
            message += RETRO_TEXT.format(n=gained)
    return {"id": row["id"], "status": status, "reason": reason, "message": message,
            "speechSeconds": row.get("speech_sec"), "channel": row.get("channel"),
            "createdAt": int(row["created_at"]), "doneAt": row.get("done_at")}


def _retro_of(row: dict[str, Any]) -> int:
    """Shu namunadan keyin nechta o'tgan yig'ilishda ism qo'yilgani (`result_json.retro`)."""
    try:
        report = json.loads(row.get("result_json") or "{}")
        return int(((report or {}).get("retro") or {}).get("meetings") or 0)
    except (TypeError, ValueError, AttributeError):
        return 0


def _derived(path: Path) -> Path:
    """Namunaning pleer uchun nusxasi (ADTS -> m4a) - asl fayl yonida."""
    return path.with_name(f"{path.stem}.play.m4a")


def playable(row: dict[str, Any]) -> tuple[Path, str, str]:
    """Namuna -> (fayl, turi, nomi): pleer, Telegram va Slack o'ynata oladigan shakl. Mobil ilova yozgan ADTS
    (`audio/aac`) - bir marta m4a ga o'giriladi (`audio.adts_to_m4a`, ffmpeg siz; davomiylik va siljitish ishlaydi),
    qolganlari (Telegram OGG/Opus, m4a, mp3, wav) - o'zi."""
    path = Path(str(row.get("path") or ""))
    if not path.is_file():
        raise MeetingProblem(404, "audio_missing", "Namuna audiosi topilmadi")
    kind = str(row.get("content_type") or "")
    if kind == "audio/aac":
        target = _derived(path)
        if not target.is_file():
            tmp = target.with_name(target.name + ".part")
            try:
                private_file(tmp)
                audio.adts_to_m4a(path, tmp)
                tmp.replace(target)
            except Exception as exc:  # noqa: BLE001 - o'girilmasa asl ADTS beriladi (ko'p pleer uni ham o'qiydi)
                remove_file(tmp)
                log.info("Ovoz namunasi m4a ga o'girilmadi (%s): %s", path.name, exc)
                return path, kind, "ovoz-namunasi.aac"
        return target, "audio/mp4", "ovoz-namunasi.m4a"
    return path, kind or "application/octet-stream", f"ovoz-namunasi{_EXT.get(kind, '.bin')}"


def sample_audio(user: AuthUser, sample_id: str) -> tuple[Path, str, str]:
    """Xodimning O'Z namunasi audiosi (eshitish uchun)."""
    row = _rt().store.row("SELECT * FROM voice_samples WHERE id=? AND actor_id=?", (sample_id, user.actorId))
    if row is None:
        raise MeetingProblem(404, "sample_not_found", "Namuna topilmadi")
    return playable(row)


def latest_ok(user: AuthUser) -> dict[str, Any] | None:
    """Oxirgi saqlangan (ok) namuna - Telegram va Slack'dagi «▶️ Namunani eshitish» uchun."""
    return _rt().store.row("SELECT * FROM voice_samples WHERE actor_id=? AND status='ok' "
                           "ORDER BY created_at DESC, rowid DESC LIMIT 1", (user.actorId,))


#: Kanal kodi -> xodimga ko'rinadigan nom.
CHANNELS = {"mobile": "mobil ilova", "telegram": "Telegram", "slack": "Slack", "web": "veb", "miniapp": "Mini App",
            "desktop": "kompyuter", "api": "ilova"}


def sample_caption(row: dict[str, Any]) -> str:
    """"🗣 Ovoz namunangiz - mobil ilova, 18.11.2026 12:33, 25 s" (Toshkent vaqti)."""
    from datetime import datetime, timedelta, timezone

    when = datetime.fromtimestamp(int(row["created_at"]), timezone(timedelta(hours=5))).strftime("%d.%m.%Y %H:%M")
    speech = f", {round(float(row['speech_sec']))} s nutq" if row.get("speech_sec") else ""
    return f"🗣 Ovoz namunangiz - {CHANNELS.get(str(row.get('channel') or ''), row.get('channel') or '')}, {when}{speech}"


def sample(user: AuthUser, sample_id: str) -> dict[str, Any]:
    return sample_view(_rt().store.row("SELECT * FROM voice_samples WHERE id=? AND actor_id=?",
                                       (sample_id, user.actorId)))


def status(user: AuthUser) -> dict[str, Any]:
    """Xodimning ovoz namunasi holati + tartib va matn (`instructions`)."""
    store = _rt().store
    person = store.row("SELECT * FROM voice_persons WHERE actor_id=?", (user.actorId,))
    voices = int(store.scalar("SELECT COUNT(*) FROM voice_links WHERE person_id=?", (person["id"],), 0)) if person else 0
    rows = store.rows("SELECT * FROM voice_samples WHERE actor_id=? ORDER BY created_at DESC, rowid DESC LIMIT 50",
                      (user.actorId,))
    ok = [r for r in rows if r["status"] == "ok"]
    return {"enabled": bool(settings.voice_samples_enabled), "enrolled": bool(person and voices and ok),
            "personId": int(person["id"]) if person else None, "name": (person or {}).get("name"),
            "samples": len(ok), "lastSampleAt": ok[0].get("done_at") if ok else None,
            "latest": sample_view(rows[0]) if rows else None,
            # Saqlangan namunalar (eshitish uchun), eng yangisi birinchi - qaysi kanaldan yozilgan bo'lsa ham.
            "items": [sample_view(r) for r in ok[:10]], "instructions": instructions()}


def delete(user: AuthUser) -> dict[str, Any]:
    """Xodimning ovozi: GAPI dagi ovozlar (har hisobda), bog'lanishlar va namuna audiolari o'chadi.
    Eski yig'ilishlardagi ism qoladi (o'sha paytdagi to'g'ri yozuv)."""
    store = _rt().store
    gapi = _gapi()
    person = store.row("SELECT * FROM voice_persons WHERE actor_id=?", (user.actorId,))
    removed = 0
    if person is not None:
        for link in store.rows("SELECT * FROM voice_links WHERE person_id=?", (person["id"],)):
            if not str(link["speaker_key"]).startswith("n:"):
                try:
                    gapi.delete_speaker(link["speaker_key"], account=int(link["account"]))
                except SttError as exc:
                    log.warning("Ovozni GAPI dan o'chirib bo'lmadi: %s", exc)
                    raise MeetingProblem(503, "stt_unavailable", "Ovoz xizmati hozir javob bermadi - "
                                         "birozdan keyin qayta urinib ko'ring") from exc
            store.execute("DELETE FROM voice_links WHERE account=? AND speaker_key=?",
                          (link["account"], link["speaker_key"]))
            removed += 1
        _staff_remove(gapi, int(person["id"]))
    samples = store.rows("SELECT id, path FROM voice_samples WHERE actor_id=?", (user.actorId,))
    for s in samples:
        remove_file(s.get("path"))
        if s.get("path"):
            remove_file(_derived(Path(s["path"])))
    store.execute("DELETE FROM voice_samples WHERE actor_id=?", (user.actorId,))
    log.info("Ovoz namunasi o'chirildi (%s): %d ovoz, %d namuna", user.actorId, removed, len(samples))
    return {"deleted": removed, "samples": len(samples), "message": DELETED_TEXT}


def coverage() -> dict[str, Any]:
    """Kim namuna yozgan, kim yo'q (ADMIN). "Yo'q" ro'yxati - Barno'ga BRB-Tech ID bilan kirgan xodimlar."""
    store = _rt().store
    enrolled = store.rows(
        "SELECT p.id, p.actor_id, p.name, "
        "(SELECT COUNT(*) FROM voice_links l WHERE l.person_id = p.id) AS voices, "
        "(SELECT COUNT(*) FROM voice_samples s WHERE s.actor_id = p.actor_id AND s.status = 'ok') AS samples, "
        "(SELECT MAX(done_at) FROM voice_samples s WHERE s.actor_id = p.actor_id AND s.status = 'ok') AS last_at "
        "FROM voice_persons p WHERE p.kind = 'employee' ORDER BY p.name")
    enrolled = [e for e in enrolled if e["voices"] and e["samples"]]
    done = {int(e["actor_id"]) for e in enrolled if e["actor_id"] is not None}
    missing: list[dict[str, Any]] = []
    try:
        from ...api.deps import get_identity_store

        identities = get_identity_store()
        for actor_id in sorted(identities.actor_ids()):
            if actor_id in done:
                continue
            found = identities.by_actor_id(actor_id)
            if found is not None:
                missing.append({"actorId": actor_id, "name": found.to_public().fullName})
    except Exception:  # noqa: BLE001 - ro'yxat qo'shimcha; asosiy javob baribir
        log.exception("Ovoz qamrovi: xodimlar ro'yxati o'qilmadi")
    guests = int(store.scalar("SELECT COUNT(*) FROM voice_persons WHERE kind='guest'", (), 0))
    return {"enrolled": [{"personId": e["id"], "actorId": e["actor_id"], "name": e["name"], "voices": e["voices"],
                          "samples": e["samples"], "lastSampleAt": e["last_at"]} for e in enrolled],
            "missing": sorted(missing, key=lambda m: str(m["name"] or "")), "guests": guests}


def stats(store: MeetingStore) -> dict[str, Any]:
    """`/api/health/detail` uchun - sonlar, ismsiz."""
    try:
        return {"employees": int(store.scalar("SELECT COUNT(DISTINCT person_id) FROM voice_links l JOIN voice_persons p "
                                              "ON p.id = l.person_id WHERE p.kind='employee'", (), 0)),
                "guests": int(store.scalar("SELECT COUNT(*) FROM voice_persons WHERE kind='guest'", (), 0)),
                "samplesOk": int(store.scalar("SELECT COUNT(*) FROM voice_samples WHERE status='ok'", (), 0))}
    except Exception:  # noqa: BLE001
        return {}
