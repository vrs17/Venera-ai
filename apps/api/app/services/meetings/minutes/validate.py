"""Bayonnoma JSON ini tekshirish va tozalash (model javobi -> saqlanadigan mazmun).

SHARTNOMA:

    class Invalid(ValueError)                  # shakl yaroqsiz (bo'limlar ham, kun tartibi ham yo'q)
    def validate(data: dict, *, lang: str, segments: list[dict], speakers: list[dict])
            -> tuple[dict, list[str]]          # (tozalangan mazmun, ogohlantirishlar)

Tekshiruvlar: kalitlar/turlar (`shapes.minutes` shakli; yetishmagan maydon default bilan to'ldiriladi,
ortiqchasi tashlanadi); matn tozalash (`export.clean`, boshqaruv belgilari, bo'shliqlar); chegaralar
(kun tartibi <= 12, bo'limlar <= 12, bandlar jami <= 120, band matni <= 1500, bayon <= 6000,
kichik bandlar <= 12 x 500, izohlar <= 20) - oshgani qisqartiriladi va `warning`; `sourceSegmentIds`
faqat MAVJUD qator id lari (yo'qlari tashlanadi; umuman qolmasa `ungrounded_item` ogohlantirish, band
qoladi); `agendaIndex` 1..len(agenda) (bo'lmasa oxirgi bandga qo'shiladi / `agenda_index`); `kind`
noma'lum -> `other`; `confidence` 0..1; `deadlineDate` YYYY-MM-DD bo'lmasa `None`.

ASOSLASH (to'qima ismlarga qarshi): `responsible` dagi har ism yoki `[S#]` token. Ism transkriptda
(normallashtirilgan: `summarize.norm`, tutuq belgilari, kirill/lotin FARQLANMAYDI - lotin transkriptda
"Aziz" bo'lsa kirill "Азиз" asosli) yoki spiker nomlarida bo'lmasa - band matnidagi o'sha ism
`text.BLANK` ga almashtiriladi, `ungrounded_name:<ism>` ogohlantirish. Raqamlar: band/bayon matnidagi
raqam guruhlari transkriptda bo'lmasa `unverified_number:<raqam>` (matn o'zgarmaydi).

YOZUV: `lang` kirill tillari (uz-cyrl, ru) uchun harflarning >= 60% kirill bo'lmasa `script_mismatch`;
uz-latn/en uchun lotin. Faqat ogohlantirish - hujjat chiqadi.

NEGA ISMLAR SHUNDAY SOLISHTIRILADI. Transkript ko'pincha lotin o'zbekcha (GAPI), hujjat esa kirillda:
model "Aziz aka"ni "Азиз" deb yozadi - bu to'qima emas. Shuning uchun ikkala tomon ham `norm` dan keyin
kirill->lotin jadvali bilan "buklanadi" va tutuq belgilari olib tashlanadi ("Ўткир" = "O'tkir" = "otkir").
O'zbek qo'shimchalari ("Azizga", "Sardorbekning") uchun so'z emas, PREFIKS solishtiriladi
(`summarize._tokens` dagi 5 harf g'oyasi): ism so'zi transkript so'zining boshi bo'lsa (yoki 5 harfi
bir xil bo'lsa) - asosli. Shubhali ism hujjatga kirmaydi: `BLANK` - kotib to'ldiradi.

NEGA `[S#]` TOKEN ISMGA AYLANMAYDI. Bu yerda faqat tekshiruv: tokenlar `compose` da ismga
(`export.render_tokens`) almashtiriladi - spiker keyin qayta nomlansa, saqlangan mazmun eskirmaydi.
`responsible` dagi token `[S#]` ko'rinishiga keltiriladi (model ba'zan "S2" deb yozadi), kun tartibidagi
`speakers` esa qavssiz "S#" (shakldagi "speaker": "S#" odatiga mos).
"""

from __future__ import annotations

import re

from datetime import date
from typing import Any

from .. import export
from ..summarize import norm
from . import text
from .text import BLANK

