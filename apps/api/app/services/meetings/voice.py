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

OVOZ IZI bizda yo'q (GAPI uni hech qachon bermaydi). Namuna AUDIOSI saqlanadi (`<meetings_dir>/voice/`, 700/600):
2-bosqichda (o'z modelimiz) xodimlardan qayta yozdirmaslik uchun. Xodim ovozini o'chirsa - audio ham o'chadi.
"""

from __future__ import annotations

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
        key, voice_no, _ = _key(identity)
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
    store.execute("UPDATE voice_samples SET status=?, reason=?, speech_sec=?, person_id=?, result_json=?, done_at=? "
                  "WHERE id=?", (status, reason, speech, person_id, jdump(report), _now(), sid))
    if status == "ok" and person_id is not None:
        _backfill(store, person_id)
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


# --- holat, o'chirish, qamrov ------------------------------------------------------------


def sample_view(row: dict[str, Any] | None) -> dict[str, Any]:
    if row is None:
        raise MeetingProblem(404, "sample_not_found", "Namuna topilmadi")
    status, reason = row["status"], row.get("reason")
    if status == "processing" and int(row["created_at"]) < _now() - STALE_SEC:
        status, reason = "failed", "interrupted"
    message = OK_TEXT if status == "ok" else ("⏳ Namuna tekshirilmoqda…" if status == "processing"
                                             else reason_text(reason))
    return {"id": row["id"], "status": status, "reason": reason, "message": message,
            "speechSeconds": row.get("speech_sec"), "channel": row.get("channel"),
            "createdAt": int(row["created_at"]), "doneAt": row.get("done_at")}


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
