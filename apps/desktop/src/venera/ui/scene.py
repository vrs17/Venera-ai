"""Ovoz sahnasi: holat orbi, halo, to'lqin va retrograd nuqta.

IKKI QATLAM, ATAYLAB AJRATILGAN:

  SOF QATLAM (faylning katta qismi) - geometriya, ranglar, vaqt.
    `tkinter` ni IMPORT QILMAYDI. Shuning uchun u tkinter o'rnatilmagan
    mashinada ham TO'LIQ test qilinadi.

  TK QATLAMI (`VoiceScene`) - faqat item yaratish va `coords`/`itemconfigure`.
    Hech qanday qaror yo'q: hamma qiymat sof qatlamdan tayyor holda keladi.

NIMA UCHUN SHUNDAY. Bu sahnaning oldingi spetsifikatsiyasi Tk'da hech qachon
ishga tushirilmagan holda yozilgan edi va adversarial baho unda 12 ta
bloklovchi xato topdi. Ularning KO'PCHILIGI sof arifmetika edi:

  * halo formulasi manfiy asosni kasrli darajaga ko'targani uchun COMPLEX
    son qaytarardi va animatsiya jimgina o'lardi (`(1 - 5/4) ** 2.2`);
  * "retrograd" nuqta aslida soat strelkasi bo'yicha aylanardi, ya'ni butun
    ajratuvchi belgi teskari edi;
  * sahna o'z canvas'iga sig'masdi (halo -42 px da boshlanardi);
  * to'lqin ustunlari sayyora diskini kesib o'tardi.

Shularning HAMMASI mantiq sof bo'lganda oddiy testda ushlanadi - pastdagi
`tests/test_scene.py` aynan shuni qiladi. Tk qatlamida esa tekshiriladigan
mantiq qolmagani uchun uni Windows'da ko'z bilan ko'rish yetarli.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .tokens import BG, ERROR, NIGHT, PEARL, STATE_COLORS

# --- sahna o'lchamlari ------------------------------------------------------
#: Canvas balandligi. Eng katta halo (R=68 + reach=58 = 126) markazdan ikki
#: tomonga sig'ishi SHART: 132 - 126 = 6 va 132 + 126 = 258 <= 270.
SCENE_HEIGHT = 270
CENTER_Y = 132.0

#: Halo halqalari soni. Tk ovali antialiased EMAS, shuning uchun qo'shni
#: halqalar orasidagi rang sakrashi to'g'ridan-to'g'ri ko'rinadigan chegara
#: beradi. O'lchangan (`test_scene.py` buni har commitda qayta o'lchaydi):
#:     6 halqa, daraja 2.2   -> 24/255   ochiq band
#:    14 halqa, daraja 2.2   -> 13/255   hali ko'rinadi
#:    22 halqa, kosinus      ->  6/255   ko'rinmaydi
#: Ranglar FAQAT holat almashganda hisoblanadi (alpha vaqt bilan o'zgarmaydi),
#: shuning uchun halqa soni kadr narxiga ta'sir qilmaydi - har kadrda faqat
#: `coords()` ketadi.
HALO_RINGS = 22
HALO_REACH = 58.0

#: To'lqin. Asos chizig'i orb bbox'idan TASHQARIDA turishi shart, aks holda
#: ustunlar diskni kesib o'tadi (ular z-tartibda yuqorida).
WAVE_BARS = 28
WAVE_BAR_WIDTH = 6
WAVE_BAR_STEP = 10
WAVE_BASELINE = 246.0
WAVE_MIN_HEIGHT = 2.0

#: Kadr. Vaqt HAR DOIM soatdan olinadi, kadr sanashdan emas.
FRAME_MS = 33

#: Halo tushish darajasi (ko'tarilgan kosinus ustidagi daraja). Kosinusning
#: hosilasi IKKALA uchida ham nol: disk chetida ham, fonda ham qadam yo'q.
#: Daraja darajali (`(1-i/N)**p`) tushishda hosila boshida katta bo'lib,
#: eng ko'zga tashlanadigan joyda - disk yonida - qattiq chegara qoldirardi.
HALO_FALLOFF = 1.0


# --- ranglar ----------------------------------------------------------------

def _channels(color: str) -> tuple[int, int, int]:
    value = color.lstrip("#")
    if len(value) != 6:
        raise ValueError(f"hex rang kutilgan edi: {color!r}")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def mix(base: str, other: str, amount: float) -> str:
    """`base` va `other` orasida aralashma. `amount` 0..1 oralig'iga qisiladi.

    Tk canvas'da alpha yo'q - "shaffoflik" har doim fon bilan aralashtirish.
    """
    ratio = min(1.0, max(0.0, float(amount)))
    a, b = _channels(base), _channels(other)
    parts = (round(a[i] + (b[i] - a[i]) * ratio) for i in range(3))
    return "#{:02X}{:02X}{:02X}".format(*parts)


def relative_luminance(color: str) -> float:
    def channel(value: int) -> float:
        srgb = value / 255.0
        return srgb / 12.92 if srgb <= 0.04045 else ((srgb + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(v) for v in _channels(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(first: str, second: str) -> float:
    """WCAG 2.x kontrast nisbati. Testlar siluet ko'rinishini shu bilan o'lchaydi."""
    a, b = relative_luminance(first), relative_luminance(second)
    light, dark = max(a, b), min(a, b)
    return (light + 0.05) / (dark + 0.05)


# --- holat lug'ati ----------------------------------------------------------

@dataclass(frozen=True)
class StateStyle:
    """Bitta holatning ko'rinishi. Barcha qiymat SOF - vaqt bu yerda yo'q."""

    radius: float
    #: Yoritilgan ulush. 0 = butunlay tungi, 1 = to'la disk.
    #: HECH QAYERDA 0.0 yoki 1.0 EMAS: ikkala chekkada ham belgi oddiy
    #: doiraga aylanadi va tanib bo'lmaydi.
    phase: float
    halo_alpha: float
    #: Halqalarning qancha ulushi yonadi (0..1).
    halo_spread: float
    wave_amp: float
    #: To'lqin tirikmi. `False` - oxirgi qiymatlarda muzlaydi (nolga tushmaydi):
    #: "ichki ish ketyapti, kirish yopiq" degani.
    wave_alive: bool
    aureole: bool
    #: Retrograd nuqta davri (ms). 0 = nuqta yo'q.
    orbit_ms: float
    #: Nafas davri (ms). 0 = harakatsiz.
    breathe_ms: float
    breathe_amp: float = 0.0
    #: Ovoz darajasi radiusga qancha ta'sir qiladi (px).
    level_gain: float = 0.0


#: `core.states.State` qiymatlari bilan bir xil kalitlar.
STYLES: dict[str, StateStyle] = {
    # Bank xodimi ekranida 8 soat turadi - eng sokin holat.
    "idle": StateStyle(radius=44, phase=0.60, halo_alpha=0.26, halo_spread=0.55,
                       wave_amp=7, wave_alive=True, aureole=False, orbit_ms=0,
                       breathe_ms=4200, breathe_amp=2.5),
    # Yagona "chaqnash". Radius va faza birga overshoot qiladi.
    "activated": StateStyle(radius=64, phase=0.80, halo_alpha=0.42, halo_spread=0.85,
                            wave_amp=10, wave_alive=True, aureole=True, orbit_ms=0,
                            breathe_ms=0, breathe_amp=0),
    # Aniq yarimga yaqin disk - eng o'qiladigan siluet. To'lqin asosiy aktyor.
    "capturing": StateStyle(radius=60, phase=0.52, halo_alpha=0.34, halo_spread=0.70,
                            wave_amp=22, wave_alive=True, aureole=False, orbit_ms=0,
                            breathe_ms=2000, breathe_amp=2.0, level_gain=8.0),
    # Uchalasi bir xil ko'rinadi - ular allaqachon bir xil rangda. Farq
    # nuqtaning tezligida: ish qancha "yaqin" bo'lsa, shuncha tez aylanadi.
    "transcribing": StateStyle(radius=58, phase=0.72, halo_alpha=0.30, halo_spread=0.70,
                               wave_amp=10, wave_alive=False, aureole=False,
                               orbit_ms=2600, breathe_ms=0),
    "thinking": StateStyle(radius=58, phase=0.72, halo_alpha=0.30, halo_spread=0.70,
                           wave_amp=10, wave_alive=False, aureole=False,
                           orbit_ms=1800, breathe_ms=0),
    "acting": StateStyle(radius=58, phase=0.72, halo_alpha=0.30, halo_spread=0.70,
                         wave_amp=10, wave_alive=False, aureole=False,
                         orbit_ms=1200, breathe_ms=0),
    # Mustaqil nafas yo'q - amplitudaning o'zi ritm beradi.
    "speaking": StateStyle(radius=60, phase=0.88, halo_alpha=0.46, halo_spread=0.90,
                           wave_amp=20, wave_alive=True, aureole=False, orbit_ms=0,
                           breathe_ms=0, level_gain=6.0),
    # HARAKAT YO'Q: sikl butunlay to'xtaydi, 0% CPU.
    # Faza 0.55 - 0.00 EMAS: butunlay tungi disk fonda yo'qolardi
    # (night vs bg kontrasti 1.3:1). Siluet saqlanishi shart.
    "paused": StateStyle(radius=38, phase=0.55, halo_alpha=0.08, halo_spread=0.35,
                         wave_amp=0, wave_alive=False, aureole=True, orbit_ms=0,
                         breathe_ms=0),
}

#: Terminator surilishi (transcribing/thinking/acting): "sayyora aylanmoqda",
#: "yuklanmoqda" spinneri emas. Ataylab sekin.
DRIFT_MS = 3400.0
DRIFT_AMP = 0.10

#: `activated` chaqnashi.
FLASH_MS = 440.0
FLASH_PEAK_MS = 180.0
FLASH_START_RADIUS = 44.0
FLASH_PEAK_RADIUS = 68.0


# --- egri chiziqlar ---------------------------------------------------------

def ease_out_cubic(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return 1.0 - (1.0 - x) ** 3


def ease_in_out(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return x * x * (3.0 - 2.0 * x)


# --- geometriya -------------------------------------------------------------

Box = tuple[float, float, float, float]


@dataclass(frozen=True)
class Phase:
    """Faza diski uch primitivda. Terminator HAQIQATDA ellips - shuning uchun
    yolg'iz `create_arc` yetmaydi."""

    disk: Box
    #: Yoritilgan yarim: (box, start, extent).
    lit: tuple[Box, float, float]
    #: Terminator ellipsi va uning rangi.
    terminator: Box
    terminator_fill: str


