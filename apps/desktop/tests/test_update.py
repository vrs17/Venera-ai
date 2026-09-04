"""Yangilanish tizimi: manifest, manba, xizmat.

Tarmoq kerak emas - manba sifatida vaqtinchalik papka ishlatiladi,
bu tarqatish uchun haqiqiy variantlardan biri (tarmoq papkasi) bilan bir xil yo'l.
"""

import hashlib
import json
from pathlib import Path

import pytest

from venera import config as config_module
from venera.update.manifest import (
    Manifest, UpdateInfo, compare_versions, is_newer, parse_version,
)
from venera.update.service import UpdateService
from venera.update.source import (
    UpdateSourceError, download, is_http, join_location, read_bytes,
)


# --- versiyalar ---------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("0.1.0", (0, 1, 0)), ("1.2.3", (1, 2, 3)), ("v2.0", (2, 0, 0)),
    ("3", (3, 0, 0)), ("0.2.0-beta", (0, 2, 0)), ("axlat", (0, 0, 0)), ("", (0, 0, 0)),
])
def test_parse_version(text, expected):
    assert parse_version(text) == expected


@pytest.mark.parametrize("left,right,expected", [
    ("0.2.0", "0.1.0", 1), ("0.1.0", "0.1.0", 0), ("0.1.0", "0.2.0", -1),
    ("1.0.0", "0.9.9", 1), ("0.1.10", "0.1.9", 1), ("0.10.0", "0.9.0", 1),
])
def test_compare_versions(left, right, expected):
    assert compare_versions(left, right) == expected


def test_is_newer():
    assert is_newer("0.2.0", "0.1.0")
    assert not is_newer("0.1.0", "0.1.0")
    assert not is_newer("0.0.9", "0.1.0")


# --- manifest -----------------------------------------------------------------

def _manifest_dict(version="0.2.0", **kwargs):
    data = {
        "version": version,
        "released": "2026-09-10",
        "notes": "sinov",
        "setup": {"file": f"setup-{version}.exe", "sha256": "a" * 64, "size": 1234},
    }
    data.update(kwargs)
    return data


def test_manifest_parse():
    m = Manifest.parse(json.dumps(_manifest_dict()))
    assert m.version == "0.2.0"
    assert m.setup.file == "setup-0.2.0.exe"
    assert m.setup.has_checksum
    assert m.setup.size == 1234
    assert not m.mandatory


def test_manifest_bom_bilan():
    payload = ("\ufeff" + json.dumps(_manifest_dict())).encode("utf-8")
    assert Manifest.parse(payload).version == "0.2.0"


@pytest.mark.parametrize("payload", [
    "buzuq json",
    "[]",
    json.dumps({"setup": {"file": "a.exe"}}),          # version yo'q
    json.dumps({"version": "0.2.0"}),                  # setup yo'q
    json.dumps({"version": "0.2.0", "setup": {}}),     # setup.file yo'q
])
def test_manifest_notogri(payload):
    with pytest.raises(ValueError):
        Manifest.parse(payload)


def test_manifest_min_version():
    m = Manifest.parse(json.dumps(_manifest_dict(min_version="0.5.0")))
    assert not m.applies_to("0.1.0")
    assert m.applies_to("0.5.0")
    assert m.applies_to("0.6.0")


def test_update_info_describe():
    m = Manifest.parse(json.dumps(_manifest_dict()))
    info = UpdateInfo(manifest=m, current_version="0.1.0", download_url="x")
    assert "0.2.0" in info.describe()


# --- manba --------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("http://a/b", True), ("https://a/b", True),
    (r"\\fs\share\v.json", False), (r"C:\updates\v.json", False), ("/tmp/v.json", False),
])
def test_is_http(value, expected):
    assert is_http(value) is expected


@pytest.mark.parametrize("base,name,expected", [
    ("http://h/u/version.json", "s.exe", "http://h/u/s.exe"),
    ("http://h/u/version.json", "http://other/s.exe", "http://other/s.exe"),
    (r"\\fs\venera\version.json", "s.exe", r"\\fs\venera\s.exe"),
    (r"C:\up\version.json", "s.exe", r"C:\up\s.exe"),
])
def test_join_location(base, name, expected):
    assert join_location(base, name) == expected


def test_read_bytes_fayldan(tmp_path):
    target = tmp_path / "version.json"
    target.write_text('{"a": 1}', encoding="utf-8")
    assert read_bytes(str(target)) == b'{"a": 1}'


def test_read_bytes_yoq(tmp_path):
    with pytest.raises(UpdateSourceError):
        read_bytes(str(tmp_path / "yoq.json"))


