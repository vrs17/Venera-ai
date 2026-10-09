# macOS build — Barno AI Assistant

Bu hujjat `.dmg` ni **Mac'da** yig'ish tartibini beradi.

> **Nega Mac kerak.** `.app` bundle'ni Linux yoki Windows'da yasab bo'lmaydi:
> PyInstaller cross-compile qilmaydi, `iconutil` / `codesign` / `notarytool`
> esa faqat macOS'da mavjud. Serverdagi Linux mashina faqat manifest yozadi va
> fayllarni tarqatadi.

Ish taqsimoti:

| Platforma | Nima yig'adi | Skript |
|---|---|---|
| Windows | `.exe` | `apps/desktop/packaging/windows/build_setup.ps1` |
| macOS | `.dmg` | `apps/desktop/packaging/macos/build_macos.sh` |
| Linux (server) | `version.json`, tarqatish | `apps/desktop/tools/make_manifest.py` |

---

## 1. Mac'ni tayyorlash

```bash
# Xcode command line tools (iconutil, codesign, notarytool shu yerdan keladi)
xcode-select --install

# Python 3.11+ (python.org o'rnatuvchisi yoki Homebrew)
python3 --version

git clone <repo> venera && cd venera/apps/desktop
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
```

`requirements.txt` macOS'da `pyobjc-core`, `pyobjc-framework-Cocoa` va
`pyobjc-framework-Quartz` ni ham tortadi — ular tray ikonkasi (pystray'ning
darwin backend'i) va ekran qulflanganini aniqlash uchun kerak.

## 2. Yig'ish

```bash
# Imzosiz — faqat shu mashinada sinash uchun
./packaging/macos/build_macos.sh

# Imzolangan
./packaging/macos/build_macos.sh --identity "Developer ID Application: Firma (TEAMID)"

# Imzolangan + notarizatsiya qilingan (tarqatish uchun SHU kerak)
./packaging/macos/build_macos.sh \
    --identity "Developer ID Application: Firma (TEAMID)" \
    --notarize-profile venera-notary

# Intel + Apple Silicon bitta faylda
./packaging/macos/build_macos.sh --universal --identity "..." --notarize-profile ...
```

Skript ketma-ketligi: bog'liqliklar → versiya va ikonka (`iconutil`) → testlar →
PyInstaller → imzo → `.dmg` → notarizatsiya → `version.json`.

Natija: `release/Venera-AI-Assistant-<versiya>-<arch>.dmg`

## 3. Imzo va notarizatsiya haqida — buni o'tkazib bo'lmaydi

**Imzosiz `.dmg` boshqa Mac'da ochilmaydi.** Gatekeeper "damaged and can't be
opened" deydi — fayl buzilmagan, shunchaki imzolanmagan. Ommaviy tarqatish
uchun **Apple Developer Program** (99 $/yil) shart:

1. **Developer ID Application** sertifikati — `codesign` uchun.
   Xcode → Settings → Accounts → Manage Certificates → `+` → Developer ID Application.
2. **notarytool profili** — bir marta yaratiladi:
   ```bash
   xcrun notarytool store-credentials venera-notary \
       --apple-id <apple-id> --team-id <TEAMID> \
       --password <app-specific-password>
   ```
   `app-specific-password` — appleid.apple.com dan olinadi (oddiy parol emas).
3. **Stapler** — notarizatsiya tasdig'ini faylga yopishtiradi, shunda internetsiz
   ham ochiladi. Skript buni o'zi bajaradi.

Ichki foydalanish uchun imzosiz ham bo'ladi, lekin har bir foydalanuvchi qo'lda
karantinni olib tashlashi kerak:
```bash
xattr -dr com.apple.quarantine /Applications/Venera.app
```

## 4. Ruxsatlar

Birinchi ishga tushganda macOS so'raydi. `Info.plist` da sabablari yozilgan
(`venera_macos.spec` ichida) — ular bo'lmasa macOS ilovani so'ramasdan yiqitadi.

| Ruxsat | Nima uchun | Bo'lmasa |
|---|---|---|
| Mikrofon | ovozli buyruqlar | ilova eshitmaydi (asosiy funksiya) |
| Screen Recording | skrinshot | `screencapture` bo'sh rasm beradi |
| Accessibility | ekran qulflashning **zaxira** yo'li | asosiy yo'l (`CGSession`) baribir ishlaydi |

Accessibility odatda **kerak emas**: `lock_workstation()` avval `CGSession
-suspend` ni sinaydi, u ruxsatsiz ishlaydi.

## 5. Tarqatish

```bash
# Mac'dan serverga
scp release/Venera-AI-Assistant-*.dmg  <server>:~/.local/share/venera/downloads/
scp release/version.json               <server>:~/.local/share/venera/downloads/
```

**Tartib muhim: avval `.dmg`, keyin `version.json`.** Manifest yangi faylga
ishora qiladi; teskari tartibda mijozlar bir necha soniya mavjud bo'lmagan
faylni so'raydi.

Manifest ikkala platformani birga saqlaydi va **birlashtirib** yoziladi, ya'ni
macOS build'i Windows yozuvini o'chirmaydi:

```bash
# Serverda, faqat macOS yangilanganda
python3 apps/desktop/tools/make_manifest.py \
    --macos ~/.local/share/venera/downloads/Venera-AI-Assistant-0.2.4-universal.dmg \
    -o ~/.local/share/venera/downloads/version.json
```

> ⚠️ Skript versiya nomuvofiqligini ogohlantiradi: macOS 0.2.4 chiqarilib
> Windows 0.2.3 da qolsa, manifestdagi `version` **hamma** mijozga tegishli
> bo'lgani uchun Windows foydalanuvchilari "yangi versiya bor" deb o'sha eski
> faylni qayta yuklaydi. Ikkala platformani birga chiqaring yoki
> `--drop-stale` bilan eski yozuvni olib tashlang.

Sayt (`llm.brb-tech.uz`) manifestni o'zi o'qiydi — frontend'ni qayta yig'ish
shart emas, `.dmg` papkaga tushishi bilan macOS kartasi faollashadi.

## 6. macOS'da auto-update qanday ishlaydi

Windows'da yangilanish jimgina o'rnatiladi (`Setup.exe /S`). **macOS'da
bunday emas:** ishlayotgan `.app` o'zini almashtira olmaydi (Gatekeeper imzoni
qayta tekshiradi). Shuning uchun mijoz:

