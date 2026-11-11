"""Chat botlari (Slack, Telegram) uchun yig'ilish quvurining umumiy qadamlari.

Qadamlar HTTP shartnomasi bilan AYNI (`api/v1/meetings.py`), faqat jarayon ichida:
yaratish -> bo'laklab yuklash -> yakunlash -> fon ishchisi o'giradi -> txt eksport ->
xulosani kutish. Transkript `summarizing` holatidayoq tayyor (`service.meeting_view`).
Faylni QAYERDAN olish va natijani QAYERGA yozish - har botning o'zida
(`app/slack/`, `app/bot/plaud.py`).

BITTA FAYL - BITTA YIG'ILISH. Kalit (`clientId`) bot faylining id'sidan yasaladi: fayl
qayta kelsa ("Qayta urinish", xabar takror keldi) - o'sha yig'ilish davom ettiriladi va
GAPI qayta to'lanmaydi.

JARAYON XABARI (`Progress`, ega talabi 2026-11-05: audio yozgan yoki yuklagan odam "vazifam
bajarilyaptimi o'zi" deb bilmay qolardi). Audio kelishi bilan bitta xabar: nima qabul qilindi
va uch bosqich - audio yuklash, matnga o'girish (foizi bilan), qisqa xulosa. Xabar joyida
yangilanadi; transkript chiqqach uning OSTIGA ko'chadi, natija (yoki xato) chiqqach o'chiriladi.
Matn ikkala botda bir xil (`steps`), xabarni yuborish va tahrirlash - botning o'zida.
"""

from __future__ import annotations

import logging
import re
import time
import urllib.parse
import uuid

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ...core.config import settings
from ...schemas import meetings as schemas
from ...schemas.auth import AuthUser
from . import export, service

log = logging.getLogger(__name__)

Sleep = Callable[[float], None]

#: Transkript shuncha kutiladi; keyin odamga "juda uzoq" deyiladi (yozuv esa hisobning
#: yig'ilishlar ro'yxatida o'girilaveradi).
WAIT_SEC = 3600
#: Xulosa shuncha kutiladi; keyin tugmalar xulosasiz chiqadi.
SUMMARY_WAIT_SEC = 600
#: Til - yig'ilishlar default'i. Boshqa til - "qayta o'girish" tugmasi.
LANGUAGE = "uz"
#: Jarayon xabarining bosqichlari (`steps`). `QUEUED` - bir xabardagi keyingi fayl: oldingisi
#: tugashini kutadi (fayllar ketma-ket o'giriladi).
QUEUED, UPLOAD, TRANSCRIBE, SUMMARY = "queued", "upload", "transcribe", "summary"
#: Faqat foiz o'zgarsa jarayon xabari shundan tez-tez tahrirlanmaydi (Slack va Telegram chegaralari).
PROGRESS_EVERY = 5.0
#: Xizmatda o'girish foizi 5 dan 80 gacha boradi (`transcribe.py`: 5 + 75 * tayyor ulush).
_STT_FROM, _STT_SPAN = 5.0, 75.0


class Problem(Exception):
    """Odamga botda ko'rsatiladigan sabab. `retry` - "Qayta urinish" tugmasi foyda
    beradimi (tarmoq, vaqt, server restarti) yoki befoydami (format, sozlama, hajm)."""

    def __init__(self, message: str, *, retry: bool = False) -> None:
        super().__init__(message)
        self.retry = retry


