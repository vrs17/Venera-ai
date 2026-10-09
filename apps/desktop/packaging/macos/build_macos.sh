#!/usr/bin/env bash
#
# Venera AI Assistant — macOS .app va .dmg yig'ish.
#
# Windows'dagi build.ps1 + build_setup.ps1 ning ekvivalenti. FAQAT macOS'da
# ishlaydi: PyInstaller cross-compile qilmaydi, iconutil/codesign/notarytool
# esa umuman boshqa OS'da yo'q.
#
# Ishlatish:
#   cd apps/desktop
#   ./packaging/macos/build_macos.sh                       # imzosiz (faqat sinov uchun)
#   ./packaging/macos/build_macos.sh --identity "Developer ID Application: Firma (TEAMID)"
#   ./packaging/macos/build_macos.sh --identity "..." --notarize-profile venera-notary
#   ./packaging/macos/build_macos.sh --universal           # Intel + Apple Silicon
#
# IMZO HAQIDA — buni tushunib olish muhim:
#   Imzosiz .dmg ni boshqa Mac'da ochib bo'lmaydi: Gatekeeper "damaged and
#   can't be opened" deydi (fayl buzilmagan, shunchaki imzolanmagan). Ya'ni
#   ommaviy tarqatish uchun Apple Developer hisobi (99 $/yil) SHART:
#     1. "Developer ID Application" sertifikati  -> codesign
#     2. notarytool profili                      -> Apple'ga yuborib tasdiqlash
#     3. stapler                                 -> tasdiqni faylga yopishtirish
#   Ichki foydalanish uchun imzosiz ham bo'ladi, lekin har bir foydalanuvchi
#   qo'lda `xattr -dr com.apple.quarantine /Applications/Venera.app` qilishi kerak.

set -euo pipefail

# --- argumentlar ------------------------------------------------------------
IDENTITY=""
NOTARY_PROFILE=""
UNIVERSAL=0
SKIP_TESTS=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --identity)          IDENTITY="${2:-}"; shift 2 ;;
        --notarize-profile)  NOTARY_PROFILE="${2:-}"; shift 2 ;;
        --universal)         UNIVERSAL=1; shift ;;
        --skip-tests)        SKIP_TESTS=1; shift ;;
        -h|--help)           sed -n '2,30p' "$0"; exit 0 ;;
        *) echo "Noma'lum argument: $1" >&2; exit 2 ;;
    esac
done

# --- muhit tekshiruvi -------------------------------------------------------
if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "XATO: bu skript faqat macOS'da ishlaydi (joriy: $(uname -s))." >&2
    echo "      PyInstaller cross-compile qilmaydi - .app ni Mac'da yig'ish shart." >&2
    exit 1
fi

# packaging/macos/ -> apps/desktop
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

echo "=== Barno AI Assistant — macOS build ==="
echo "Loyiha: $ROOT"

PYTHON="python3"
[[ -x ".venv/bin/python" ]] && PYTHON=".venv/bin/python"
echo "Python: $PYTHON ($($PYTHON --version))"

# --- 1/6 bog'liqliklar ------------------------------------------------------
echo ""
echo "1/6  Bog'liqliklar..."
$PYTHON -m pip install -r requirements-dev.txt --quiet
# pyobjc pystray'ning macOS backend'i va Quartz uchun kerak. requirements.txt
# da platforma markeri bilan turibdi, lekin dev muhitida ham bo'lsin.
$PYTHON -m pip install --quiet "pyobjc-core>=10.0" "pyobjc-framework-Cocoa>=10.0" "pyobjc-framework-Quartz>=10.0"

# --- 2/6 versiya va ikonka --------------------------------------------------
echo "2/6  Versiya va ikonka..."
VERSION="$($PYTHON tools/sync_version.py | tr -d '[:space:]')"
echo "     Versiya: $VERSION"

$PYTHON tools/make_icon.py >/dev/null
ICONSET="src/venera/resources/icons/Venera.iconset"
ICNS_DIR="build/icons"
mkdir -p "$ICNS_DIR"
iconutil -c icns "$ICONSET" -o "$ICNS_DIR/Venera.icns"
echo "     Ikonka: $ICNS_DIR/Venera.icns"

# --- 3/6 testlar ------------------------------------------------------------
if [[ $SKIP_TESTS -eq 0 ]]; then
    echo "3/6  Testlar..."
    $PYTHON -m pytest tests -q
