"""Yig'ilish testlari uchun soxtalar: GAPI (asinxron vazifalar), Router, model va audio.

Hech biri tarmoqqa chiqmaydi. `FakeLLM` javobini promptdagi transkript
qatorlaridan O'ZI yasaydi (`auto_reply`) - shuning uchun oxiridan-oxirigacha
testlar har chaqiruvni qo'lda yozmasdan ishlaydi; maxsus holat kerak bo'lsa
`script[op]` ga javoblar navbati qo'yiladi.
"""

from __future__ import annotations

import hashlib
import json
import re
import struct
import uuid

from typing import Any, Callable

from app.services.integrations.ollama import OllamaError
from app.services.meetings import audio
from app.services.stt import SttError, Transcript

LINE = re.compile(r"^#(\d+) \[[^\]]+\] (S\d+|\?)(?: \((?!CONTEXT ONLY\))([^)]*)\))?( \(CONTEXT ONLY\))?: (.*)$")


def adts_bytes(seconds: float, *, payload: int = 90) -> bytes:
    """Sintetik ADTS (16 kHz mono): `seconds` davomiylikka yetadigan kadrlar."""
    frames = max(1, int(round(seconds * 16000 / 1024)))
    return b"".join(audio.adts_frame(payload + (i % 5)) for i in range(frames))


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def gapi_segments(lines: list[tuple[Any, float, float, str]]) -> list[dict[str, Any]]:
    return [{"speaker": spk, "start": start, "end": end, "text": text} for spk, start, end, text in lines]


DEFAULT_RESULT = {
    "audio_seconds": 64.0,
    "language": {"code": "uz", "share": {"uz": 0.9, "ru": 0.1}},
    "diarization_error": False,
    "segments": gapi_segments([
        (0, 0.0, 6.0, "Assalomu alaykum, bugun hisobot bo'yicha yig'ildik, boshlaymiz."),
        (1, 6.5, 14.0, "Men ertaga hisobotni tayyorlab yuboraman, Aziz aka."),
        (0, 14.5, 22.0, "Yaxshi, unda narxni 15 mln so'm qilib belgilashga kelishdik."),
        (1, 22.5, 30.0, "Mayli, juma kuni mijoz bilan gaplashaman va natijani aytaman."),
        (0, 30.5, 40.0, "Keyingi yig'ilish seshanba kuni soat 10:00 da bo'ladi, hammaga rahmat."),
        (2, 40.5, 50.0, "Men ham dizaynni chorshanbagacha tekshirib chiqaman, savol bo'lsa yozing."),
        (1, 50.5, 63.0, "Byudjet masalasi hali ochiq, buxgalteriya javob bermadi, kutamiz."),
    ]),
}


class FakeGapiMeeting:
    """`GapiSttClient` ning yig'ilish metodlari. `states` - `get_job` ketma-ketligi."""

    def __init__(self) -> None:
        self.configured = True
        self.submits: list[dict[str, Any]] = []
        self.polls = 0
        self.states: list[Any] = ["processing", "done"]
        self.result: Any = json.loads(json.dumps(DEFAULT_RESULT))
        self.submit_error: SttError | None = None
        self.poll_error: SttError | None = None
        self.result_errors: list[SttError] = []
        self.jobs_list: list[dict[str, Any]] = []
        self.usage_payload: dict[str, Any] = {"available_g": 400.0, "topup_target_g": 480.0}
        self.cancelled: list[str] = []
        self.noted = 0.0
        #: Hisoblar (1 - `GAPI_API_KEY`, 2 - `GAPI_API_KEY2`): har birining balansi
        #: (`usage_by_account`, bo'lmasa `usage_payload`), yuborishda balansi yetmaydiganlari
        #: (`no_balance` - `429 insufficient_balance`) va ishchi "tugadi" deb belgilaganlari.
        self.accounts: list[int] = [1]
        self.usage_by_account: dict[int, dict[str, Any]] = {}
        self.no_balance: set[int] = set()
        self.empty: set[int] = set()
        #: Har so'rov qaysi hisob bilan ketgani: `(amal, hisob)`.
        self.account_calls: list[tuple[str, int]] = []

    def usable_accounts(self):
        return [a for a in self.accounts if a not in self.empty]

    def mark_out_of_balance(self, account):
        self.empty.add(account)

    def submit_job(self, path, content_type, settings, *, account=1):
        self.account_calls.append(("submit", account))
        if self.submit_error is not None:
            raise self.submit_error
        if account in self.no_balance:
            raise gapi_error(429, "insufficient_balance", retryable=True)
        with open(path, "rb") as fh:
            size = len(fh.read())
        job_id = f"job-{len(self.submits) + 1}"
        self.submits.append({"path": str(path), "contentType": content_type, "settings": dict(settings),
                             "size": size, "id": job_id, "account": account})
        return {"id": job_id, "state": "queued", "estimatedSeconds": 64.0,
                "resultUrl": f"https://gapi.test/v1/jobs/{job_id}/result"}

    def get_job(self, job_id, *, account=1):
        self.account_calls.append(("job", account))
        self.polls += 1
        if self.poll_error is not None:
            raise self.poll_error
        state = self.states.pop(0) if self.states else "done"
        if isinstance(state, dict):
            return state
        return {"id": job_id, "state": state, "progress_seconds": 32.0, "audio_seconds": 64.0}

    def get_result(self, job_id, result_url=None, *, account=1):
        self.account_calls.append(("result", account))
        if self.result_errors:
            raise self.result_errors.pop(0)
        return self.result

    def list_jobs(self, limit=20, *, account=1):
        self.account_calls.append(("list", account))
        return list(self.jobs_list)

    def cancel_job(self, job_id, *, account=1):
        self.account_calls.append(("cancel", account))
        self.cancelled.append(job_id)
        return True

    def usage(self, *, account=1):
        self.account_calls.append(("usage", account))
        return dict(self.usage_by_account.get(account, self.usage_payload))

    def note_meeting_audio(self, seconds):
        self.noted += seconds

    def spend(self):
        return {"day": "2026-10-09", "audio_sec": self.noted, "calls": len(self.submits), "sent": len(self.submits)}