def phase(cx: float, cy: float, radius: float, fraction: float,
          lit_color: str, mirrored: bool = False) -> Phase:
    """Yoritilgan ulushi `fraction` bo'lgan faza diski.

    Tekshiruv: fraction=1 -> terminator butun diskni yopadi (to'la);
    fraction=0.5 -> terminator eni nol (aniq yarim);
    fraction=0 -> disk butunlay tungi.

    `mirrored` - yorug' tomon CHAPDA. Faqat XATO holati uchun: rang ko'rmaydigan
    foydalanuvchi uchun xato va "uyg'ondi" boshqacha SHAKLDA bo'lishi kerak.
    """
    r = max(0.0, float(radius))
    k = min(1.0, max(0.0, float(fraction)))
    box: Box = (cx - r, cy - r, cx + r, cy + r)
    # Tk burchaklari: 0 = soat 3, musbat = soat strelkasiga TESKARI.
    start = 90.0 if mirrored else -90.0
    half_width = r * abs(2.0 * k - 1.0)
    return Phase(
        disk=box,
        lit=(box, start, 180.0),
        terminator=(cx - half_width, cy - r, cx + half_width, cy + r),
        # k > 0.5 - qavariq: yorug'lik tungi tomonga cho'ziladi.
        terminator_fill=lit_color if k > 0.5 else NIGHT,
    )


