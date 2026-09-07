"""Ovoz sahnasining SOF mantiqi.

Bu fayl adversarial baho topgan 12 ta bloklovchining har birini qaytib
kelishidan to'sadi. Ularning ko'pi arifmetik edi va aynan shuning uchun
sahna mantiqi tkinter'siz yozilgan - shu mashinada tkinter YO'Q, lekin
quyidagilarning hammasi shu yerda o'lchanadi.
"""

import math
from pathlib import Path

import pytest

from venera.core.states import State
from venera.ui import scene
from venera.ui.tokens import BG, NIGHT

SOURCE = Path(scene.__file__).read_text(encoding="utf-8")

#: Har bir holat uchun butun sikl bo'ylab namuna vaqtlar.
TIMES = tuple(float(t) for t in range(0, 5000, 97))
LEVELS = (0.0, 0.35, 1.0)


def frames(state: str):
    for t in TIMES:
        for level in LEVELS:
            yield t, level, scene.compose(state, t, level)


# --- 0. Tk mantiqdan ajratilganmi ------------------------------------------

def test_sof_qatlam_tkinter_ni_import_qilmaydi():
    """Sof mantiq tkinter'ga bog'lansa, u tkinter yo'q mashinada test
    qilinmasdi - oldingi spetsifikatsiyani aynan shu o'ldirgan."""
    head = SOURCE.split("class VoiceScene", 1)[0]
    assert "import tkinter" not in head
    assert "from tkinter" not in head


def test_har_bir_holat_uchun_uslub_bor():
    for holat in State:
        assert holat.value in scene.STYLES, f"{holat.value} uchun uslub yo'q"


# --- 1. Halo formulasi complex son bermaydi --------------------------------

def test_halo_hech_qachon_yiqilmaydi():
    """`(1 - i/N) ** 2.2` manfiy asosda complex son berardi va animatsiya
    jimgina o'lardi. Endi asos hech qachon manfiy emas."""
    for spread in (0.01, 0.1, 0.35, 0.5, 0.7, 1.0):
        colors = scene.halo_colors("#2F6FED", 0.30)
        assert len(scene.halo_ring_boxes(0.0, 0.0, 40.0, spread)) == scene.HALO_RINGS
        assert len(colors) == scene.HALO_RINGS
        for value in colors:
            assert len(value) == 7 and value.startswith("#")
            int(value[1:], 16)          # hex ekanini tasdiqlaydi


def test_halo_har_bir_holatda_ishlaydi():
    for holat in State:
        uslub = scene.STYLES[holat.value]
        colors = scene.halo_colors(scene.color_for(holat.value), uslub.halo_alpha)
        assert len(colors) == scene.HALO_RINGS


# --- 5. Halo bandingi -------------------------------------------------------

def _max_step(colors):
    step = 0
    for first, second in zip(colors, colors[1:]):
        a, b = scene._channels(first), scene._channels(second)
        step = max(step, max(abs(a[i] - b[i]) for i in range(3)))
    return step


def test_halo_qadamlari_kozga_tashlanmaydi():
    """Tk ovali antialiased emas: qo'shni halqalar orasidagi katta sakrash
    ko'rinadigan halqa chegarasi (banding) beradi. 6 halqada bu 24/255 edi."""
    for holat in State:
        uslub = scene.STYLES[holat.value]
        colors = scene.halo_colors(scene.color_for(holat.value), uslub.halo_alpha)
        step = _max_step(colors)
        assert step <= 6, f"{holat.value}: halo qadami {step}/255 - band ko'rinadi"


def test_halo_tashqaridan_ichkariga_kuchayadi():
    """Yaratilish tartibi = z-tartib: eng katta halqa birinchi chiziladi."""
    colors = scene.halo_colors("#2F6FED", 0.30)
    lum = [scene.relative_luminance(c) for c in colors]
    assert lum[0] <= lum[-1], "halo teskari tartibda"


# --- 2. Retrograd nuqta -----------------------------------------------------