#: Band turlari (`shapes.minutes` enum emas - noma'lum `other` ga o'giriladi).
KINDS = ("acknowledge", "task", "warning", "permission", "control", "other")
#: Saqlanadigan mazmun kalitlari - `shapes.minutes()` tartibida.
KEYS = ("coverage", "title", "agenda", "preamble", "sections", "controller", "notes")

# Chegaralar (shartnoma). Oshgani qisqartiriladi va ogohlantirish beriladi - hujjat chiqadi.
MAX_AGENDA = 12
MAX_SECTIONS = 12
MAX_ITEMS = 120
MAX_ITEM_TEXT = 1500
MAX_REPORT = 6000
MAX_SUBPOINTS = 12
MAX_SUBPOINT = 500
MAX_NOTES = 20
MAX_NOTE = 400
MAX_TITLE = 200
MAX_AGENDA_TITLE = 300
MAX_PREAMBLE = 1000
MAX_DEADLINE = 200
MAX_RESPONSIBLE = 10
MAX_NAME = 150
MAX_IDS = 8
#: Ogohlantirishlar soni (ko'rinishda ro'yxat sifatida chiqadi) va raqam ogohlantirishlari ulushi.
MAX_WARNINGS = 60
MAX_NUMBER_WARNINGS = 20
#: Yozuv tekshiruvi: kamida shuncha harf bo'lsa va kutilgan yozuv ulushi shundan kam bo'lsa - `script_mismatch`.
SCRIPT_MIN_LETTERS = 20
SCRIPT_SHARE = 0.6

_TOKEN = re.compile(r"^\[?\s*(S\d{1,2})\s*\]?$")
_TOKEN_IN_TEXT = re.compile(r"\[(S\d{1,2})\]")
_BLANK = re.compile(r"^[_\s]{3,}$")
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
#: Raqam guruhi: "15", "1 500 000", "2,5", "10.5".
_NUMBER = re.compile(r"\d+(?:[  ]\d{3})*(?:[.,]\d+)?")
#: Kichik band boshidagi belgi ("- ", "• ", "1) ") - `compose` o'zi "- " qo'yadi, ikki marta bo'lmasin.
_BULLET = re.compile(r"^(?:[-–—•*]|\d{1,2}[.)])\s*")

#: Kirill -> lotin (o'zbek va rus harflari) - ismlarni yozuvdan qat'i nazar solishtirish uchun.
_CYR2LAT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "j", "з": "z", "и": "i",
    "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
    "у": "u", "ф": "f", "х": "x", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "'", "ы": "i", "ь": "",
    "э": "e", "ю": "yu", "я": "ya", "ў": "o", "ғ": "g", "қ": "q", "ҳ": "h",
}
#: Lotin tomonida bir xil tovushning ikki yozuvi (ruscha ismlar ASR da "Mikhail", "Zhanna") va unlidan
#: keyingi "е" ("Ғаниев" = "G'aniyev", "Елена" = "Yelena"): "ye" -> "e" ikkala tomonda ham.
_LAT_FOLD = (("kh", "x"), ("zh", "j"), ("ts", "c"), ("ye", "e"))


class Invalid(ValueError):
    """Javob shakli yaroqsiz - bu provayder bilan hujjat chiqmaydi."""


def fold(value: Any) -> str:
    """Ism/so'zni solishtirish shakli: `norm` + kirill->lotin + lotin juftliklari + tutuq belgisisiz."""
    folded = "".join(_CYR2LAT.get(ch, ch) for ch in norm(value))
    for pair, one in _LAT_FOLD:
        folded = folded.replace(pair, one)
    return folded.replace("'", "")


def _numbers(value: Any) -> tuple[set[str], set[str]]:
    """(normallashtirilgan raqamlar: "1500000", "2.5"; faqat raqamlar: "1500000", "25")."""
    keys: set[str] = set()
    digits: set[str] = set()
    for found in _NUMBER.finditer(_TOKEN_IN_TEXT.sub(" ", str(value or ""))):
        raw = found.group(0).replace(" ", "").replace(" ", "")
        keys.add(raw.replace(",", "."))
        digits.add(re.sub(r"\D", "", raw))
    return keys, digits