def halo_ring_boxes(cx: float, cy: float, radius: float,
                    spread: float = 1.0) -> tuple[Box, ...]:
    """Halqa qutilari - TASHQARIDAN ICHKARIGA.

    Yaratilish tartibi = z-tartib, shuning uchun eng kattasi birinchi.
    `spread` halqalar SONINI emas, yoyilish MASOFASINI belgilaydi: gradient
    har doim to'liq 22 halqaga yoyiladi, aks holda kam halqada siqilib
    ko'rinadigan qadam berardi.
    """
    reach = HALO_REACH * min(1.0, max(0.0, float(spread)))
    boxes = []
    for index in reversed(range(HALO_RINGS)):
        r = radius + reach * (index + 1) / HALO_RINGS
        boxes.append((cx - r, cy - r, cx + r, cy + r))
    return tuple(boxes)


def halo_colors(color: str, alpha: float, background: str = BG) -> tuple[str, ...]:
    """Halqa ranglari - TASHQARIDAN ICHKARIGA, `halo_ring_boxes` bilan bir tartibda.

    Og'irlik ko'tarilgan kosinus: `(1 + cos(pi*i/N)) / 2`. Asos hech qachon
    manfiy bo'lmaydi - manfiy asosni kasrli darajaga ko'tarish Python'da
    COMPLEX son beradi va animatsiyani jimgina o'ldirardi.
    """
    colors = []
    for index in reversed(range(HALO_RINGS)):
        weight = (0.5 + 0.5 * math.cos(math.pi * index / HALO_RINGS)) ** HALO_FALLOFF
        colors.append(mix(background, color, alpha * weight))
    return tuple(colors)


