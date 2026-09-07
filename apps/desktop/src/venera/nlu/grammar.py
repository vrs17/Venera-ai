"""Deklarativ slot-grammatika: `rules.yaml` -> `Intent`.

NEGA: ilgari har bir qoida `rules.py` da Python funksiyasi bilan yozilardi, ya'ni
yangi til = yangi Python kodi. Endi qoida MA'LUMOT: naqsh + slotlar. Yangi til
qo'shuvchi faqat YAML yozadi, bu modulga tegmaydi.

SXEMA:

    version: 1
    strip_wake: true          # matn boshidagi uyg'otish so'zi kesilsinmi
    # TARTIB MUHIM: birinchi mos kelgan qoida yutadi.
    # Umumiy qoidalar ("... och") OXIRIDA - aks holda ular aniqroq
    # qoidalarni ("... saytini och") yeb qo'yadi.
    rules:
      - name: volume_set            # ixtiyoriy, loglar uchun
        intent: volume_set          # IntentName qiymati
        slots:
          level: {transform: number, clamp: [0, 100], required: true}
        patterns:
          - |-
            \\b(ovoz|tovush)(ni)?\\s+(?P<level>{num})\\s*(foiz)?\\s*$

NAQSH YOZISH QOIDASI: HAR DOIM `|-` blok skalyari. YAML ning qo'shtirnoqli
satrida `\\s` NOTO'G'RI ESCAPE hisoblanadi va PyYAML ScannerError tashlaydi;
blok skalyarida escape umuman qayta ishlanmaydi.

SLOT nomi `(?P<nom>...)` guruh nomi bilan bir xil bo'lishi va `Intent`
maydonlaridan biriga (app, url, query, level, confidence) mos kelishi kerak.

`required: true` slot qiymati chiqmasa QOIDA MOS KELMAGAN hisoblanadi va
keyingi qoidaga o'tiladi. Bu eski `_volume_set` xatti-harakatining aynan
o'zi: "ovozni salom foiz" -> volume_set emas.

HECH QACHON EXCEPTION TASHLAMAYDI: buzuq naqsh butun grammatikani emas, faqat
o'sha qoidani o'chiradi va `problems` ga yozuv qo'shadi.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, fields as dataclass_fields
from typing import Any, Mapping

from .intents import Intent, IntentName
from .transforms import TRANSFORMS
from .words import WordBook

log = logging.getLogger(__name__)

#: Slot qaysi `Intent` maydoniga yozilishi mumkin.
INTENT_FIELDS = frozenset(
    f.name for f in dataclass_fields(Intent)
    if f.name not in ("name", "raw_text", "source")
)

DEFAULT_TRANSFORM = "text"

#: `found.group("yo'q")` odatda `IndexError` beradi; ba'zi holatlarda `re.error`
#: ham uchraydi - ikkalasini ham ushlaymiz, naqsh xatosi buyruqni yiqitmasin.
_GROUP_ERRORS = (IndexError, re.error)


@dataclass(frozen=True)
class SlotSpec:
    """Bitta `(?P<nom>...)` guruhi qanday qayta ishlanishi."""

    name: str
    transform: str = DEFAULT_TRANSFORM
    required: bool = False
    clamp: tuple[int, int] | None = None
    default: Any = ""


@dataclass(frozen=True)
class CompiledRule:
    """Kompilyatsiya qilingan qoida. Bir nechta naqsh bo'lishi mumkin."""

    intent: IntentName
    name: str
    patterns: tuple["re.Pattern[str]", ...]
    slots: tuple[SlotSpec, ...] = ()
    order: int = 0

    def match(self, text: str) -> "re.Match[str] | None":
        for pattern in self.patterns:
            found = pattern.search(text)
            if found is not None:
                return found
        return None

    def build(self, found: "re.Match[str]", text: str, book: WordBook) -> Intent | None:
        """Moslikdan Intent quradi. Majburiy slot chiqmasa None (= qoida o'tdi)."""
        values: dict[str, Any] = {}
        for slot in self.slots:
            try:
                raw = found.group(slot.name)
            except _GROUP_ERRORS:
                raw = None
            raw = raw or ""

            fn = TRANSFORMS.get(slot.transform) or TRANSFORMS[DEFAULT_TRANSFORM]
            try:
                value = fn(raw, book, slot)
            except Exception:  # noqa: BLE001 - transformatsiya xatosi qoidani o'chirsin
                log.debug("Transformatsiya xatosi: %s.%s", self.name, slot.name, exc_info=True)
                value = None

            if value is None or value == "":
                if slot.required:
                    return None
                value = slot.default

            if slot.clamp is not None and isinstance(value, int) and not isinstance(value, bool):
                low, high = slot.clamp
                value = max(low, min(high, value))

            values[slot.name] = value

        return Intent(name=self.intent, raw_text=text, source="rules", **values)