1. `.dmg` ni yuklab oladi va sha256 ni tekshiradi;
2. uni **Finder'da ochadi** (`open -R`);
3. foydalanuvchi ilovani (`Venera.app`) Applications papkasiga sudrab tashlaydi.

"O'rnatildi" belgisi qo'yilmaydi — aks holda keyingi ishga tushishda noto'g'ri
"yangilandi" xabari chiqardi.

## 7. Tekshirish ro'yxati

```bash
# Imzo joyidami
codesign --verify --deep --strict --verbose=2 /Applications/Venera.app

# Notarizatsiya joyidami
spctl -a -vvv -t install /Applications/Venera.app
xcrun stapler validate release/Venera-AI-Assistant-*.dmg

# Ilova diagnostikasi (yo'llar, adapter, ruxsatlar)
/Applications/Venera.app/Contents/MacOS/Venera --check

# Loglar
tail -f ~/Library/Logs/Venera/assistant.log
```

## Ma'lum cheklovlar

- **Ovoz sintezi** — macOS'ning `say` buyrug'i ishlatiladi. Unda o'zbek ovozi
  yo'q, shuning uchun talaffuz noto'g'ri bo'ladi. Bu Windows'dagi SAPI bilan
  bir xil vaqtinchalik holat; Step 4 dagi on-prem TTS ikkalasini ham
  almashtiradi.
- **Universal build** uchun barcha bog'liqlik g'ildiraklari (`numpy`, `Pillow`,
  ...) `universal2` bo'lishi shart. Bo'lmasa har bir arxitektura uchun alohida
  `.dmg` yig'ing — manifest `arch` maydonini fayl nomidan o'zi aniqlaydi.