def test_orbit_nuqta_soat_strelkasiga_teskari_aylanadi():
    """Veneraning -243 kunlik teskari aylanishi - butun ajratuvchi belgi shu.
    Ekranda y PASTGA o'sadi, shuning uchun bu oson chalkashadigan joy."""
    cx = cy = 100.0
    davr = 2000.0
    x0, y0 = scene.orbit_point(cx, cy, 50.0, 0.0, davr)
    assert y0 == pytest.approx(cy - 50.0), "boshlanish nuqtasi tepada emas"
    assert x0 == pytest.approx(cx, abs=1e-6)

    # Tepadan chapga siljish = ekranda soat strelkasiga TESKARI.
    x1, _ = scene.orbit_point(cx, cy, 50.0, davr / 8.0, davr)
    assert x1 < cx, "nuqta soat strelkasi bo'yicha aylanmoqda - teskari"


def test_orbit_davri_toliq_aylanadi():
    cx = cy = 0.0
    davr = 1000.0
    boshi = scene.orbit_point(cx, cy, 10.0, 0.0, davr)
    oxiri = scene.orbit_point(cx, cy, 10.0, davr, davr)
    assert boshi[0] == pytest.approx(oxiri[0], abs=1e-9)
    assert boshi[1] == pytest.approx(oxiri[1], abs=1e-9)


def test_davr_nol_bolsa_bolinish_yoq():
    assert scene.orbit_point(0.0, 0.0, 5.0, 100.0, 0.0) == (5.0, 0.0)


# --- faza geometriyasi ------------------------------------------------------

def test_toliq_faza_diskni_yopadi():
    p = scene.phase(100.0, 100.0, 40.0, 1.0, "#2F6FED")
    assert p.terminator == p.disk
    assert p.terminator_fill == "#2F6FED"


def test_yarim_faza_terminatori_nol_enli():
    p = scene.phase(100.0, 100.0, 40.0, 0.5, "#2F6FED")
    assert p.terminator[0] == pytest.approx(p.terminator[2])


def test_nol_faza_butunlay_tungi():
    """k=0 da terminator BUTUN diskni tungi rang bilan yopadi - k=1 ning
    aynan teskarisi. Nol enli terminator faqat k=0.5 da bo'ladi."""
    p = scene.phase(100.0, 100.0, 40.0, 0.0, "#2F6FED")
    assert p.terminator == p.disk
    assert p.terminator_fill == NIGHT


def test_faza_chekkalarga_qisiladi():
    for k in (-3.0, 5.0):
        p = scene.phase(0.0, 0.0, 10.0, k, "#2F6FED")
        assert p.terminator[0] <= p.terminator[2]


# --- 12. Siluet hech qachon yo'qolmaydi ------------------------------------

def test_hech_bir_holat_toliq_disk_yoki_toliq_tungi_emas():
    """k=1 da belgi oddiy doiraga aylanadi; k=0 da butunlay tungi disk fonda
    yo'qoladi (night vs bg = 1.3:1). Ikkala chekka ham tanilishni o'ldiradi."""
    for holat in State:
        k = scene.STYLES[holat.value].phase
        assert 0.0 < k < 1.0, f"{holat.value}: k={k} siluetni yo'qotadi"
        assert 0.35 <= k <= 0.95, f"{holat.value}: k={k} chekkaga juda yaqin"


def test_toxtatilgan_holat_ham_korinadi():
    """PAUSED tunda 8 soat ekranda turadi - siluet saqlanishi shart."""
    f = scene.compose("paused")
    assert f.terminator[0] < f.terminator[2], "terminator nol enli - siluet yo'q"
    assert scene.contrast(f.lit_color, NIGHT) > 1.5


# --- 4/8. Sahna canvas'ga sig'adi ------------------------------------------

def test_hamma_narsa_canvas_ichida():
    """Oldingi spetsifikatsiyada halo -42 px da boshlanardi va gorizontal
    kesim chizig'i butun halo mehnatini bekor qilardi."""
    for holat in State:
        for t, level, f in frames(holat.value):
            eng_tepa = min(box[1] for box in f.halo_boxes)
            eng_past = max(box[3] for box in f.halo_boxes)
            assert eng_tepa >= 0, f"{holat.value} t={t}: halo tepadan chiqdi ({eng_tepa})"
            assert eng_past <= scene.SCENE_HEIGHT, \
                f"{holat.value} t={t}: halo pastdan chiqdi ({eng_past})"


