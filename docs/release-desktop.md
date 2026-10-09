# Desktop uchun yangi versiya chiqarish

Bir marta sozlangandan keyin (→ [deploy-desktop-download.md](deploy-desktop-download.md))
har bir yangi versiya shu to'rt qadamdan iborat. Natijada:

* saytdagi **"Yuklab olish"** yangi faylni beradi,
* **allaqachon o'rnatilgan** kompyuterlarda bildirishnoma chiqadi va foydalanuvchi
  bir tugma bosib yangilanadi.

Ikkalasi bitta `version.json` ni o'qiydi, shuning uchun ular hech qachon
bir-biridan farq qilmaydi.

---

## 1. Versiyani ko'taring

Yagona manba — `src/venera/__init__.py` dagi `__version__`. Skript uni
`resources/VERSION` va `pyproject.toml` ga tarqatadi:

```bash
cd apps/desktop
python3 tools/sync_version.py 0.2.4
```

> Versiya **oshishi shart**. Auto-update `is_newer()` bilan solishtiradi —
> teng yoki kichik versiya e'lon qilinsa, hech kimda bildirishnoma chiqmaydi.

## 2. Windows'da yig'ing

PyInstaller faqat o'z OS'i uchun fayl yasaydi — bu qadam **Windows mashinada**
bajarilishi shart, Linux'dan bo'lmaydi.

```powershell
cd C:\Venera\apps\desktop
powershell -ExecutionPolicy Bypass -File packaging\windows\build_setup.ps1 `
    -UpdateUrl "https://llm.brb-tech.uz/download/version.json"
```

`-UpdateUrl` manzilni o'rnatuvchi ichiga yopishtiradi. O'rnatuvchi ishga
tushganda `Venera.exe --set-update-url "..."` ni chaqiradi va manzil
foydalanuvchining `%APPDATA%\Venera\config.yaml` fayliga yoziladi.

Natija: `apps\desktop\dist\Venera-AI-Assistant-Setup.exe`

## 3. Manifest yarating

SHA256 va hajmni o'zi hisoblaydi:

```bash
python3 apps/desktop/tools/make_manifest.py \
    apps/desktop/dist/Venera-AI-Assistant-Setup.exe \
    --notes "Barno nomiga o'tildi"
```

`--notes` — foydalanuvchi bildirishnoma panelida **ko'radigan** matn. Qisqa va
tushunarli yozing.

Ikkala faylni `release/` ga qo'ying (fayl nomida versiya bo'lishi kerak, masalan
`Venera-AI-Assistant-Setup-0.2.4.exe` — shunda eski nusxa keshda qolib ketmaydi).

## 4. Serverga qo'ying

```bash
cp release/Venera-AI-Assistant-Setup-0.2.4.exe  ~/.local/share/venera/downloads/
cp release/version.json                          ~/.local/share/venera/downloads/
```

**Tartib muhim: avval `.exe`, keyin `version.json`.** Manifest yangi versiyani
e'lon qilgan payt fayl allaqachon joyida bo'lishi kerak — aks holda birinchi
yangilanayotgan kompyuter 404 oladi.

Konteynerga tegish shart emas: papka read-only mount qilingan, o'zgarishni
darhol ko'radi.

---

## Kompyuterlarda nima bo'ladi

| Vaqt | Nima sodir bo'ladi |
|---|---|
| Ilova ishga tushgach **90 soniya** | birinchi tekshiruv (`startup_delay_seconds`) |
| Keyin har **6 soatda** | takroriy tekshiruv (`check_interval_hours`) |
| Yangi versiya topilsa | Windows bildirishnomasi: *"Yangi versiya 0.2.4 mavjud. Yangilash uchun bosing."* |
| | Tray menyusida yangilanish belgisi paydo bo'ladi |
| | Ilova oynasida ko'k panel: versiya, hajm va `--notes` matni + **"Yangilash"** tugmasi |
| Foydalanuvchi tugmani bosadi | `.exe` yuklanadi, progress chizig'i to'ladi |
| | **SHA256 tekshiriladi** — mos kelmasa fayl ishga tushirilmaydi |
| | `Setup.exe /S` jim rejimda ishlaydi: ilovani to'xtatadi, fayllarni almashtiradi, qayta ishga tushiradi |
| Qayta ishga tushgach | *"0.2.4 versiyasiga yangilandi"* bildirishnomasi |

Foydalanuvchi kutmasdan ham tekshirishi mumkin: **tray → "Yangilanishni tekshirish"**.

### IT ommaviy tarqatishi

So'ramasdan o'rnatish kerak bo'lsa, `%APPDATA%\Venera\config.yaml` da:

```yaml
update:
  auto_install: true
```

Yoki umuman kutmasdan, skript orqali: `Venera.exe --update`.

---

## Tekshirish

```bash
# Manifest yangi versiyani e'lon qilyaptimi
curl -sS https://llm.brb-tech.uz/download/version.json

# Fayl joyidami va to'liqmi (son manifestdagi `setup.size` bilan bir xil bo'lsin)
curl -sS -o /dev/null -w '%{http_code} %{size_download}\n' \
    https://llm.brb-tech.uz/download/Venera-AI-Assistant-Setup-0.2.4.exe
```

Kompyuterda: `Venera.exe --check` — `Yangilanish` bo'limida manba va natija
ko'rinadi.

## Orqaga qaytarish

Yangi versiya muammoli chiqsa, `version.json` ni eski versiyaga qaytaring:

```bash
cp release/version-0.2.3.json ~/.local/share/venera/downloads/version.json
```

Auto-update faqat **yangi** versiyani taklif qiladi, shuning uchun bu yangi
yangilanishlarni to'xtatadi. Allaqachon yangilanganlarni orqaga qaytarish uchun
eski `Setup.exe` ni qo'lda ishga tushirish kerak.

---

## Nosozliklar

| Belgi | Sabab |
|---|---|
| Hech kimda bildirishnoma chiqmaydi | Versiya oshmagan, yoki `version.json` hali eski. `curl` bilan tekshiring. |
| "Nazorat yig'indisi mos kelmadi" | `.exe` `version.json` dan keyin yuklangan, yoki fayl yarim ko'chgan. Qayta nusxalang: avval `.exe`. |
| "O'rnatuvchi ishga tushmadi" | Antivirus bloklagan yoki foydalanuvchida huquq yo'q. `%LOCALAPPDATA%\Venera\logs\assistant.log` ga qarang. |
| Yangilandi, lekin eski nom ko'rinadi | `.exe` `sync_version.py` dan keyin qayta yig'ilmagan. |
| `--check` da "manba (ko'rsatilmagan)" | `-UpdateUrl` berilmasdan yig'ilgan. Qayta yig'ing yoki `Venera.exe --set-update-url "..."` ni ishga tushiring. |
