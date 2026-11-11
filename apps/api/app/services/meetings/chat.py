"""Yig'ilish CHATI (2026-11-11, ega so'rovi): bitta audio - bitta suhbat.

Suhbat - yig'ilishning FAOL savol-javoblari (`questions` jadvali, `archived_at IS NULL`): hisob egasining
mobil ilova, web va Telegram'dagi savollari - bitta tarix. "Yangi suhbat" - yumshoq tozalash (`archived_at`),
qatorlar bazada qoladi; qayta o'girish ham hamma faol navbatni arxivga o'tkazadi (eski matnga havolalar).
Boshqa yig'ilishning navbati hech qachon qo'shilmaydi: tarix faqat shu yig'ilish id si bilan o'qiladi, egalik
esa `service._owned` da tekshiriladi.

SO'ROVCHI (`asker`, `asker_of`): UMUMIY hisobda (Slack'dagi hamma odam - bitta `SLACK_ACTOR_ID`) har odamning
suhbati alohida: xotira, tarix va "Yangi suhbat" faqat o'sha odamniki. Kalit ochiq matn (`slack:<user id>`),
uni faqat server ichidagi kanallar beradi - HTTP API olmaydi. `None` - hisob egasining o'zi (ilova, web,
Telegram); eski `/questions` va `GET /chat` faqat egasining navbatlarini ko'rsatadi.

KLIENT KALITI (`client_id_of`, idempotentlik): ilova har xabarga tasodifiy kalit beradi (`ChatRequest.clientId`)
va noaniq xatodan (proksi 504, uzilgan ulanish, vaqt tugashi) keyin «Qayta yuborish»da O'SHANI yuboradi. Kalit
(yig'ilish, so'rovchi, kalit) bo'yicha: shu kalitli FAOL navbat bor - o'sha qaytadi (modelga so'rov ham, soatlik
chegara ham yo'q); shu kalitli xabar SHU jarayonda hali javob kutyapti (`claim`) - birinchisi kutiladi
(`MEETINGS_ASK_DEADLINE + WAIT_EXTRA_SEC` gacha), keyin yana qaraladi; hech narsa saqlanmagan bo'lsa (birinchisi
yiqildi) - oddiy urinish. Saqlashda ham tekshiriladi (`store.add_turn`): parallel urinish (masalan boshqa
jarayonda) yozib ulgurgan bo'lsa - o'sha navbat qaytadi, ikkinchisi yozilmaydi. Arxivdagi navbat kalitni band
qilmaydi. Botlar (Slack, Telegram) kalit bermaydi - har chaqiruv yangi navbat.

XOTIRA (`memory`): oxirgi `MEETINGS_CHAT_HISTORY_TURNS` ta navbat; savol+javob matni
`MEETINGS_CHAT_HISTORY_CHARS` dan oshsa - eng eskilari tushadi. Zanjir (`ask.answer_chain`) Claude'ni shu
yerdagi `converse` bilan chaqiradi; qolgan modellarga (v3, OpenAI, Ollama, agent) tarix matn bloki bo'lib
ketadi (`ask.answer`, `ask.conversation`).

CLAUDE (`converse`) - ko'p navbatli `messages`:
  * `system` - ikki matn bloki: `prompts.CHAT_SYSTEM` va kontekst (meta, xulosa qaydlari, transkript;
    `cache_control: ephemeral`). Kontekst yig'ilish bo'yicha BAYTMA-BAYT barqaror - joriy vaqt va til yo'q,
    transkript chegarasining nonce'i matnning o'z xeshidan: keyingi savollarda prompt keshi ishlaydi;
  * transkript `MEETINGS_CHAT_CONTEXT_CHARS` gacha TO'LIQ, undan uzuni - savol va oxirgi 2 savol so'zlari
    bo'yicha tanlangan qatorlar (`ask._select`). Tanlov har savolda boshqa - bunda kontekst KESHLANMAYDI
    (kesh yozuvi oddiy kirishdan qimmat, keyingi savol uni o'qimaydi);
  * har oldingi navbat - `user` (o'sha shakldagi savol) + `assistant` (JSON matn: javob, manba id lari,
    keyingi savollar). Faqat MATN: "o'ylash" bloklari saqlanmaydi va qayta yuborilmaydi;
  * oxirgi `user` xabari - javob tili va yangi savol (keshlangan prefiksdan keyin).
Javob savol-javobdagi tekshiruvdan o'tadi (`ask.grounded`): manba - faqat yuborilgan qatorlar.
"""