def test_download_va_checksum(tmp_path):
    source = tmp_path / "setup.exe"
    payload = b"VEN" * 5000
    source.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()

    seen = []
    result = download(str(source), tmp_path / "out" / "setup.exe",
                      expected_sha256=digest, expected_size=len(payload),
                      progress=lambda d, t: seen.append((d, t)))
    assert result.read_bytes() == payload
    assert seen and seen[-1][0] == len(payload)


def test_download_notogri_checksum(tmp_path):
    source = tmp_path / "setup.exe"
    source.write_bytes(b"asl fayl")
    destination = tmp_path / "out" / "setup.exe"
    with pytest.raises(UpdateSourceError, match="nazorat yig'indisi"):
        download(str(source), destination, expected_sha256="b" * 64)
    assert not destination.exists(), "buzuq fayl saqlanmasligi kerak"
    assert not destination.with_suffix(".exe.part").exists()


def test_download_notogri_hajm(tmp_path):
    source = tmp_path / "setup.exe"
    source.write_bytes(b"qisqa")
    with pytest.raises(UpdateSourceError, match="hajm"):
        download(str(source), tmp_path / "out.exe", expected_size=999)


# --- xizmat -------------------------------------------------------------------

@pytest.fixture
def repo(tmp_path):
    """Tarqatish papkasi: version.json + setup fayli."""
    folder = tmp_path / "repo"
    folder.mkdir()

    def publish(version: str, notes: str = "", **extra):
        setup = folder / f"setup-{version}.exe"
        payload = f"SETUP {version}".encode()
        setup.write_bytes(payload)
        data = _manifest_dict(version, notes=notes)
        data["setup"] = {
            "file": setup.name,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size": len(payload),
        }
        data.update(extra)
        (folder / "version.json").write_text(json.dumps(data), encoding="utf-8")
        return setup

    return folder, publish


def _service(folder: Path, current: str, **overrides):
    cfg, _ = config_module.load(Path("__yoq__.yaml"))
    cfg.update.url = str(folder / "version.json")
    cfg.update.enabled = True
    for key, value in overrides.items():
        setattr(cfg.update, key, value)
    return UpdateService(config=cfg, current_version=current)


def test_yangilanish_topiladi(repo):
    folder, publish = repo
    publish("0.2.0", notes="yangi imkoniyat")
    service = _service(folder, "0.1.0")
    result = service.check()
    assert result.available
    assert result.info.version == "0.2.0"
    assert result.info.manifest.notes == "yangi imkoniyat"
    assert service.pending is not None


def test_ayni_versiya_yangilanish_emas(repo):
    folder, publish = repo
    publish("0.1.0")
    service = _service(folder, "0.1.0")
    result = service.check()
    assert not result.available and result.checked and not result.error


def test_eski_versiya_yangilanish_emas(repo):
    folder, publish = repo
    publish("0.1.0")
    service = _service(folder, "0.5.0")
    assert not _service(folder, "0.5.0").check().available
    assert service.check().info is None


def test_manba_yoq(tmp_path):
    service = _service(tmp_path / "yoq", "0.1.0")
    result = service.check()
    assert not result.available and result.error


def test_url_bosh_bolsa_ochiq(tmp_path):
    cfg, _ = config_module.load(Path("__yoq__.yaml"))
    cfg.update.url = ""
    service = UpdateService(config=cfg, current_version="0.1.0")
    assert not service.enabled
    assert not service.check().available


def test_min_version_bloklaydi(repo):
    folder, publish = repo
    publish("0.9.0", min_version="0.5.0")
    errors = []
    service = _service(folder, "0.1.0")
    service.on_error = errors.append
    result = service.check()
    assert not result.available
    assert errors and "0.5.0" in errors[0]


def test_hodisalar_chaqiriladi(repo):
    folder, publish = repo
    publish("0.3.0")
    found = []
    service = _service(folder, "0.1.0")
    service.on_available = found.append
    service.check()
    assert found and found[0].version == "0.3.0"


def test_yangilandi_belgisi(repo, tmp_path, monkeypatch):
    from venera import paths

    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path / "state")
    folder, publish = repo
    publish("0.2.0")
    service = _service(folder, "0.2.0")

    assert service.consume_completed_update() == ""
    service._write_pending_marker("0.2.0")
    assert service.consume_completed_update() == "0.2.0"
    assert service.consume_completed_update() == "", "belgi bir marta ishlashi kerak"


# --- bir nechta manba ---------------------------------------------------------

def test_manbalar_royxati(tmp_path):
    service = _service(tmp_path, "0.1.0")
    service.config.update.fallback_urls = ["https://b/v.json", "https://c/v.json"]
    assert service.sources[1:] == ["https://b/v.json", "https://c/v.json"]


