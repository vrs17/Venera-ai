"""Yig'ilish xulosasi - eng muhim qism (spetsifikatsiya 6).

MAQSAD: Plaud xulosasi qamraydigan HAMMA narsa (qisqacha, mavzular, asosiy
fikrlar, vazifalar egasi va muddati bilan, qarorlar, keyingi qadamlar, ochiq
savollar, raqamlar, muhim lahzalar, ...), va ustiga - har qaror va vazifa
transkriptdagi aniq qatorga BOG'LANGAN, ya'ni tekshirib bo'ladi.

QUVUR (gemma4:31b, Ollama Cloud):

    0. darvoza     10 s yoki 30 so'zdan kam - xulosa yo'q (`too_short`)
    1. shablon     `auto` -> qisqa qo'ng'iroq qoidasi, keyin tasniflovchi
    2a. bir o'tish matn <= 45K belgi - bitta chaqiruv
    2b. map        uzun matn - ~24K belgilik bo'laklar, ketma-ket; har tekshirilgan
                   bo'lak `summary_parts` da (yiqilsa qaytadan to'lanmaydi)
    3. birlashtirish KOD: vazifalar egasi + so'z o'xshashligi bo'yicha, qarorlar matn bo'yicha
    4. yozuvchi    faqat uzun yo'lda: bo'lak xulosalaridan sarlavha va umumiy xulosa
    5. tekshiruvchi vazifa va qarorlarni keltirilgan qatorlar bilan solishtiradi
    6. yakun       id lar, vaqtlar, gapirish ulushi, belgilar qamrovi - KOD

MODELGA ISHONILMAYDI (6.7): JSON qutqariladi, har element sxema bo'yicha
yumshoq tekshiriladi, keltirilgan qator id lari mavjudligi, iqtibos haqiqatan
o'sha qatorda borligi, egasining ismi transkriptda borligi, muddat KOD jadvali
bilan qayta hal qilinishi tekshiriladi. Tasdiqlanmagan narsa yo tashlanadi,
yo "tekshiring" (`needsConfirmation`) belgisini oladi.

TO'LIQLIK KAFOLATI: map bosqichida tekshiruvdan o'tgan har vazifa va qaror
yakuniy xulosada bor. Yozuvchi ularni o'chira olmaydi - faqat kod birlashtiradi.
"""

from __future__ import annotations

import difflib
import json
import logging
import re
import unicodedata

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

from ..integrations.ollama import OllamaError
from . import dates as dates_mod
from . import prompts, templates

log = logging.getLogger(__name__)

SCHEMA_VERSION = "meeting-summary/1"

#: Ro'yxat chegaralari (yakun bosqichi).
CAPS = {"actionItems": 60, "decisions": 40}
CAP_DEFAULT = 30

_ITEM_LISTS = ("keyPoints", "decisions", "actionItems", "openQuestions", "risks", "numbers", "dates",
               "nextSteps", "highlights")

#: Tokenlar taxmini: o'lchangan 47K belgi ~ 21K token (o'zbekcha). Inglizcha ~4.4
#: belgi/token - shuning uchun "prompt jim qisqartirildi" chegarasi 0.25 (0.5 da
#: inglizcha prompt har safar "kesilgan" deb topilardi). Jonli o'lchovgacha
#: asosiy belgi - `done_reason == "length"` va `coverage` aks-sadosi.
CHARS_PER_TOKEN = 2.2
PROMPT_CUT_RATIO = 0.25


# --- xatolar --------------------------------------------------------------------


class LlmUnavailable(Exception):
    """Model sozlanmagan (kalit yo'q) - qayta urinish befoyda."""


class LlmRateLimited(Exception):
    """429 - ishchi 5/15/30 daqiqadan keyin qayta uradi."""


class LlmFailed(Exception):
    """Boshqa xato - ishchi jami 3 marta uradi."""


class LlmBusy(Exception):
    """O'Z navbatimiz to'la (`navbat to'la` - boshqa ip modelni band qilgan). Bu
    urinish EMAS: ishchi bir oz kutib qayta oladi, `attempts` oshmaydi."""


class _Fallback(Exception):
    """Bir o'tish natija bermadi - map yo'liga o'tiladi."""


def call_llm(llm: Any, system: str, user: str, *, num_predict: int, temperature: float, op: str,
             num_ctx: int = 0, think: bool | None = None) -> tuple[str, dict[str, Any]]:
    if not getattr(llm, "configured", False):
        raise LlmUnavailable("model sozlanmagan")
    extra: dict[str, Any] = {}
    if think is not None:
        # Faqat sozlangan bo'lsa yuboriladi: `think` ni bilmaydigan klient (va
        # testlardagi soxta) eski imzo bilan ishlayversin.
        extra["think"] = think
    try:
        return llm.complete_meta(system, user, num_predict=num_predict, temperature=temperature, op=op,
                                 format="json", options={"num_ctx": num_ctx} if num_ctx else None, **extra)
    except OllamaError as exc:
        if getattr(exc, "status", None) == 429:
            raise LlmRateLimited(str(exc)) from exc
        if str(exc) == "Ollama sozlanmagan":
            raise LlmUnavailable(str(exc)) from exc
        if str(exc) == "navbat to'la":
            raise LlmBusy(str(exc)) from exc
        raise LlmFailed(str(exc)) from exc


# --- JSON ni o'qish (6.7.1) -------------------------------------------------------

_FENCE = re.compile(r"```(?:json|JSON)?\s*(.*?)(?:```|$)", re.DOTALL)


def _skip(text: str, pos: int, chars: str = " \t\r\n,") -> int:
    while pos < len(text) and text[pos] in chars:
        pos += 1
    return pos


def salvage(text: str) -> dict[str, Any]:
    """Kesilgan JSON dan BUTUN qismlarni qutqaradi: to'liq maydonlar va
    massivlarning to'liq elementlari (`briefs.parse_list` g'oyasi)."""
    decoder = json.JSONDecoder()
    start = text.find("{")
    if start < 0:
        return {}
    out: dict[str, Any] = {}
    pos = start + 1
    while True:
        pos = _skip(text, pos)
        if pos >= len(text) or text[pos] == "}":
            break
        try:
            key, pos = decoder.raw_decode(text, pos)
        except ValueError:
            break
        if not isinstance(key, str):
            break
        pos = _skip(text, pos, " \t\r\n")
        if pos >= len(text) or text[pos] != ":":
            break
        pos = _skip(text, pos + 1, " \t\r\n")
        try:
            value, pos = decoder.raw_decode(text, pos)
            out[key] = value
            continue
        except ValueError:
            pass
        if pos < len(text) and text[pos] == "[":
            items: list[Any] = []
            p = pos + 1
            while True:
                p = _skip(text, p)
                if p >= len(text) or text[p] == "]":
                    break
                try:
                    item, p = decoder.raw_decode(text, p)
                except ValueError:
                    break
                items.append(item)
            out[key] = items
        break
    return out


def parse_json(raw: str) -> tuple[dict[str, Any] | None, bool]:
    """Model javobi -> (obyekt, qutqarilganmi). Chegaralar olib tashlanadi,
    keyin `json.loads`, keyin birinchi `{` dan oxirgi `}` gacha, keyin qutqarish."""
    text = (raw or "").strip()
    fenced = _FENCE.search(text)
    if fenced:
        text = fenced.group(1).strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data, False
    except ValueError:
        pass
    start = text.find("{")
    if start < 0:
        return None, False
    end = text.rfind("}")
    if end > start:
        try:
            data = json.loads(text[start:end + 1])
            if isinstance(data, dict):
                return data, False
        except ValueError:
            pass
    try:
        data, _ = json.JSONDecoder().raw_decode(text, start)
        if isinstance(data, dict):
            return data, False
    except ValueError:
        pass
    data = salvage(text[start:])
    return (data or None), True


# --- matn normallashtirish ------------------------------------------------------------

_APOS = str.maketrans({c: "'" for c in "ʻʼ’‘`´"})
_PUNCT = re.compile(r"[^\w\s']", re.UNICODE)
_TAGS = re.compile(r"<[^>]{1,200}>")
_MD_LINK = re.compile(r"\[([^\]]{0,200})\]\((?:[^)]{0,500})\)")
_S_TOKEN = re.compile(r"\[(S\d{1,2})\]")


def norm(text: Any) -> str:
    """Iqtibos solishtirish uchun: NFKC, kichik harf, apostroflar bir xil,
    tinish belgilarisiz, bo'shliqlar yig'ilgan."""
    value = unicodedata.normalize("NFKC", str(text or "")).lower().translate(_APOS)
    value = _PUNCT.sub(" ", value)
    return " ".join(value.split())


def first_words(text: str, n: int = 20) -> str:
    return " ".join(str(text or "").split()[:n])


def _tokens(text: str) -> set[str]:
    """So'zlarning BIRINCHI 5 HARFI - o'zbek qo'shimchalari uchun arzon "o'zak":
    "hisobotni" = "hisobot" = "hisob(o)", "tayyorlab" = "tayyorlash"."""
    return {t[:5] for t in norm(text).split() if len(t) > 1}


