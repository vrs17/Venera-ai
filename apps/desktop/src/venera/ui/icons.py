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


# Apple talab qiladigan to'plam: (piksel o'lchami, iconset ichidagi nom).
# @2x variantlari Retina uchun - ular AYNAN shu nom bilan bo'lishi shart,
# aks holda `iconutil` "Invalid Iconset" deb rad etadi.
ICONSET_ENTRIES: tuple[tuple[int, str], ...] = (
    (16, "icon_16x16.png"),
    (32, "icon_16x16@2x.png"),
    (32, "icon_32x32.png"),
    (64, "icon_32x32@2x.png"),
    (128, "icon_128x128.png"),
    (256, "icon_128x128@2x.png"),
    (256, "icon_256x256.png"),
    (512, "icon_256x256@2x.png"),
    (512, "icon_512x512.png"),
    (1024, "icon_512x512@2x.png"),
)


def save_iconset(destination) -> None:
    """macOS `.iconset` papkasini yasaydi (PNG'lar to'plami).

    ATAYLAB `.icns` emas: Pillow'ning ICNS yozuvi barcha platformada
    ishonchli emas. PNG'larni istalgan OS'da yasab, `.icns` ga aylantirishni
    Mac'dagi `iconutil` bajaradi:

        iconutil -c icns Venera.iconset -o Venera.icns

    Shu tufayli ikonka manbasi bitta joyda (shu modul) qoladi va Windows
    bilan macOS bir xil rasmdan kelib chiqadi.
    """
    from pathlib import Path

    target = Path(destination)
    target.mkdir(parents=True, exist_ok=True)
    # 1024 dan pastga qarab kichraytiramiz - o'stirish emas, shuning uchun
    # chekkalar toza chiqadi.
    master = build(State.IDLE.value).resize((1024, 1024), Image.LANCZOS)
    for size, name in ICONSET_ENTRIES:
        master.resize((size, size), Image.LANCZOS).save(target / name, format="PNG")