def test_orbit_nuqta_ham_canvas_ichida():
    for holat in State:
        for _t, _level, f in frames(holat.value):
            if f.orbit is None:
                continue
            assert f.orbit[1] >= 0 and f.orbit[3] <= scene.SCENE_HEIGHT


# --- 4. To'lqin diskni kesib o'tmaydi --------------------------------------

def test_tolqin_orbni_teshib_otmaydi():
    """Ustunlar z-tartibda orbdan yuqorida - kesishsa ular sayyorani teshadi."""
    for holat in State:
        for t, level, f in frames(holat.value):
            orb_pasti = f.disk[3]
            tolqin_tepasi = min(box[1] for box in f.wave)
            assert tolqin_tepasi > orb_pasti, (
                f"{holat.value} t={t} level={level}: to'lqin orbni kesdi "
                f"({tolqin_tepasi:.1f} <= {orb_pasti:.1f})")


def test_tolqin_muzlaganda_ham_korinadi():
    """Muzlagan to'lqin nolga tushsa "ish ketyapti" o'rniga "hech narsa yo'q"
    ko'rinardi."""
    f = scene.compose("thinking", 500.0, 0.0)
    balandliklar = [box[3] - box[1] for box in f.wave]
    assert min(balandliklar) >= scene.WAVE_MIN_HEIGHT
    assert max(balandliklar) > scene.WAVE_MIN_HEIGHT * 2


# --- 14. To'xtatilgan holatda sikl to'xtaydi -------------------------------

def test_toxtatilgan_holat_animatsiyasiz():
    """0% CPU: `after()` sikli butunlay bekor qilinadi."""
    assert scene.compose("paused").animated is False


def test_tirik_holatlar_animatsiyali():
    for nom in ("idle", "capturing", "thinking", "speaking"):
        assert scene.compose(nom).animated is True, nom


# --- xato holati ------------------------------------------------------------

def test_xato_yorug_tomonni_aks_ettiradi():
    """Rang ko'rmaydigan foydalanuvchi uchun xato va "uyg'ondi" bir xil
    ko'rinardi - shuning uchun farq SHAKLDA."""
    oddiy = scene.compose("acting", 0.0)
    xato = scene.compose("acting", 0.0, error=True)
    assert oddiy.lit[1] != xato.lit[1], "yorug' yarim aks ettirilmadi"
    assert xato.lit_color != oddiy.lit_color


# --- ranglar ----------------------------------------------------------------

def test_mix_chekkalarga_qisiladi():
    assert scene.mix("#000000", "#FFFFFF", -1.0) == "#000000"
    assert scene.mix("#000000", "#FFFFFF", 2.0) == "#FFFFFF"
    assert scene.mix("#000000", "#FFFFFF", 0.5) == "#808080"


def test_kontrast_malum_qiymatlar():
    assert scene.contrast("#FFFFFF", "#000000") == pytest.approx(21.0, abs=0.01)
    assert scene.contrast("#FFFFFF", "#FFFFFF") == pytest.approx(1.0, abs=0.01)


def test_yorug_tomon_tungi_tomondan_ajralib_turadi():
    """Ikki tonlilik bezak emas - u siluetni ushlab turadigan muhandislik."""
    for holat in State:
        rang = scene.color_for(holat.value)
        assert scene.contrast(rang, NIGHT) >= 1.5, f"{holat.value} tungi tomonga qo'shilib ketadi"


def test_kadr_sof_funksiya():
    """Bir xil kirish - bir xil kadr. Butun vizual mantiq shu tufayli
    tkintersiz tekshiriladi."""
    a = scene.compose("capturing", 1234.0, 0.5)
    b = scene.compose("capturing", 1234.0, 0.5)
    assert a == b


