"""Dasturlar katalogi - STT fonetik yozuvini ham topishi kerak."""

import pytest

from venera.actions import apps as apps_module


@pytest.fixture(scope="module")
def catalog():
    return apps_module.load()


def test_katalog_bosh_emas(catalog):
    assert len(catalog.entries) >= 10
    assert all(entry.targets for entry in catalog.entries)


@pytest.mark.parametrize("query,expected", [
    ("chrome", "Google Chrome"),
    ("krom", "Google Chrome"),
    ("xrom", "Google Chrome"),
    ("brauzer", "Google Chrome"),
    ("eksel", "Microsoft Excel"),
    ("excel", "Microsoft Excel"),
    ("telegramm", "Telegram"),
    ("autluk", "Microsoft Outlook"),
    ("kalkulator", "Kalkulyator"),
    ("bloknot", "Bloknot"),
    ("sozlamalar", "Sozlamalar"),
])
def test_fonetik_moslik(catalog, query, expected):
    entry, score = catalog.find(query)
    assert entry is not None, f"{query!r} topilmadi (ball {score:.0f})"
    assert entry.name == expected


@pytest.mark.parametrize("query", ["", "   ", "qwertyuiop asdfgh", "allaqanday narsa"])
def test_notanish_topilmaydi(catalog, query):
    entry, _ = catalog.find(query)
    assert entry is None


def test_buzuq_yaml_yiqitmaydi(tmp_path):
    path = tmp_path / "apps.yaml"
    path.write_text("apps: [buzuq\n", encoding="utf-8")
    catalog = apps_module.load(path)
    assert catalog.entries == []


def test_maqsadsiz_yozuv_otkazib_yuboriladi(tmp_path):
    path = tmp_path / "apps.yaml"
    path.write_text(
        "apps:\n"
        "  - name: Maqsadsiz\n"
        "    aliases: [test]\n"
        "  - name: Toliq\n"
        "    aliases: [toliq]\n"
        "    windows: ['a.exe']\n"
        "    macos: ['A']\n",
        encoding="utf-8",
    )
    catalog = apps_module.load(path)
    assert [e.name for e in catalog.entries] == ["Toliq"]