def test_takroriy_va_bosh_manbalar_tashlanadi(tmp_path):
    service = _service(tmp_path, "0.1.0")
    same = service.config.update.url
    service.config.update.fallback_urls = [same, "", "   ", "https://b/v.json"]
    assert service.sources == [same, "https://b/v.json"]


def test_asosiy_ishlamasa_zaxiradan_olinadi(repo):
    """Ofisda tarmoq papkasi yopiq bo'lsa, tashqi manzil ishlashi kerak."""
    folder, publish = repo
    publish("0.4.0")
    service = _service(folder, "0.1.0")
    service.config.update.url = str(folder / "yoq" / "version.json")   # ochilmaydi
    service.config.update.fallback_urls = [str(folder / "version.json")]

    result = service.check()
    assert result.available, result.error
    assert result.info.version == "0.4.0"
    assert service.active_source == str(folder / "version.json")


def test_yuklash_ishlagan_manbadan_boradi(repo):
    """Zaxira manba ishlatilsa, setup fayli ham AYNAN o'sha joydan olinishi kerak."""
    folder, publish = repo
    publish("0.4.0")
    service = _service(folder, "0.1.0")
    service.config.update.url = "http://ochilmaydi.invalid/version.json"
    service.config.update.fallback_urls = [str(folder / "version.json")]

    info = service.check().info
    assert info is not None
    assert info.download_url.startswith(str(folder))


def test_hech_qaysi_manba_ishlamasa(tmp_path):
    service = _service(tmp_path / "yoq", "0.1.0")
    service.config.update.fallback_urls = [str(tmp_path / "ham-yoq" / "version.json")]
    result = service.check()
    assert not result.available and result.error


# --- SPA sayt (nginx try_files -> index.html) ---------------------------------
# llm.brb-tech.uz mavjud bo'lmagan har qanday yo'lga HTTP 200 + index.html
# qaytaradi. Bu eng yashirin nosozlik: hamma narsa "muvaffaqiyatli" ko'rinadi.

SPA_HTML = b'<!doctype html>\n<html lang="en">\n  <head>\n    <title>Venera LLM</title>\n'


def test_manifest_rejects_html_page():
    """SPA index.html manifest o'rniga kelsa - aniq sabab bilan rad etiladi."""
    with pytest.raises(ValueError) as exc:
        Manifest.parse(SPA_HTML)
    assert "HTML" in str(exc.value)
    assert "sozlanmagan" in str(exc.value)


def test_manifest_rejects_html_with_leading_whitespace():
    with pytest.raises(ValueError):
        Manifest.parse(b"\n\n   " + SPA_HTML)


def test_manifest_rejects_html_with_bom():
    with pytest.raises(ValueError):
        Manifest.parse(b"\xef\xbb\xbf" + SPA_HTML)


def test_html_source_falls_back_to_next(tmp_path, monkeypatch):
    """Birinchi manba SPA bo'lsa, xizmat ikkinchisiga o'tishi kerak."""
    good = tmp_path / "version.json"
    good.write_text(json.dumps({
        "version": "9.9.9",
        "setup": {"file": "Setup-9.9.9.exe", "sha256": "a" * 64, "size": 10},
    }), encoding="utf-8")

    import venera.update.service as service_module

    real_read = service_module.read_bytes

    def fake_read(location, **kwargs):
        if location.startswith("https://"):
            return SPA_HTML          # SPA: 200 OK, lekin HTML
        return real_read(location, **kwargs)

    monkeypatch.setattr(service_module, "read_bytes", fake_read)

    cfg, _ = config_module.load(Path("__yoq__.yaml"))
    cfg.update.enabled = True
    cfg.update.url = "https://llm.brb-tech.uz/download/version.json"
    cfg.update.fallback_urls = [str(good)]

    seen: list = []
    service = UpdateService(config=cfg, current_version="0.2.1",
                            on_available=seen.append)
    result = service.check(notify_when_current=False)

    assert result.error == ""
    assert service.active_source == str(good)
    assert seen and seen[0].manifest.version == "9.9.9"


def test_download_rejects_html_response(tmp_path, monkeypatch):
    """SPA .exe o'rniga index.html bersa - 45 MB kutmasdan darrov to'xtaydi."""
    import venera.update.source as source_module

    class _FakeResponse:
        headers = {"Content-Type": "text/html; charset=utf-8",
                   "Content-Length": str(len(SPA_HTML))}

        def read(self, _size):
            return SPA_HTML

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    class _FakeOpener:
        def open(self, _request, timeout=None):
            return _FakeResponse()

    monkeypatch.setattr(source_module, "_build_opener", lambda _no_proxy: _FakeOpener())

    destination = tmp_path / "Setup.exe"
    with pytest.raises(UpdateSourceError) as exc:
        download("https://llm.brb-tech.uz/download/Setup.exe", destination)

    assert "HTML" in str(exc.value)
    assert not destination.exists()
    assert not destination.with_suffix(".exe.part").exists()