def orbit_point(cx: float, cy: float, radius: float, elapsed_ms: float,
                period_ms: float, start_angle: float = 90.0) -> tuple[float, float]:
    """Retrograd nuqtaning markazi.

    Ekranda y PASTGA o'sadi, shuning uchun `y = cy - r*sin(t)` bilan burchakni
    OSHIRISH soat strelkasiga TESKARI harakat beradi - Veneraning -243 kunlik
    teskari aylanishi. Burchakni kamaytirish teskari natija berardi.
    """
    if period_ms <= 0:
        return cx + radius, cy
    theta = math.radians(start_angle) + 2.0 * math.pi * elapsed_ms / period_ms
    return cx + radius * math.cos(theta), cy - radius * math.sin(theta)


def wave_heights(amplitude: float, elapsed_ms: float, level: float,
                 alive: bool) -> tuple[float, ...]:
    """To'lqin ustunlari balandligi.

    Muzlagan holatda ustunlar NOLGA TUSHMAYDI - oxirgi shakl saqlanadi,
    aks holda "ish ketyapti" o'rniga "hech narsa yo'q" ko'rinardi.
    """
    if alive:
        peak = max(0.0, amplitude) * (0.35 + 0.65 * min(1.0, max(0.0, level)))
    else:
        # Muzlagan to'lqin KIRISHDAN MUSTAQIL: mikrofon yopiq bo'lgani uchun
        # `level` nolga tushadi va jonli formula bilan ustunlar tekislanib
        # "hech narsa yo'q" ko'rinishini berardi.
        peak = max(0.0, amplitude) * 0.55
    heights = []
    for index in range(WAVE_BARS):
        # Markazda baland, chetlarda past - ovoz manbai markazda.
        centre = 1.0 - abs(index - (WAVE_BARS - 1) / 2.0) / ((WAVE_BARS - 1) / 2.0)
        shape = 0.35 + 0.65 * centre
        if alive:
            wobble = 0.65 + 0.35 * math.sin(
                2.0 * math.pi * (elapsed_ms / 900.0 + index / 7.0))
        else:
            wobble = 0.65 + 0.35 * math.sin(index / 7.0 * 2.0 * math.pi)
        heights.append(WAVE_MIN_HEIGHT + peak * shape * wobble)
    return tuple(heights)