@dataclass(frozen=True)
class Grammar:
    """Bitta tilning kompilyatsiya qilingan qoidalari. O'ZGARMAS."""

    code: str = ""
    rules: tuple[CompiledRule, ...] = ()
    book: WordBook = None  # type: ignore[assignment]
    strip_wake: bool = False
    problems: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.book is None:
            object.__setattr__(self, "book", WordBook(code=self.code))

    def prepare(self, text: str) -> str:
        """Xom matnni qoidalarga solishtirishga tayyorlaydi."""
        clean = self.book.normalize(text)
        if self.strip_wake:
            clean = self.book.strip_wake(clean)
        return clean

    def match(self, text: str) -> Intent:
        """Xom matndan Intent. Hech qanday qoida mos kelmasa UNKNOWN."""
        clean = self.prepare(text)
        if not clean:
            return Intent(name=IntentName.UNKNOWN, raw_text="", source="rules")

        for rule in self.rules:
            found = rule.match(clean)
            if found is None:
                continue
            intent = rule.build(found, clean, self.book)
            if intent is not None and intent.is_known:
                return intent

        return Intent(name=IntentName.UNKNOWN, raw_text=clean, source="rules")

    def intents(self) -> tuple[IntentName, ...]:
        """Grammatika qamrab olgan intentlar (`--check` uchun)."""
        seen: list[IntentName] = []
        for rule in self.rules:
            if rule.intent not in seen:
                seen.append(rule.intent)
        return tuple(seen)


# --- kompilyatsiya ----------------------------------------------------------


def _slot_spec(name: str, raw: Any, label: str, problems: list[str]) -> SlotSpec | None:
    if name not in INTENT_FIELDS:
        problems.append(f"{label}: slot {name!r} Intent maydoni emas "
                        f"({sorted(INTENT_FIELDS)}) - o'tkazib yuborildi")
        return None

    if raw is None:
        raw = {}
    if isinstance(raw, str):           # qisqa yozuv: `app: strip_affixes`
        raw = {"transform": raw}
    if not isinstance(raw, Mapping):
        problems.append(f"{label}.{name}: mapping kutilgan edi, {type(raw).__name__} keldi")
        return None

    transform = str(raw.get("transform") or DEFAULT_TRANSFORM).strip()
    if transform not in TRANSFORMS:
        problems.append(f"{label}.{name}: transform={transform!r} noma'lum "
                        f"({sorted(TRANSFORMS)}) - {DEFAULT_TRANSFORM!r} ishlatildi")
        transform = DEFAULT_TRANSFORM

    clamp: tuple[int, int] | None = None
    clamp_raw = raw.get("clamp")
    if clamp_raw is not None:
        try:
            low, high = (int(clamp_raw[0]), int(clamp_raw[1]))
            clamp = (min(low, high), max(low, high))
        except (TypeError, ValueError, IndexError, KeyError):
            problems.append(f"{label}.{name}: clamp [min, max] ko'rinishida bo'lishi kerak "
                            f"({clamp_raw!r}) - e'tiborsiz")

    default = raw.get("default", 0 if transform == "number" else "")
    return SlotSpec(
        name=name,
        transform=transform,
        required=bool(raw.get("required", False)),
        clamp=clamp,
        default=default,
    )