# --- ko'p platformali manifest -------------------------------------------------
#
# `setup` va `platforms` birga yashaydi: `setup` tarqatilgan eski mijozlar
# (0.2.3 va oldingilar) uchun majburiy meros. Quyidagi testlar aynan shu
# yashash qoidalarini qotiradi - ular buzilsa eski mijozlar yangilanishni
# yo'qotadi yoki noto'g'ri platformaning faylini yuklab oladi.

def _multi_manifest_dict(version="0.2.4"):
    return {
        "version": version,
        "released": "2026-09-10",
        "setup": {"file": f"setup-{version}.exe", "sha256": "a" * 64, "size": 1234},
        "platforms": {
            "windows": {"file": f"setup-{version}.exe", "sha256": "a" * 64, "size": 1234},
            "macos": {"file": f"venera-{version}-universal.dmg", "sha256": "b" * 64,
                      "size": 5678, "arch": "universal", "min_os": "11.0"},
        },
    }


def test_platforms_bloki_oqiladi():
    m = Manifest.parse(json.dumps(_multi_manifest_dict()))
    assert set(m.platforms) == {"windows", "macos"}

    mac = m.asset_for("macos")
    assert mac is not None
    assert mac.file == "venera-0.2.4-universal.dmg"
    assert mac.arch == "universal"
    assert mac.min_os == "11.0"
    assert mac.size == 5678
    assert mac.has_checksum

    win = m.asset_for("windows")
    assert win is not None and win.file == "setup-0.2.4.exe"


def test_platforms_yoq_bolsa_setup_hamma_uchun():
    """Eski format: platforma haqida ma'lumot yo'q -> yagona fayl hammaga."""
    m = Manifest.parse(json.dumps(_manifest_dict()))
    assert m.platforms == {}
    for key in ("windows", "macos", "linux"):
        asset = m.asset_for(key)
        assert asset is not None and asset.file == "setup-0.2.0.exe"


def test_platforms_bor_lekin_bu_os_yoq():
    """Nashr qiluvchi platformalarni ochiq sanagan - ro'yxatda yo'q OS uchun fayl yo'q."""
    data = _multi_manifest_dict()
    del data["platforms"]["macos"]
    m = Manifest.parse(json.dumps(data))
    assert m.asset_for("macos") is None
    assert m.asset_for("linux") is None
    # Windows esa `setup` ga tushadi - u kelishuvga ko'ra Windows o'rnatuvchisi.
    assert m.asset_for("windows") is not None


def test_faqat_platforms_bilan_manifest():
    """`setup` yo'q, lekin platformalar bor - yangi mijozlar uchun yaroqli."""
    data = _multi_manifest_dict()
    del data["setup"]
    m = Manifest.parse(json.dumps(data))
    assert m.setup.file == ""
    assert m.asset_for("macos") is not None
    # Windows `platforms` dan keladi, `setup` dan emas.
    assert m.asset_for("windows").file == "setup-0.2.4.exe"


def test_setup_ham_platforms_ham_yoq_xato():
    with pytest.raises(ValueError):
        Manifest.parse(json.dumps({"version": "0.2.4"}))
    with pytest.raises(ValueError):
        Manifest.parse(json.dumps({"version": "0.2.4", "platforms": {}}))


def test_fayl_nomsiz_platforma_etiborsiz():
    data = _multi_manifest_dict()
    data["platforms"]["linux"] = {"sha256": "c" * 64, "size": 1}
    m = Manifest.parse(json.dumps(data))
    assert "linux" not in m.platforms


def test_update_info_hajmi_platforma_faylidan():
    m = Manifest.parse(json.dumps(_multi_manifest_dict()))
    mac = m.asset_for("macos")
    info = UpdateInfo(manifest=m, current_version="0.2.0",
                      download_url="x", asset=mac)
    assert info.resolved_asset is mac
    assert info.size_mb == round(5678 / 1048576.0, 1)


def test_update_info_asset_berilmasa_manifestdan():
    """Eski chaqiruvlar (asset=None) buzilmasligi kerak."""
    m = Manifest.parse(json.dumps(_manifest_dict()))
    info = UpdateInfo(manifest=m, current_version="0.1.0", download_url="x")
    assert info.resolved_asset.file == "setup-0.2.0.exe"
