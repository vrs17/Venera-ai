# Barno AI — Linux serverda

Bu server ikki ish qiladi: kod bilan ishlash va relizni tarqatish.

## Nima mumkin, nima mumkin emas

Desktop ilova **Windows dasturi** — mikrofon, tray ikonkasi va SAPI ovoziga
tayanadi. Shuning uchun:

| Mumkin | Mumkin emas |
|---|---|
| Kodni tahrirlash | Ilovani ishga tushirish (audio/tray qurilmalari yo'q) |
| `pytest` — 207 test | `.exe` yig'ish (PyInstaller Windows'da ishlashi shart) |
| `version.json` yasash | `packaging/windows/*.ps1` ni bajarish (PowerShell) |
| **Relizni tarqatish** | |

Oxirgi qator eng muhimi: **relizni shu server tarqatadi.**

## 1. Kod bilan ishlash

```bash
cd apps/desktop
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt      # Windows paketlari o'zi o'tkazib yuboriladi
python -m pytest -q
```

`requirements.txt` dagi `pywin32`, `comtypes`, `pycaw` paketlari
`sys_platform == "win32"` sharti bilan belgilangan, shuning uchun Linux'da
o'rnatilmaydi va xato bermaydi.

## 2. Relizni tarqatish

Fayllar `~/.local/share/venera/downloads/` da turadi. O'sha papkani web
konteyneri read-only mount qiladi va `llm.brb-tech.uz/download/` ostida beradi.

**Alohida update serveri yo'q va kerak emas.** Sayt ham, desktop auto-update
ham xuddi shu manzildan o'qiydi — bitta host, bitta papka, bitta fayl.
Shuning uchun ular ikki xil versiya ko'rsatishi mumkin emas.

Bir martalik sozlash: [deploy-desktop-download.md](deploy-desktop-download.md)

Har bir reliz: [release-desktop.md](release-desktop.md)

## 3. Ish ikki mashina orasida qanday taqsimlanadi

```
Windows mashinasi                        Linux server
─────────────────────                    ────────────────────────────
packaging/windows/build_setup.ps1   ──►  tools/make_manifest.py
  .exe yig'adi                             version.json yozadi
  update URL ni ichiga yopishtiradi        fayllarni papkaga qo'yadi
```

`make_manifest.py` sha256 va hajmni o'zi hisoblaydi.

Eski `.exe` fayllarni darhol o'chirmang: yangilanish yarim yo'lda uzilgan
kompyuter qayta urinishi mumkin.

## Hal qilinmagan masalalar

- Nom o'zgarishidan **oldingi** o'rnatmalarda (`%LOCALAPPDATA%\Programs\BRB-Tech\`)
  update manzili yo'q yoki eskirgan bo'lishi mumkin. Ularni tuzatish:

  ```powershell
  "$env:LOCALAPPDATA\Programs\BRB-Tech\BRBTechAssistant.exe" --set-update-url "https://llm.brb-tech.uz/download/version.json"
  ```

  Yoki yangi `Setup.exe` ni bir marta qo'lda o'rnatish. Ikkalasidan keyin ham
  keyingi barcha yangilanishlar avtomatik bo'ladi.

- macOS uchun `.dmg` hali chiqarilmagan — nginx va manifest uni qo'llab-quvvatlaydi,
  faqat build kerak ([build-macos.md](build-macos.md)).
