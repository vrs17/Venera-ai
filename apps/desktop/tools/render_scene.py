#!/usr/bin/env python3
"""Ovoz sahnasini PNG ga chizadi - Tk'siz ko'z bilan ko'rish uchun.

    python3 tools/render_scene.py                # barcha holatlar bitta varaqda
    python3 tools/render_scene.py speaking 1200  # bitta holat, 1200 ms

NIMA UCHUN KERAK. Sahna Tk Canvas'da chiziladi, lekin Tk ko'p ishlab chiqish
mashinalarida (CI, WSL, konteyner) umuman yo'q. Bu skript AYNAN o'sha
`scene.compose()` chiqishini oladi va PIL bilan chizadi - ya'ni geometriya,
ranglar va faza bo'yicha bu haqiqiy dalil.

CHEGARA - halol bo'lish uchun: PIL va Tk ikki xil rasterizator (PIL o'z
scanline'i; Tk X11 `XFillArc` / Win32 GDI). Ikkalasi ham antialiasing
qilmaydi, lekin CHEKKA piksellari bir xil bo'lishi shart emas. Ya'ni bu
rasm geometriyani isbotlaydi, piksel-aniq ko'rinishni emas.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PIL import Image, ImageDraw  # noqa: E402

from venera.core.states import State  # noqa: E402
from venera.ui import scene  # noqa: E402
from venera.ui.tokens import BG  # noqa: E402

WIDTH = 488


def render(state: str, elapsed_ms: float = 0.0, level: float = 0.6,
           error: bool = False) -> Image.Image:
    """Bitta kadr. `scene.compose()` dan boshqa manba ishlatilmaydi."""
    frame = scene.compose(state, elapsed_ms, level, WIDTH, error)
    image = Image.new("RGB", (WIDTH, scene.SCENE_HEIGHT), BG)
    draw = ImageDraw.Draw(image)

    # Tartib = Tk dagi z-tartib: halo (tashqaridan ichkariga) -> orb -> to'lqin.
    for box, color in zip(frame.halo_boxes, frame.halo_colors):
        draw.ellipse(_box(box), fill=color)

    draw.ellipse(_box(frame.disk), fill=scene.NIGHT)
    # PIL burchaklari SOAT BO'YICHA, Tk niki soat teskari. `start=-90,
    # extent=180` ikkalasida ham o'ng yarimni beradi (180 gradus simmetriya),
    # lekin extent o'zgarsa ikki fayl ikki xil buziladi - shuning uchun
    # bu yerda burchak ATAYLAB qayta hisoblanadi.
    start = frame.lit[1]
    end = start + frame.lit[2]
    draw.pieslice(_box(frame.lit[0]), -end, -start, fill=frame.lit_color)
    draw.ellipse(_box(frame.terminator), fill=frame.terminator_fill)

    if frame.aureole is not None:
        draw.ellipse(_box(frame.aureole), outline=frame.aureole_color, width=2)
    if frame.orbit is not None:
        draw.ellipse(_box(frame.orbit), fill=frame.orbit_color)
    for box in frame.wave:
        draw.rectangle(_box(box), fill=frame.wave_color)
    return image


def _box(box):
    x0, y0, x1, y1 = box
    return [round(x0), round(y0), round(max(x0, x1)), round(max(y0, y1))]


def sheet(elapsed_ms: float = 700.0) -> Image.Image:
    """Barcha holatlar + xato - bitta ustunda."""
    names = [s.value for s in State] + ["acting"]
    frames = [render(n, elapsed_ms, error=(i == len(names) - 1))
              for i, n in enumerate(names)]
    out = Image.new("RGB", (WIDTH, scene.SCENE_HEIGHT * len(frames)), BG)
    for index, frame in enumerate(frames):
        out.paste(frame, (0, index * scene.SCENE_HEIGHT))
    return out


def main() -> int:
    target = Path("scene.png")
    if len(sys.argv) > 1:
        state = sys.argv[1]
        elapsed = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
        render(state, elapsed).save(target)
        print(f"{state} @ {elapsed:.0f} ms -> {target}")
    else:
        sheet().save(target)
        print(f"barcha holatlar -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