def gapi_error(status: int, code: str = "", *, retryable: bool = False, retry_after: float | None = None) -> SttError:
    err = SttError(f"GAPI {status} {code}", status=502 if status in (401, 403) else status, retryable=retryable)
    err.gapi_status = status
    err.gapi_code = code
    if retry_after:
        err.retry_after = retry_after
    return err


class FakeRouter:
    def __init__(self, text: str = "Добрый день. Обсудим бюджет! Я пришлю отчёт завтра.") -> None:
        self.text = text
        self.calls: list[dict[str, Any]] = []

    def transcribe(self, data: bytes, *, language: str, content_type: str = "audio/aac", budget=None):
        self.calls.append({"size": len(data), "language": language, "contentType": content_type})
        return Transcript(text=self.text, language=language, backend="fake")


# --- model --------------------------------------------------------------------------


def parse_lines(user: str) -> list[dict[str, Any]]:
    """Promptdagi `#id [vaqt] S1 (Ism): matn` qatorlari."""
    out = []
    for raw in user.splitlines():
        found = LINE.match(raw.strip())
        if found:
            out.append({"id": int(found.group(1)), "speaker": None if found.group(2) == "?" else found.group(2),
                        "name": found.group(3), "context": bool(found.group(4)), "text": found.group(5)})
    return out


def _quote(text: str) -> str:
    return " ".join(text.split()[:6])


def _items(lines: list[dict[str, Any]]) -> dict[str, Any]:
    own = [x for x in lines if not x["context"]]
    if not own:
        return {}
    first, last = own[0], own[-1]
    return {
        "coverage": {"firstId": first["id"], "lastId": last["id"]},
        "participants": [{"speaker": x["speaker"], "suggestedName": None, "nameEvidence": [], "role": None}
                         for x in own if x["speaker"]][:1],
        "topics": [{"title": f"Mavzu {first['id']}", "summary": "Muhokama.", "outcome": "decided",
                    "startId": first["id"], "endId": last["id"],
                    "keyPoints": [{"text": "Asosiy fikr", "sourceSegmentIds": [first["id"]]}]}],
        "keyPoints": [{"text": f"Fikr {first['id']}", "sourceSegmentIds": [first["id"]]}],
        "decisions": [{"text": f"Qaror {last['id']}", "status": "final", "condition": None, "rationale": None,
                       "proposedBy": [last["speaker"]] if last["speaker"] else [], "agreedBy": [],
                       "quote": _quote(last["text"]), "sourceSegmentIds": [last["id"]]}],
        "actionItems": [{"task": f"Vazifa {first['id']}ni bajarish", "deliverable": None,
                         "owner": {"speaker": first["speaker"], "name": None, "kind": "person",
                                   "basis": "self_commitment"},
                         "assignedBy": None, "due": {"raw": None, "date": None, "time": None, "basis": "none"},
                         "priority": "normal", "status": "open", "origin": "explicit",
                         "quote": _quote(first["text"]), "confidence": 0.9,
                         "sourceSegmentIds": [first["id"]], "ref": None}],
        "openQuestions": [], "risks": [], "numbers": [], "dates": [], "nextSteps": [],
        "nextMeeting": None, "highlights": [], "templateSections": [],
    }