from __future__ import annotations

import json
import threading

from typing import Any, Iterable, Mapping

from ...core.config import settings
from . import prompts
from .ask import _focus, _note_ids, _notes, _select, grounded
from .store import jload

#: Kanal (`questions.channel`): HTTP klientlari (`ChatRequest.channel`) va server o'zi chaqiradigan botlar.
CHANNELS: tuple[str, ...] = ("mobile", "web", "miniapp", "desktop", "api", "slack", "telegram")

#: So'rovchi kalitining (`questions.asker`) eng katta uzunligi (belgi).
ASKER_CHARS = 100

#: Klient kalitining (`questions.client_id`, `ChatRequest.clientId`) eng katta uzunligi (belgi).
CLIENT_ID_CHARS = 64

#: Takroriy xabar birinchisini shuncha ko'p kutadi: `MEETINGS_ASK_DEADLINE` (butun zanjir muddati) + zaxira (s).
WAIT_EXTRA_SEC = 15.0

#: SHU jarayonda javob kutayotgan xabarlar: (yig'ilish, so'rovchi, klient kaliti) -> urinish tugaganini bildiradi.
_flights: dict[tuple[str, str | None, str], threading.Event] = {}
_flights_lock = threading.Lock()


def channel_of(value: Any) -> str:
    """Noma'lum yoki bo'sh kanal - `api`."""
    name = str(value or "").strip().lower()
    return name if name in CHANNELS else "api"


def asker_of(value: Any) -> str | None:
    """So'rovchi kaliti - OCHIQ matn (ma'nosi chaqiruvchida, masalan `slack:<user id>`): chetidagi bo'shliqsiz,
    `ASKER_CHARS` gacha; bo'sh - `None` (hisob egasining o'zi)."""
    text = "" if value is None else str(value).strip()
    return text[:ASKER_CHARS] or None


def client_id_of(value: Any) -> str | None:
    """Xabarning klient kaliti - OCHIQ matn (HTTP'da `ChatRequest.clientId` tekshiradi): chetidagi bo'shliqsiz,
    `CLIENT_ID_CHARS` gacha; bo'sh - `None` (kalitsiz: har chaqiruv yangi navbat)."""
    text = "" if value is None else str(value).strip()
    return text[:CLIENT_ID_CHARS] or None


def claim(key: tuple[str, str | None, str]) -> tuple[threading.Event, bool]:
    """Kalit (yig'ilish, so'rovchi, klient kaliti) bilan urinish boshlash -> (hodisa, egasimi). Kalit bo'sh bo'lsa -
    endi bizniki (`True`; tugaganda ALBATTA `release`); band bo'lsa - birinchi urinishning hodisasi (`False`):
    uni kutib, keyin saqlangan navbatga qaraladi."""
    with _flights_lock:
        held = _flights.get(key)
        if held is not None:
            return held, False
        event = _flights[key] = threading.Event()
        return event, True


def release(key: tuple[str, str | None, str], event: threading.Event) -> None:
    """Urinish tugadi (javob, xato yoki istisno): kalit bo'shaydi va kutayotganlar uyg'onadi. Faqat O'Z hodisasi
    o'chiriladi - kalitni keyin boshqa urinish olgan bo'lsa, uniki joyida qoladi."""
    with _flights_lock:
        if _flights.get(key) is event:
            del _flights[key]
    event.set()


