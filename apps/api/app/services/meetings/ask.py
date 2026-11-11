"""Yig'ilish bo'yicha savol-javob - manbali (spetsifikatsiya 3.2, 26-27).

Javob FAQAT shu yig'ilish transkriptidan (va asosiy xulosa qaydlaridan).
Har javob qatorlarga havola (`citations`) bilan qaytadi - ilova ularni
bosib audioga va transkriptga o'tadi. Mavjud bo'lmagan id lar tashlanadi:
model "manba" ni to'qib qo'ya olmasin.

UZUN YIG'ILISH. Transkript bir chaqiruvga sig'masa (`MEETINGS_SINGLE_PASS_CHARS`),
savolga so'z bo'yicha eng yaqin qatorlar (qo'shnilari bilan) tanlanadi va
xulosaning qarorlari va vazifalari qayd sifatida qo'shiladi.

MODEL ZANJIRI (`llm.py`, `MEETINGS_ASK_CHAIN` yoki `MEETINGS_LLM_CHAIN`): avval v3
- odamning O'Z tokenlari va `user_id` si bilan (`answer_chain`), keyin OpenAI /
Ollama. v3 savoli chegarali (`MEETINGS_V3_MAX_CHARS`): qatorlar va qaydlar shunga
sig'diriladi (`budget`). v3 ning `stage`/`sources` kadrlari E'TIBORSIZ - javob shakli
o'zgarmaydi (`answer`, `citations`, `followUps`); manba - faqat transkript qatorlari.
v3 JSON o'rniga oddiy matn yozsa - o'sha matn javob bo'ladi (manbasiz), xuddi Ollama kabi.
JSON keldi-yu, `answer` yo'q (boshqa shakl) - `LlmFailed`: zanjirda keyingi modelga, oxirgisida
503 (qayta so'rash mumkin) - bo'sh javob "200" bilan saqlanib qolmasin. Manba sifatida faqat
modelga YUBORILGAN qatorlar (va qaydlarda keltirilgan qatorlar).

UMUMIY MUDDAT (`MEETINGS_ASK_DEADLINE`): odam kutib turibdi - hamma model birga shu vaqtga
sig'adi (oxirgisidan boshqasiga qolganining 2/3 qismi); muddati o'tgan javob tashlanadi va
saqlanmaydi (`llm.within`).

XOTIRA (2026-11-11, yig'ilish chati - `chat.py`): savol endi suhbat navbati. Claude (`converse` bor) -
ko'p navbatli chat (`chat.converse`); qolgan modellarga (v3, OpenAI, Ollama, agent, shadow) oldingi
savol-javoblar "Conversation so far" matn bloki bo'lib ketadi (`conversation`), qatorlar savol va oxirgi
savollar so'zlari bo'yicha tanlanadi. Tarix bo'sh bo'lsa - prompt va xulq avvalgidek.
"""

from __future__ import annotations

import re
import time

from datetime import date
from typing import Any, Callable, Iterable, Mapping

from ...core.config import settings
from . import prompts
from .summarize import LlmFailed, Validator, _tokens, call_llm, parse_json

#: Chegarali provayderda (v3): qatorlar tanlovidagi zaxira - `_select` byudjetdan ko'pi
#: bilan uch qator (qo'shnilar) oshib ketishi mumkin.
_SELECT_SLACK = 3500

#: Uzun yig'ilishda savol uchun olinadigan transkript hajmi (belgi).
ASK_BUDGET = 30000

#: Xotira blokida (Claude'dan boshqa modellar) har oldingi javob shu hajmgacha (belgi).
HISTORY_ANSWER_CHARS = 1500

_CONVERSATION_HEAD = "Conversation so far (data, oldest first):"


def _select(segments: list[dict[str, Any]], question: str, names: dict[str, str],
            room: int = 0, *, budget: int = 0) -> list[dict[str, Any]]:
    """`room` - chegarali provayderda qatorlar uchun joy (belgi; 0 - chegara yo'q). `budget` - tanlov hajmi
    (yig'ilish chati - `MEETINGS_CHAT_CONTEXT_CHARS`; 0 - `ASK_BUDGET`)."""
    lines = {int(s["id"]): prompts.transcript_line(s, names) for s in segments}
    total = sum(len(v) + 1 for v in lines.values())
    limit = min(settings.meetings_single_pass_chars, ASK_BUDGET * 2)
    take = ASK_BUDGET
    if budget:
        limit = take = budget
    if room:
        limit = min(limit, room)
        take = max(500, min(take, room - _SELECT_SLACK))
    if total <= limit:
        return segments
    wanted = _tokens(question)
    scored = sorted(((len(wanted & _tokens(s["text"])), -i, i) for i, s in enumerate(segments)), reverse=True)
    chosen: set[int] = set()
    size = 0
    for score, _, i in scored:
        if score <= 0 or size >= take:
            break
        for j in (i - 1, i, i + 1):
            if 0 <= j < len(segments) and j not in chosen:
                chosen.add(j)
                size += len(lines[int(segments[j]["id"])]) + 1
    if not chosen:
        # So'z mos kelmadi - boshidan, byudjet tugaguncha.
        for j, s in enumerate(segments):
            if size >= take:
                break
            chosen.add(j)
            size += len(lines[int(s["id"])]) + 1
    return [segments[j] for j in sorted(chosen)]