def auto_reply(op: str, system: str, user: str) -> str:
    lines = parse_lines(user)
    if op == "meeting_classify":
        return json.dumps({"template": "general", "confidence": 0.9})
    if op == "meeting_extract":
        data = _items(lines)
        data.update({"title": "Hisobot yig'ilishi", "meetingType": {"value": "general", "confidence": 0.8},
                     "overview": "[S1] va [S2] hisobotni muhokama qildi. Qaror qabul qilindi. Keyingi qadamlar belgilandi.",
                     "purpose": "Hisobot", "keywords": ["hisobot"],
                     "sentiment": {"overall": "neutral", "note": None, "sourceSegmentIds": []}})
        if "followUpMessage" in system:
            data["followUpMessage"] = {"subject": "Yig'ilish yakuni", "body": "Rahmat!\n[S1] hisobotni yuboradi."}
        return json.dumps(data, ensure_ascii=False)
    if op == "meeting_map":
        data = _items(lines)
        data["chunkSummary"] = f"Bo'lak #{data['coverage']['firstId']}-#{data['coverage']['lastId']} muhokamasi."
        return json.dumps(data, ensure_ascii=False)
    if op == "meeting_write":
        ids = [int(x) for x in re.findall(r"#(\d+)", user)]
        return json.dumps({"title": "Uzun yig'ilish", "meetingType": {"value": "general", "confidence": 0.7},
                           "overview": "Uzun muhokama bo'ldi. Qarorlar qabul qilindi. Vazifalar taqsimlandi.",
                           "purpose": None, "keyPoints": [{"text": "Umumiy fikr", "sourceSegmentIds": ids[:1]}],
                           "topics": [], "keywords": ["reja"], "sentiment": None, "duplicateGroups": [],
                           "followUpMessage": None}, ensure_ascii=False)
    if op == "meeting_verify":
        refs = re.findall(r"^([AD]\d+) \|", user, flags=re.MULTILINE)
        return json.dumps({"results": [{"id": r, "supported": True, "ownerCorrect": True, "dueCorrect": True,
                                        "note": None} for r in refs]})
    if op == "meeting_minutes":
        return json.dumps(minutes_reply(lines, user), ensure_ascii=False)
    if op == "meeting_ask":
        first = lines[0]["id"] if lines else 1
        return json.dumps({"answer": "[S1] hisobotni ertaga yuboradi.", "citations": [first, 99999],
                           "followUps": ["Kim?", "Qachon?", "Nima?"]}, ensure_ascii=False)
    return "{}"


