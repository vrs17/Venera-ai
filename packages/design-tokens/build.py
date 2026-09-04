#!/usr/bin/env python3
"""tokens.json -> desktop uchun tokens.py, web uchun tokens.css.

Ishlatish (repo ildizidan yoki istalgan joydan):

    python3 packages/design-tokens/build.py

Hech qanday tashqi kutubxona kerak emas - faqat standart Python.
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = HERE / "tokens.json"

PY_OUT = ROOT / "apps" / "desktop" / "src" / "venera" / "ui" / "tokens.py"
CSS_OUT = ROOT / "apps" / "web" / "src" / "tokens.css"

BANNER = "GENERATSIYA QILINGAN FAYL - QO'LDA TAHRIRLAMANG."
SOURCE_HINT = "Manba: packages/design-tokens/tokens.json | Qayta yig'ish: python3 packages/design-tokens/build.py"


def _clean(section: dict) -> dict:
    """`_` bilan boshlanadigan izoh kalitlarini olib tashlaydi."""
    return {k: v for k, v in section.items() if not k.startswith("_")}


def render_python(data: dict) -> str:
    states = _clean(data["state"])
    semantic = _clean(data["semantic"])
    desktop = _clean(data["desktop"])
    mark = data["brand"]["mark"]

    lines = [
        f'"""Venera dizayn tokenlari (desktop).',
        "",
        BANNER,
        SOURCE_HINT,
        '"""',
        "",
        "from __future__ import annotations",
        "",
        f"# Brend belgisi - tray ikonkasi va installer sarlavhasida chiziladi.",
        f"MARK = {mark!r}",
        "",
        "# --- Holat ranglari (core.states.State qiymatlari bilan mos) ---",
        "STATE_COLORS: dict[str, str] = {",
    ]
    for name, spec in states.items():
        note = spec.get("note", "")
        suffix = f"  # {note}" if note else ""
        lines.append(f"    {name!r}: {spec['color']!r},{suffix}")
    lines += [
        "}",
        "",
        "# --- Natija ranglari ---",
    ]
    for name, value in semantic.items():
        lines.append(f"{name.upper()} = {value!r}")
    lines += [
        "",
        "# --- Desktop palitrasi (tkinter oynasi + tray) ---",
    ]
    for name, value in desktop.items():
        lines.append(f"{name.upper()} = {value!r}")
    lines.append("")
    return "\n".join(lines)


def render_css(data: dict) -> str:
    states = _clean(data["state"])
    semantic = _clean(data["semantic"])

    lines = [
        "/* Venera dizayn tokenlari (web).",
        f"   {BANNER}",
        f"   {SOURCE_HINT}",
        "",
        "   Bu faylda FAQAT ikkala mahsulot uchun umumiy tokenlar bor (holat va natija",
        "   ranglari). Web'ning o'z mavzusi (och/qorong'i, --accent, --bg va h.k.)",
        "   index.css da qoladi - u web'ga xos va desktop bilan ulashilmaydi. */",
        "",
        ":root {",
        "  /* Ovozli yordamchi holatlari */",
    ]
    for name, spec in states.items():
        note = spec.get("note", "")
        suffix = f"  /* {note} */" if note else ""
        lines.append(f"  --venera-state-{name}: {spec['color']};{suffix}")
    lines += ["", "  /* Natija ranglari */"]
    for name, value in semantic.items():
        lines.append(f"  --venera-{name}: {value};")
    lines += ["}", ""]
    return "\n".join(lines)


def main() -> int:
    data = json.loads(SOURCE.read_text(encoding="utf-8"))

    for target, content in ((PY_OUT, render_python(data)), (CSS_OUT, render_css(data))):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        print(f"yozildi: {target.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