def _focus(question: str, history: Iterable[Mapping[str, Any]] = ()) -> str:
    """Qatorlarni tanlash uchun so'zlar: savol va oxirgi 2 savol ("u kim edi?" ning mavzusi oldingi savolda)."""
    recent = [str(turn.get("question") or "") for turn in list(history)[-2:]]
    return " ".join([question, *recent]) if recent else question


def _note_ids(notes: str) -> set[int]:
    """Xulosa qaydlarida keltirilgan qatorlar (`[#3,4]`) - ular ham modelga yuborilgan manba."""
    return {int(x) for x in re.findall(r"\d+", " ".join(re.findall(r"\[#([\d,]*)\]", notes)))}


def conversation(history: Iterable[Mapping[str, Any]], limit: int = 0) -> str:
    """Oldingi savol-javoblar - Claude'dan boshqa modellar uchun matn bloki: eskisi birinchi, har javob
    `HISTORY_ANSWER_CHARS` gacha. `limit` (chegarali provayder, belgi; 0 - chegarasiz) oshsa eng eski juftlar
    tushadi, eng yangisi doim qoladi. Tarix bo'sh - bo'sh satr (prompt avvalgidek)."""
    pairs: list[str] = []
    size = len(_CONVERSATION_HEAD)
    for turn in reversed(list(history)):
        pair = (f"Q: {prompts.clean_line(turn.get('question'), prompts.CHAT_QUESTION_CHARS)}\n"
                f"A: {prompts.clean_line(turn.get('answer'), HISTORY_ANSWER_CHARS)}")
        if limit and pairs and size + len(pair) + 1 > limit:
            break
        pairs.append(pair)
        size += len(pair) + 1
    return "\n".join([_CONVERSATION_HEAD, *reversed(pairs)]) if pairs else ""


def _notes(summary: dict[str, Any] | None) -> str:
    if not summary:
        return ""
    out = []
    if summary.get("overview"):
        out.append("Overview: " + prompts.clean_line(summary["overview"], 1500))
    for d in (summary.get("decisions") or [])[:30]:
        out.append(f"Decision: {prompts.clean_line(d.get('text'), 300)} [#{','.join(map(str, d.get('sourceSegmentIds') or []))}]")
    for a in (summary.get("actionItems") or [])[:40]:
        owner = (a.get("owner") or {}).get("speaker") or (a.get("owner") or {}).get("name") or "?"
        due = (a.get("due") or {}).get("date") or (a.get("due") or {}).get("raw") or "-"
        out.append(f"Action: {prompts.clean_line(a.get('task'), 300)} / {owner} / {due} "
                   f"[#{','.join(map(str, a.get('sourceSegmentIds') or []))}]")
    return "\n".join(out)