def minutes_reply(lines: list[dict[str, Any]], user: str) -> dict[str, Any]:
    """Bayonnoma JSON i (`shapes.minutes` shakli) - promptdagi chiqish tiliga mos yozuvda. Ikki
    kun tartibi bandi, ikki bo'lim, [S#] tokenli mas'ullar, bitta kichik bandli va "Bunda" li band."""
    own = [x for x in lines if not x["context"]] or [{"id": 1, "speaker": "S1", "text": ""}]
    first, last = own[0], own[-1]
    mid = own[len(own) // 2]
    spk = [x["speaker"] for x in own if x["speaker"]] or ["S1"]
    cyr = "Output language: Uzbek (Cyrillic" in user
    ru = "Output language: Russian" in user
    en = "Output language: English" in user
    if ru:
        t = {"a1": "О ходе исполнения плана", "a2": "О текущих вопросах", "r1": "Был заслушан отчёт [S1] о ходе работ.",
             "r2": "Обсуждены текущие вопросы.", "ack": "Отчёт принять к сведению.", "dl": "В течение двух дней",
             "task": "обеспечить подготовку отчёта.", "sub": "- уточнить сроки;", "fu": "При этом учесть замечания.",
             "ctl": "[S1]", "pre": "Принимая во внимание вышеизложенное, Совещание", "title": "Совещание по отчёту"}
    elif en:
        t = {"a1": "On the progress of the plan", "a2": "On current matters", "r1": "The report of [S1] was heard.",
             "r2": "Current matters were discussed.", "ack": "Take the report into account.", "dl": "Within two days",
             "task": "ensure the report is prepared.", "sub": "- clarify the deadlines;", "fu": "The remarks shall be considered.",
             "ctl": "[S1]", "pre": "Having considered the above, the Meeting", "title": "Report meeting"}
    elif cyr:
        t = {"a1": "Режа ижроси тўғрисида", "a2": "Жорий масалалар тўғрисида",
             "r1": "Кун тартибидаги биринчи масала юзасидан [S1] ҳисоботи эшитилди.",
             "r2": "Жорий масалалар муҳокама қилинди.", "ack": "ҳисоботи маълумот учун қабул қилинсин.",
             "dl": "Икки кун муддатда", "task": "ҳисобот тайёрлаш вазифаси юклатилсин.",
             "sub": "- муддатлар аниқлаштирилсин;", "fu": "Бунда, билдирилган эътирозлар инобатга олинсин.",
             "ctl": "[S1]", "pre": "Юқоридагиларни инобатга олиб, Йиғилиш", "title": "Ҳисобот йиғилиши"}
    else:
        t = {"a1": "Reja ijrosi to'g'risida", "a2": "Joriy masalalar to'g'risida",
             "r1": "Kun tartibidagi birinchi masala yuzasidan [S1] hisoboti eshitildi.",
             "r2": "Joriy masalalar muhokama qilindi.", "ack": "hisoboti ma'lumot uchun qabul qilinsin.",
             "dl": "Ikki kun muddatda", "task": "hisobot tayyorlash vazifasi yuklatilsin.",
             "sub": "- muddatlar aniqlashtirilsin;", "fu": "Bunda, bildirilgan e'tirozlar inobatga olinsin.",
             "ctl": "[S1]", "pre": "Yuqoridagilarni inobatga olib, Yig'ilish", "title": "Hisobot yig'ilishi"}
    item = lambda kind, text, **kw: {"kind": kind, "deadline": None, "deadlineDate": None, "responsible": [],  # noqa: E731
                                     "text": text, "subpoints": [], "followUp": None,
                                     "sourceSegmentIds": [first["id"]], "confidence": 0.9, **kw}
    return {
        "coverage": {"firstId": first["id"], "lastId": last["id"]},
        "title": t["title"],
        "agenda": [{"title": t["a1"], "speakers": spk[:1], "report": t["r1"], "sourceSegmentIds": [first["id"]]},
                   {"title": t["a2"], "speakers": spk[-1:], "report": t["r2"], "sourceSegmentIds": [mid["id"]]}],
        "preamble": t["pre"],
        "sections": [
            {"agendaIndex": 1, "items": [
                item("acknowledge", f"[{spk[0]}] {t['ack']}"),
                item("task", f"[{spk[-1]}] {t['task']}", deadline=t["dl"], responsible=[f"[{spk[-1]}]"],
                     subpoints=[t["sub"]], followUp=t["fu"], sourceSegmentIds=[mid["id"], last["id"]]),
            ]},
            {"agendaIndex": 2, "items": [item("task", t["task"], responsible=[], sourceSegmentIds=[last["id"]])]},
        ],
        "controller": t["ctl"],
        "notes": [],
    }


class FakeLLM:
    """`OllamaChat` o'rnida. `script[op]` - navbat: matn, `OllamaError` yoki
    `(matn, meta)`; bo'sh bo'lsa `auto_reply`."""

    def __init__(self, *, configured: bool = True) -> None:
        self.configured = configured
        self.model = "gemma4:31b"
        self.calls: list[dict[str, Any]] = []
        self.script: dict[str, list[Any]] = {}
        self.reply: Callable[[str, str, str], str] = auto_reply

    def complete_meta(self, system, user, *, num_predict=1200, temperature=0.2, op="group", format=None,
                      options=None):
        self.calls.append({"op": op, "system": system, "user": user, "temperature": temperature,
                           "num_predict": num_predict, "options": options})
        queue = self.script.get(op)
        if queue:
            item = queue.pop(0)
            if isinstance(item, BaseException):
                raise item
            if isinstance(item, tuple):
                return item
            return item, {"doneReason": "stop", "tokensIn": None, "tokensOut": 10}
        return self.reply(op, system, user), {"doneReason": "stop", "tokensIn": None, "tokensOut": 10}

    def ops(self) -> list[str]:
        return [c["op"] for c in self.calls]


def rate_limited() -> OllamaError:
    return OllamaError("Ollama HTTP 429", status=429)


def client_uuid() -> str:
    return str(uuid.uuid4())


# --- API yordamchilari ------------------------------------------------------------------


def enable(monkeypatch, *, logins: str = "") -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "meetings_enabled", True, raising=False)
    monkeypatch.setattr(settings, "meetings_logins", logins, raising=False)


