# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller konfiguratsiyasi.

    pyinstaller packaging/venera.spec --noconfirm

Nima uchun onedir (onefile emas):
  * Defender va SmartScreen onefile'ni ancha tez-tez bloklaydi;
  * onefile har ishga tushganda %TEMP% ga ochiladi - sekinroq;
  * onedir'da DLL muammosini ko'rish oson.

--noconsole rejimida sys.stdout None bo'ladi, shuning uchun kodda print()
ishlatilmaydi va barcha xatolar log fayliga yoziladi.
"""

import sys
from pathlib import Path

block_cipher = None

ROOT = Path(SPECPATH).resolve().parent
SRC = ROOT / "src"

datas = [
    (str(SRC / "venera" / "resources"), "venera/resources"),
]

hiddenimports = [
    "venera",
    "venera.__main__",
    "venera.app",
    "comtypes",
    "comtypes.client",
    "comtypes.stream",
    "pycaw",
    "pycaw.pycaw",
    "win32timezone",
    "pystray._win32",
    "PIL._tkinter_finder",
]

# DIQQAT: kirish nuqtasi paket ichidagi __main__.py EMAS, balki entrypoint.py.
# PyInstaller __main__.py ni paketdan tashqarida ishga tushiradi va nisbiy
# importlar buziladi (ImportError: attempted relative import).
a = Analysis(
    [str(ROOT / "packaging" / "entrypoint.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "scipy", "pandas", "pytest", "setuptools"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Venera",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                     # tray ilova - konsol oynasi yo'q
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(SRC / "venera" / "resources" / "icons" / "app.ico"),
    version=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Venera",
)