def client_id(namespace: str, file_id: str) -> str:
    """Bot fayli -> yig'ilish kaliti (`CreateMeetingRequest.clientId`, UUID)."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{namespace}:{file_id}"))


def meeting_of(user: AuthUser, client: str) -> str | None:
    found = service.runtime().store.by_client(user.actorId, client)
    return found["id"] if found else None


def resume(user: AuthUser, meeting_id: str) -> bool:
    """Oldin kelgan fayl: `True` - yig'ilish bor, davom etiladi (xato bergani `service.retry`
    bilan); `False` - yarim yuklangan, qolgan joyidan yuklash kerak."""
    view = service.detail(user, meeting_id)
    if view["status"] == "failed":
        error = view.get("error") or {}
        if not error.get("retryable"):
            raise Problem(error.get("message") or "Yozuvni o'girib bo'lmadi.")
        service.retry(user, meeting_id)
        return True
    return view["status"] != "uploading"


def upload(user: AuthUser, client: str, path: Path, size: int, sha: str, kind: str, *, title: str,
           recorded_at: float, channel: str = "api", source: str = "share", origin: str | None = None) -> str:
    """Yig'ilish yaratadi (yoki oldingisini oladi), audioni bo'laklab beradi va yakunlaydi.
    `origin` - Plaud filtri uchun manba (`slack`, `telegram`): `channel` uni har doim aytmaydi."""
    body = schemas.CreateMeetingRequest(
        clientId=client, title=title[:120], recordedAt=iso(recorded_at),
        language=LANGUAGE, contentType=kind, source=source)
    view = service.create(user, body, channel, origin=origin)[0]
    meeting_id = view["id"]
    # Oldingi urinish yarim qolgan bo'lsa - qolgan joyidan (`append_chunk` faqat shuni qabul qiladi).
    offset = int(view["upload"]["receivedBytes"])
    with open(path, "rb") as fh:
        fh.seek(offset)
        while data := fh.read(int(settings.meetings_chunk_bytes)):
            offset = int(service.append_chunk(user, meeting_id, offset, data, None)["receivedBytes"])
    service.complete(user, meeting_id, schemas.CompleteRequest(totalBytes=size, sha256=sha))
    return meeting_id


def wait_transcript(user: AuthUser, meeting_id: str, *, sleep: Sleep = time.sleep,
                    progress: Callable[[dict[str, Any]], None] | None = None) -> str:
    """Transkript tayyor bo'lguncha kutadi va matnini qaytaradi: txt eksport, vaqt
    belgilarisiz, spiker nomlari faqat bir nechta spiker bo'lsa. `progress` - har so'rovdagi
    holat (jarayon xabari, `Progress.view`)."""
    deadline = time.monotonic() + WAIT_SEC
    while True:
        view = service.detail(user, meeting_id)
        if progress is not None:
            progress(view)
        if view["transcript"]["available"]:
            break
        if view["status"] == "waiting_quota":
            # Yozuv ertaga o'girilardi, lekin natijasi chatga hech qachon yetib
            # bormaydi - ertangi limitni behuda yemasin.
            service.delete(user, meeting_id)
            raise Problem("Bugungi transkripsiya limiti tugagan - audioni ertaga qayta yuboring.")
        if view["status"] == "failed":
            error = view.get("error") or {}
            raise Problem(error.get("message") or "Yozuvni o'girib bo'lmadi.", retry=bool(error.get("retryable")))
        if time.monotonic() > deadline:
            raise Problem("Matnga o'girish juda uzoq cho'zildi.", retry=True)
        sleep(poll_interval(view))
    text, _, _ = service.export_transcript(user, meeting_id, "txt",
                                           with_speakers=len(view.get("speakers") or []) > 1,
                                           with_timestamps=False)
    return text.strip()


def wait_summary(user: AuthUser, meeting_id: str, *, sleep: Sleep = time.sleep) -> dict[str, Any]:
    """Asosiy xulosa yozilib bo'lguncha (yoki chegaragacha) kutadi - so'nggi holat."""
    deadline = time.monotonic() + SUMMARY_WAIT_SEC
    while True:
        view = service.detail(user, meeting_id)
        if view["status"] != "summarizing" and view["summaryStatus"] not in ("queued", "running"):
            return view
        if time.monotonic() > deadline:
            return view
        sleep(poll_interval(view))


def wait_summary_card(user: AuthUser, meeting_id: str, summary_id: str, *,
                      sleep: Sleep = time.sleep) -> dict[str, Any]:
    deadline = time.monotonic() + SUMMARY_WAIT_SEC
    while True:
        card = next((s for s in service.summaries(user, meeting_id)["items"] if s["id"] == summary_id), None)
        if card is None:
            raise Problem("Xulosa topilmadi.")
        if card["status"] not in ("queued", "running") or time.monotonic() > deadline:
            return card
        sleep(5.0)


def summary_error(user: AuthUser, meeting_id: str) -> str | None:
    for card in service.summaries(user, meeting_id)["items"]:
        if card["primary"] and card.get("error"):
            return card["error"].get("message")
    return None


def brief_markdown(user: AuthUser, meeting_id: str, *, summary_id: str | None = None,
                   parts: str = "brief") -> str:
    """"Qisqa xulosa" - mobil kartadagi bilan AYNI matn (`export_meeting(parts="brief")`)."""
    data, _, _ = service.export_meeting(user, meeting_id, "md", parts=parts, summary_id=summary_id)
    return data.decode("utf-8")


def poll_interval(view: dict[str, Any]) -> float:
    """Keyingi so'rov - xizmat aytgan `pollAfterSec`, 2-30 s oralig'ida."""
    return min(max(float(view.get("pollAfterSec") or 5), 2.0), 30.0)


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def filename(disposition: str | None) -> str | None:
    """`Content-Disposition` -> fayl nomi (`filename*=UTF-8''...` ustun)."""
    value = disposition or ""
    found = re.search(r"filename\*=UTF-8''([^;]+)", value, re.IGNORECASE)
    if found:
        return urllib.parse.unquote(found.group(1).strip())
    found = re.search(r'filename="([^"]+)"', value)
    return found.group(1) if found else None


# --- jarayon xabari ---------------------------------------------------------------------------


def steps(stage: str, *, duration: float | None = None, percent: int | None = None,
          transcript_above: bool = True) -> str:
    """Jarayon xabarining tanasi: bosqichlar va oxirgi qator. Belgilashsiz sodda matn - Slack
    mrkdwn va Telegram HTML uchun bir xil (fayl nomi kabi qochiriladigan narsa yo'q).
    `transcript_above` - bot transkriptni chatga yozadimi (Telegram - ha; Slack 2026-11-11 dan - yo'q,
    u faylda: "📥 Transkriptni yuklab olish")."""
    if stage == QUEUED:
        upload_line = "⏳ Navbatda - oldingi audio tugagach boshlanadi"
    elif stage == UPLOAD:
        upload_line = "⏳ Audio yuklanmoqda…"
    else:
        upload_line = "✅ Audio yuklandi" + (f" ({export.brief_duration(duration, 'uz')})" if duration else "")
    if stage == TRANSCRIBE:
        text_line = "⏳ Matnga o'girilmoqda…" + (f" {percent}%" if percent else "")
    elif stage == SUMMARY:
        text_line = "✅ Matnga o'girildi" + (" - matn yuqorida" if transcript_above else "")
    else:
        text_line = "◻️ Matnga o'girish"
    summary_line = "⏳ Qisqa xulosa yozilmoqda…" if stage == SUMMARY else "◻️ Qisqa xulosa"
    if stage == SUMMARY:
        tail = "Xulosa tayyor bo'lishi bilan shu yerga keladi."
    elif stage == QUEUED:
        tail = "Natija shu yerga keladi."
    else:
        tail = "Natija shu yerga keladi - odatda 1-3 daqiqada."
    return f"{upload_line}\n{text_line}\n{summary_line}\n\n{tail}"


def percent_of(view: dict[str, Any]) -> int | None:
    """O'girish bosqichining foizi (1-99); xizmat hali aytmagan bo'lsa `None`."""
    value = view.get("progress")
    if view.get("status") != "transcribing" or value is None:
        return None
    done = int((float(value) - _STT_FROM) / _STT_SPAN * 100)
    return done if 0 < done < 100 else None


class Progress:
    """Bitta audioning jarayon xabari: sarlavha (nima qabul qilindi - bot formatida, qochirilgan)
    va `steps`.

    `show(ref, text)` - botning o'zi: `ref` yo'q bo'lsa yangi xabar yuboradi va uning id'sini
    qaytaradi (yuborilmasa `None`), bor bo'lsa tahrirlaydi; `drop(ref)` - o'chiradi. Bot xatosi
    (tarmoq, chegara) audio ishini TO'XTATMAYDI - jurnalda ogohlantirish, xolos."""

    def __init__(self, head: str, *, show: Callable[[Any, str], Any], drop: Callable[[Any], None],
                 clock: Callable[[], float] = time.monotonic, transcript_above: bool = True) -> None:
        self.head = head
        self._show, self._drop, self._clock = show, drop, clock
        self.transcript_above = transcript_above
        self.ref: Any = None
        self.duration: float | None = None
        self._text = self._stage = ""
        self._at = 0.0

    def show(self, stage: str, percent: int | None = None) -> None:
        body = steps(stage, duration=self.duration, percent=percent, transcript_above=self.transcript_above)
        text = f"{self.head}\n\n{body}"
        now = self._clock()
        if text == self._text or (stage == self._stage and now - self._at < PROGRESS_EVERY):
            return
        try:
            ref = self._show(self.ref, text)
        except Exception as exc:  # noqa: BLE001 - xabar yangilanmasa ham audio ishi davom etadi
            log.warning("Jarayon xabari yangilanmadi (%s)", type(exc).__name__)
            return
        if ref is not None:
            self.ref, self._text, self._stage, self._at = ref, text, stage, now

    def view(self, view: dict[str, Any]) -> None:
        """`wait_transcript` ning har so'rovi: davomiylik, bosqich va foiz - xizmat holatidan."""
        if view.get("durationSec"):
            self.duration = float(view["durationSec"])
        if view.get("status") in ("uploaded", "transcribing"):
            self.show(TRANSCRIBE, percent_of(view))

    def close(self) -> None:
        """Xabarni o'chiradi (natija yoki xato chiqdi). Keyingi `show` - yangi xabar."""
        ref, self.ref, self._text, self._stage = self.ref, None, "", ""
        if ref is None:
            return
        try:
            self._drop(ref)
        except Exception as exc:  # noqa: BLE001
            log.warning("Jarayon xabari o'chirilmadi (%s)", type(exc).__name__)