def create_meeting(client, auth, **body) -> dict:
    payload = {"clientId": client_uuid(), "title": None, "recordedAt": "2026-10-09T06:00:00Z",
               "language": "uz", "template": "auto", "expectedSpeakers": None, "contentType": "audio/aac",
               "source": "launcher", "appVersion": "1.0.0", "device": "SM-S921B"}
    payload.update(body)
    response = client.post("/api/v1/meetings", json=payload, headers={**auth, "X-Venera-Client": "mobile"})
    assert response.status_code in (200, 201), response.text
    return response.json()


def put_chunk(client, auth, meeting_id: str, offset: int, data: bytes, *, with_sha: bool = True):
    headers = {**auth, "Content-Type": "application/octet-stream"}
    if with_sha:
        headers["X-Chunk-Sha256"] = sha(data)
    return client.put(f"/api/v1/meetings/{meeting_id}/audio?offset={offset}", content=data, headers=headers)


def upload_all(client, auth, meeting_id: str, data: bytes, chunk: int = 4096) -> None:
    for offset in range(0, len(data), chunk):
        response = put_chunk(client, auth, meeting_id, offset, data[offset:offset + chunk])
        assert response.status_code == 200, response.text


def complete(client, auth, meeting_id: str, data: bytes, **extra):
    body = {"totalBytes": len(data), "sha256": sha(data), "durationSec": 60.0,
            "endedAt": "2026-10-09T07:00:00Z", "marks": []}
    body.update(extra)
    return client.post(f"/api/v1/meetings/{meeting_id}/complete", json=body, headers=auth)