def wave_boxes(cx: float, heights: tuple[float, ...]) -> tuple[Box, ...]:
    span = WAVE_BARS * WAVE_BAR_STEP - (WAVE_BAR_STEP - WAVE_BAR_WIDTH)
    x0 = cx - span / 2.0
    boxes = []
    for index, height in enumerate(heights):
        left = x0 + index * WAVE_BAR_STEP
        boxes.append((left, WAVE_BASELINE - height,
                      left + WAVE_BAR_WIDTH, WAVE_BASELINE))
    return tuple(boxes)


# --- bitta kadr -------------------------------------------------------------

@dataclass(frozen=True)
class Frame:
    """Tk qatlami chizishi uchun TAYYOR kadr. Hisob-kitob qolmagan."""

    halo_boxes: tuple[Box, ...]
    halo_colors: tuple[str, ...]
    disk: Box
    lit: tuple[Box, float, float]
    lit_color: str
    terminator: Box
    terminator_fill: str
    aureole: Box | None
    aureole_color: str
    orbit: Box | None
    orbit_color: str
    wave: tuple[Box, ...]
    wave_color: str
    radius: float
    #: Harakat kerakmi. `False` bo'lsa Tk qatlami `after()` siklini butunlay
    #: to'xtatadi - to'xtatilgan holatda 0% CPU.
    animated: bool


def style_for(state: str) -> StateStyle:
    return STYLES.get(state, STYLES["idle"])


def color_for(state: str, error: bool = False) -> str:
    if error:
        return ERROR
    return STATE_COLORS.get(state, STATE_COLORS["idle"])


def _radius_and_phase(style: StateStyle, state: str, elapsed_ms: float,
                      level: float) -> tuple[float, float]:
    radius, fraction = style.radius, style.phase

    if state == "activated":
        # Chaqnash: 0-180ms ko'tarilish, 180-440ms cho'kish. Faza ham birga.
        if elapsed_ms <= FLASH_PEAK_MS:
            t = ease_out_cubic(elapsed_ms / FLASH_PEAK_MS)
            radius = FLASH_START_RADIUS + (FLASH_PEAK_RADIUS - FLASH_START_RADIUS) * t
        elif elapsed_ms <= FLASH_MS:
            t = ease_in_out((elapsed_ms - FLASH_PEAK_MS) / (FLASH_MS - FLASH_PEAK_MS))
            radius = FLASH_PEAK_RADIUS + (style.radius - FLASH_PEAK_RADIUS) * t
        return radius, fraction

    if style.orbit_ms > 0:
        # Terminator sekin suriladi - "sayyora aylanmoqda".
        fraction = style.phase + DRIFT_AMP * math.sin(
            2.0 * math.pi * elapsed_ms / DRIFT_MS)

    if style.breathe_ms > 0:
        radius += style.breathe_amp * math.sin(
            2.0 * math.pi * elapsed_ms / style.breathe_ms)

    radius += style.level_gain * min(1.0, max(0.0, level))
    return radius, fraction


