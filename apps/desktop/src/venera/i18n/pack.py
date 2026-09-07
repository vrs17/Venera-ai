"""`LanguagePack` - bitta tilning to'liq yuklangan mazmuni.

O'ZGARMAS (frozen). Sabab thread bilan bog'liq: `i18n.t()` PortAudio callback
thread'idan ham, Tk thread'idan ham, orchestrator korutinasidan ham
chaqiriladi. Paket o'zgarmas bo'lgani uchun ularning hech biri qulf kutmaydi -
audio oqimi uzilmaydi.

FALLBACK: kalit topilmasa `uz` paketidan olinadi (`locale.FALLBACK_CODE`).
Yetishmagan kalit BIR MARTA log.warning qiladi va `pack.missing` to'plamiga
tushadi - `--check` shu to'plamni ko'rsatadi.

HECH QACHON EXCEPTION TASHLAMAYDI: buzuq YAML butun ilovani yiqitmasin.
Har bir muammo `problems` ro'yxatiga yoziladi - `config.load()` bilan bir xil
naqsh.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

from ..nlu import grammar as grammar_module
from ..nlu import words as words_module
from ..nlu.grammar import Grammar
from ..nlu.words import WordBook
from .locale import SECTIONS, LocaleSpec, empty as empty_spec
from .locale import parse as parse_spec

log = logging.getLogger(__name__)


def read_yaml(path: Path) -> tuple[Any, str]:
    """YAML o'qiydi. `(ma'lumot, xato_matni)` - exception tashlamaydi."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, ""
    except OSError as exc:
        return None, f"{path.name}: o'qilmadi ({exc})"
    try:
        return yaml.safe_load(text), ""
    except Exception as exc:  # noqa: BLE001 - buzuq YAML ilovani yiqitmasin
        return None, f"{path.name}: YAML xatosi ({exc})"


def _flat_strings(data: Any, label: str, problems: list[str]) -> dict[str, str]:
    """`ui.yaml` ni tekis `kalit -> matn` lug'atiga aylantiradi.

    Ichma-ich mapping ham qabul qilinadi va nuqta bilan tekislanadi:
    `window: {title: ...}` -> `window.title`. Shu tufayli til paketi muallifi
    xohlagan uslubda yozishi mumkin.
    """
    out: dict[str, str] = {}

    def walk(node: Any, prefix: str) -> None:
        if isinstance(node, Mapping):
            for key, value in node.items():
                walk(value, f"{prefix}.{key}" if prefix else str(key))
        elif isinstance(node, (list, tuple)):
            problems.append(f"{label}.{prefix}: ro'yxat qo'llab-quvvatlanmaydi - e'tiborsiz")
        elif node is None:
            problems.append(f"{label}.{prefix}: qiymat bo'sh - e'tiborsiz")
        else:
            out[prefix] = str(node)

    if data is None:
        return out
    if not isinstance(data, Mapping):
        problems.append(f"{label}: mapping kutilgan edi, {type(data).__name__} keldi")
        return out
    walk(data, "")
    return out


@dataclass(frozen=True)
class LanguagePack:
    """Bitta tilning hamma narsasi. Faqat FAOL til to'liq yuklanadi."""

    code: str
    spec: LocaleSpec
    ui: Mapping[str, str] = field(default_factory=dict)
    phrases: Mapping[str, Any] = field(default_factory=dict)
    apps: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    words: WordBook = field(default_factory=WordBook)
    grammar: Grammar = field(default_factory=grammar_module.empty)
    problems: tuple[str, ...] = ()
    source: Path | None = None
    fallback: "LanguagePack | None" = None
    #: Topilmagan kalitlar - `--check` uchun. Mazmuni o'zgaradi, lekin
    #: obyektning o'zi almashmaydi, shuning uchun frozen shartnomasi buzilmaydi.
    missing: set = field(default_factory=set)

    # --- matn olish ---------------------------------------------------------

    def text(self, key: str, **kwargs: Any) -> str:
        """UI matni. Topilmasa fallback tildan, u ham bo'lmasa kalitning o'zi."""
        return self._lookup(self.ui, "ui", key, kwargs)

    def phrase(self, key: str, **kwargs: Any) -> str:
        """Ovozli javob shabloni."""
        return self._lookup(self.phrases, "phrases", key, kwargs)

    def raw(self, section: str, key: str, default: Any = None) -> Any:
        """Formatlanmagan qiymat (ro'yxatlar uchun: weekdays, months)."""
        source = self.phrases if section == "phrases" else self.ui
        if key in source:
            return source[key]
        if self.fallback is not None:
            return self.fallback.raw(section, key, default)
        return default

    def _lookup(self, source: Mapping[str, Any], section: str,
                key: str, kwargs: dict[str, Any]) -> str:
        template = source.get(key)
        if template is None or not isinstance(template, str):
            template = self._from_fallback(section, key)
        if template is None:
            self._note_missing(section, key, final=True)
            return key
        return self._format(key, template, kwargs)

    def _from_fallback(self, section: str, key: str) -> str | None:
        pack = self.fallback
        if pack is None:
            return None
        source = pack.phrases if section == "phrases" else pack.ui
        value = source.get(key)
        if isinstance(value, str):
            self._note_missing(section, key, final=False)
            return value
        return None

    def _note_missing(self, section: str, key: str, final: bool) -> None:
        marker = f"{section}.{key}"
        if marker in self.missing:
            return
        self.missing.add(marker)
        if final:
            log.warning("i18n: %s kaliti %s tilida ham, zaxira tilda ham yo'q",
                        marker, self.code)
        else:
            log.warning("i18n: %s kaliti %s tilida yo'q - %s dan olindi",
                        marker, self.code, self.fallback.code if self.fallback else "?")

    @staticmethod
    def _format(key: str, template: str, kwargs: dict[str, Any]) -> str:
        if not kwargs:
            return template
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError, ValueError) as exc:
            log.warning("i18n: shablon to'ldirilmadi (%s): %s", key, exc)
            return template

    # --- ma'lumot -----------------------------------------------------------

    @property
    def ok(self) -> bool:
        """Paket ishlatishga yaroqli (matnlar ham, qoidalar ham bor)."""
        return bool(self.ui) and bool(self.grammar.rules)

    def describe(self) -> dict[str, Any]:
        """`--check` uchun qisqacha holat."""
        return {
            "code": self.code,
            "name": self.spec.display,
            "complete": self.spec.complete,
            "fallback": self.fallback.code if self.fallback else "-",
            "ui_keys": len(self.ui),
            "phrases": len(self.phrases),
            "rules": len(self.grammar.rules),
            "problems": len(self.problems),
            "missing": len(self.missing),
            "source": str(self.source) if self.source else "-",
        }


def empty(code: str = "") -> LanguagePack:
    """Hech narsa o'qilmaganda ishlatiladigan bo'sh paket."""
    return LanguagePack(code=code, spec=empty_spec(code))


def _apps(data: Any, label: str, problems: list[str]) -> dict[str, tuple[str, ...]]:
    """`apps.yaml`: dastur nomi -> shu tildagi qo'shimcha aliaslar.

    DIQQAT: `resources/apps.default.yaml` ga TEGILMAYDI. Sabab
    `config.upgrade_apps_file()` yozuvlarni `name` bo'yicha solishtiradi va
    MAVJUD yozuvga yangi kalit qo'sha olmaydi - foydalanuvchi mashinasida
    yangi aliaslar ko'rinmasdi. Til aliaslari shuning uchun shu yerda,
    til paketining ichida yashaydi.
    """
    if data is None:
        return {}
    if not isinstance(data, Mapping):
        problems.append(f"{label}: mapping kutilgan edi, {type(data).__name__} keldi")
        return {}
    raw = data.get("aliases", data)
    if not isinstance(raw, Mapping):
        problems.append(f"{label}.aliases: mapping kutilgan edi")
        return {}

    out: dict[str, tuple[str, ...]] = {}
    for name, aliases in raw.items():
        if name in ("version", "aliases"):
            continue
        if isinstance(aliases, str):
            aliases = [aliases]
        if not isinstance(aliases, (list, tuple)):
            problems.append(f"{label}.aliases.{name}: ro'yxat kutilgan edi")
            continue
        values = tuple(str(a).strip().lower() for a in aliases if str(a).strip())
        if values:
            out[str(name).strip()] = values
    return out


def load_pack(code: str, directory: Path,
              fallback: "LanguagePack | None" = None) -> LanguagePack:
    """Til papkasidan to'liq paket quradi. HECH QACHON exception tashlamaydi."""
    problems: list[str] = []
    directory = Path(directory)

    spec_data, error = read_yaml(directory / "locale.yaml")
    if error:
        problems.append(f"{code}: {error}")
    spec, spec_problems = parse_spec(code, spec_data if spec_data is not None else {})
    problems.extend(spec_problems)

    sections: dict[str, Any] = {}
    for section in SECTIONS:
        data, error = read_yaml(directory / f"{section}.yaml")
        if error:
            problems.append(f"{code}: {error}")
        sections[section] = data

    ui = _flat_strings(sections.get("ui"), f"{code}/ui.yaml", problems)

    phrases_raw = sections.get("phrases")
    phrases: dict[str, Any] = {}
    if isinstance(phrases_raw, Mapping):
        phrases = dict(phrases_raw)
    elif phrases_raw is not None:
        problems.append(f"{code}/phrases.yaml: mapping kutilgan edi, "
                        f"{type(phrases_raw).__name__} keldi")

    book, word_problems = words_module.from_data(code, sections.get("words"))
    problems.extend(word_problems)

    grammar = grammar_module.compile(sections.get("rules"), book, code)
    problems.extend(grammar.problems)

    apps = _apps(sections.get("apps"), f"{code}/apps.yaml", problems)

    if fallback is not None and fallback.code == code:
        fallback = None   # o'zini o'ziga zaxira qilish - cheksiz halqa

    # Qoidalar umuman yo'q bo'lsa zaxira tilnikini olamiz. NEGA: aks holda
    # paketi hali yozilmagan tilni tanlagan foydalanuvchi UMUMAN buyruq
    # bera olmasdi. Boshqa tildagi nutqqa o'zbekcha naqshlar mos kelmaydi
    # (kirill/xitoy harflari `\b[a-z]` ga tushmaydi), shuning uchun bu
    # xavfsiz - eng yomoni "Tushunmadim" javobi.
    if not grammar.rules and fallback is not None and fallback.grammar.rules:
        problems.append(f"{code}: intent qoidalari yo'q - {fallback.code} "
                        "grammatikasi ishlatilmoqda")
        grammar = fallback.grammar
        book = fallback.words

    pack = LanguagePack(
        code=code, spec=spec, ui=ui, phrases=phrases, apps=apps,
        words=book, grammar=grammar, problems=tuple(problems),
        source=directory, fallback=fallback,
    )
    log.info("Til paketi yuklandi: %s (%d ui, %d ibora, %d qoida, %d muammo)",
             code, len(ui), len(phrases), len(grammar.rules), len(problems))
    return pack
