# Venera AI Assistant — Linux serverda

Bu paket loyihaning to'liq manbasini va tayyor `0.2.3` o'rnatuvchisini o'z
ichiga oladi.

## Linux serverda nima mumkin, nima mumkin emas

Ilova o'zi **Windows desktop dasturi** — mikrofon, tray ikonkasi va SAPI
ovoziga tayanadi. Shuning uchun:

| Mumkin | Mumkin emas |
|---|---|
| Kodni tahrirlash | Ilovani ishga tushirish (audio/tray qurilmalari yo'q) |
| `pytest` — 199 test | `.exe` yig'ish (PyInstaller Windows kerak) |
| `version.json` yasash | `packaging/publish.ps1` ni bajarish (PowerShell) |
| **Yangilanishlarni tarqatish** | |

Oxirgi qator eng muhimi: **Linux server yangilanish serveri bo'la oladi.**
Bu unga eng mos rol.

## 1. Kod bilan ishlash

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt      # Windows paketlari o'zi o'tkazib yuboriladi
python -m pytest tests/ -q               # 199 test
```

`requirements.txt` dagi `pywin32`, `comtypes`, `pycaw` paketlari
`sys_platform == "win32"` sharti bilan belgilangan, shuning uchun Linux'da
o'rnatilmaydi va xato bermaydi.

## 2. Yangilanish serveri sifatida

`release/` papkasida tayyor fayllar bor:

```
release/version.json                            417 B
release/Venera-AI-Assistant-Setup-0.2.3.exe    43 MB
```

nginx sozlamasi `infra/nginx/venera-updates.conf` da. Fayllarni o'z joyiga
qo'ying:

```bash
sudo mkdir -p /var/www/venera/assistant
sudo cp release/Venera-AI-Assistant-Setup-0.2.3.exe /var/www/venera/assistant/
sudo cp release/version.json                          /var/www/venera/assistant/
sudo chown -R www-data:www-data /var/www/venera
```

**Tartib muhim: avval `.exe`, keyin `version.json`.** Teskari bo'lsa manifest
hali yuklanmagan faylga ishora qilib turadi va kompyuterlar xato oladi.

To'liq qo'llanma: `docs/deploy-update-server.md`.

## 3. Keyingi versiyani chiqarish

Ish ikki mashina orasida taqsimlanadi:

```
Windows mashinasi                     Linux server
─────────────────────                 ──────────────────────────
packaging/build_setup.ps1     ──►     tools/make_manifest.py
  .exe yig'adi                          version.json yozadi
                                        fayllarni tarqatadi
```

Windows'da yangi `.exe` yig'ilgach, uni Linux serverga ko'chiring va:

```bash
python3 apps/desktop/tools/make_manifest.py release/Venera-AI-Assistant-Setup-0.2.4.exe \
        --notes "Nima o'zgardi"

sudo cp release/Venera-AI-Assistant-Setup-0.2.4.exe /var/www/venera/assistant/
sudo cp release/version.json                          /var/www/venera/assistant/
```

`make_manifest.py` sha256 va hajmni o'zi hisoblaydi — `publish.ps1` bilan
bir xil natija beradi (tekshirilgan).

Eski `.exe` fayllarni o'chirmang: yangilanish yarim yo'lda uzilgan kompyuter
qayta urinishi mumkin.

## 4. Tekshirish

```bash
curl -sS https://ccs.venera.uz/assistant/version.json
#   kutilgan:  {"version": "0.2.3", ...}
#   xato:      <!doctype html>   -> nginx yo'li sozlanmagan

curl -sSI https://ccs.venera.uz/assistant/Venera-AI-Assistant-Setup-0.2.3.exe
#   kutilgan:  Content-Type: application/octet-stream
```

## Hal qilinmagan masalalar

- `ccs.venera.uz` hozircha HTTP javob bermaydi — vhost sozlanmagan.
- Tashqi `195.158.16.251:443` internetga e'lon qilinganmi — tasdiqlanmagan.
- 0.1.0 o'rnatilgan kompyuterlarda yangilanish moduli yo'q — ularga
  `0.2.3` bir marta qo'lda o'rnatilishi kerak.

Batafsil: `docs/deploy-update-server.md`.
