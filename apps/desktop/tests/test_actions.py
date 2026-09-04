"""Harakatlar qatlami - OS adapteri o'rniga soxta obyekt ishlatiladi."""

from pathlib import Path

import pytest

from venera import config as config_module
from venera.actions import apps as apps_module
from venera.actions import phrases as phrases_module
from venera.actions import registry
from venera.actions.base import ActionContext
from venera.nlu.intents import IntentName
from venera.nlu.rules import parse
from venera.osadapter.base import AutostartStatus, OSAdapter


class FakeAdapter(OSAdapter):
    name = "fake"

    def __init__(self):
        self.launched = []
        self.urls = []
        self.volume = 50
        self.muted = False
        self.locked = False
        self.shots = []

    def launch(self, targets):
        self.launched.append(list(targets))
        return True

    def open_url(self, url):
        self.urls.append(url)
        return True

    def get_volume(self):
        return self.volume

    def set_volume(self, percent):
        self.volume = percent
        return True

    def set_mute(self, muted):
        self.muted = muted
        return True

    def lock_workstation(self):
        self.locked = True
        return True

    def screenshot(self, destination: Path):
        self.shots.append(destination)
        return destination

    def is_session_locked(self):
        return False

    def acquire_single_instance(self, key):
        return True

    def autostart_status(self):
        return AutostartStatus(False)

    def autostart_install(self, command):
        return AutostartStatus(True)

    def autostart_remove(self):
        return AutostartStatus(False)


@pytest.fixture
def ctx():
    cfg, _ = config_module.load(Path("__yoq__.yaml"))
    return ActionContext(
        adapter=FakeAdapter(), config=cfg,
        phrases=phrases_module.Phrases.load(), catalog=apps_module.load(),
    )


def run(text, ctx):
    return parse(text), registry.execute(parse(text), ctx)


def test_dastur_ochiladi(ctx):
    _, result = run("chromeni och", ctx)
    assert result.ok
    assert ctx.adapter.launched
    assert "ochilmoqda" in result.spoken


def test_topilmagan_dastur(ctx):
    _, result = run("allaqanday dastur och", ctx)
    assert not result.ok
    assert "topilmadi" in result.spoken


def test_ovoz_ornatiladi(ctx):
    _, result = run("ovozni qirq besh foiz", ctx)
    assert result.ok and ctx.adapter.volume == 45
    assert "45" in result.spoken


def test_ovoz_kotariladi(ctx):
    ctx.adapter.volume = 50
    _, result = run("ovozni ko'tar", ctx)
    assert ctx.adapter.volume == 60 and result.ok


def test_ovoz_chegarada_toxtaydi(ctx):
    ctx.adapter.volume = 95
    run("ovozni ko'tar", ctx)
    assert ctx.adapter.volume == 100


def test_ovoz_ochiriladi(ctx):
    _, result = run("ovozni o'chir", ctx)
    assert ctx.adapter.muted is True and result.ok


def test_ekran_qulflanadi(ctx):
    intent, result = run("ekranni qulfla", ctx)
    assert ctx.adapter.locked and result.ok
    assert registry.is_deferred(intent), "javob qulflashdan OLDIN aytilishi kerak"


def test_skrinshot(ctx):
    _, result = run("skrinshot ol", ctx)
    assert result.ok and ctx.adapter.shots
    assert ctx.adapter.shots[0].suffix == ".png"


def test_qidiruv_url_kodlanadi(ctx):
    _, result = run("googlda venera bank qidir", ctx)
    assert result.ok
    assert "venera+bank" in ctx.adapter.urls[0]


def test_vaqt_va_sana(ctx):
    assert run("soat necha", ctx)[1].ok
    assert run("bugun qaysi kun", ctx)[1].ok


def test_takrorlash(ctx):
    run("soat necha", ctx)
    previous = ctx.last_reply
    _, result = run("yana ayt", ctx)
    assert result.spoken == previous


def test_nomalum(ctx):
    _, result = run("bugun ob-havo qanday bo'ladi", ctx)
    assert not result.ok and "Tushunmadim" in result.spoken


def test_handler_xatosi_yiqitmaydi(ctx):
    def boom(*_args, **_kwargs):
        raise RuntimeError("sinov xatosi")

    ctx.adapter.launch = boom
    _, result = run("chromeni och", ctx)
    assert not result.ok
    assert "sinov xatosi" in result.detail


def test_barcha_intentlar_uchun_handler_bor():
    from venera.actions.handlers import HANDLERS

    missing = [name for name in IntentName if name not in HANDLERS]
    assert not missing, f"handler yo'q: {missing}"