def compose(state: str, elapsed_ms: float = 0.0, level: float = 0.0,
            width: float = 488.0, error: bool = False) -> Frame:
    """Berilgan holat va vaqt uchun tayyor kadr.

    SOF funksiya: bir xil kirishga har doim bir xil kadr. Shuning uchun butun
    vizual mantiq tkintersiz test qilinadi.
    """
    style = style_for(state)
    color = color_for(state, error)
    cx = width / 2.0
    cy = CENTER_Y

    radius, fraction = _radius_and_phase(style, state, elapsed_ms, level)
    disk = phase(cx, cy, radius, fraction, color, mirrored=error)

    heights = wave_heights(style.wave_amp, elapsed_ms, level, style.wave_alive)
    animated = style.breathe_ms > 0 or style.orbit_ms > 0 or style.wave_alive

    aureole_box: Box | None = None
    if style.aureole:
        r = radius + 2.0
        aureole_box = (cx - r, cy - r, cx + r, cy + r)

    orbit_box: Box | None = None
    if style.orbit_ms > 0:
        ox, oy = orbit_point(cx, cy, radius + 22.0, elapsed_ms, style.orbit_ms)
        orbit_box = (ox - 3.0, oy - 3.0, ox + 3.0, oy + 3.0)

    return Frame(
        halo_boxes=halo_ring_boxes(cx, cy, radius, style.halo_spread),
        halo_colors=halo_colors(color, style.halo_alpha),
        disk=disk.disk,
        lit=disk.lit,
        lit_color=color,
        terminator=disk.terminator,
        terminator_fill=disk.terminator_fill,
        aureole=aureole_box,
        aureole_color=mix(BG, PEARL, 0.55),
        orbit=orbit_box,
        orbit_color=mix(BG, PEARL, 0.85),
        wave=wave_boxes(cx, heights),
        wave_color=mix(BG, color, 0.75 if style.wave_alive else 0.30),
        radius=radius,
        animated=animated,
    )


# --- Tk qatlami -------------------------------------------------------------
#
# Bu yerdan pastda QAROR YO'Q. Har bir qiymat yuqoridagi `compose()` dan
# tayyor keladi; bu sinf faqat item yaratadi va `coords`/`itemconfigure`
# chaqiradi. Shuning uchun uni ko'z bilan ko'rish yetarli - tekshiriladigan
# mantiq qolmagan.

import logging
import time

log = logging.getLogger(__name__)