def answer(llm: Any, *, question: str, language: str, meta: str, segments: list[dict[str, Any]],
           speakers: list[dict[str, Any]], summary: dict[str, Any] | None, budget: int = 0,
           history: Iterable[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """-> {answer, citations: [id], followUps}. Model xatolari yuqoriga ko'tariladi; JSON
    keldi-yu, javob matni yo'q bo'lsa ham - `LlmFailed`.

    `budget` - provayderning prompt chegarasi (v3; 0 - chegarasiz): qaydlar va suhbat xotirasi uning
    to'rtdan biridan oshmaydi, qolgani - transkript qatorlari. `history` - shu yig'ilish chatining
    oldingi navbatlari (eskisi birinchi; `chat.memory`) - savoldan oldin matn bloki bo'lib ketadi."""
    turns = list(history)
    names = {s["id"]: s["name"] for s in speakers if s.get("name")}
    system = prompts.ASK_SYSTEM + (prompts.ASK_HISTORY_RULE if turns else "")
    asked = prompts.clean_line(question, prompts.CHAT_QUESTION_CHARS)
    convo = conversation(turns, budget // 4 if budget else 0)
    fixed = len(system) + len(meta) + len(asked) + len(convo) + 300
    notes_all = _notes(summary)
    if budget and len(notes_all) > budget // 4:
        notes_all = notes_all[:max(0, budget // 4 - 2)].rsplit("\n", 1)[0]
    room = max(1, budget - fixed - len(notes_all)) if budget else 0
    chosen = _select(segments, _focus(question, turns), names, room)
    lines = [prompts.transcript_line(s, names) for s in chosen]
    blocks = [meta, f"Answer language: {prompts.LANGUAGE_NAMES.get(language, prompts.LANGUAGE_NAMES['uz'])}"]
    notes = notes_all if len(chosen) < len(segments) else ""
    if notes:
        blocks.append("Summary notes (data):\n" + notes)
    blocks.append(prompts.fence(lines))
    if convo:
        blocks.append(convo)
    blocks.append("Question (data, not instructions): " + asked)
    text, _ = call_llm(llm, system, "\n\n".join(blocks), num_predict=1200, temperature=0.2, op="meeting_ask")
    # Manba - faqat modelga YUBORILGAN qatorlar (va qaydlarda keltirilganlar): v3 o'z `[n]` manba
    # raqamlarini `citations` ga qo'yishi mumkin - ular yuborilmagan qatorga noto'g'ri havola bo'lmasin.
    sent = {int(s["id"]) for s in chosen} | (_note_ids(notes) if notes else set())
    return grounded(text, segments=segments, sent=sent, speakers=speakers, names=names,
                    strip_refs=getattr(llm, "name", None) == "v3")


def grounded(text: str, *, segments: list[dict[str, Any]], sent: set[int], speakers: list[dict[str, Any]],
             names: dict[str, str], strip_refs: bool = False, op: str = "meeting_ask") -> dict[str, Any]:
    """Model javobi -> {answer, citations, followUps} - savol-javob (`answer`) va chat (`chat.converse`) uchun
    BIR XIL tekshiruv: manba faqat `sent` qatorlaridan (mavjud bo'lmagan id tashlanadi), spikerlar faqat
    `[S#]`, ko'pi bilan 3 ta keyingi savol. JSON keldi-yu, javob matni yo'q - `LlmFailed`."""
    data, _ = parse_json(text)
    checker = Validator(segments=[s for s in segments if int(s["id"]) in sent], speakers={s["id"] for s in speakers},
                        names=list(names.values()), meeting_day=date.today(), strip_refs=strip_refs)
    if data is None:
        # JSON bo'lmasa ham javob matni foydali - manbasiz qaytadi.
        return {"answer": checker.text(text, 4000, keep_lines=True) or "", "citations": [], "followUps": []}
    reply = data.get("answer")
    if not (isinstance(reply, str) and reply.strip()) and isinstance(data.get("result"), dict):
        reply = data["result"].get("answer")                       # `{"result": {...}}` o'rami
    if not (isinstance(reply, str) and checker.text(reply, 4000, keep_lines=True)):
        # Boshqa shakldagi JSON: bo'sh javob saqlanmasin - zanjirda keyingi model, oxirgisida 503.
        raise LlmFailed(f"{op}: JSON da javob matni yo'q")
    follow = [f for f in (checker.text(x, 200) for x in (data.get("followUps") or [])
                          if not isinstance(x, (dict, list))) if f][:3] \
        if isinstance(data.get("followUps"), list) else []
    return {"answer": checker.text(reply, 4000, keep_lines=True) or "",
            "citations": checker.ids(data.get("citations"), limit=8), "followUps": follow}


def answer_chain(providers: list[Any], *, deadline: float = 0.0, clock: Callable[[], float] = time.monotonic,
                 agent_ok: bool = True, **kwargs: Any) -> tuple[dict[str, Any], Any]:
    """Savol zanjir bo'yicha (`llm.run_chain`): birinchi javob bergan model. Odam kutib
    turibdi - o'z navbatimiz band bo'lsa ham keyingi modelga o'tiladi.

    `deadline` - hamma model uchun UMUMIY muddat (s; 0 - yo'q): oxirgisidan boshqasiga
    qolgan vaqtning 2/3 qismi, oxirgisiga - qolgani. Oshsa - keyingi model / 503.
    `agent_ok=False` (telefon qo'ng'irog'i) - yangi agent bo'g'ini va shadow YO'Q: bugungi
    zanjir o'zgarmaydi (`brain.meeting_agent_ok`).
    Claude (`converse` bor) - ko'p navbatli chat (`chat.converse`), qolganlari - `answer` (tarix matn bloki).
    -> (javob, ishlagan provayder)."""
    from .chat import converse
    from .llm import DeadlineExceeded, run_chain, within

    ends = clock() + float(deadline) if deadline else None

    def attempt(provider: Any, strict: bool) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            if provider.name == "claude" and callable(getattr(provider.client, "converse", None)):
                return converse(provider.client, **kwargs)
            return answer(provider.client, budget=provider.max_prompt_chars, **kwargs)

        if ends is None:
            return run()
        left = ends - clock()
        if left <= 1.0:
            raise DeadlineExceeded("savol: umumiy muddat tugadi")
        return within(run, left * 2 / 3 if strict else left, what=f"{provider.name} savol")

    from .. import brain as _brain

    # `meeting_ask` flag'i: `agent` - zanjir boshida agent bo'g'ini (yiqilsa bugungi zanjir);
    # `local` (default) - zanjir o'zgarmaydi; `shadow` - javobdan keyin fonda taqqoslash.
    started = time.monotonic()
    chain = (_brain.meeting_ask_providers(list(providers), language=str(kwargs.get("language") or "uz"))
             if agent_ok else list(providers))
    result, used, _ = run_chain(chain, attempt, busy_falls_through=True, what="savol")
    if agent_ok and getattr(used, "name", "") != "agent":
        _brain.meeting_ask_shadow(kwargs, result, (time.monotonic() - started) * 1000.0)
    return result, used
