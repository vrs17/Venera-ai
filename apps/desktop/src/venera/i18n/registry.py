"""`LocaleRegistry` - qanday tillar bor va ularni qanday yuklash.

KASHF QILISH: kodda QATTIQ TILLAR RO'YXATI YO'Q va bu ataylab. Yangi til
qo'shish = `resources/i18n/<kod>/` papkasi yaratish. `discover()` faqat
`locale.yaml` larni o'qiydi (ular kichik), `load()` esa faqat FAOL til uchun
qolgan beshta faylni oladi. Shu tufayli 4 til ham, 40 til ham ishga tushish
vaqtiga bir xil ta'sir qiladi.

IKKI MANBA:
  1. `config_dir()/i18n/<kod>/`  - foydalanuvchi qo'shgan yoki tuzatgan til
  2. `resources/i18n/<kod>/`     - paket bilan kelgan til
Birinchisi ustun. Shu tufayli IT xodimi ilovani qayta yig'masdan tarjimani
tuzatishi mumkin.

`config.LANGUAGES` bilan farqi MUHIM: u STT serveri qabul qiladigan tillar
ro'yxati (server shartnomasi), bu esa UI paketi BOR tillar. `zh` birinchisida
bor, ikkinchisida yo'q - o'shanda STT xitoycha ishlaydi, interfeys esa
zaxira tilga tushadi.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable, Sequence

from .. import paths
from .locale import FALLBACK_CODE, LocaleSpec
from .locale import parse as parse_spec
from .pack import LanguagePack, empty as empty_pack, load_pack, read_yaml

log = logging.getLogger(__name__)

#: Papka nomi shu ko'rinishda bo'lishi kerak: "uz", "en", "pt-br"
_CODE_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789-_")


def default_roots() -> tuple[Path, ...]:
    """Til papkalari qidiriladigan joylar - MUHIMLIK tartibida."""
    return (paths.config_dir() / "i18n", paths.resource("i18n"))


def _valid_code(name: str) -> bool:
    return bool(name) and not name.startswith(".") and set(name.lower()) <= _CODE_CHARS


class LocaleRegistry:
    """Tillar katalogi. Bir marta yaratiladi, `i18n` moduli ichida yashaydi."""

    def __init__(self, roots: Sequence[Path] | None = None) -> None:
        self._roots: tuple[Path, ...] = tuple(Path(r) for r in roots) if roots else ()
        self._specs: dict[str, LocaleSpec] | None = None
        self._dirs: dict[str, Path] = {}
        self._problems: list[str] = []

    @property
    def roots(self) -> tuple[Path, ...]:
        return self._roots or default_roots()

    @property
    def problems(self) -> tuple[str, ...]:
        self.discover()
        return tuple(self._problems)

    # --- kashf qilish -------------------------------------------------------

    def discover(self, force: bool = False) -> dict[str, LocaleSpec]:
        """Barcha tillarning pasportini o'qiydi (qolgan fayllarga tegmasdan)."""
        if self._specs is not None and not force:
            return self._specs

        specs: dict[str, LocaleSpec] = {}
        dirs: dict[str, Path] = {}
        problems: list[str] = []

        for root in self.roots:
            try:
                if not root.is_dir():
                    continue
                children = sorted(root.iterdir())
            except OSError as exc:
                problems.append(f"i18n: {root} o'qilmadi ({exc})")
                continue

            for child in children:
                try:
                    if not child.is_dir():
                        continue
                except OSError:
                    continue
                code = child.name.lower()
                if not _valid_code(code) or code in specs:
                    continue   # birinchi ildiz ustun
                passport = child / "locale.yaml"
                if not passport.exists():
                    continue
                data, error = read_yaml(passport)
                if error:
                    problems.append(f"i18n: {error}")
                spec, spec_problems = parse_spec(code, data if data is not None else {})
                problems.extend(spec_problems)
                specs[code] = spec
                dirs[code] = child

        self._specs = specs
        self._dirs = dirs
        self._problems = problems
        log.info("Til paketlari topildi: %s", ", ".join(sorted(specs)) or "yo'q")
        return specs

    def codes(self) -> tuple[str, ...]:
        """Mavjud til kodlari. Etalon til ("uz") har doim birinchi."""
        found = sorted(self.discover())
        if FALLBACK_CODE in found:
            found.remove(FALLBACK_CODE)
            found.insert(0, FALLBACK_CODE)
        return tuple(found)

    def names(self) -> dict[str, str]:
        """kod -> tilning O'Z tilidagi nomi (UI ro'yxati uchun)."""
        specs = self.discover()
        return {code: specs[code].display for code in self.codes()}

    def spec(self, code: str) -> LocaleSpec | None:
        return self.discover().get(str(code).strip().lower())

    def has(self, code: str) -> bool:
        return str(code).strip().lower() in self.discover()

    def directory(self, code: str) -> Path | None:
        self.discover()
        return self._dirs.get(str(code).strip().lower())

    # --- yuklash ------------------------------------------------------------

    def load(self, code: str, fallback: LanguagePack | None = None) -> LanguagePack:
        """Bitta tilni TO'LIQ yuklaydi. Topilmasa bo'sh paket qaytadi."""
        code = str(code or "").strip().lower()
        directory = self.directory(code)
        if directory is None:
            log.warning("Til paketi topilmadi: %r (mavjud: %s)",
                        code, ", ".join(self.codes()) or "yo'q")
            pack = empty_pack(code)
            fallback = fallback if fallback and fallback.code != code else None
            problems = [f"{code}: til paketi topilmadi"]
            grammar = pack.grammar
            book = pack.words
            if fallback is not None and fallback.grammar.rules:
                # Interfeys ham, qoidalar ham zaxira tildan. STT esa
                # foydalanuvchi tanlagan tilda ishlayveradi.
                problems.append(f"{code}: intent qoidalari {fallback.code} tilidan olindi")
                grammar = fallback.grammar
                book = fallback.words
            return LanguagePack(
                code=pack.code, spec=pack.spec, grammar=grammar, words=book,
                problems=tuple(problems), fallback=fallback,
            )
        return load_pack(code, directory, fallback=fallback)

    def load_fallback(self) -> LanguagePack:
        """Etalon (`uz`) paketi - qolgan hamma til unga suyanadi."""
        return self.load(FALLBACK_CODE)

    def missing(self, codes: Iterable[str]) -> tuple[str, ...]:
        """Berilgan kodlardan qaysilari uchun til paketi YO'Q.

        `config.LANGUAGES` bilan solishtirish uchun: `zh` STT'da bor, lekin
        UI paketi yo'q - `--check` shuni aniq yozishi kerak.
        """
        available = set(self.discover())
        return tuple(c for c in codes if str(c).strip().lower() not in available)