def memory(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Faol navbatlar (`store.chat_turns`, eskisi birinchi) -> modelga xotira: oxirgi
    `MEETINGS_CHAT_HISTORY_TURNS` ta; savol+javob matni `MEETINGS_CHAT_HISTORY_CHARS` ga sig'maguncha eng
    eskilari tushadi (ikkalasi 0 - xotira yo'q). Har navbat: `question`, `answer`, `citations` (qator id lari),
    `followUps`, `language` (eski qatorda `None`)."""
    turns = [{"question": str(row.get("question") or ""), "answer": str(row.get("answer") or ""),
              "citations": [x for x in jload(row.get("citations"), []) or [] if isinstance(x, int)],
              "followUps": [x for x in jload(row.get("follow_ups"), []) or [] if isinstance(x, str)],
              "language": row.get("language")} for row in rows]
    keep = max(0, int(settings.meetings_chat_history_turns or 0))
    turns = turns[-keep:] if keep else []
    cap = max(0, int(settings.meetings_chat_history_chars or 0))
    while turns and sum(len(t["question"]) + len(t["answer"]) for t in turns) > cap:
        turns.pop(0)
    return turns


def context_segments(segments: list[dict[str, Any]], question: str, history: list[Mapping[str, Any]],
                     names: dict[str, str]) -> list[dict[str, Any]]:
    """Claude'ga transkript: `MEETINGS_CHAT_CONTEXT_CHARS` ga sig'sa - hammasi; aks holda savol va oxirgi 2
    savol so'zlari bo'yicha tanlangan qatorlar (`ask._select`, o'sha hajmdagi byudjet bilan)."""
    limit = max(1, int(settings.meetings_chat_context_chars or 0))
    if sum(len(prompts.transcript_line(s, names)) + 1 for s in segments) <= limit:
        return list(segments)
    return _select(segments, _focus(question, history), names, budget=limit)


def system_blocks(meta: str, notes: str, lines: list[str], *, cache: bool = True) -> list[dict[str, Any]]:
    """`system` - ikki blok: ko'rsatma (hamma yig'ilishda bir xil) va kontekst (shu yig'ilishniki). `cache` -
    kontekstga `cache_control`: faqat transkript TO'LIQ ketganda (o'shanda blok har savolda bir xil)."""
    context: dict[str, Any] = {"type": "text", "text": prompts.chat_context(meta, notes, lines)}
    if cache:
        context["cache_control"] = {"type": "ephemeral"}
    return [{"type": "text", "text": prompts.CHAT_SYSTEM}, context]


def replay(history: Iterable[Mapping[str, Any]], language: str) -> list[dict[str, str]]:
    """Oldingi navbatlar -> `messages`: `user` (o'sha shakldagi savol - o'sha tilda; eski qatorda joriy til) va
    `assistant` (javob JSON matni - modelning o'z shakli). Faqat matn bloklari."""
    out: list[dict[str, str]] = []
    for turn in history:
        asked = prompts.chat_question(turn["question"], turn.get("language") or language)
        reply = {"answer": turn["answer"], "citations": list(turn.get("citations") or []),
                 "followUps": list(turn.get("followUps") or [])}
        out.append({"role": "user", "content": asked})
        out.append({"role": "assistant", "content": json.dumps(reply, ensure_ascii=False)})
    return out


def converse(client: Any, *, question: str, language: str, meta: str, segments: list[dict[str, Any]],
             speakers: list[dict[str, Any]], summary: dict[str, Any] | None,
             history: Iterable[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """Claude'ga ko'p navbatli chat (`ClaudeChat.converse`) -> {answer, citations, followUps, model?}; `model` -
    javobni aynan qaysi model yozgani (rad-zahirasi ishlasa - zahira modeli). Model xatolari yuqoriga
    ko'tariladi; JSON da javob matni yo'q - `LlmFailed` (zanjirda keyingi model, oxirgisida 503)."""
    turns = list(history)
    names = {s["id"]: s["name"] for s in speakers if s.get("name")}
    chosen = context_segments(segments, question, turns, names)
    notes = _notes(summary)
    # Tanlangan qatorlar har savolda boshqa: keshlash faqat transkript to'liq ketganda foyda beradi.
    system = system_blocks(meta, notes, [prompts.transcript_line(s, names) for s in chosen],
                           cache=len(chosen) == len(segments))
    messages = replay(turns, language) + [{"role": "user", "content": prompts.chat_question(question, language)}]
    text, info = client.converse(system, messages, op="meeting_chat", num_predict=1200, format="json")
    sent = {int(s["id"]) for s in chosen} | _note_ids(notes)
    result = grounded(text, segments=segments, sent=sent, speakers=speakers, names=names, op="meeting_chat")
    if (info or {}).get("model"):
        result["model"] = str(info["model"])
    return result
