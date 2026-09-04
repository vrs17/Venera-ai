# -*- mode: python ; coding: utf-8 -*-
"""O'rnatuvchi (Setup.exe) uchun PyInstaller konfiguratsiyasi.

Bu yerda onefile ISHLATILADI - maqsad aynan bitta fayl olish. Ilovaning
o'zi esa onedir bo'lib qoladi va shu exe ichiga "payload" sifatida
joylashtiriladi. Shuning uchun:
  * foydalanuvchi bitta faylni ko'chiradi va ikki marta bosadi;
  * o'rnatilgan ilova tez ishga tushadi (har safar arxivdan ochilmaydi);
  * antivirus onedir ilovani onefile'dan kamroq shubha bilan qaraydi.

Avval `packaging/venera.spec` yig'ilgan bo'lishi shart.
"""

from pathlib import Path

block_cipher = None

ROOT = Path(SPECPATH).resolve().parent
SRC = ROOT / "src"
APP_BUILD = ROOT / "dist" / "Venera"

if not (APP_BUILD / "Venera.exe").exists():
    raise SystemExit(
        f"Ilova build'i topilmadi: {APP_BUILD}\n"
        "Avval ishga tushiring: powershell -File packaging\\build.ps1"
    )

# Yangilanish manzili build paytida yopishtiriladi (ixtiyoriy).
# build_setup.ps1 -UpdateUrl "..." shu faylni yozadi.
_datas = [(str(APP_BUILD), "payload")]     # butun ilova shu yerga joylashadi
_update_url = ROOT / "packaging" / "update_url.txt"
if _update_url.exists() and _update_url.read_text(encoding="utf-8").strip():
    _datas.append((str(_update_url), "."))

a = Analysis(
    [str(ROOT / "packaging" / "setup_entrypoint.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=_datas,
    hiddenimports=["tkinter", "tkinter.ttk"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["numpy", "PIL", "sounddevice", "pystray", "pycaw", "yaml",
              "rapidfuzz", "matplotlib", "scipy", "pandas", "pytest"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="Venera-AI-Assistant-Setup",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(SRC / "venera" / "resources" / "icons" / "app.ico"),
)
