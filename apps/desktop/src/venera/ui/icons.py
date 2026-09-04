"""Tray ikonkalari - kod bilan chiziladi, binar fayl saqlanmaydi.

Shu sababli PyInstaller'ga qo'shimcha resurs kerak emas va ikonka har qanday
o'lchamda aniq chiqadi. Ranglar holatni bir qarashda bildiradi.
"""

from __future__ import annotations

from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from ..core.states import State

# Ranglar va brend harfi packages/design-tokens/tokens.json dan generatsiya qilinadi.
from .tokens import ERROR, MARK, ON_ACCENT, STATE_COLORS

SIZE = 64

#: Holat -> halqa rangi
COLORS: dict[str, str] = STATE_COLORS
ERROR_COLOR = ERROR


def _font(size: int) -> ImageFont.ImageFont:
    for name in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:  # noqa: BLE001
            continue
    return ImageFont.load_default()


@lru_cache(maxsize=16)
def build(state: str = State.IDLE.value, error: bool = False) -> Image.Image:
    """Berilgan holat uchun ikonka rasmi."""
    ring = ERROR_COLOR if error else COLORS.get(state, COLORS[State.IDLE.value])

    image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    margin = 3
    draw.ellipse([margin, margin, SIZE - margin, SIZE - margin], fill=ring)

    text = MARK
    font = _font(38)
    try:
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
        width, height = right - left, bottom - top
        position = ((SIZE - width) / 2 - left, (SIZE - height) / 2 - top)
    except Exception:  # noqa: BLE001 - juda eski Pillow
        position = (SIZE / 3, SIZE / 4)
    draw.text(position, text, font=font, fill=ON_ACCENT)

    # Pastki o'ng burchakda holat nuqtasi (kichik o'lchamda ham farqlanadi)
    if state != State.IDLE.value or error:
        dot = 16
        draw.ellipse(
            [SIZE - dot - 2, SIZE - dot - 2, SIZE - 2, SIZE - 2],
            fill=ON_ACCENT, outline=ring, width=2,
        )
    return image


def app_icon(size: int = 256) -> Image.Image:
    """Ilova ikonkasi (.exe va installer uchun)."""
    return build(State.IDLE.value).resize((size, size), Image.LANCZOS)


def save_ico(destination, sizes: tuple[int, ...] = (16, 24, 32, 48, 64, 128, 256)) -> None:
    """Ko'p o'lchamli .ico faylini saqlaydi."""
    base = app_icon(256)
    base.save(destination, format="ICO", sizes=[(s, s) for s in sizes])