def jaccard(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _digits(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:[.,]\d+)?", str(text or "")))


def similar(a: str, b: str, threshold: float = 0.6) -> bool:
    """Bir xil narsami: so'zlar o'xshash VA raqamlar bir xil ("narx 15 mln" va
    "narx 18 mln" - IKKI xil qaror, birlashtirilmaydi)."""
    return _digits(a) == _digits(b) and jaccard(a, b) >= threshold


#: Shoshilinchlik aytilganmi - `priority: high` faqat shunda.
_URGENT = re.compile(r"(?<!\w)(?:shoshilinch\w*|tezroq|tezda|zudlik\w*|birinchi\s+navbat\w*|muhim\w*|"
                     r"срочн\w*|srochn\w*|в\s+первую\s+очередь|v\s+pervuyu\s+ochered|urgent\w*|asap|"
                     r"as\s+soon\s+as\s+possible|priority|приоритет\w*|prioritet\w*)(?!\w)")
_NOT_URGENT = re.compile(r"(?<!\w)(?:muhim\s+emas|shoshilmas\w*|shoshilinch\s+emas|keyinroq\s+ham|не\s+срочно|"
                         r"ne\s+srochno|не\s+горит|ne\s+gorit|not\s+urgent|low\s+priority|no\s+rush)(?!\w)")
#: O'zini tanishtirish ("men Azizman", "меня зовут", "I'm") - `suggestedName` dalili.
_INTRO_CUES = (r"\bmen\b", r"\bismim\b", r"меня\s+зовут", r"menya\s+zovut", r"\bя\b", r"\bya\b",
               r"\bmy\s+name\s+is\b", r"\bi'?m\b", r"\bi\s+am\b", r"\bthis\s+is\b", r"\bэто\b", r"\beto\b")
_HONORIFIC_WORDS = {"aka", "opa", "domla", "ustoz", "akа", "xola", "amaki", "janob", "xonim", "hoji"}
#: O'zbek lotin chiqishida bo'lmasligi kerak bo'lgan harflar (kirill, turkcha).
_FOREIGN_LETTERS = re.compile(r"[\u0400-\u04ffşçğıöüŞÇĞİÖÜ]")
_LETTERS = re.compile(r"[^\W\d_]")


def _time_stated(hour: int, minute: int, text: str) -> bool:
    """Soat cited qatorlarda aytilganmi (`briefs._time_stated` g'oyasi). "soat 3 da"
    -> 15:00 (1-7 tushdan keyin qoidasi) ham qabul."""
    hours = {hour} | ({hour - 12} if hour > 12 else set())
    for h in hours:
        if re.search(rf"(?<!\d)0?{h}[:.]{minute:02d}(?!\d)", text):
            return True
        if minute == 0 and re.search(rf"(?:soat\s*0?{h}(?!\d))|(?<!\d)0?{h}\s*(?:da\b|ga\b|gacha|часов|часа|"
                                     rf"chasov|chasa|o'clock|pm|am)", text):
            return True
    return False


# --- tekshiruvchi (6.7.2 - 6.7.7) -------------------------------------------------


@dataclass
class Validator:
    """Model natijasini transkript bilan solishtiradi."""

    segments: list[dict[str, Any]]
    speakers: set[str]
    names: list[str]
    meeting_day: date
    template_keys: tuple[str, ...] = ()
    language: str = "uz"
    #: Shu chaqiruv ko'rgan qatorlar (map bo'lagi) - `coverage` tekshiruvi uchun.
    total: int = 0
    invalid: int = 0
    dropped: int = 0
    errors: list[str] = field(default_factory=list)
    #: Tekshirilgan natija (chaqiruvchi to'ldiradi) - tuzatish urinishida qaysi
    #: javob tanlansa, natija ham aynan o'sha javobniki bo'lsin.
    result: Any = None
    #: O'zbekcha chiqishda kirill/turkcha harflar ulushi 2% dan oshdimi.
    script_bad: bool = False

    def __post_init__(self) -> None:
        self.by_id = {int(s["id"]): s for s in self.segments}
        self.order = [int(s["id"]) for s in self.segments]
        self.pos = {sid: i for i, sid in enumerate(self.order)}
        self.norm_text = {sid: norm(s["text"]) for sid, s in self.by_id.items()}
        blob = " ".join(str(s["text"]) for s in self.segments).lower()
        self.blob = (blob + " " + " ".join(n.lower() for n in self.names if n)).translate(_APOS)

    # --- umumiy ---

    def _err(self, where: str, why: str) -> None:
        if len(self.errors) < 10:
            self.errors.append(f"{where}: {why}")

    @property
    def bad_ratio(self) -> float:
        return (self.invalid + self.dropped) / self.total if self.total else 0.0

    @property
    def needs_repair(self) -> bool:
        return self.bad_ratio > 0.3 or self.script_bad

    def check_script(self, data: Any) -> None:
        """O'zbekcha chiqish LOTINDA bo'lsin: iqtiboslar, iboralar va ismlardan
        tashqari matnda kirill yoki turkcha harflar 2% dan ko'p bo'lsa - tuzatish."""
        if self.language != "uz":
            return
        letters = foreign = 0

        def walk(value: Any, key: str = "") -> None:
            nonlocal letters, foreign
            if key in ("quote", "raw", "value", "name", "suggestedName", "keywords", "coverage"):
                return
            if isinstance(value, str):
                letters += len(_LETTERS.findall(value))
                foreign += len(_FOREIGN_LETTERS.findall(value))
            elif isinstance(value, list):
                for item in value:
                    walk(item, key)
            elif isinstance(value, dict):
                for k, v in value.items():
                    walk(v, str(k))

        walk(data)
        if letters >= 50 and foreign / letters > 0.02:
            self.script_bad = True
            self._err("language", "Uzbek values must use Latin script (o', g', sh, ch): no Cyrillic, no Turkish letters")

    def text(self, value: Any, limit: int, *, keep_lines: bool = False) -> str | None:
        if value is None or isinstance(value, (dict, list)):
            return None
        raw = str(value)
        raw = _MD_LINK.sub(r"\1", raw)
        raw = _TAGS.sub("", raw)
        raw = _S_TOKEN.sub(lambda m: f"[{m.group(1)}]" if m.group(1) in self.speakers else m.group(1), raw)
        if keep_lines:
            lines = [" ".join(line.split()) for line in raw.replace("\r", "").split("\n")]
            raw = "\n".join(lines).strip()
            while "\n\n\n" in raw:
                raw = raw.replace("\n\n\n", "\n\n")
        else:
            raw = " ".join(raw.split())
        if not raw or raw.lower() in ("null", "none", "n/a", "-"):
            return None
        return raw if len(raw) <= limit else raw[:limit - 1] + "…"

    def speaker(self, value: Any) -> str | None:
        if value is None:
            return None
        found = re.search(r"S(\d{1,2})", str(value).upper())
        if not found:
            return None
        sid = f"S{int(found.group(1))}"
        return sid if sid in self.speakers else None

    def speakers_list(self, value: Any) -> list[str]:
        out: list[str] = []
        for item in value if isinstance(value, list) else []:
            sid = self.speaker(item)
            if sid and sid not in out:
                out.append(sid)
        return out

    @staticmethod
    def enum(value: Any, allowed: tuple[str, ...], default: Any) -> Any:
        text = str(value).strip().lower() if value is not None else ""
        for option in allowed:
            if text == option.lower():
                return option
        return default

    @staticmethod
    def number(value: Any, default: float, lo: float = 0.0, hi: float = 1.0) -> float:
        try:
            result = float(value)
        except (TypeError, ValueError):
            return default
        if result != result:          # NaN
            return default
        return max(lo, min(hi, result))

    def ids(self, value: Any, limit: int = 5) -> list[int]:
        out: list[int] = []
        items = value if isinstance(value, list) else ([value] if value is not None else [])
        for item in items:
            try:
                sid = int(str(item).lstrip("#").strip())
            except (TypeError, ValueError):
                continue
            if sid in self.by_id and sid not in out:
                out.append(sid)
            if len(out) >= limit:
                break
        return out

    def find_quote(self, quote: str | None) -> int | None:
        needle = norm(quote)
        if len(needle) < 4:
            return None
        for sid in self.order:
            if needle in self.norm_text[sid]:
                return sid
        return None

    def evidence(self, raw_ids: Any, quote: Any = None, limit: int = 5) -> list[int]:
        """Mavjud id lar; hammasi yaroqsiz bo'lsa - iqtibos bo'yicha tiklanadi."""
        ids = self.ids(raw_ids, limit)
        if not ids and isinstance(quote, str):
            found = self.find_quote(quote)
            if found is not None:
                ids = [found]
        return ids

    def context_text(self, ids: list[int]) -> str:
        """Keltirilgan qatorlar + har biri atrofidagi bitta qo'shni."""
        chosen: list[int] = []
        for sid in ids:
            p = self.pos.get(sid)
            if p is None:
                continue
            for q in (p - 1, p, p + 1):
                if 0 <= q < len(self.order) and self.order[q] not in chosen:
                    chosen.append(self.order[q])
        return " ".join(self.norm_text[s] for s in sorted(chosen, key=lambda s: self.pos[s]))

    def quote_ok(self, quote: str | None, ids: list[int]) -> bool:
        needle = norm(quote)
        if not needle:
            return False
        hay = self.context_text(ids)
        if needle in hay:
            return True
        words, qwords = hay.split(), needle.split()
        if not words or not qwords:
            return False
        width = len(qwords)
        best = 0.0
        for i in range(0, max(1, len(words) - width + 1)):
            window = " ".join(words[i:i + width])
            best = max(best, difflib.SequenceMatcher(None, needle, window).ratio())
            if best >= 0.75:
                return True
        return False

    def grounded(self, name: str) -> bool:
        """Ism transkriptda yoki foydalanuvchi bergan ismlarda bormi (`briefs._grounded`)."""
        words = [w for w in re.findall(r"\w+", name.lower().translate(_APOS)) if len(w) >= 3]
        return any(re.search(rf"(?<!\w){re.escape(w)}", self.blob) for w in words)

    def time(self, value: Any, ids: list[int]) -> str | None:
        found = re.fullmatch(r"\s*([01]?\d|2[0-3])[:.]([0-5]\d)\s*", str(value or ""))
        if not found:
            return None
        hour, minute = int(found.group(1)), int(found.group(2))
        text = " ".join(str(self.by_id[s]["text"]).lower() for s in ids if s in self.by_id)
        return f"{hour:02d}:{minute:02d}" if _time_stated(hour, minute, text) else None

    def phrase_ok(self, raw: str | None, ids: list[int]) -> bool:
        """Ibora (`due.raw`, `dates[].raw`) keltirilgan qatorlarda AYNAN aytilganmi -
        iqtibos kabi. To'qilgan "ertaga" jadvaldan o'tib "aniq" sana bo'lmasin."""
        return bool(raw) and self.quote_ok(raw, ids)

    def resolve_date(self, raw: str | None, model_value: Any, ids: list[int] | None = None, *,
                     event: bool = False) -> tuple[str | None, str, bool]:
        """(sana, asos, shubhali). Kod jadvali model bilan kelishmasa - kod g'olib.

        Muddat (`event=False`): o'tmish bo'lmaydi. Voqea (`dates[]`, `event=True`):
        yilsiz sana eng yaqin kunga, ~6 oy o'tmishgacha ham."""
        model_day = dates_mod.parse_iso(model_value)
        if not raw:
            # Ibora yo'q, sana bor - model qayerdan oldi? Sana qo'yilmaydi, belgi qo'yiladi.
            return None, "none", model_day is not None
        if ids is not None and not self.phrase_ok(raw, ids):
            return None, "none", True
        code_day, basis = dates_mod.resolve(raw, self.meeting_day, event=event)
        if basis == "past":
            return None, "none", True
        if basis == "vague":
            return None, "vague", model_day is not None
        if code_day is not None:
            if not event and code_day < self.meeting_day:
                return None, "none", True
            flagged = model_day is not None and model_day != code_day
            if not event and (code_day - self.meeting_day).days > 183:
                flagged = True                     # yilsiz sana bir yilga siljigan bo'lishi mumkin
            return code_day.isoformat(), basis, flagged
        if model_day is not None:
            if not event and model_day < self.meeting_day:
                return None, "none", True
            # Jadval iborani tanimadi - model sanasi qoladi, lekin "tekshiring".
            return model_day.isoformat(), "relative_resolved", True
        return None, "none", False

    def priority(self, value: Any, ids: list[int]) -> str | None:
        """`high` faqat shoshilinchlik AYTILGAN bo'lsa, `low` - ahamiyatsiz deyilgan bo'lsa."""
        level = self.enum(value, ("high", "normal", "low"), None)
        hay = self.context_text(ids)
        if level == "high" and _URGENT.search(hay) and not _NOT_URGENT.search(hay):
            return "high"
        if level == "low" and _NOT_URGENT.search(hay):
            return "low"
        return None

    # --- bo'limlar ---

    def _list(self, raw: Any, name: str, fn: Callable[[Any, str], Any]) -> list[Any]:
        out = []
        for i, item in enumerate(raw if isinstance(raw, list) else []):
            self.total += 1
            where = f"{name}[{i}]"
            if not isinstance(item, dict):
                self.invalid += 1
                self._err(where, "not an object")
                continue
            result = fn(item, where)
            if result is not None:
                out.append(result)
        return out

    def _need_ids(self, item: dict, where: str, quote: Any = None) -> list[int] | None:
        ids = self.evidence(item.get("sourceSegmentIds"), quote)
        if not ids:
            self.dropped += 1
            self._err(where, "no valid sourceSegmentIds")
            return None
        return ids

    def simple(self, item: dict, where: str) -> dict | None:
        text = self.text(item.get("text"), 400)
        if not text:
            self.invalid += 1
            self._err(where, "empty text")
            return None
        ids = self._need_ids(item, where)
        return {"text": text, "sourceSegmentIds": ids} if ids else None

    def decision(self, item: dict, where: str) -> dict | None:
        text = self.text(item.get("text"), 400)
        if not text:
            self.invalid += 1
            self._err(where, "empty text")
            return None
        quote = self.text(item.get("quote"), 300)
        ids = self._need_ids(item, where, quote)
        if not ids:
            return None
        needs = False
        if not quote or not self.quote_ok(quote, ids):
            needs = True
            quote = first_words(self.by_id[ids[0]]["text"])
        ref = item.get("ref")
        ref = str(ref).strip() if isinstance(ref, str) and re.fullmatch(r"\s*D\d+\s*", ref) else None
        return {
            "text": text,
            "status": self.enum(item.get("status"), ("final", "tentative", "conditional", "reversed"), "final"),
            "condition": self.text(item.get("condition"), 300),
            "rationale": self.text(item.get("rationale"), 300),
            "proposedBy": self.speakers_list(item.get("proposedBy")),
            "agreedBy": self.speakers_list(item.get("agreedBy")),
            "quote": quote, "needsConfirmation": needs, "verified": None, "sourceSegmentIds": ids, "ref": ref,
        }

    def action_item(self, item: dict, where: str) -> dict | None:
        task = self.text(item.get("task"), 300)
        if not task:
            self.invalid += 1
            self._err(where, "empty task")
            return None
        quote = self.text(item.get("quote"), 300)
        ids = self._need_ids(item, where, quote)
        if not ids:
            return None
        needs = False
        if not quote or not self.quote_ok(quote, ids):
            needs = True
            quote = first_words(self.by_id[ids[0]]["text"])
        owner_raw = item.get("owner") if isinstance(item.get("owner"), dict) else {}
        speaker = self.speaker(owner_raw.get("speaker"))
        name = self.text(owner_raw.get("name"), 80)
        if name and not self.grounded(name):
            name, needs = None, True
        kind = self.enum(owner_raw.get("kind"), ("person", "team", "role", "unknown"), "unknown")
        basis = self.enum(owner_raw.get("basis"), ("self_commitment", "assigned_and_accepted",
                                                   "assigned_no_reply", "volunteered", "unclear"), "unclear")
        if basis in ("assigned_no_reply", "unclear"):
            needs = True
        if kind == "person" and not speaker and not name:
            kind = "unknown"
        due_raw = item.get("due") if isinstance(item.get("due"), dict) else {}
        raw = self.text(due_raw.get("raw"), 80)
        day, day_basis, flagged = self.resolve_date(raw, due_raw.get("date"), ids)
        if raw and not self.phrase_ok(raw, ids):
            raw = None                               # ibora qatorlarda yo'q - ko'rsatilmaydi
        if flagged:
            needs = True
        clock = self.time(due_raw.get("time"), ids)
        if due_raw.get("time") and not clock:
            needs = True
        confidence = self.number(item.get("confidence"), 0.7)
        if confidence < 0.6:
            needs = True
        ref = item.get("ref")
        ref = str(ref).strip() if isinstance(ref, str) and re.fullmatch(r"\s*A\d+\s*", ref) else None
        return {
            "task": task, "deliverable": self.text(item.get("deliverable"), 200),
            "owner": {"speaker": speaker, "name": name, "kind": kind, "basis": basis},
            "assignedBy": self.speaker(item.get("assignedBy")),
            "due": {"raw": raw, "date": day, "time": clock, "basis": day_basis if (day or raw) else "none"},
            "priority": self.priority(item.get("priority"), ids),
            "status": self.enum(item.get("status"), ("open", "done_in_meeting"), "open"),
            "origin": self.enum(item.get("origin"), ("explicit", "implicit_commitment"), "explicit"),
            "condition": self.text(item.get("condition"), 300),
            "dependsOn": [], "quote": quote, "confidence": round(confidence, 2),
            "needsConfirmation": needs, "verified": None, "sourceSegmentIds": ids, "ref": ref,
        }

    def open_question(self, item: dict, where: str) -> dict | None:
        base = self.simple(item, where)
        if base is None:
            return None
        base.update({"raisedBy": self.speaker(item.get("raisedBy")),
                     "directedTo": self.speaker(item.get("directedTo")),
                     "whyOpen": self.enum(item.get("whyOpen"), ("no_answer", "no_owner", "deferred"), "no_answer")})
        return base

    def risk(self, item: dict, where: str) -> dict | None:
        base = self.simple(item, where)
        if base is None:
            return None
        base.update({"kind": self.enum(item.get("kind"), ("risk", "blocker", "objection", "concern"), "risk"),
                     "raisedBy": self.speaker(item.get("raisedBy")),
                     "severity": self.enum(item.get("severity"), ("high", "medium", "low"), None),
                     "mitigation": self.text(item.get("mitigation"), 300)})
        return base

    def number_item(self, item: dict, where: str) -> dict | None:
        value = self.text(item.get("value"), 80)
        if not value:
            self.invalid += 1
            self._err(where, "empty value")
            return None
        ids = self._need_ids(item, where)
        if not ids:
            return None
        hay = self.context_text(ids)
        digits = re.findall(r"\d+", value)
        if digits:
            # "1 500 000" va "1500000" ikkalasi ham bir raqam.
            known = set(re.findall(r"\d+", hay)) | set(re.findall(r"\d+", hay.replace(" ", "")))
            grounded = all(d in known for d in digits)
        else:
            grounded = any(w in hay for w in norm(value).split() if len(w) >= 3)
        if not grounded:
            # Shakldagi misol qiymat yoki to'qilgan raqam - "Raqamlar" bo'limiga kirmaydi.
            self.dropped += 1
            self._err(where, "the value is not in the cited lines")
            return None
        return {"value": value, "unit": self.text(item.get("unit"), 40),
                "what": self.text(item.get("what"), 300) or "", "sourceSegmentIds": ids}

    def date_item(self, item: dict, where: str) -> dict | None:
        raw = self.text(item.get("raw"), 80)
        if not raw:
            self.invalid += 1
            self._err(where, "empty raw")
            return None
        ids = self._need_ids(item, where)
        if not ids:
            return None
        if not self.phrase_ok(raw, ids):
            self.dropped += 1
            self._err(where, "raw is not in the cited lines")
            return None
        day, _, _ = self.resolve_date(raw, item.get("date"), ids, event=True)
        return {"date": day, "time": self.time(item.get("time"), ids), "raw": raw,
                "what": self.text(item.get("what"), 300) or "", "sourceSegmentIds": ids}

    def highlight(self, item: dict, where: str) -> dict | None:
        quote = self.text(item.get("quote"), 300)
        if not quote:
            self.invalid += 1
            self._err(where, "empty quote")
            return None
        ids = self.evidence([item.get("segmentId")], quote, limit=1)
        if not ids or not self.quote_ok(quote, ids):
            self.dropped += 1
            self._err(where, "quote not found in the cited line")
            return None
        return {"quote": quote, "segmentId": ids[0], "why": self.text(item.get("why"), 300) or "",
                "sourceSegmentIds": ids}

    def topic(self, item: dict, where: str) -> dict | None:
        title = self.text(item.get("title"), 120)
        if not title:
            self.invalid += 1
            self._err(where, "empty title")
            return None
        points = []
        raw_points = item.get("keyPoints") if isinstance(item.get("keyPoints"), list) else []
        for j, raw_point in enumerate(raw_points):
            self.total += 1
            if not isinstance(raw_point, dict):
                self.invalid += 1
                continue
            point = self.simple(raw_point, f"{where}.keyPoints[{j}]")
            if point:
                points.append(point)
        start = self.ids([item.get("startId")], 1)
        end = self.ids([item.get("endId")], 1)
        cited = [sid for p in points for sid in p["sourceSegmentIds"]]
        first = start[0] if start else (min(cited, key=self.pos.get) if cited else None)
        last = end[0] if end else (max(cited, key=self.pos.get) if cited else None)
        if first is None or last is None:
            self.dropped += 1
            self._err(where, "no startId/endId")
            return None
        if self.pos[first] > self.pos[last]:
            first, last = last, first
        return {"title": title, "summary": self.text(item.get("summary"), 800) or "",
                "outcome": self.enum(item.get("outcome"), ("decided", "open", "info"), "info"),
                "startSegmentId": first, "endSegmentId": last, "keyPoints": points}

    def _name_line_ok(self, speaker: str, sid: int, words: list[str]) -> bool:
        """Bitta dalil qatori ismni SHU spikerga bog'laydimi.

        * qatorni spikerning O'ZI aytgan - faqat o'zini tanishtirish ("men Azizman");
        * boshqa odam aytgan - murojaat: ism aytilgandan keyingi 1-2 qatorda SHU
          spiker javob beradi ("Aziz aka, ...?" -> keyingi qator S2 - demak S2 Aziz).
        "Men ertaga yuboraman, Aziz aka" - S2 Azizga MUROJAAT qildi, o'zi Aziz emas."""
        seg = self.by_id.get(sid)
        if seg is None:
            return False
        text = str(seg["text"]).lower().translate(_APOS)
        if not any(re.search(rf"(?<!\w){re.escape(w)}", text) for w in words):
            return False
        if seg.get("speaker") == speaker:
            return any(re.search(rf"{cue}\W+(?:\w+\W+)?{re.escape(w)}", text)
                       for cue in _INTRO_CUES for w in words)
        p = self.pos[sid]
        return any(self.by_id[self.order[q]].get("speaker") == speaker
                   for q in range(p + 1, min(len(self.order), p + 3)))

    @staticmethod
    def _plain_name(name: str) -> str | None:
        """Hurmat so'zlarisiz: "Aziz aka" -> "Aziz", "Azizjon" -> "Aziz"."""
        words = [w for w in name.split() if w.lower().strip(".,") not in _HONORIFIC_WORDS]
        out = []
        for w in words:
            low = w.lower()
            for suffix in ("jon", "xon"):
                if low.endswith(suffix) and len(w) - len(suffix) >= 3:
                    w = w[:-len(suffix)].rstrip("-")
            out.append(w)
        return " ".join(out) or None

    def participant(self, item: dict, where: str) -> dict | None:
        speaker = self.speaker(item.get("speaker"))
        if not speaker:
            return None
        name = self.text(item.get("suggestedName"), 60)
        evidence = self.ids(item.get("nameEvidence"), 3)
        if name:
            plain = self._plain_name(name) or ""
            words = list(dict.fromkeys(w for w in re.findall(r"\w+", f"{name} {plain}".lower().translate(_APOS))
                                       if len(w) >= 3 and w not in _HONORIFIC_WORDS))
            evidence = [sid for sid in evidence if words and self._name_line_ok(speaker, sid, words)]
            name = self._plain_name(name) if evidence else None
            if not name:
                evidence = []
        return {"speaker": speaker, "suggestedName": name, "nameEvidence": evidence if name else [],
                "role": self.text(item.get("role"), 80),
                "contribution": self.text(item.get("contribution"), 300)}

    def template_sections(self, raw: Any) -> list[dict]:
        out: dict[str, list[dict]] = {}
        for group in raw if isinstance(raw, list) else []:
            if not isinstance(group, dict):
                continue
            key = str(group.get("key") or "").strip()
            if key not in self.template_keys:
                continue
            items = []
            for i, item in enumerate(group.get("items") or [] if isinstance(group.get("items"), list) else []):
                self.total += 1
                if not isinstance(item, dict):
                    self.invalid += 1
                    continue
                base = self.simple(item, f"templateSections.{key}[{i}]")
                if base:
                    base["speaker"] = self.speaker(item.get("speaker"))
                    items.append(base)
            out.setdefault(key, []).extend(items)
        return [{"key": k, "items": v} for k, v in out.items()]

    def next_meeting(self, item: Any) -> dict | None:
        if not isinstance(item, dict):
            return None
        raw = self.text(item.get("raw"), 80)
        ids = self.evidence(item.get("sourceSegmentIds"))
        if not ids or not (raw or item.get("date")):
            return None
        if raw and not self.phrase_ok(raw, ids):
            raw = None                                # to'qilgan ibora - sanasi ham olinmaydi
        day = self.resolve_date(raw, item.get("date"), ids)[0] if raw else None
        clock = self.time(item.get("time"), ids)
        agenda = [a for a in (self.text(x, 200) for x in (item.get("agenda") or [])
                              if not isinstance(x, (dict, list))) if a][:10] \
            if isinstance(item.get("agenda"), list) else []
        if not (raw or day or clock or agenda):
            return None
        return {"date": day, "time": clock, "raw": raw, "agenda": agenda, "sourceSegmentIds": ids}

    def sentiment(self, item: Any) -> dict | None:
        if not isinstance(item, dict):
            return None
        return {"overall": self.enum(item.get("overall"), ("positive", "neutral", "mixed", "negative", "tense"),
                                     "neutral"),
                "note": self.text(item.get("note"), 300), "sourceSegmentIds": self.ids(item.get("sourceSegmentIds"))}

    def meeting_type(self, item: Any) -> dict:
        if not isinstance(item, dict):
            return {"value": "general", "confidence": 0.5}
        value = str(item.get("value") or "")
        if value not in templates.TEMPLATE_IDS or value in ("auto", "follow_up"):
            value = "general"
        return {"value": value, "confidence": round(self.number(item.get("confidence"), 0.5), 2)}

    def keywords(self, raw: Any) -> list[str]:
        out: list[str] = []
        for item in raw if isinstance(raw, list) else []:
            word = self.text(item, 40) if not isinstance(item, (dict, list)) else None
            if word and word.lower() not in (w.lower() for w in out):
                out.append(word)
        return out[:12]

    def items(self, data: dict[str, Any]) -> dict[str, Any]:
        """Hamma ro'yxat bo'limlari (extract va map uchun umumiy)."""
        return {
            "participants": [p for p in (self.participant(x, "participants") for x in
                                         (data.get("participants") or [] if isinstance(data.get("participants"), list)
                                          else []) if isinstance(x, dict)) if p],
            "topics": self._list(data.get("topics"), "topics", self.topic),
            "keyPoints": self._list(data.get("keyPoints"), "keyPoints", self.simple),
            "decisions": self._list(data.get("decisions"), "decisions", self.decision),
            "actionItems": self._list(data.get("actionItems"), "actionItems", self.action_item),
            "openQuestions": self._list(data.get("openQuestions"), "openQuestions", self.open_question),
            "risks": self._list(data.get("risks"), "risks", self.risk),
            "numbers": self._list(data.get("numbers"), "numbers", self.number_item),
            "dates": self._list(data.get("dates"), "dates", self.date_item),
            "nextSteps": self._list(data.get("nextSteps"), "nextSteps", self.simple),
            "nextMeeting": self.next_meeting(data.get("nextMeeting")),
            "highlights": self._list(data.get("highlights"), "highlights", self.highlight),
            "templateSections": self.template_sections(data.get("templateSections")),
        }

    def coverage_last(self, data: dict[str, Any]) -> int | None:
        return self._coverage(data, "lastId")

    def coverage_first(self, data: dict[str, Any]) -> int | None:
        return self._coverage(data, "firstId")

    @staticmethod
    def _coverage(data: dict[str, Any], key: str) -> int | None:
        cov = data.get("coverage") if isinstance(data, dict) else None
        if not isinstance(cov, dict):
            return None
        try:
            return int(cov.get(key))
        except (TypeError, ValueError):
            return None


# --- birlashtirish (kod, 6.6.3) ------------------------------------------------------


def _owner_key(item: dict) -> str:
    owner = item.get("owner") or {}
    if owner.get("speaker"):
        return f"s:{owner['speaker']}"
    if owner.get("name"):
        return f"n:{norm(owner['name'])}"
    return f"k:{owner.get('kind') or 'unknown'}"


def _join_ids(a: list[int], b: list[int], limit: int = 8) -> list[int]:
    out = list(a)
    for sid in b:
        if sid not in out:
            out.append(sid)
    return out[:limit]


class Merger:
    """Map bo'laklarini ketma-ket qo'shadi. Vazifalar va qarorlarga ichki `ref`
    (A1.., D1..) beriladi - keyingi bo'lak shu id bilan avvalgisini yangilaydi:
    vazifaning egasi o'zgardi ("buni Bobur qilsin"), qaror bekor bo'ldi
    ("yo'q, 18 mln qilamiz")."""

    def __init__(self) -> None:
        self.data: dict[str, Any] = {k: [] for k in ("topics", "keyPoints", "decisions", "actionItems",
                                                     "openQuestions", "risks", "numbers", "dates",
                                                     "nextSteps", "highlights")}
        self.participants: dict[str, dict] = {}
        self.sections: dict[str, list[dict]] = {}
        self.next_meeting: dict | None = None
        self.chunk_summaries: list[str] = []
        self._counter = 0
        self._dcounter = 0

    def running(self) -> list[dict]:
        return [i for i in self.data["actionItems"] if i.get("status") == "open"]

    def running_decisions(self) -> list[dict]:
        return [d for d in self.data["decisions"] if d.get("status") != "reversed"]

    def _dedupe(self, key: str, item: dict, sig: str) -> None:
        for existing in self.data[key]:
            if existing.get("_sig") == sig:
                existing["sourceSegmentIds"] = _join_ids(existing["sourceSegmentIds"], item["sourceSegmentIds"])
                return
        item["_sig"] = sig
        self.data[key].append(item)

    def _dedupe_similar(self, key: str, item: dict) -> None:
        for existing in self.data[key]:
            if similar(existing["text"], item["text"]):
                existing["sourceSegmentIds"] = _join_ids(existing["sourceSegmentIds"], item["sourceSegmentIds"])
                return
        self.data[key].append(item)

    def add(self, part: dict[str, Any]) -> None:
        if part.get("chunkSummary"):
            self.chunk_summaries.append(part["chunkSummary"])
        self.data["topics"].extend(dict(t) for t in part.get("topics") or [])
        for item in part.get("actionItems") or []:
            self._add_action(dict(item))
        for item in part.get("decisions") or []:
            self._add_decision(dict(item))
        for item in part.get("openQuestions") or []:
            self._dedupe_similar("openQuestions", dict(item))
        for key in ("keyPoints", "risks", "nextSteps"):
            for item in part.get(key) or []:
                self._dedupe(key, dict(item), norm(item["text"]))
        for item in part.get("numbers") or []:
            self._dedupe("numbers", dict(item), norm(f"{item['value']} {item.get('what') or ''}"))
        for item in part.get("dates") or []:
            self._dedupe("dates", dict(item), norm(f"{item['raw']} {item.get('what') or ''}"))
        for item in part.get("highlights") or []:
            self._dedupe("highlights", dict(item), f"{item['segmentId']}")
        for p in part.get("participants") or []:
            known = self.participants.get(p["speaker"])
            if known is None:
                self.participants[p["speaker"]] = dict(p)
                continue
            if not known.get("suggestedName") and p.get("suggestedName"):
                known.update(suggestedName=p["suggestedName"], nameEvidence=p.get("nameEvidence") or [])
            for name in ("role", "contribution"):
                if not known.get(name) and p.get(name):
                    known[name] = p[name]
        for group in part.get("templateSections") or []:
            bucket = self.sections.setdefault(group["key"], [])
            for item in group["items"]:
                sig = norm(item["text"])
                if all(norm(x["text"]) != sig for x in bucket):
                    bucket.append(dict(item))
        if part.get("nextMeeting"):
            self.next_meeting = dict(part["nextMeeting"])

    def _add_action(self, item: dict) -> None:
        ref = item.pop("ref", None)
        target = None
        if ref:
            target = next((x for x in self.data["actionItems"] if x["ref"] == ref), None)
        if target is None:
            key = _owner_key(item)
            target = next((x for x in self.data["actionItems"]
                           if _owner_key(x) == key and jaccard(x["task"], item["task"]) >= 0.6), None)
        if target is None:
            self._counter += 1
            item["ref"] = f"A{self._counter}"
            self.data["actionItems"].append(item)
            return
        if ref:
            # Keyingi bo'lak shu vazifani O'ZGARTIRDI - oxirgi shakli qoladi.
            target["task"] = item["task"]
        if item.get("status"):
            target["status"] = item["status"]
        if (item.get("due") or {}).get("raw") or (item.get("due") or {}).get("date"):
            target["due"] = item["due"]
        owner = item.get("owner") or {}
        has_owner = bool(owner.get("speaker") or owner.get("name"))
        if has_owner and (ref or not (target["owner"].get("speaker") or target["owner"].get("name"))):
            # `ref` bilan kelgan yangi ega - QAYTA TAYINLASH ("buni Bobur qilsin").
            target["owner"] = owner
            if item.get("assignedBy"):
                target["assignedBy"] = item["assignedBy"]
        target["sourceSegmentIds"] = _join_ids(target["sourceSegmentIds"], item["sourceSegmentIds"])
        target["needsConfirmation"] = bool(target.get("needsConfirmation") or item.get("needsConfirmation"))
        target["confidence"] = max(target.get("confidence") or 0, item.get("confidence") or 0)
        for name in ("priority", "deliverable", "assignedBy", "condition"):
            if item.get(name) and not target.get(name):
                target[name] = item[name]

    def _new_decision(self, item: dict) -> None:
        self._dcounter += 1
        item["ref"] = f"D{self._dcounter}"
        self.data["decisions"].append(item)

    def _add_decision(self, item: dict) -> None:
        ref = item.pop("ref", None)
        target = next((x for x in self.data["decisions"] if x.get("ref") == ref), None) if ref else None
        if target is not None and not similar(target["text"], item["text"]) and item["status"] != "reversed":
            # Keyingi bo'lak qarorni O'ZGARTIRDI: eskisi "bekor qilingan", yangisi - alohida.
            target["status"] = "reversed"
            target["rationale"] = target.get("rationale") or f"→ {item['text']}"
            self._new_decision(item)
            return
        if target is None:
            sig = norm(item["text"])
            target = next((x for x in self.data["decisions"]
                           if norm(x["text"]) == sig or similar(x["text"], item["text"])), None)
        if target is None:
            self._new_decision(item)
            return
        target["sourceSegmentIds"] = _join_ids(target["sourceSegmentIds"], item["sourceSegmentIds"])
        # Keyinroq aytilgan holat (masalan bekor qilish yoki "taxminiy" -> "yakuniy") g'olib.
        target["status"] = item["status"]
        target["needsConfirmation"] = bool(target["needsConfirmation"] or item["needsConfirmation"])
        for name in ("condition", "rationale"):
            if item.get(name):
                target[name] = item[name]

    def result(self) -> dict[str, Any]:
        out = {k: [{kk: vv for kk, vv in i.items() if kk != "_sig"} for i in v] for k, v in self.data.items()}
        out["participants"] = list(self.participants.values())
        out["templateSections"] = [{"key": k, "items": v} for k, v in self.sections.items()]
        out["nextMeeting"] = self.next_meeting
        return out


# --- quvur ----------------------------------------------------------------------------------


@dataclass
class SummaryInput:
    meeting_id: str
    rev: int
    recorded_at: float
    duration_sec: float
    language: str
    template: str
    segments: list[dict[str, Any]]
    speakers: list[dict[str, Any]]           # birlashtirilmaganlar: {id, name, talk_sec}
    marks: list[dict[str, Any]]              # {t, note}
    speakers_available: bool
    language_warning: str | None = None
    #: Ilova aytgan ishtirokchilar soni - 4 dan ko'p bo'lsa bitta yorliqda bir necha odam bo'lishi mumkin.
    expected_speakers: int | None = None


@dataclass
class SummaryOutput:
    status: str                               # ready | skipped
    template: str
    content: dict[str, Any] | None = None
    error_code: str | None = None


class Pipeline:
    def __init__(self, llm: Any, *, single_pass_chars: int = 30000, map_chars: int = 20000,
                 verify: bool = True, num_ctx: int = 0, extract_predict: int = 8192, map_predict: int = 6144,
                 write_predict: int = 3000, think: bool | None = None,
                 cache_get: Callable[[str, int, int], Any] | None = None,
                 cache_put: Callable[[str, int, int, Any], None] | None = None,
                 progress: Callable[[int, int], None] | None = None) -> None:
        self.llm = llm
        self.single_pass_chars = int(single_pass_chars)
        self.map_chars = int(map_chars)
        self.verify_enabled = bool(verify)
        self.num_ctx = int(num_ctx or 0)
        #: Javob byudjeti (token). Bitta 45 daqiqalik yig'ilish JSON i ~6-7K token -
        #: 4000 da bir o'tish deyarli doim kesilardi (spetsifikatsiya, build notes).
        self.extract_predict = int(extract_predict)
        self.map_predict = int(map_predict)
        self.write_predict = int(write_predict)
        self.think = think
        #: Map keshi: (aniqlangan shablon, birinchi id, oxirgi id) -> tekshirilgan bo'lak.
        self.cache_get = cache_get or (lambda t, a, b: None)
        self.cache_put = cache_put or (lambda t, a, b, c: None)
        self.progress = progress or (lambda done, total: None)
        self.warnings: list[str] = []
        self.steps = 0
        self.est_steps = 1
        self.chunks = 0
        self.coverage_ok = True
        self.dropped = 0
        self._parts_ok = 0

    # --- yordamchilar ---

    def _call(self, system: str, user: str, *, num_predict: int, temperature: float, op: str):
        result = call_llm(self.llm, system, user, num_predict=num_predict, temperature=temperature, op=op,
                          num_ctx=self.num_ctx, think=self.think)
        self.steps += 1
        self.progress(self.steps, max(self.est_steps, self.steps + 1))
        return result

    def _truncated(self, system: str, user: str, meta: dict[str, Any]) -> bool:
        if (meta or {}).get("doneReason") == "length":
            return True
        tokens_in = (meta or {}).get("tokensIn")
        if isinstance(tokens_in, int) and tokens_in > 0:
            estimated = (len(system) + len(user)) / CHARS_PER_TOKEN
            if tokens_in < PROMPT_CUT_RATIO * estimated:
                return True
        return False

    def _ask_json(self, system: str, user: str, *, num_predict: int, op: str,
                  validate: Callable[[dict], Validator | None], temperature: float = 0.1,
                  ) -> tuple[dict | None, Validator | None, dict, bool]:
        """Chaqiruv + bitta tuzatish urinishi. -> (obyekt, tekshiruvchi, meta, kesilganmi)."""
        text, meta = self._call(system, user, num_predict=num_predict, temperature=temperature, op=op)
        truncated = self._truncated(system, user, meta)
        data, salvaged = parse_json(text)
        checker = validate(data) if data is not None else None
        if truncated or salvaged:
            return data, checker, meta, True
        if data is not None and checker is not None and not checker.needs_repair:
            return data, checker, meta, False
        problems = (checker.errors if checker else []) or ["the reply was not one valid JSON object"]
        repair = (user + "\n\nYour previous reply was invalid: " + "; ".join(problems[:10]) +
                  ". Return only the corrected JSON object.")
        text2, meta2 = self._call(system, repair, num_predict=num_predict, temperature=0.0, op=op)
        data2, salvaged2 = parse_json(text2)
        checker2 = validate(data2) if data2 is not None else None
        if data2 is not None and not salvaged2:
            if checker2 is not None and checker2.bad_ratio > 0.3:
                self.warnings.append("validation_errors")
            if checker2 is not None and checker2.script_bad:
                self.warnings.append("wrong_script")
            return data2, checker2, meta2, self._truncated(system, repair, meta2)
        if data is not None:
            self.warnings.append("validation_errors")
            return data, checker, meta, False
        return None, None, meta2, False

    def _validator(self, inp: SummaryInput, segments: list[dict[str, Any]], template: str) -> Validator:
        return Validator(segments=segments, speakers={s["id"] for s in inp.speakers},
                         names=[s["name"] for s in inp.speakers if s.get("name")],
                         meeting_day=dates_mod.tashkent(inp.recorded_at).date(),
                         template_keys=tuple(templates.section_keys(template)), language=inp.language)

    def _names(self, inp: SummaryInput) -> dict[str, str]:
        return {s["id"]: s["name"] for s in inp.speakers if s.get("name")}

    def _meta(self, inp: SummaryInput) -> str:
        day = dates_mod.tashkent(inp.recorded_at)
        return prompts.meta_line(day.date(), dates_mod.WEEKDAYS["en"][day.weekday()], inp.duration_sec,
                                 inp.speakers, inp.speakers_available, inp.expected_speakers)

    def _marks(self, inp: SummaryInput) -> list[dict[str, Any]]:
        out = []
        for i, mark in enumerate(inp.marks or [], start=1):
            t = float(mark.get("t") or 0)
            ids = [int(s["id"]) for s in inp.segments if s["end"] >= t - 20 and s["start"] <= t + 10]
            out.append({"id": f"m{i}", "t": round(t, 2), "note": mark.get("note"), "segmentIds": ids})
        return out

    # --- asosiy ---

    def run(self, inp: SummaryInput) -> SummaryOutput:
        words = sum(len(str(s["text"]).split()) for s in inp.segments)
        if (inp.duration_sec or 0) < 10 or words < 30:
            return SummaryOutput("skipped", inp.template if inp.template != "auto" else "short_call",
                                 error_code="too_short")
        template, meeting_type = self._template(inp, words)
        names = self._names(inp)
        lines = [prompts.transcript_line(s, names) for s in inp.segments]
        total_chars = sum(len(line) + 1 for line in lines)
        marks = self._marks(inp)
        if total_chars <= self.single_pass_chars:
            self.est_steps = 2 + (1 if self.verify_enabled else 0)
            try:
                extracted = self._single(inp, template, lines, marks)
                self.chunks = 1
            except _Fallback:
                self.warnings.append("single_pass_fallback")
                extracted = self._long(inp, template, marks)
        else:
            extracted = self._long(inp, template, marks)
        if meeting_type is not None:
            extracted["meetingType"] = meeting_type
        if self.verify_enabled:
            self._verify(inp, extracted)
        content = self._finalise(inp, template, extracted, marks)
        return SummaryOutput("ready", template, content)

    def _template(self, inp: SummaryInput, words: int) -> tuple[str, dict | None]:
        if inp.template != "auto":
            return inp.template, None
        if (inp.duration_sec or 0) < 300 or words < 200:
            return "short_call", {"value": "short_call", "confidence": 1.0}
        names = self._names(inp)
        head, size = [], 0
        for seg in inp.segments:
            line = prompts.transcript_line(seg, names)
            if size + len(line) > 4000:
                break
            head.append(line)
            size += len(line) + 1
        user = (f"{self._meta(inp)}\nSpeakers: {len(inp.speakers)}.\n\n" + prompts.fence(head))
        try:
            text, _ = self._call(prompts.CLASSIFY_SYSTEM, user, num_predict=200, temperature=0.0,
                                 op="meeting_classify")
        except LlmFailed:
            self.warnings.append("classifier_failed")
            return "general", {"value": "general", "confidence": 0.0}
        data, _ = parse_json(text)
        value = str((data or {}).get("template") or "")
        confidence = Validator.number((data or {}).get("confidence"), 0.0)
        tpl = templates.TEMPLATES.get(value)
        if tpl is None or not tpl.auto or confidence < 0.55:
            return "general", {"value": value if tpl and tpl.auto else "general", "confidence": round(confidence, 2)}
        return value, {"value": value, "confidence": round(confidence, 2)}

    def _single(self, inp: SummaryInput, template: str, lines: list[str], marks: list[dict]) -> dict[str, Any]:
        system = prompts.extract_system(template)
        user = prompts.user_message(meta=self._meta(inp), language=inp.language, template_id=template,
                                    marks=prompts.marks_block(marks), running="", lines=lines)
        def validate(data: dict) -> Validator:
            checker = self._validator(inp, inp.segments, template)
            checker.result = checker.items(data)
            checker.check_script(data)
            return checker

        data, checker, _, truncated = self._ask_json(system, user, num_predict=self.extract_predict,
                                                     op="meeting_extract", validate=validate)
        if data is None or checker is None:
            raise _Fallback()
        last, first = checker.coverage_last(data), checker.coverage_first(data)
        if truncated or (last is not None and last < int(inp.segments[-1]["id"])) \
                or (first is not None and first > int(inp.segments[0]["id"])):
            raise _Fallback()
        items = checker.result
        self._quality(checker)
        out = dict(items)
        out.update({
            "title": checker.text(data.get("title"), 80),
            "meetingType": checker.meeting_type(data.get("meetingType")),
            "overview": checker.text(data.get("overview"), 1500) or "",
            "purpose": checker.text(data.get("purpose"), 400),
            "keywords": checker.keywords(data.get("keywords")),
            "sentiment": checker.sentiment(data.get("sentiment")),
            "followUpMessage": self._follow_up(checker, data.get("followUpMessage")) if template == "follow_up"
            else None,
        })
        return out

    def _quality(self, checker: Validator) -> None:
        self.dropped += checker.dropped

    @staticmethod
    def _follow_up(checker: Validator, raw: Any) -> dict | None:
        if not isinstance(raw, dict):
            return None
        body = checker.text(raw.get("body"), 4000, keep_lines=True)
        return {"subject": checker.text(raw.get("subject"), 150), "body": body} if body else None

    # --- uzun yo'l: map -> merge -> writer ---

    def _chunks(self, inp: SummaryInput) -> list[list[dict[str, Any]]]:
        names = self._names(inp)
        out: list[list[dict]] = []
        current: list[dict] = []
        size = 0
        for seg in inp.segments:
            length = len(prompts.transcript_line(seg, names)) + 1
            if current and size + length > self.map_chars:
                out.append(current)
                current, size = [], 0
            current.append(seg)
            size += length
        if current:
            out.append(current)
        return out

    def _long(self, inp: SummaryInput, template: str, marks: list[dict]) -> dict[str, Any]:
        chunks = self._chunks(inp)
        self.est_steps = self.steps + len(chunks) + 1 + (1 if self.verify_enabled else 0)
        merger = Merger()
        self._parts_ok = 0
        for chunk in chunks:
            self._map_chunk(inp, template, chunk, marks, merger, depth=0)
        if not self._parts_ok:
            raise LlmFailed("hech bir bo'lak xulosalanmadi")
        merged = merger.result()
        merged["chunkSummaries"] = merger.chunk_summaries
        self._write(inp, template, merged, marks)
        return merged

    def _map_chunk(self, inp: SummaryInput, template: str, chunk: list[dict], marks: list[dict],
                   merger: Merger, depth: int) -> None:
        first, last = int(chunk[0]["id"]), int(chunk[-1]["id"])
        cached = self.cache_get(template, first, last)
        if cached is not None:
            merger.add(cached)
            self.chunks += 1
            self._parts_ok += 1
            return
        names = self._names(inp)
        index = next(i for i, s in enumerate(inp.segments) if int(s["id"]) == first)
        context = inp.segments[max(0, index - 2):index]
        lines = [prompts.transcript_line(s, names, context=True) for s in context]
        lines += [prompts.transcript_line(s, names) for s in chunk]
        ids = {int(s["id"]) for s in chunk}
        chunk_marks = [m for m in marks if any(sid in ids for sid in m["segmentIds"])]
        running = [{"ref": i["ref"], "task": i["task"], "owner": i["owner"], "due": i["due"]}
                   for i in merger.running()]
        decisions = [{"ref": d["ref"], "text": d["text"], "status": d["status"]}
                     for d in merger.running_decisions()]
        system = prompts.map_system()
        user = prompts.user_message(meta=self._meta(inp), language=inp.language, template_id=template,
                                    marks=prompts.marks_block(chunk_marks),
                                    running=prompts.running_block(running, decisions), lines=lines)
        refs = {i["ref"] for i in running}
        drefs = {d["ref"] for d in decisions}

        def validate(data: dict) -> Validator:
            checker = self._validator(inp, inp.segments, template)
            items = checker.items(data)
            for item in items["actionItems"]:
                if item.get("ref") not in refs:
                    item["ref"] = None
            for item in items["decisions"]:
                if item.get("ref") not in drefs:
                    item["ref"] = None
            items["chunkSummary"] = checker.text(data.get("chunkSummary"), 1500) or ""
            checker.result = items
            checker.check_script(data)
            return checker

        data, checker, _, truncated = self._ask_json(system, user, num_predict=self.map_predict, op="meeting_map",
                                                     validate=validate)
        last_seen = checker.coverage_last(data) if (checker and data) else None
        first_seen = checker.coverage_first(data) if (checker and data) else None
        if (last_seen is not None and last_seen < last) or (first_seen is not None and first_seen > first):
            truncated = True
        if ((truncated and depth < 2) or (data is None and depth < 1)) and len(chunk) >= 2:
            # Kesilgan YOKI ikki marta o'qib bo'lmagan bo'lak - ikkiga bo'linadi.
            half = len(chunk) // 2
            self.est_steps += 2
            self._map_chunk(inp, template, chunk[:half], marks, merger, depth + 1)
            self._map_chunk(inp, template, chunk[half:], marks, merger, depth + 1)
            return
        if data is None or checker is None:
            # Bo'lakning vazifa va qarorlari yo'q - "to'liq" deb aytilmaydi.
            self.warnings.append(f"part_dropped:#{first}-#{last}")
            self.coverage_ok = False
            return
        if truncated:
            self.warnings.append(f"part_truncated:#{first}-#{last}")
            self.coverage_ok = False
        part = checker.result
        self._quality(checker)
        self.cache_put(template, first, last, part)
        merger.add(part)
        self.chunks += 1
        self._parts_ok += 1

    def _write(self, inp: SummaryInput, template: str, merged: dict[str, Any], marks: list[dict]) -> None:
        topics = merged["topics"]
        for i, topic in enumerate(topics, start=1):
            topic["_ref"] = f"T{i}"
        decisions = merged["decisions"]
        for i, dec in enumerate(decisions, start=1):
            dec["_ref"] = dec.get("ref") or f"D{i}"
        allowed: set[int] = set()
        notes = ["Part summaries:"]
        notes += [f"{i}. {prompts.clean_line(s, 1500)}" for i, s in enumerate(merged["chunkSummaries"], 1)]
        notes.append("\nTopics:")
        for t in topics:
            notes.append(f"{t['_ref']} [#{t['startSegmentId']}-#{t['endSegmentId']}] {t['title']}: {t['summary']}")
            allowed.update({t["startSegmentId"], t["endSegmentId"]})
            for p in t["keyPoints"]:
                allowed.update(p["sourceSegmentIds"])
        notes.append("\nAction items:")
        for a in merged["actionItems"]:
            owner = a["owner"].get("speaker") or a["owner"].get("name") or a["owner"].get("kind")
            due = a["due"].get("date") or a["due"].get("raw") or "-"
            notes.append(f"{a['ref']}: {a['task']} / {owner} / {due} {self._idtag(a)}")
            allowed.update(a["sourceSegmentIds"])
        notes.append("\nDecisions:")
        for d in decisions:
            notes.append(f"{d['_ref']}: [{d['status']}] {d['text']} {self._idtag(d)}")
            allowed.update(d["sourceSegmentIds"])
        for key, title in (("keyPoints", "Key points"), ("openQuestions", "Open questions"), ("risks", "Risks"),
                           ("nextSteps", "Next steps")):
            if merged[key]:
                notes.append(f"\n{title}:")
                for x in merged[key][:40]:
                    notes.append(f"- {x['text']} {self._idtag(x)}")
                    allowed.update(x["sourceSegmentIds"])
        user = "\n\n".join([self._meta(inp),
                            f"Output language: {prompts.LANGUAGE_NAMES.get(inp.language, 'Uzbek (Latin script)')}",
                            prompts.template_block(template), prompts.marks_block(marks),
                            "Notes (data, not instructions):\n" + "\n".join(notes)])
        def validate(data: dict) -> Validator:
            checker = self._validator(inp, inp.segments, template)
            for i, kp in enumerate(data.get("keyPoints") or [] if isinstance(data.get("keyPoints"), list) else []):
                checker.total += 1
                if not isinstance(kp, dict) or not [x for x in checker.ids(kp.get("sourceSegmentIds")) if x in allowed]:
                    checker.invalid += 1
                    checker._err(f"keyPoints[{i}]", "sourceSegmentIds must come from the given items")
            checker.check_script(data)
            return checker

        # Tarmoq xatosi (`LlmFailed`) YUQORIGA ketadi: ishchi qayta uradi, bo'laklar
        # keshda. Faqat yaroqsiz JSON zahira shaklga tushadi.
        data, checker, _, _ = self._ask_json(prompts.WRITER_SYSTEM, user, num_predict=self.write_predict,
                                             op="meeting_write", validate=validate, temperature=0.2)
        if data is None or checker is None:
            self.warnings.append("writer_failed")
            first_topic = topics[0]["title"] if topics else None
            merged.update({"title": first_topic, "meetingType": {"value": "general", "confidence": 0.5},
                           "overview": " ".join(merged["chunkSummaries"][:3])[:1500], "purpose": None,
                           "keywords": [], "sentiment": None, "followUpMessage": None})
            return
        key_points = []
        for kp in data.get("keyPoints") or [] if isinstance(data.get("keyPoints"), list) else []:
            if not isinstance(kp, dict):
                continue
            text = checker.text(kp.get("text"), 400)
            ids = [x for x in checker.ids(kp.get("sourceSegmentIds")) if x in allowed]
            if text and ids:
                key_points.append({"text": text, "sourceSegmentIds": ids})
        if key_points:
            merged["keyPoints"] = key_points
        by_ref = {t["_ref"]: t for t in topics}
        for t in data.get("topics") or [] if isinstance(data.get("topics"), list) else []:
            if isinstance(t, dict) and str(t.get("ref")) in by_ref:
                target = by_ref[str(t.get("ref"))]
                target["title"] = checker.text(t.get("title"), 120) or target["title"]
                target["summary"] = checker.text(t.get("summary"), 800) or target["summary"]
        self._apply_duplicates(merged, data.get("duplicateGroups"))
        merged.update({
            "title": checker.text(data.get("title"), 80),
            "meetingType": checker.meeting_type(data.get("meetingType")),
            "overview": checker.text(data.get("overview"), 1500) or " ".join(merged["chunkSummaries"][:3])[:1500],
            "purpose": checker.text(data.get("purpose"), 400),
            "keywords": checker.keywords(data.get("keywords")),
            "sentiment": checker.sentiment(data.get("sentiment")),
            "followUpMessage": self._follow_up(checker, data.get("followUpMessage")) if template == "follow_up"
            else None,
        })

    @staticmethod
    def _idtag(item: dict) -> str:
        return "[" + ",".join(f"#{i}" for i in item["sourceSegmentIds"]) + "]"

    @staticmethod
    def _apply_duplicates(merged: dict[str, Any], groups: Any) -> None:
        """Yozuvchi aytgan takrorlar KOD bilan birlashtiriladi: vazifalar - FAQAT egalari
        bir xil bo'lsa, qarorlar - FAQAT raqamlari bir xil bo'lsa ("15 mln" != "18 mln")."""
        actions = {i["ref"]: i for i in merged["actionItems"]}
        decisions = {d["_ref"]: d for d in merged["decisions"] if d.get("_ref")}
        removed: set[str] = set()
        for group in groups if isinstance(groups, list) else []:
            if not isinstance(group, list):
                continue
            for pool, same in ((actions, lambda a, b: _owner_key(a) == _owner_key(b)),
                               (decisions, lambda a, b: _digits(a["text"]) == _digits(b["text"]))):
                refs = [str(r) for r in group if str(r) in pool and str(r) not in removed]
                if len(refs) < 2:
                    continue
                keep = pool[refs[0]]
                for ref in refs[1:]:
                    other = pool[ref]
                    if not same(keep, other):
                        continue
                    keep["sourceSegmentIds"] = _join_ids(keep["sourceSegmentIds"], other["sourceSegmentIds"])
                    keep["needsConfirmation"] = bool(keep["needsConfirmation"] or other["needsConfirmation"])
                    removed.add(ref)
        merged["actionItems"] = [i for i in merged["actionItems"] if i["ref"] not in removed]
        merged["decisions"] = [d for d in merged["decisions"] if d.get("_ref") not in removed]

    # --- tekshiruvchi chaqiruv (6.6.5) ---

    def _verify(self, inp: SummaryInput, extracted: dict[str, Any]) -> None:
        names = self._names(inp)
        by_id = {int(s["id"]): s for s in inp.segments}
        order = [int(s["id"]) for s in inp.segments]
        pos = {sid: i for i, sid in enumerate(order)}
        entries: list[tuple[str, dict]] = []
        entries += [(f"A{i}", item) for i, item in enumerate(extracted.get("actionItems") or [], start=1)]
        entries += [(f"D{i}", item) for i, item in enumerate(extracted.get("decisions") or [], start=1)]
        # Ochiq savollar va xavflar - kam, lekin to'qilgani ham zararli (hech kim so'ramagan savol).
        entries += [(f"Q{i}", item) for i, item in enumerate(extracted.get("openQuestions") or [], start=1)]
        entries += [(f"R{i}", item) for i, item in enumerate(extracted.get("risks") or [], start=1)]
        if not entries:
            return
        unsupported: set[int] = set()
        for start in range(0, len(entries), 25):
            batch = entries[start:start + 25]
            blocks = []
            for ref, item in batch:
                if ref.startswith("A"):
                    owner = item["owner"].get("speaker") or item["owner"].get("name") or item["owner"].get("kind")
                    due = item["due"].get("date") or "-"
                    if item["due"].get("time"):
                        due += " " + item["due"]["time"]
                    head = (f"{ref} | task: {item['task']} | owner: {owner} (basis: {item['owner'].get('basis')}) | "
                            f"due: {due} (said: {item['due'].get('raw') or '-'})")
                elif ref.startswith("D"):
                    head = f"{ref} | decision ({item['status']}): {item['text']}"
                elif ref.startswith("Q"):
                    head = f"{ref} | open question: {item['text']}"
                else:
                    head = f"{ref} | risk: {item['text']}"
                chosen: list[int] = []
                for sid in item["sourceSegmentIds"]:
                    p = pos.get(sid)
                    if p is None:
                        continue
                    for q in (p - 1, p, p + 1):
                        if 0 <= q < len(order) and order[q] not in chosen:
                            chosen.append(order[q])
                lines = [prompts.transcript_line(by_id[s], names) for s in sorted(chosen, key=pos.get)]
                blocks.append(head + "\n" + "\n".join("   " + line for line in lines))
            user = (self._meta(inp) + "\n\n" + prompts.fence(blocks))
            try:
                text, _ = self._call(prompts.VERIFY_SYSTEM, user, num_predict=1500, temperature=0.0,
                                     op="meeting_verify")
            except (LlmFailed, LlmRateLimited, LlmBusy):
                self.warnings.append("verify_failed")
                break
            data, _ = parse_json(text)
            results = {}
            for row in (data or {}).get("results") or [] if isinstance((data or {}).get("results"), list) else []:
                if isinstance(row, dict) and row.get("id"):
                    results[str(row["id"]).strip()] = row
            for ref, item in batch:
                row = results.get(ref)
                if row is None:
                    continue
                if ref[0] in "QR":
                    if row.get("supported") is False:
                        unsupported.add(id(item))
                    continue
                ok = all(row.get(k) is not False
                         for k in ("supported", "ownerCorrect", "acceptanceCorrect", "dueCorrect"))
                item["verified"] = ok
                if not ok:
                    item["needsConfirmation"] = True
        if unsupported:
            for key in ("openQuestions", "risks"):
                kept = [x for x in extracted.get(key) or [] if id(x) not in unsupported]
                self.dropped += len(extracted.get(key) or []) - len(kept)
                extracted[key] = kept

    # --- hal qilinmagan masalalar (Plaud "AI Suggestion" o'rnida, modelsiz) ---

    @staticmethod
    def _follow_ups(content: dict[str, Any]) -> list[dict[str, Any]]:
        """Kuzatish kerak bo'lgan narsalar BIR JOYDA: ochiq savollar, taxminiy yoki shartli
        qarorlar, egasiz / muddatsiz / shartli ochiq vazifalar, yechimsiz xavflar. Har biri
        o'z elementiga havola (`ref`) va sabab kodlari bilan - maslahat to'qilmaydi."""
        out: list[dict[str, Any]] = []

        def add(kind: str, item: dict, text: str, reasons: list[str]) -> None:
            out.append({"id": f"F{len(out) + 1}", "kind": kind, "ref": item["id"], "text": text,
                        "reasons": reasons, "sourceSegmentIds": list(item.get("sourceSegmentIds") or []),
                        "start": item.get("start")})

        for q in content.get("openQuestions") or []:
            add("openQuestion", q, q["text"], [q.get("whyOpen") or "no_answer"])
        for d in content.get("decisions") or []:
            if d["status"] in ("tentative", "conditional"):
                text = f"{d['text']} ({d['condition']})" if d.get("condition") else d["text"]
                add("decision", d, text, [d["status"]])
        for a in content.get("actionItems") or []:
            if a.get("status") != "open":
                continue
            owner, due = a.get("owner") or {}, a.get("due") or {}
            reasons = []
            if owner.get("kind") == "unknown" or not (owner.get("speaker") or owner.get("name")
                                                      or owner.get("kind") in ("team", "role")):
                reasons.append("no_owner")
            if not due.get("date"):
                reasons.append("no_due")
            if a.get("condition"):
                reasons.append("conditional")
            if reasons:
                add("actionItem", a, a["task"], reasons)
        for r in content.get("risks") or []:
            if not r.get("mitigation"):
                add("risk", r, r["text"], ["no_mitigation"])
        return out[:CAP_DEFAULT]

    # --- yakun (6.6.6) ---

    def _finalise(self, inp: SummaryInput, template: str, ex: dict[str, Any], marks: list[dict]) -> dict[str, Any]:
        by_id = {int(s["id"]): s for s in inp.segments}

        def start_of(ids: list[int]) -> float | None:
            return round(float(by_id[ids[0]]["start"]), 2) if ids and ids[0] in by_id else None

        def ev(item: dict) -> dict:
            ids = list(item.get("sourceSegmentIds") or [])
            return {"sourceSegmentIds": ids, "start": start_of(ids)}

        def cap(key: str, items: list) -> list:
            return items[:CAPS.get(key, CAP_DEFAULT)]

        topics = []
        for i, t in enumerate(cap("topics", ex.get("topics") or []), start=1):
            first, last = t["startSegmentId"], t["endSegmentId"]
            topics.append({"id": f"T{i}", "title": t["title"], "summary": t["summary"], "outcome": t["outcome"],
                           "startSegmentId": first, "endSegmentId": last,
                           "start": round(float(by_id[first]["start"]), 2) if first in by_id else 0.0,
                           "end": round(float(by_id[last]["end"]), 2) if last in by_id else 0.0,
                           "keyPoints": [{"text": p["text"], **ev(p)} for p in t["keyPoints"]]})

        def topic_of(ids: list[int]) -> str | None:
            if not ids:
                return None
            for t in topics:
                if t["startSegmentId"] <= ids[0] <= t["endSegmentId"]:
                    return t["id"]
            return None

        def numbered(key: str, prefix: str, fields: tuple[str, ...]) -> list[dict]:
            out = []
            for i, item in enumerate(cap(key, ex.get(key) or []), start=1):
                out.append({"id": f"{prefix}{i}", **{f: item.get(f) for f in fields}, **ev(item)})
            return out

        decisions = []
        for i, d in enumerate(cap("decisions", ex.get("decisions") or []), start=1):
            decisions.append({"id": f"D{i}", "text": d["text"], "status": d["status"], "condition": d["condition"],
                              "rationale": d["rationale"], "proposedBy": d["proposedBy"], "agreedBy": d["agreedBy"],
                              "topicId": topic_of(d["sourceSegmentIds"]), "quote": d["quote"],
                              "needsConfirmation": bool(d["needsConfirmation"]), "verified": d.get("verified"),
                              **ev(d)})
        actions = []
        for i, a in enumerate(cap("actionItems", ex.get("actionItems") or []), start=1):
            actions.append({"id": f"A{i}", "task": a["task"], "deliverable": a.get("deliverable"),
                            "condition": a.get("condition"),
                            "owner": a["owner"], "assignedBy": a.get("assignedBy"), "due": a["due"],
                            "priority": a.get("priority"), "status": a.get("status") or "open",
                            "origin": a.get("origin") or "explicit", "dependsOn": [],
                            "topicId": topic_of(a["sourceSegmentIds"]), "quote": a["quote"],
                            "confidence": a.get("confidence", 0.7),
                            "needsConfirmation": bool(a.get("needsConfirmation")), "verified": a.get("verified"),
                            **ev(a)})
        highlights = []
        for i, h in enumerate(cap("highlights", ex.get("highlights") or []), start=1):
            seg = by_id.get(h["segmentId"]) or {}
            highlights.append({"id": f"H{i}", "quote": h["quote"], "speaker": seg.get("speaker"),
                               "segmentId": h["segmentId"], "start": round(float(seg.get("start") or 0), 2),
                               "why": h["why"], "fromMark": None})
        next_meeting = ex.get("nextMeeting")
        if next_meeting:
            next_meeting = {"date": next_meeting["date"], "time": next_meeting["time"], "raw": next_meeting["raw"],
                            "agenda": next_meeting["agenda"], **ev(next_meeting)}
        sentiment = ex.get("sentiment")
        if sentiment:
            sentiment = {"overall": sentiment["overall"], "note": sentiment["note"], **ev(sentiment)}
        content: dict[str, Any] = {
            "topics": topics,
            "keyPoints": numbered("keyPoints", "K", ("text",)),
            "decisions": decisions,
            "actionItems": actions,
            "openQuestions": numbered("openQuestions", "Q", ("text", "raisedBy", "directedTo", "whyOpen")),
            "risks": numbered("risks", "R", ("text", "kind", "raisedBy", "severity", "mitigation")),
            "numbers": numbered("numbers", "N", ("value", "unit", "what")),
            "dates": numbered("dates", "E", ("date", "time", "raw", "what")),
            "nextSteps": numbered("nextSteps", "X", ("text",)),
            "nextMeeting": next_meeting,
            "highlights": highlights,
            "keywords": (ex.get("keywords") or [])[:12],
            "sentiment": sentiment,
            "templateSections": [{"key": g["key"], "items": [
                {"text": x["text"], "speaker": x.get("speaker"), **ev(x)} for x in g["items"][:CAP_DEFAULT]]}
                for g in ex.get("templateSections") or [] if g["items"]],
        }
        if template == "short_call":
            # Qisqa qo'ng'iroqda ham narx, ochiq savol, keyingi uchrashuv va muhim lahza QOLADI.
            for key in ("topics", "keyPoints", "risks", "nextSteps", "keywords", "templateSections"):
                content[key] = []
            content["sentiment"] = None
        elif len(inp.segments) >= 20:
            covered: set[int] = set()
            pos = {int(s["id"]): i for i, s in enumerate(inp.segments)}
            for t in content["topics"]:
                a, b = pos.get(t["startSegmentId"]), pos.get(t["endSegmentId"])
                if a is not None and b is not None:
                    covered.update(range(min(a, b), max(a, b) + 1))
            if len(covered) < 0.8 * len(inp.segments):
                # Mavzular yig'ilishning bir qismini qoplamaydi - "bobsiz" joy bor.
                self.warnings.append("topics_gap")
        content["followUps"] = self._follow_ups(content)
        # Gapirish ulushi va taklif qilingan ismlar - kod hisoblaydi.
        total_talk = sum(float(s.get("talk_sec") or 0) for s in inp.speakers) or 0.0
        suggested = {p["speaker"]: p for p in ex.get("participants") or []}
        participants = []
        for sp in inp.speakers:
            p = suggested.get(sp["id"]) or {}
            talk = round(float(sp.get("talk_sec") or 0), 2)
            participants.append({"speaker": sp["id"], "suggestedName": p.get("suggestedName"),
                                 "nameEvidence": p.get("nameEvidence") or [], "role": p.get("role"),
                                 "contribution": p.get("contribution"),
                                 "talkSec": talk, "talkShare": round(talk / total_talk, 3) if total_talk else 0.0})
        # Foydalanuvchi belgilari: har biri biror element bilan qoplanishi SHART.
        user_marks = []
        for mark in marks:
            window = set(mark["segmentIds"])
            covered = []
            for key in ("decisions", "actionItems", "keyPoints", "openQuestions", "risks", "numbers", "dates",
                        "nextSteps"):
                for item in content[key]:
                    if window & set(item["sourceSegmentIds"]):
                        covered.append(item["id"])
            for t in content["topics"]:
                for kp in t["keyPoints"]:
                    if window & set(kp["sourceSegmentIds"]) and t["id"] not in covered:
                        covered.append(t["id"])
            for h in content["highlights"]:
                if h["segmentId"] in window:
                    covered.append(h["id"])
            if not covered and inp.segments:
                seg = min(inp.segments, key=lambda s: (int(s["id"]) not in window, abs(float(s["start"]) - mark["t"])))
                hid = f"H{len(content['highlights']) + 1}"
                note = mark.get("note") or {"ru": "Отмечено пользователем", "en": "Marked by the user"}.get(
                    inp.language, "Foydalanuvchi belgilagan lahza")
                content["highlights"].append({"id": hid, "quote": first_words(seg["text"]),
                                              "speaker": seg.get("speaker"), "segmentId": int(seg["id"]),
                                              "start": round(float(seg["start"]), 2), "why": note,
                                              "fromMark": mark["id"]})
                covered = [hid]
            else:
                for h in content["highlights"]:
                    if h["id"] in covered and h["fromMark"] is None:
                        h["fromMark"] = mark["id"]
            user_marks.append({"id": mark["id"], "t": mark["t"], "note": mark.get("note"),
                               "segmentIds": mark["segmentIds"], "coveredBy": covered})
        day = dates_mod.tashkent(inp.recorded_at)
        lang = inp.language if inp.language in dates_mod.WEEKDAYS else "uz"
        flagged = sum(1 for x in actions + decisions if x["needsConfirmation"])
        title = ex.get("title") or (topics[0]["title"] if topics else None) or ""
        meeting_type = ex.get("meetingType") or {"value": template if template in templates.TEMPLATE_IDS
                                                 else "general", "confidence": 0.5}
        return {
            "schemaVersion": SCHEMA_VERSION,
            "template": template, "language": inp.language,
            "meeting": {"date": day.date().isoformat(), "weekday": dates_mod.WEEKDAYS[lang][day.weekday()],
                        "timezone": "Asia/Tashkent", "durationSec": round(float(inp.duration_sec or 0), 2),
                        "speakerCount": len(inp.speakers)},
            "title": title[:80],
            "meetingType": meeting_type,
            "overview": ex.get("overview") or "",
            "purpose": ex.get("purpose"),
            "participants": participants,
            **content,
            "userMarks": user_marks,
            "followUpMessage": ex.get("followUpMessage") if template == "follow_up" else None,
            "quality": {"warnings": list(dict.fromkeys(self.warnings)),
                        "droppedItems": int(self.dropped), "flaggedItems": flagged,
                        "chunks": self.chunks, "coverageOk": self.coverage_ok,
                        "speakersAvailable": bool(inp.speakers_available),
                        "languageWarning": inp.language_warning},
        }
