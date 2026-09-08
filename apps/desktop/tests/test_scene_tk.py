"""Tk adapteri - soxta Canvas bilan.

`VoiceScene` `tk` ni PARAMETR sifatida oladi, shuning uchun adapter mexanikasi
(itemlar bir marta yaratiladimi, sikl to'xtaydimi, `after` bekor qilinadimi)
tkinter'siz ham tekshiriladi. Ilgari bu qism faqat "Windows'da ko'z bilan
ko'rish" ga qolgandi.
"""

import pytest

from venera.ui import scene as scene_module
from venera.ui.scene import HALO_RINGS, WAVE_BARS, VoiceScene
from venera.ui.window import _make_scene


class FakeCanvas:
    def __init__(self, parent=None, **kw):
        self.kw = kw
        self.items = []
        self.after_calls = 0
        self.cancelled = []
        self.viewable = True
        self.packed = False
        self._next = 0
        self.config_calls = 0

    def _item(self, kind):
        self._next += 1
        self.items.append(kind)
        return self._next

    def create_oval(self, *a, **k): return self._item("oval")
    def create_arc(self, *a, **k): return self._item("arc")
    def create_rectangle(self, *a, **k): return self._item("rect")
    def bind(self, *a, **k): pass
    def pack(self, **k): self.packed = True
    def coords(self, *a): pass
    def itemconfigure(self, *a, **k): self.config_calls += 1
    def winfo_viewable(self): return self.viewable

    def after(self, ms, fn):
        self.after_calls += 1
        return f"after#{self.after_calls}"

    def after_cancel(self, ident): self.cancelled.append(ident)


class FakeTk:
    def __init__(self, canvas_cls=FakeCanvas):
        self.canvas_cls = canvas_cls

    def Canvas(self, parent=None, **kw):  # noqa: N802 - tkinter nomi
        return self.canvas_cls(parent, **kw)


class BrokenTk:
    def Canvas(self, parent=None, **kw):  # noqa: N802
        raise RuntimeError("Tk versiyasi bu argumentni bilmaydi")


# --- oyna himoyasi ----------------------------------------------------------

def test_sahna_qurilmasa_oyna_yoqolmaydi():
    """Sahna Tk'da eng kam sinalgan qism. Uning xatosi holat oynasini
    yo'qotsa, foydalanuvchi buyruq ham yozolmay, jurnalni ham ko'rolmay
    qolardi - sahnasiz esa ilova to'liq ishlaydi."""
    assert _make_scene(BrokenTk(), None) is None


def test_sahna_qurilsa_qaytariladi():
    got = _make_scene(FakeTk(), None)
    assert got is not None
    assert got.canvas.packed, "canvas oynaga joylashtirilmadi"


# --- adapter mexanikasi -----------------------------------------------------

def test_itemlar_bir_marta_yaratiladi():
    """Yaratish tartibi = z-tartib. Har kadrda qayta yaratilsa tartib
    buzilardi va Tk sekinlashardi."""
    s = VoiceScene(FakeTk(), None)
    boshlangich = len(s.canvas.items)
    for holat in ("capturing", "thinking", "speaking", "idle"):
        s.set_state(holat)
    assert len(s.canvas.items) == boshlangich, "itemlar qayta yaratildi"


def test_item_soni_kutilganicha():
    s = VoiceScene(FakeTk(), None)
    # halo + qorong'i disk + yorug' yoy + terminator + aureole + orbit + to'lqin
    assert len(s.canvas.items) == HALO_RINGS + 5 + WAVE_BARS


def test_z_tartib_halo_pastda_tolqin_tepada():
    s = VoiceScene(FakeTk(), None)
    assert s.canvas.items[:HALO_RINGS] == ["oval"] * HALO_RINGS
    assert s.canvas.items[-WAVE_BARS:] == ["rect"] * WAVE_BARS


def test_toxtatilgan_holatda_sikl_rejalashtirilmaydi():
    """PAUSED da `after()` umuman qayta chaqirilmaydi - 0% CPU."""
    s = VoiceScene(FakeTk(), None)
    oldingi = s.canvas.after_calls
    s.set_state("paused")
    assert s.canvas.after_calls == oldingi, "to'xtatilgan holatda sikl davom etdi"


def test_tirik_holatda_sikl_rejalashtiriladi():
    s = VoiceScene(FakeTk(), None)
    s.set_state("paused")
    oldingi = s.canvas.after_calls
    s.set_state("capturing")
    assert s.canvas.after_calls > oldingi


def test_stop_kutayotgan_afterni_bekor_qiladi():
    """Oyna yopilgandan keyin otilgan tick `TclError: invalid command name`
    berardi."""
    s = VoiceScene(FakeTk(), None)
    s.set_state("idle")
    s.stop()
    assert s.canvas.cancelled, "after bekor qilinmadi"


def test_stop_idempotent():
    s = VoiceScene(FakeTk(), None)
    s.stop()
    s.stop()


def test_stopdan_keyin_sikl_qayta_boshlanmaydi():
    s = VoiceScene(FakeTk(), None)
    s.stop()
    oldingi = s.canvas.after_calls
    s.set_state("capturing")
    assert s.canvas.after_calls == oldingi


def test_korinmayotgan_oyna_chizilmaydi():
    """Minimallashtirilgan oynada 30 fps chizish bekorga CPU yeydi."""
    s = VoiceScene(FakeTk(), None)
    s.canvas.viewable = False
    oldingi = s.canvas.config_calls
    s._tick()
    assert s.canvas.config_calls == oldingi, "ko'rinmayotgan oyna chizildi"


def test_korinadigan_oyna_chiziladi():
    s = VoiceScene(FakeTk(), None)
    s.canvas.viewable = True
    oldingi = s.canvas.config_calls
    s._tick()
    assert s.canvas.config_calls > oldingi


# --- kirish tozalash --------------------------------------------------------

def test_notogri_daraja_yiqitmaydi():
    s = VoiceScene(FakeTk(), None)
    for qiymat in (None, "salom", float("nan"), -5, 99):
        s.set_level(qiymat)
        assert 0.0 <= s._level <= 1.0


def test_notanish_holat_idle_ga_tushadi():
    s = VoiceScene(FakeTk(), None)
    s.set_state("bunday-holat-yoq")
    assert s._state == "idle"


def test_chizish_xatosi_yutiladi():
    """Oyna yopilayotganda Tk chaqiruvlari xato beradi - ular animatsiyani
    o'ldirmasligi kerak."""
    class Yiqiluvchi(FakeCanvas):
        def coords(self, *a):
            raise RuntimeError("invalid command name")

    s = VoiceScene(FakeTk(Yiqiluvchi), None)
    s._draw()          # xato ko'tarilmasligi kerak
