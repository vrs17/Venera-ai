# -*- mode: python ; coding: utf-8 -*-
"""macOS uchun PyInstaller konfiguratsiyasi (.app bundle).

    pyinstaller packaging/macos/venera_macos.spec --noconfirm

Windows'dagi venera.spec ning egizagi, farqlari:
  * COLLECT dan keyin BUNDLE - natija Venera.app bo'ladi;
  * ikonka .icns (build_macos.sh uni iconutil bilan yasaydi);
  * Info.plist shu yerda, alohida faylda emas - versiya __init__.py dan
    olinadi, ya'ni ikki joyda qo'lda yangilash kerak emas;
  * LSUIElement=True - tray (menyu paneli) ilovasi Dock'da ko'rinmasin;
  * hiddenimports pystray'ning DARWIN backend'i uchun.

Nima uchun onedir: Windows'dagi bilan bir xil sabab emas - macOS'da .app
allaqachon papka. onefile bu yerda umuman ma'nosiz.
"""

import os
import sys
from pathlib import Path

block_cipher = None

# packaging/macos/ ichida turibmiz -> ikki daraja yuqori = apps/desktop
ROOT = Path(SPECPATH).resolve().parent.parent
SRC = ROOT / "src"

sys.path.insert(0, str(SRC))
from venera import APP_DISPLAY_NAME, APP_NAME, __version__  # noqa: E402

BUNDLE_ID = "uz.venera.assistant"
ICNS = ROOT / "build" / "icons" / f"{APP_NAME}.icns"

datas = [
    (str(SRC / "venera" / "resources"), "venera/resources"),
]

hiddenimports = [
    "venera",
    "venera.__main__",
    "venera.app",
    # pystray macOS backend'ini avtomatik topmaydi - qo'lda ko'rsatamiz.
    "pystray._darwin",
    "PIL._tkinter_finder",
    # is_session_locked() Quartz'ni ishlatadi; pyobjc modullari dinamik
    # yuklanadi, shuning uchun PyInstaller ularni o'zi ko'rmaydi.
    "objc",
    "Quartz",
    "AppKit",
    "Foundation",
]

a = Analysis(
    [str(ROOT / "packaging" / "common" / "entrypoint.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Windows-only bog'liqliklar macOS build'iga umuman kirmasin.
    excludes=["matplotlib", "scipy", "pandas", "pytest", "setuptools",
              "comtypes", "pycaw", "win32com", "win32api", "pythoncom"],
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
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    # argv_emulation Finder'dan ochilgan fayllarni argv ga o'giradi. Bizga
    # kerak emas va u Apple Events ruxsatini so'rashga sabab bo'ladi.
    argv_emulation=False,
    # Default: joriy mashina arxitekturasi. build_macos.sh --universal bergan
    # bo'lsa muhit o'zgaruvchisi orqali universal2 ga o'tadi - shunda spec
    # faylni tahrirlash kerak emas. DIQQAT: universal2 uchun BARCHA bog'liqlik
    # g'ildiraklari (numpy, Pillow, ...) ham universal2 bo'lishi shart.
    target_arch=os.environ.get("VENERA_TARGET_ARCH") or None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)

app = BUNDLE(
    coll,
    name=f"{APP_NAME}.app",
    icon=str(ICNS) if ICNS.exists() else None,
    bundle_identifier=BUNDLE_ID,
    version=__version__,
    info_plist={
        "CFBundleName": "Barno",
        "CFBundleDisplayName": APP_DISPLAY_NAME,
        "CFBundleShortVersionString": __version__,
        "CFBundleVersion": __version__,
        "CFBundleIdentifier": BUNDLE_ID,
        "NSHumanReadableCopyright": f"© {APP_DISPLAY_NAME}",
        # Menyu panelidagi ilova: Dock'da ikonka ham, Cmd+Tab'da ham ko'rinmaydi.
        "LSUIElement": True,
        "NSHighResolutionCapable": True,
        # Universal2 va Apple Silicon uchun xavfsiz quyi chegara.
        "LSMinimumSystemVersion": "11.0",
        # --- ruxsat izohlari ---------------------------------------------
        # Bu matnlar foydalanuvchiga tizim dialogida KO'RINADI. Ular
        # bo'lmasa macOS ilovani so'ramasdan yiqitadi (TCC crash).
        "NSMicrophoneUsageDescription":
            "Barno sizning ovozli buyruqlaringizni eshitishi uchun mikrofon kerak.",
        "NSAppleEventsUsageDescription":
            "Barno tizim ovozini boshqarish va ekranni qulflash uchun System Events'ga murojaat qiladi.",
        "NSSystemAdministrationUsageDescription":
            "Barno ekranni qulflash uchun tizim xizmatlaridan foydalanadi.",
    },
)