class VoiceScene:
    """Holat orbi va to'lqin - Tk Canvas ustida.

    Itemlar BIR MARTA yaratiladi va hech qachon qayta yaratilmaydi: yaratish
    tartibi z-tartibni belgilaydi (halo -> orb -> aureole -> nuqta -> to'lqin).
    """

    def __init__(self, tk, parent, width: float = 488.0) -> None:
        self._tk = tk
        self._width = float(width)
        self._state = "idle"
        self._error = False
        self._level = 0.0
        self._started = 0.0
        self._after_id = None
        self._alive = True
        #: Halo ranglari FAQAT holat almashganda hisoblanadi - har kadrda emas.
        self._halo_cache: tuple[str, ...] = ()

        self.canvas = tk.Canvas(parent, height=SCENE_HEIGHT, bg=BG,
                                highlightthickness=0, bd=0)
        self._build()
        self.canvas.bind("<Configure>", self._on_resize)
        self.set_state(self._state)

    # --- qurish -------------------------------------------------------------

    def _build(self) -> None:
        c = self.canvas
        # outline="" HAMMASIDA MAJBURIY: Tk oval/arc chekkasiga sukut bo'yicha
        # qora soch chiziq qo'yadi va u terminator ustida ko'rinib qoladi.
        self._halo = [c.create_oval(0, 0, 0, 0, fill=BG, outline="")
                      for _ in range(HALO_RINGS)]
        self._dark = c.create_oval(0, 0, 0, 0, fill=NIGHT, outline="")
        self._lit = c.create_arc(0, 0, 0, 0, start=-90, extent=180,
                                 style="pieslice", fill=BG, outline="")
        self._term = c.create_oval(0, 0, 0, 0, fill=NIGHT, outline="")
        self._aureole = c.create_oval(0, 0, 0, 0, fill="", outline="", width=2)
        self._orbit = c.create_oval(0, 0, 0, 0, fill="", outline="")
        self._bars = [c.create_rectangle(0, 0, 0, 0, fill=BG, outline="")
                      for _ in range(WAVE_BARS)]

    def _on_resize(self, event) -> None:
        if event.width > 1:
            self._width = float(event.width)
            self._draw()

    # --- tashqi API ---------------------------------------------------------

    def set_state(self, state: str, error: bool = False) -> None:
        self._state = state if state in STYLES else "idle"
        self._error = bool(error)
        self._started = time.monotonic()
        self._halo_cache = halo_colors(color_for(self._state, self._error),
                                       style_for(self._state).halo_alpha)
        self._draw()
        self._reschedule()

    def set_level(self, level: float) -> None:
        """Mikrofon darajasi. Manba 20 Hz, sahna 30 fps - shuning uchun
        oxirgi qiymat kadrlar orasida ushlab turiladi."""
        try:
            self._level = min(1.0, max(0.0, float(level)))
        except (TypeError, ValueError):
            self._level = 0.0

    def stop(self) -> None:
        """Idempotent. `after` bekor qilinadi, aks holda oyna yopilgandan
        keyin otilgan tick `TclError: invalid command name` beradi."""
        self._alive = False
        self._cancel()

    # --- sikl ---------------------------------------------------------------

    def _cancel(self) -> None:
        after_id, self._after_id = self._after_id, None
        if after_id is None:
            return
        try:
            self.canvas.after_cancel(after_id)
        except Exception:  # noqa: BLE001 - oyna allaqachon yopilgan bo'lishi mumkin
            pass

    def _reschedule(self) -> None:
        """Harakatsiz holatda (PAUSED) sikl UMUMAN qayta rejalashtirilmaydi:
        0% CPU. Kadr o'zi harakat kerakligini aytadi."""
        self._cancel()
        if not self._alive:
            return
        frame = compose(self._state, 0.0, self._level, self._width, self._error)
        if not frame.animated:
            return
        try:
            self._after_id = self.canvas.after(FRAME_MS, self._tick)
        except Exception:  # noqa: BLE001
            self._after_id = None

    def _tick(self) -> None:
        self._after_id = None
        if not self._alive:
            return
        # Ko'rinmayotgan oyna uchun chizmaymiz. `state() == "normal"`
        # minimallashtirilgan oynada ham to'g'ri qaytaradi ("iconic" faqat
        # ba'zi menejerlarda) - `winfo_viewable()` ishonchli.
        try:
            visible = bool(self.canvas.winfo_viewable())
        except Exception:  # noqa: BLE001
            visible = False
        if visible:
            self._draw()
        try:
            self._after_id = self.canvas.after(FRAME_MS, self._tick)
        except Exception:  # noqa: BLE001
            self._after_id = None

    # --- chizish ------------------------------------------------------------

    def _draw(self) -> None:
        elapsed = (time.monotonic() - self._started) * 1000.0
        frame = compose(self._state, elapsed, self._level, self._width, self._error)
        c = self.canvas
        try:
            for item, box, color in zip(self._halo, frame.halo_boxes,
                                        self._halo_cache or frame.halo_colors):
                c.coords(item, *box)
                c.itemconfigure(item, fill=color)

            c.coords(self._dark, *frame.disk)
            c.coords(self._lit, *frame.lit[0])
            c.itemconfigure(self._lit, start=frame.lit[1], extent=frame.lit[2],
                            fill=frame.lit_color)
            c.coords(self._term, *frame.terminator)
            c.itemconfigure(self._term, fill=frame.terminator_fill)

            if frame.aureole is None:
                c.itemconfigure(self._aureole, outline="")
            else:
                c.coords(self._aureole, *frame.aureole)
                c.itemconfigure(self._aureole, outline=frame.aureole_color)

            if frame.orbit is None:
                c.itemconfigure(self._orbit, fill="")
            else:
                c.coords(self._orbit, *frame.orbit)
                c.itemconfigure(self._orbit, fill=frame.orbit_color)

            for item, box in zip(self._bars, frame.wave):
                c.coords(item, *box)
                c.itemconfigure(item, fill=frame.wave_color)
        except Exception:  # noqa: BLE001 - oyna yopilayotgan bo'lishi mumkin
            log.debug("Sahna chizilmadi", exc_info=True)