class _Ground:
    """Transkript so'zlari (buklangan), ularning prefikslari, raqamlari va spiker id lari."""

    def __init__(self, segments: list[dict[str, Any]], speakers: list[dict[str, Any]]) -> None:
        words: set[str] = set()
        self.number_keys: set[str] = set()
        self.number_digits: set[str] = set()
        self.speaker_ids: set[str] = set()
        for seg in segments:
            words.update(fold(seg.get("text")).split())
            keys, digits = _numbers(seg.get("text"))
            self.number_keys |= keys
            self.number_digits |= digits
            if seg.get("speaker"):
                self.speaker_ids.add(str(seg["speaker"]))
        #: ISMGA O'XSHASH so'zlar: spiker nomlari va transkriptda BOSH HARF bilan yozilgan so'zlar (GAPI
        #: matni bosh harflarni saqlaydi, 2026-11-04 o'lchov: so'zlarning ~9% i gap o'rtasida bosh harfli).
        #: 5 harfli prefiks tekshiruvi FAQAT shularga: "Komila" oddiy "komil" (to'liq) so'zi orqali asosli
        #: bo'lib qolmasin, "Sardorga" esa "Sardor" orqali asosli bo'lsin.
        namelike: set[str] = set()
        for seg in segments:
            for token in str(seg.get("text") or "").split():
                stripped = token.strip("\"'«»()[],.;:!?-–—")
                if stripped[:1].isupper():
                    namelike.update(fold(stripped).split())
        for sp in speakers:
            if sp.get("id"):
                self.speaker_ids.add(str(sp["id"]))
            if sp.get("name"):
                words.update(fold(sp["name"]).split())
                namelike.update(fold(sp["name"]).split())
        self.words = words
        self.prefixes = {w[:k] for w in words for k in range(3, min(len(w), 8) + 1)}
        self.name_prefixes = {w[:5] for w in namelike if len(w) >= 5}

    def word_ok(self, word: str) -> bool:
        """So'z transkriptda bor yoki transkript so'zining boshi (qo'shimchalar: "Azizga"); 5+ harfli
        so'zda 5 harfli prefiks ham yetarli ("Sardorga" <-> "Sardor"), lekin faqat ISMGA O'XSHASH
        (bosh harfli yoki spiker nomi) so'zlar bilan - oddiy so'z ("komil") ism yasamasin."""
        return word in self.words or word[:8] in self.prefixes or (len(word) >= 5 and word[:5] in self.name_prefixes)

    def name_ok(self, name: str) -> bool:
        """Ismning (yoki "Bo'lim (F.Familiya)" iborasining) 3+ harfli HAR so'zi transkriptda bo'lsin;
        tekshiriladigan so'z yo'q bo'lsa ("IT") - asosli deb qabul qilinadi."""
        return all(self.word_ok(w) for w in fold(name).split() if len(w) >= 3)

    def number_ok(self, key: str, digits: str) -> bool:
        return key in self.number_keys or digits in self.number_digits