def recorded(client, auth, seconds: float = 64.0, **create) -> tuple[dict, bytes]:
    """Yaratish + yuklash + yakunlash -> (yig'ilish, audio)."""
    meeting = create_meeting(client, auth, **create)
    data = adts_bytes(seconds)
    upload_all(client, auth, meeting["id"], data, chunk=max(4096, len(data) // 3 + 1))
    response = complete(client, auth, meeting["id"], data)
    assert response.status_code == 202, response.text
    return response.json(), data


def worker(rt):
    from app.services.meetings.worker import Worker

    return Worker(rt)


def run_all(rt, now: float | None = None, rounds: int = 30) -> None:
    """Navbat bo'shaguncha (vaqt oldinga suriladi - so'rash oraliqlari o'tib ketsin)."""
    import time as _time

    w = worker(rt)
    moment = now if now is not None else _time.time()
    for _ in range(rounds):
        w.run_once(moment)
        moment += 15
        pending = rt.store.scalar(
            "SELECT COUNT(*) FROM meetings WHERE status IN ('uploaded','transcribing','summarizing')", (), 0)
        queued = rt.store.scalar("SELECT COUNT(*) FROM summaries WHERE status IN ('queued','running')", (), 0)
        if not pending and not queued:
            return


# --- v3 ("Venera Core") va OpenAI soxtalari ------------------------------------------------------


def v3_frames(text: str, *, engine: str = "v3", extra: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """v3 oqimi: stage, sources, (qo'shimcha kadrlar), matn bo'laklari, done (trace_id, task bilan)."""
    frames: list[dict[str, Any]] = [{"type": "stage", "text": "O'ylayapman"},
                                    {"type": "sources", "sources": [{"kind": "doc", "doc_id": "HR_1"}]}]
    frames += list(extra or [])
    frames += [{"type": "token", "text": text[i:i + 40]} for i in range(0, len(text), 40)]
    frames.append({"type": "done", "route": "agent", "engine": engine, "request_id": "up-1", "trace_id": "tr-1",
                   "task": {"state": "done"}})
    return frames


def v3_auto(op: str, question: str) -> list[dict[str, Any]]:
    """`auto_reply` javobi - v3 odatidek markdown ichida (```json ... ```)."""
    return v3_frames("Mana natija:\n```json\n" + auto_reply(op, question, question) + "\n```\nTayyor.")


class FakeAssistant:
    """`AssistantClient.stream` o'rnida. `script[op]` - navbat: kadrlar ro'yxati, istisno yoki
    `fn(question) -> kadrlar`; bo'sh bo'lsa `reply(op, question)` (default - `v3_auto`)."""

    def __init__(self, *, configured: bool = True) -> None:
        self.configured = configured
        self.calls: list[dict[str, Any]] = []
        self.script: dict[str, list[Any]] = {}
        self.reply: Callable[[str, str], list[dict[str, Any]]] = v3_auto
        self.closed = 0
        #: Birinchi kadrdan oldingi kutish (s) - "jim" v3 ni sinash uchun.
        self.delay = 0.0
        self.cancelled: list[dict[str, Any]] = []

    def cancel_action(self, token, *, user_id, tokens=None):
        self.cancelled.append({"token": token, "user_id": user_id, "tokens": dict(tokens or {})})
        return {"token": token, "status": "cancelled", "ok": True}

    def stream(self, question, *, user_id, chat_id=None, tokens=None, hrm_employee=None, max_chars=2000,
               mode="standard", engine="", op="stream"):
        from app.services.integrations.assistant import AnswerStream, AssistantError

        self.calls.append({"question": question, "user_id": user_id, "chat_id": chat_id, "tokens": dict(tokens or {}),
                           "max_chars": max_chars, "engine": engine, "op": op, "mode": mode})
        if len(question) > max_chars:
            raise AssistantError(f"savol juda uzun ({len(question)} > {max_chars})", status=400)
        queue = self.script.get(op)
        item = queue.pop(0) if queue else None
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            frames = item(question)
        elif item is not None:
            frames = item
        else:
            frames = self.reply(op, question)
        if isinstance(frames, BaseException):
            raise frames
        lines = [json.dumps(f, ensure_ascii=False).encode("utf-8") + b"\n" for f in frames]

        fake = self
        delay = self.delay

        def gen():
            import time as _time

            try:
                if delay:
                    _time.sleep(delay)
                yield from lines
            finally:
                fake.closed += 1

        return AnswerStream(request_id="req-1", frames=gen(), engine=engine)

    def ops(self) -> list[str]:
        return [c["op"] for c in self.calls]


class FakeOpenAI:
    """Mahalliy HTTP server - OpenAI `/v1/chat/completions` o'rnida (tarmoqqa chiqilmaydi).

    `responses` - navbat: `(status, payload)`; bo'sh bo'lsa so'rovdagi sxema nomi (`op`)
    bo'yicha `auto_reply` javobi qaytadi. Har so'rov `requests` da (yo'l, sarlavha, tana)."""

    def __init__(self) -> None:
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        self.requests: list[dict[str, Any]] = []
        self.responses: list[tuple[int, Any]] = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):                     # jim
                return

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                fake.requests.append({"path": self.path, "auth": self.headers.get("Authorization"),
                                      "body": body})
                status, payload = fake.responses.pop(0) if fake.responses else (200, fake.auto(body))
                raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                if payload == FakeOpenAI.TRUNCATED:
                    # Javob o'rtada uzildi: e'lon qilingan hajmdan kam bayt -> `http.client.IncompleteRead`.
                    self.send_header("Content-Length", str(len(raw) + 500))
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(raw)
                    self.wfile.flush()
                    self.close_connection = True
                    return
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05},
                                       daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}/v1"

    #: `responses` dagi maxsus javob: tana e'lon qilinganidan qisqa (uzilgan ulanish).
    TRUNCATED = {"truncated": True}

    @staticmethod
    def auto(body: dict[str, Any]) -> dict[str, Any]:
        fmt = body.get("response_format") or {}
        op = ((fmt.get("json_schema") or {}).get("name")) or "meeting_extract"
        messages = body.get("messages") or [{}, {}]
        content = auto_reply(op, messages[0].get("content", ""), messages[-1].get("content", ""))
        return completion(content)

    def ops(self) -> list[str]:
        return [((r["body"].get("response_format") or {}).get("json_schema") or {}).get("name") or "?"
                for r in self.requests]

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def completion(content: str, *, finish: str = "stop") -> dict[str, Any]:
    return {"id": "chatcmpl-1", "object": "chat.completion", "model": "gpt-test",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 1200, "completion_tokens": 340, "total_tokens": 1540}}


# --- OGG (Opus) sintetik fayl ---------------------------------------------------------


def _ogg_page(packets: list[bytes], *, granule: int, serial: int, sequence: int, flags: int = 0) -> bytes:
    from app.services.meetings.audio import ogg_crc

    table = bytearray()
    for packet in packets:
        size = len(packet)
        while size >= 255:
            table.append(255)
            size -= 255
        table.append(size)
    head = (b"OggS" + bytes([0, flags]) + struct.pack("<q", granule) + struct.pack("<I", serial)
            + struct.pack("<I", sequence) + b"\0\0\0\0" + bytes([len(table)]) + bytes(table) + b"".join(packets))
    page = bytearray(head)
    page[22:26] = struct.pack("<I", ogg_crc(bytes(page)))
    return bytes(page)