else
    echo "3/6  Testlar o'tkazib yuborildi (--skip-tests)"
fi

# --- 4/6 PyInstaller --------------------------------------------------------
echo "4/6  PyInstaller..."
if [[ $UNIVERSAL -eq 1 ]]; then
    # target_arch spec faylida None; universal uchun muhit o'zgaruvchisi orqali
    # beramiz, shunda spec faylni tahrirlash shart emas.
    export VENERA_TARGET_ARCH="universal2"
    echo "     universal2 (Intel + Apple Silicon)"
fi
$PYTHON -m PyInstaller packaging/macos/venera_macos.spec --noconfirm --log-level WARN

APP="dist/Venera.app"
[[ -d "$APP" ]] || { echo "XATO: $APP yasalmadi" >&2; exit 1; }
ARCH="$(uname -m)"
[[ $UNIVERSAL -eq 1 ]] && ARCH="universal"
echo "     $APP  ($(du -sh "$APP" | cut -f1))"

# --- 5/6 imzo ---------------------------------------------------------------
echo "5/6  Imzo..."
if [[ -n "$IDENTITY" ]]; then
    # --deep ATAYLAB ishlatilmaydi: Apple uni eskirgan deb hisoblaydi va u
    # ichki imzolarni buzadi. To'g'ri yo'l - avval ichkaridagi barcha binarlar,
    # keyin .app ning o'zi.
    find "$APP" -type f \( -name "*.so" -o -name "*.dylib" \) -print0 |
        while IFS= read -r -d '' lib; do
            codesign --force --timestamp --options runtime \
                     --entitlements packaging/macos/entitlements.plist \
                     --sign "$IDENTITY" "$lib"
        done
    codesign --force --timestamp --options runtime \
             --entitlements packaging/macos/entitlements.plist \
             --sign "$IDENTITY" "$APP"
    codesign --verify --deep --strict --verbose=2 "$APP"
    echo "     Imzolandi: $IDENTITY"
else
    echo "     ⚠️  IMZOSIZ. Faqat shu mashinada sinash uchun yaroqli."
    echo "        Boshqa Mac'da Gatekeeper 'damaged' deb rad etadi."
fi

# --- 6/6 DMG ----------------------------------------------------------------
echo "6/6  DMG..."
DMG_NAME="Venera-AI-Assistant-${VERSION}-${ARCH}.dmg"
DMG="release/$DMG_NAME"
mkdir -p release
rm -f "$DMG"

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
cp -R "$APP" "$STAGE/"
# /Applications ga symlink: foydalanuvchi ilovani sudrab tashlaydi - macOS'da
# o'rnatishning standart usuli, alohida installer kerak emas.
ln -s /Applications "$STAGE/Applications"

hdiutil create -volname "Barno AI Assistant" \
               -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
echo "     $DMG  ($(du -h "$DMG" | cut -f1))"

if [[ -n "$IDENTITY" ]]; then
    codesign --force --timestamp --sign "$IDENTITY" "$DMG"
fi

# --- notarizatsiya ----------------------------------------------------------
if [[ -n "$NOTARY_PROFILE" ]]; then
    echo ""
    echo "Notarizatsiya (Apple'ga yuborilmoqda, bir necha daqiqa)..."
    xcrun notarytool submit "$DMG" --keychain-profile "$NOTARY_PROFILE" --wait
    xcrun stapler staple "$DMG"
    xcrun stapler validate "$DMG"
    echo "Notarizatsiya tugadi - endi istalgan Mac'da ochiladi."
elif [[ -n "$IDENTITY" ]]; then
    echo ""
    echo "⚠️  Imzolandi, lekin notarizatsiya qilinmadi."
    echo "   Profil yaratish (bir marta):"
    echo "     xcrun notarytool store-credentials venera-notary \\"
    echo "       --apple-id <apple-id> --team-id <TEAMID> --password <app-specific-password>"
fi

# --- manifest ---------------------------------------------------------------
echo ""
echo "Manifest yangilanmoqda..."
$PYTHON tools/make_manifest.py --macos "$DMG" --version "$VERSION" \
        -o release/version.json

echo ""
echo "Tayyor:"
echo "  $ROOT/$DMG"
echo "  $ROOT/release/version.json"
echo ""
echo "Serverga qo'yish (tartib MUHIM - avval .dmg, keyin version.json):"
echo "  scp $DMG           <server>:/var/www/venera/assistant/"
echo "  scp release/version.json  <server>:/var/www/venera/assistant/"