# --- PIKSEL DALILI ----------------------------------------------------------
#
# Bu mashinada tkinter yo'q, lekin Pillow bor (u allaqachon majburiy
# bog'liqlik - `pyproject.toml`). `tools/render_scene.py` AYNAN `compose()`
# chiqishini chizadi, shuning uchun quyidagilar geometriya haqida haqiqiy
# o'lchov, taxmin emas.
#
# HALOL CHEGARA: PIL va Tk ikki xil rasterizator. Bu testlar geometriyani
# isbotlaydi, chekka piksellarining aynan mosligini emas.

import importlib.util

TOOLS = Path(__file__).resolve().parents[1] / "tools" / "render_scene.py"


def _renderer():
    spec = importlib.util.spec_from_file_location("render_scene", TOOLS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def render():
    pytest.importorskip("PIL")
    return _renderer().render


def _row(image, y):
    return [image.getpixel((x, y)) for x in range(image.width)]


def test_render_har_bir_holatda_ishlaydi(render):
    for holat in State:
        image = render(holat.value, 700.0, 0.6)
        assert image.size == (488, scene.SCENE_HEIGHT)


def test_siluet_har_bir_holatda_korinadi(render):
    """Disk ekvatorida IKKALA ton ham bo'lishi shart: bir tonli disk oddiy
    doiraga aylanadi va belgi tanilmay qoladi."""
    night = scene._channels(NIGHT)
    for holat in State:
        image = render(holat.value, 700.0, 0.6)
        row = _row(image, int(scene.CENTER_Y))
        tungi = sum(1 for px in row if px == night)
        yorug = sum(1 for px in row if px == scene._channels(scene.color_for(holat.value)))
        assert tungi >= 3, f"{holat.value}: tungi tomon yo'qoldi ({tungi} px)"
        assert yorug >= 3, f"{holat.value}: yorug' tomon yo'qoldi ({yorug} px)"


def test_xato_yorug_tomoni_chapda(render):
    """Rang ko'rmaydigan foydalanuvchi xatoni SHAKL bo'yicha ajratadi."""
    y = int(scene.CENTER_Y)
    markaz = 488 // 2

    oddiy = _row(render("acting", 0.0, 0.0), y)
    rang = scene._channels(scene.color_for("acting"))
    ong = sum(1 for x, px in enumerate(oddiy) if px == rang and x > markaz)
    chap = sum(1 for x, px in enumerate(oddiy) if px == rang and x < markaz)
    assert ong > chap, "oddiy holatda yorug' tomon o'ngda bo'lishi kerak"

    xato = _row(render("acting", 0.0, 0.0, error=True), y)
    rang = scene._channels(scene.ERROR)
    ong = sum(1 for x, px in enumerate(xato) if px == rang and x > markaz)
    chap = sum(1 for x, px in enumerate(xato) if px == rang and x < markaz)
    assert chap > ong, "xato holatida yorug' tomon CHAPDA bo'lishi kerak"


def test_haloda_korinadigan_chegara_yoq(render):
    """Diskdan tashqariga gorizontal skanerlash: qo'shni piksellar orasidagi
    sakrash halqa chegarasini ko'rsatadi. 6 halqali eski sxemada bu 24 edi."""
    image = render("speaking", 0.0, 0.0)      # eng katta alpha
    y = int(scene.CENTER_Y)
    frame = scene.compose("speaking", 0.0, 0.0, 488.0)
    boshi = int(frame.disk[2]) + 2            # disk chekkasidan keyin
    oxiri = int(max(box[2] for box in frame.halo_boxes)) - 1

    eng_katta = 0
    for x in range(boshi, oxiri):
        a = image.getpixel((x, y))
        b = image.getpixel((x + 1, y))
        eng_katta = max(eng_katta, max(abs(a[i] - b[i]) for i in range(3)))
    assert eng_katta <= 6, f"halo chegarasi ko'rinadi: {eng_katta}/255"


def test_tolqin_va_disk_piksellari_kesishmaydi(render):
    """Ustunlar z-tartibda yuqorida - kesishsa ular sayyorani teshadi."""
    for holat in State:
        frame = scene.compose(holat.value, 700.0, 1.0, 488.0)
        disk_pasti = frame.disk[3]
        tolqin_tepasi = min(box[1] for box in frame.wave)
        assert tolqin_tepasi > disk_pasti + 5, \
            f"{holat.value}: to'lqin diskka juda yaqin"