def ogg_opus_bytes(seconds: float, *, pre_skip: int = 312, frame_ms: int = 20, per_page: int = 50) -> bytes:
    """Ogg Opus: OpusHead + OpusTags + nol uzunlikdagi (sukut) kadrlar - har biri 1 bayt TOC
    (CELT FB, `frame_ms`, mono). Davomiylik `seconds` ga yaxlitlangan kadrlar soni."""
    samples = 48000 * frame_ms // 1000
    toc = bytes([(31 << 3)])                                   # config 31 = CELT fullband 20 ms, code 0
    head = (b"OpusHead" + bytes([1, 1]) + struct.pack("<H", pre_skip) + struct.pack("<I", 48000)
            + struct.pack("<h", 0) + bytes([0]))
    tags = b"OpusTags" + struct.pack("<I", 5) + b"barno" + struct.pack("<I", 0)
    frames = max(1, int(round(seconds * 1000 / frame_ms)))
    out = [_ogg_page([head], granule=0, serial=7, sequence=0, flags=0x02),
           _ogg_page([tags], granule=0, serial=7, sequence=1)]
    done, sequence = 0, 2
    while done < frames:
        take = min(per_page, frames - done)
        done += take
        last = done == frames
        out.append(_ogg_page([toc] * take, granule=pre_skip + done * samples, serial=7, sequence=sequence,
                             flags=0x04 if last else 0))
        sequence += 1
    return b"".join(out)


# --- Claude (Anthropic SDK) soxtasi -------------------------------------------------------------------


CLAUDE_MODEL = "claude-sonnet-5-5"


def claude_message(text: str, *, stop_reason: str = "end_turn", thinking: bool = True, tokens_in: int = 1200,
                   tokens_out: int = 340, model: str = CLAUDE_MODEL, cache_read: int | None = None,
                   cache_write: int | None = None) -> Any:
    """`anthropic.types.Message`: (default bo'sh "o'ylash" bloki +) matn bloki va `usage` - klient
    o'ylash blokini tashlab, faqat matnni olishi sinaladi. `stop_reason="refusal"` - rad,
    `"max_tokens"` - kesilgan javob. `cache_read` / `cache_write` - prompt keshi tokenlari (chat)."""
    from anthropic.types import Message, TextBlock, ThinkingBlock, Usage

    blocks: list[Any] = []
    if thinking:
        blocks.append(ThinkingBlock(type="thinking", thinking="", signature="sig"))
    blocks.append(TextBlock(type="text", text=text))
    return Message(id="msg_test", type="message", role="assistant", model=model, content=blocks,
                   stop_reason=stop_reason, stop_sequence=None,
                   usage=Usage(input_tokens=tokens_in, output_tokens=tokens_out, cache_read_input_tokens=cache_read,
                               cache_creation_input_tokens=cache_write))


def claude_error(kind: Any, status: int | None = None, message: str = "xato") -> Exception:
    """Anthropic SDK istisnosi: status xatolari (`anthropic.RateLimitError`, `BadRequestError`, ...) -
    `httpx2.Response` bilan, xabari SDK dagidek (`Error code: <status> - <tana>`); `APIConnectionError` /
    `APITimeoutError` - faqat `httpx2.Request` bilan (javob yo'q)."""
    import anthropic
    import httpx2

    request = httpx2.Request("POST", "https://api.anthropic.test/v1/messages")
    if issubclass(kind, anthropic.APIConnectionError):
        return kind(request=request) if kind is anthropic.APITimeoutError else kind(message=message, request=request)
    body = {"type": "error", "error": {"type": "api_error", "message": message}}
    response = httpx2.Response(status or 500, request=request, json=body)
    return kind(f"Error code: {status or 500} - {body}", response=response, body=body)