def _patterns(raw: Any, book: WordBook, label: str,
              problems: list[str]) -> tuple["re.Pattern[str]", ...]:
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        problems.append(f"{label}: patterns ro'yxat bo'lishi kerak "
                        f"({type(raw).__name__}) - qoida o'tkazib yuborildi")
        return ()

    compiled: list["re.Pattern[str]"] = []
    for index, item in enumerate(raw):
        source = str(item)
        unknown = book.unknown_macros(source)
        if unknown:
            problems.append(f"{label}.patterns[{index}]: noma'lum makro(lar) "
                            f"{list(unknown)} - words.yaml ga qo'shing")
        expanded = book.expand(source)
        try:
            compiled.append(re.compile(expanded))
        except re.error as exc:
            problems.append(f"{label}.patterns[{index}]: regex xatosi ({exc}) "
                            "- naqsh o'tkazib yuborildi")
    return tuple(compiled)


def compile(data: Any, book: WordBook, code: str = "") -> Grammar:  # noqa: A001
    """`rules.yaml` mazmunidan Grammar. HECH QACHON exception tashlamaydi."""
    problems: list[str] = []

    if not isinstance(data, Mapping):
        if data is not None:
            problems.append(f"{code}/rules.yaml: mapping kutilgan edi, "
                            f"{type(data).__name__} keldi")
        data = {}

    raw_rules = data.get("rules")
    if raw_rules is None:
        raw_rules = []
    if not isinstance(raw_rules, (list, tuple)):
        problems.append(f"{code}/rules.yaml: rules ro'yxat bo'lishi kerak "
                        f"({type(raw_rules).__name__})")
        raw_rules = []

    rules: list[CompiledRule] = []
    for index, item in enumerate(raw_rules):
        label = f"{code}/rules.yaml: rules[{index}]"
        if not isinstance(item, Mapping):
            problems.append(f"{label}: mapping kutilgan edi, {type(item).__name__} keldi")
            continue

        intent_raw = str(item.get("intent") or "").strip()
        try:
            intent = IntentName(intent_raw)
        except ValueError:
            problems.append(f"{label}: intent={intent_raw!r} noma'lum "
                            f"({[str(i) for i in IntentName]}) - qoida o'tkazib yuborildi")
            continue
        if intent is IntentName.UNKNOWN:
            problems.append(f"{label}: intent 'unknown' bo'lishi mumkin emas "
                            "- qoida o'tkazib yuborildi")
            continue

        name = str(item.get("name") or intent_raw)
        patterns = _patterns(item.get("patterns"), book, f"{label} ({name})", problems)
        if not patterns:
            problems.append(f"{label} ({name}): birorta ishlaydigan naqsh yo'q "
                            "- qoida o'tkazib yuborildi")
            continue

        slots: list[SlotSpec] = []
        slots_raw = item.get("slots") or {}
        if isinstance(slots_raw, Mapping):
            for slot_name, slot_data in slots_raw.items():
                spec = _slot_spec(str(slot_name), slot_data,
                                  f"{label} ({name}).slots", problems)
                if spec is not None:
                    slots.append(spec)
        else:
            problems.append(f"{label} ({name}): slots mapping bo'lishi kerak")

        # Naqshda e'lon qilinmagan guruh bormi - odatda bu yozuv xatosi
        declared = {slot.name for slot in slots}
        for pattern in patterns:
            for group in pattern.groupindex:
                if group not in declared:
                    problems.append(f"{label} ({name}): naqshdagi (?P<{group}>...) "
                                    "guruhi slots da e'lon qilinmagan - e'tiborsiz")

        rules.append(CompiledRule(
            intent=intent, name=name, patterns=patterns,
            slots=tuple(slots), order=index,
        ))

    if problems:
        for problem in problems:
            log.warning("Grammatika: %s", problem)

    return Grammar(
        code=code,
        rules=tuple(rules),
        book=book,
        strip_wake=bool(data.get("strip_wake", False)),
        problems=tuple(problems),
    )


def empty(code: str = "") -> Grammar:
    """Til paketi umuman o'qilmaganda ishlatiladigan bo'sh grammatika."""
    return Grammar(code=code, book=WordBook(code=code))