class _Checker:
    """Bitta javob uchun holat: ogohlantirishlar, band hisobi, yozuv tekshiruvi uchun matn."""

    def __init__(self, lang: str, segments: list[dict[str, Any]], speakers: list[dict[str, Any]]) -> None:
        self.lang = lang
        self.ground = _Ground(segments, speakers)
        self.ids = {int(s["id"]) for s in segments if str(s.get("id", "")).lstrip("-").isdigit()}
        self.warnings: list[str] = []
        #: Noasosli (to'qima) ismlar - hujjatning HAMMA matnlarida `BLANK` ga almashtiriladi (`scrub`).
        self.ungrounded: list[str] = []
        self.number_warnings = 0
        self.prose: list[str] = []

    # --- umumiy ---

    def warn(self, message: str) -> None:
        if message not in self.warnings and len(self.warnings) < MAX_WARNINGS:
            self.warnings.append(message)

    def line(self, value: Any, limit: int, where: str) -> str:
        """Bir qatorli tozalangan matn; `limit` dan uzuni qisqartiriladi va ogohlantiriladi."""
        if not isinstance(value, str):
            return ""
        out = export.one_line(value)
        if len(out) > limit:
            self.warn(f"{where}_truncated")
            out = out[:limit - 1].rstrip() + "…"
        return out

    def optional(self, value: Any, limit: int, where: str) -> str | None:
        return self.line(value, limit, where) or None

    def ids_of(self, value: Any) -> list[int]:
        """Faqat MAVJUD qator id lari, takrorsiz, tartib saqlanadi, ko'pi bilan `MAX_IDS`."""
        out: list[int] = []
        for raw in value if isinstance(value, list) else []:
            if isinstance(raw, bool):
                continue
            if isinstance(raw, (int, float)) and float(raw).is_integer():
                sid = int(raw)
            elif isinstance(raw, str) and raw.strip().lstrip("#").isdigit():
                sid = int(raw.strip().lstrip("#"))
            else:
                continue
            if sid in self.ids and sid not in out:
                out.append(sid)
            if len(out) >= MAX_IDS:
                break
        return out

    def numbers(self, value: str) -> None:
        """Matndagi raqam guruhlari transkriptda yo'q bo'lsa - ogohlantirish (matn o'zgarmaydi)."""
        keys, _ = _numbers(value)
        for key in sorted(keys):
            if self.ground.number_ok(key, re.sub(r"\D", "", key)):
                continue
            if self.number_warnings >= MAX_NUMBER_WARNINGS:
                return
            before = len(self.warnings)
            self.warn(f"unverified_number:{key}")
            self.number_warnings += len(self.warnings) - before

    def prose_of(self, *values: Any) -> None:
        self.prose.extend(v for v in values if isinstance(v, str) and v)

    # --- ismlar ---

    def token(self, value: str) -> str | None:
        found = _TOKEN.match(value)
        return found.group(1) if found else None

    def speaker_known(self, sid: str) -> bool:
        return sid in self.ground.speaker_ids

    def responsible(self, value: Any, body: str) -> tuple[list[str], str]:
        """Mas'ullar: `[S#]` token (ma'lum spiker), `BLANK`, yoki transkriptda ASOSLI ism. Noasosli ism
        yoki noma'lum spiker -> `BLANK`, band matnida ham."""
        out: list[str] = []
        entries = value if isinstance(value, list) else ([value] if isinstance(value, str) else [])
        for entry in entries[:MAX_RESPONSIBLE]:
            name = self.line(entry, MAX_NAME, "responsible")
            if not name:
                continue
            sid = self.token(name)
            if sid:
                if self.speaker_known(sid):
                    out.append(f"[{sid}]")
                else:
                    self.warn(f"unknown_speaker:{sid}")
                    body = body.replace(f"[{sid}]", BLANK)
                    out.append(BLANK)
            elif _BLANK.match(name):
                out.append(BLANK)
            elif self.ground.name_ok(name):
                out.append(name)
            else:
                self.warn(f"ungrounded_name:{name[:60]}")
                self.ungrounded.append(name)
                body = self.scrub(body)
                out.append(BLANK)
        unique: list[str] = []
        for who in out:
            if who not in unique:
                unique.append(who)
        return unique, body

    def person(self, value: Any, where: str) -> str | None:
        """Bitta shaxs maydoni (`controller`): token `[S#]`, asosli ism yoki `None`."""
        name = self.optional(value, MAX_NAME, where)
        if not name or _BLANK.match(name):
            return None
        sid = self.token(name)
        if sid:
            if self.speaker_known(sid):
                return f"[{sid}]"
            self.warn(f"unknown_speaker:{sid}")
            return None
        if self.ground.name_ok(name):
            return name
        self.warn(f"ungrounded_name:{name[:60]}")
        self.ungrounded.append(name)
        return None

    def scrub(self, value: str | None) -> str | None:
        """Matndagi noasosli ismlarni (to'liq ibora va uning transkriptda YO'Q 3+ harfli so'zlari,
        qo'shimchasi bilan) `BLANK` ga almashtiradi: "Бобур Каримов" -> "Бобурга" ham, "Каримов Б." dagi
        "Каримов" ham (agar Karimov transkriptda bo'lmasa)."""
        if not value:
            return value
        out = value
        stems: list[str] = []
        for name in self.ungrounded:
            out = _blank_name(out, name)
            for word in name.split():
                plain = word.strip(_PUNCT)
                folded = fold(plain)
                if len(folded) >= 3 and not self.ground.word_ok(folded):
                    out = _blank_name(out, plain)
                    stems.append(folded)
        if stems:
            # Rus kelishiklari o'zakni O'ZGARTIRADI ("Елена" -> "Елене", "Юсупова" -> "Юсуповой"): literal
            # prefiks + qo'shimcha qoidasi ularni topmaydi. Har so'z buklanib, ismning (uzunligi - 1) harfi
            # bilan solishtiriladi; transkriptda asosli so'zlar ("Нодир" bor bo'lsa) tegilmaydi.
            out = _blank_declined(out, stems, self.ground)
        return out

    def agenda_speakers(self, value: Any) -> list[str]:
        """Kun tartibi bandida so'zga chiqqanlar: qavssiz "S#" (ma'lum spiker) yoki asosli ism."""
        out: list[str] = []
        for entry in value if isinstance(value, list) else []:
            name = self.line(entry, MAX_NAME, "speaker")
            if not name or _BLANK.match(name):
                continue
            sid = self.token(name)
            if sid:
                if self.speaker_known(sid):
                    who = sid
                else:
                    self.warn(f"unknown_speaker:{sid}")
                    continue
            elif self.ground.name_ok(name):
                who = name
            else:
                self.warn(f"ungrounded_name:{name[:60]}")
                self.ungrounded.append(name)
                continue
            if who not in out:
                out.append(who)
            if len(out) >= MAX_RESPONSIBLE:
                break
        return out

    # --- bo'laklar ---

    def agenda(self, value: list[Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for raw in value:
            if not isinstance(raw, dict):
                self.warn("agenda_dropped")
                continue
            if len(out) >= MAX_AGENDA:
                self.warn(f"agenda_capped:{len(value)}")
                break
            number = len(out) + 1
            title = self.line(raw.get("title"), MAX_AGENDA_TITLE, f"agenda_title:{number}")
            report = self.line(raw.get("report"), MAX_REPORT, f"report:{number}")
            if not title and not report:
                self.warn("agenda_dropped")
                continue
            src = self.ids_of(raw.get("sourceSegmentIds"))
            if not src:
                self.warn(f"ungrounded_agenda:{number}")
            self.numbers(report)
            self.prose_of(title, report)
            out.append({"title": title, "speakers": self.agenda_speakers(raw.get("speakers")), "report": report,
                        "sourceSegmentIds": src})
        return out

    def item(self, raw: dict[str, Any], number: int) -> dict[str, Any] | None:
        body = self.line(raw.get("text"), MAX_ITEM_TEXT, f"item_text:{number}")
        if not body:
            self.warn(f"empty_item:{number}")
            return None
        kind = str(raw.get("kind") or "").strip().lower()
        if kind not in KINDS:
            if kind:
                self.warn(f"unknown_kind:{kind[:30]}")
            kind = "other"
        deadline = self.optional(raw.get("deadline"), MAX_DEADLINE, f"deadline:{number}")
        deadline_date = _iso_date(raw.get("deadlineDate"))
        if raw.get("deadlineDate") and deadline_date is None:
            self.warn(f"deadline_date:{str(raw.get('deadlineDate'))[:20]}")
        if deadline_date and not deadline:
            # Aytilmagan muddat sanaga aylanmasin: ibora yo'q - sana ham yo'q.
            self.warn(f"deadline_without_phrase:{number}")
            deadline_date = None
        responsible, body = self.responsible(raw.get("responsible"), body)
        subpoints: list[str] = []
        raw_sub = raw.get("subpoints") if isinstance(raw.get("subpoints"), list) else []
        for sub in raw_sub:
            if len(subpoints) >= MAX_SUBPOINTS:
                self.warn(f"subpoints_capped:{number}")
                break
            point = _BULLET.sub("", self.line(sub, MAX_SUBPOINT, f"subpoint:{number}"))
            if point:
                subpoints.append(point)
        follow = self.optional(raw.get("followUp"), MAX_ITEM_TEXT, f"follow_up:{number}")
        src = self.ids_of(raw.get("sourceSegmentIds"))
        if not src:
            self.warn(f"ungrounded_item:{number}")
        for value in (body, follow or "", *subpoints):
            self.numbers(value)
        self.prose_of(body, follow, deadline, *subpoints)
        return {"kind": kind, "deadline": deadline, "deadlineDate": deadline_date, "responsible": responsible,
                "text": body, "subpoints": subpoints, "followUp": follow, "sourceSegmentIds": src,
                "confidence": _confidence(raw.get("confidence"))}

    def sections(self, value: list[Any], agenda_count: int) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        raw_total = sum(len(s.get("items")) for s in value
                        if isinstance(s, dict) and isinstance(s.get("items"), list))
        if raw_total > MAX_ITEMS:
            self.warn(f"items_capped:{raw_total}")
        total = 0
        for raw in value:
            if not isinstance(raw, dict):
                self.warn("section_dropped")
                continue
            if len(out) >= MAX_SECTIONS:
                self.warn(f"sections_capped:{len(value)}")
                break
            index = _int(raw.get("agendaIndex"))
            if index is None or not 1 <= index <= agenda_count:
                self.warn(f"agenda_index:{str(raw.get('agendaIndex'))[:20]}")
                index = max(1, agenda_count)
            items: list[dict[str, Any]] = []
            for raw_item in raw.get("items") if isinstance(raw.get("items"), list) else []:
                if total >= MAX_ITEMS:
                    break
                if not isinstance(raw_item, dict):
                    self.warn("item_dropped")
                    continue
                item = self.item(raw_item, total + 1)
                if item is not None:
                    items.append(item)
                    total += 1
            if not items:
                self.warn(f"empty_section:{len(out) + 1}")
                continue
            out.append({"agendaIndex": index, "items": items})
        return out

    def notes(self, value: Any) -> list[str]:
        out: list[str] = []
        for raw in value if isinstance(value, list) else []:
            if len(out) >= MAX_NOTES:
                self.warn(f"notes_capped:{len(value)}")
                break
            note = self.line(raw, MAX_NOTE, "note")
            if note and note not in out:
                out.append(note)
        self.prose_of(*out)
        return out

    def coverage(self, value: Any) -> dict[str, int]:
        first = min(self.ids) if self.ids else 0
        last = max(self.ids) if self.ids else 0
        cov = value if isinstance(value, dict) else {}
        first_id = _int(cov.get("firstId"))
        last_id = _int(cov.get("lastId"))
        return {"firstId": first_id if first_id in self.ids else first,
                "lastId": last_id if last_id in self.ids else last}

    def check_script(self) -> None:
        """Hujjat tilining yozuvi: kirill tillarida kirill, lotin tillarida lotin harflar >= 60%."""
        cyr, lat, total = text.script_share(" ".join(self.prose))
        if total < SCRIPT_MIN_LETTERS:
            return
        expected = cyr if self.lang in ("uz-cyrl", "ru") else lat
        if expected / total < SCRIPT_SHARE:
            self.warn("script_mismatch")


#: Token chetidagi tinish belgilari - ism solishtirishda olib tashlanadi, matnda qoladi.
_PUNCT = "\"'«»()[],.;:!?-–—"


def _blank_declined(body: str, stems: list[str], ground: "_Ground") -> str:
    """Matn tokenlari ichida to'qima ism o'zagining kelishik shakllarini `BLANK` ga almashtiradi:
    buklangan token to'qima so'z bilan `max(3, len - 1)` harfda bir xil va o'zi transkriptda asosli
    bo'lmasa. Tinish belgilari joyida qoladi."""
    out: list[str] = []
    changed = False
    for token in body.split(" "):
        core = token.strip(_PUNCT)
        folded = fold(core)
        hit = False
        if len(folded) >= 3 and not ground.word_ok(folded):
            for stem in stems:
                k = max(3, len(stem) - 1)
                if folded[:k] == stem[:k]:
                    hit = True
                    break
        if hit:
            head = token[:len(token) - len(token.lstrip(_PUNCT))]
            tail = token[len(token.rstrip(_PUNCT)):]
            out.append(f"{head}{BLANK}{tail}")
            changed = True
        else:
            out.append(token)
    if not changed:
        return body
    return re.sub(rf"{BLANK}(?:\s*{BLANK})+", BLANK, " ".join(out))


def _blank_name(body: str, name: str) -> str:
    """Band matnidagi ismni (qo'shimchasi bilan: "Бобурга") `BLANK` ga almashtiradi; topilmasa matn qoladi."""
    pattern = re.compile(rf"(?<!\w){re.escape(name)}\w*", re.IGNORECASE)
    out = pattern.sub(BLANK, body)
    if out == body:
        out = body.replace(name, BLANK)
    return re.sub(rf"{BLANK}(?:\s*{BLANK})+", BLANK, out)


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and float(value).is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def _confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.5
    if number != number:  # NaN
        return 0.5
    return round(min(1.0, max(0.0, number)), 3)


def _iso_date(value: Any) -> str | None:
    if not isinstance(value, str) or not _ISO.match(value.strip()):
        return None
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError:
        return None


def _unwrap(data: dict[str, Any]) -> dict[str, Any]:
    """`{"minutes": {...}}` kabi o'ralgan javob - ichidagi obyekt (bitta bo'lsa)."""
    if "sections" in data or "agenda" in data:
        return data
    inner = [v for v in data.values() if isinstance(v, dict) and ("sections" in v or "agenda" in v)]
    return inner[0] if len(inner) == 1 else data


def validate(data: dict[str, Any], *, lang: str, segments: list[dict[str, Any]],
             speakers: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    """Model javobi -> (`KEYS` tartibidagi tozalangan mazmun, ogohlantirishlar). `Invalid` - obyekt emas,
    `sections` ro'yxat emas, yoki tekshiruvdan keyin bo'lim ham, kun tartibi ham qolmadi."""
    if not isinstance(data, dict):
        raise Invalid("bayonnoma: javob obyekt emas")
    data = _unwrap(data)
    agenda_raw = data.get("agenda")
    sections_raw = data.get("sections")
    if sections_raw is not None and not isinstance(sections_raw, list):
        raise Invalid("bayonnoma: sections ro'yxat emas")
    code = text.normalize(lang) or "uz-cyrl"
    checker = _Checker(code, segments, speakers)
    if agenda_raw is not None and not isinstance(agenda_raw, list):
        checker.warn("agenda_invalid")
        agenda_raw = []
    agenda = checker.agenda(agenda_raw or [])
    sections = checker.sections(sections_raw or [], len(agenda))
    if not agenda and not sections:
        raise Invalid("bayonnoma: bo'limlar ham, kun tartibi ham yo'q")
    title = checker.line(data.get("title"), MAX_TITLE, "title")
    preamble = checker.optional(data.get("preamble"), MAX_PREAMBLE, "preamble")
    controller = checker.person(data.get("controller"), "controller")
    notes = checker.notes(data.get("notes"))
    checker.prose_of(title, preamble)
    checker.check_script()
    if checker.ungrounded:
        # To'qima ism hujjatning HECH QAYERIDA qolmasin: bandlar (oldingilari ham), "Bunda", kichik
        # bandlar, bayon paragraflari, kirish gap - hammasi bitta yakuniy o'tishda.
        for entry in agenda:
            entry["title"] = checker.scrub(entry["title"]) or ""
            entry["report"] = checker.scrub(entry["report"]) or ""
        for section in sections:
            for item in section["items"]:
                item["text"] = checker.scrub(item["text"]) or ""
                item["deadline"] = checker.scrub(item["deadline"])
                item["followUp"] = checker.scrub(item["followUp"])
                item["subpoints"] = [checker.scrub(x) or "" for x in item["subpoints"]]
        preamble = checker.scrub(preamble)
        title = checker.scrub(title) or ""
        scrubbed = [checker.scrub(n) or "" for n in notes]
        notes = [n for n in dict.fromkeys(scrubbed) if n and not _BLANK.match(n)]
    content = {"coverage": checker.coverage(data.get("coverage")), "title": title, "agenda": agenda,
               "preamble": preamble, "sections": sections, "controller": controller, "notes": notes}
    assert tuple(content) == KEYS
    return content, checker.warnings