class FakeAnthropic:
    """`anthropic.Anthropic` o'rnida - `ClaudeChat(client_factory=fake)`.

    Klient ZAVODI sifatida chaqiriladi (`fake(api_key=..., base_url=..., timeout=..., max_retries=...)`
    -> o'zi; argumentlar `inits` da) va `messages.stream(**kwargs)` ni beradi: har so'rov `requests` da
    (kwargs aynan), natija - `with ... as stream: stream.get_final_message()`. `beta.messages.stream` (chatdagi
    rad-zahirasi) - o'sha `requests` ga, qo'shimcha `betas` / `fallbacks` kalitlari bilan.

    `script` - navbat: matn (-> `claude_message`), tayyor `Message`, istisno (`claude_error`) yoki
    `fn(kwargs) -> shulardan biri`; bo'sh bo'lsa so'rovdagi JSON sxemadan aniqlangan `op` bo'yicha
    `auto_reply` (`shapes.*` bilan solishtirib - `op_of`; chat sxemasi savol-javobniki - `meeting_ask`).
    Istisno real SDK dagidek `with` ga kirishda (`__enter__`) otiladi - so'rov o'shanda ketadi."""

    def __init__(self) -> None:
        self.inits: list[dict[str, Any]] = []
        self.requests: list[dict[str, Any]] = []
        self.script: list[Any] = []
        self.reply: Callable[[str, str, str], str] = auto_reply
        self.messages = _FakeClaudeMessages(self)
        self.beta = _FakeClaudeBeta(self)

    def __call__(self, **kwargs: Any) -> FakeAnthropic:
        self.inits.append(dict(kwargs))
        return self

    @staticmethod
    def op_of(request: dict[str, Any]) -> str:
        """So'rovdagi `output_config.format.schema` -> amal (`shapes.for_op` ning teskarisi);
        sxemasiz so'rov - `meeting_extract` (`FakeOpenAI` kabi); noma'lum sxema - `?`."""
        from app.services.meetings import shapes

        schema = ((request.get("output_config") or {}).get("format") or {}).get("schema")
        if schema is None:
            return "meeting_extract"
        known = (("meeting_extract", shapes.extract()), ("meeting_extract", shapes.extract(follow_up=True)),
                 ("meeting_map", shapes.map_part()), ("meeting_write", shapes.writer()),
                 ("meeting_verify", shapes.verify()), ("meeting_classify", shapes.classify()),
                 ("meeting_ask", shapes.ask()), ("meeting_minutes", shapes.minutes()))
        return next((op for op, candidate in known if schema == candidate), "?")

    def ops(self) -> list[str]:
        return [self.op_of(r) for r in self.requests]

    def chats(self) -> list[dict[str, Any]]:
        """Chat so'rovlari (`ClaudeChat.converse`): `system` - bloklar ro'yxati."""
        return [r for r in self.requests if isinstance(r.get("system"), list)]

    def final_message(self, request: dict[str, Any]) -> Any:
        """Navbatdagi javob yoki `auto_reply` -> `Message`; istisno otiladi. Chatda (`system` - bloklar)
        ko'rsatma birinchi blokda, transkript - kontekst blokida: `auto_reply` qatorlarni o'sha yerdan topadi."""
        item = self.script.pop(0) if self.script else None
        if callable(item) and not isinstance(item, BaseException):
            item = item(request)
        if isinstance(item, BaseException):
            raise item
        if item is None:
            system = request.get("system") or ""
            parts: list[str] = []
            if isinstance(system, list):
                texts = [str(block.get("text") or "") for block in system if isinstance(block, dict)]
                system, parts = (texts[0] if texts else ""), texts[1:]
            parts += [str(m.get("content") or "") for m in request.get("messages") or [] if m.get("role") == "user"]
            item = self.reply(self.op_of(request), system if isinstance(system, str) else "", "\n".join(parts))
        if isinstance(item, str):
            item = claude_message(item, model=str(request.get("model") or CLAUDE_MODEL))
        return item


class _FakeClaudeBeta:
    """`client.beta` - faqat `messages.stream` (rad-zahirasi: so'rov `betas` va `fallbacks` bilan)."""

    def __init__(self, fake: FakeAnthropic) -> None:
        self.messages = _FakeClaudeMessages(fake)


class _FakeClaudeMessages:
    """`client.messages` - faqat `stream`."""

    def __init__(self, fake: FakeAnthropic) -> None:
        self._fake = fake

    def stream(self, **kwargs: Any) -> _FakeClaudeStream:
        self._fake.requests.append(dict(kwargs))
        return _FakeClaudeStream(self._fake, kwargs)


class _FakeClaudeStream:
    """`MessageStreamManager` + `MessageStream`: `with` ga kirishda so'rov "ketadi" (istisno shu
    yerda), `get_final_message()` - yakuniy xabar."""

    def __init__(self, fake: FakeAnthropic, request: dict[str, Any]) -> None:
        self._fake = fake
        self._request = request
        self._message: Any = None

    def __enter__(self) -> _FakeClaudeStream:
        self._message = self._fake.final_message(self._request)
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def get_final_message(self) -> Any:
        return self._message
