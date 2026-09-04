# Venera AI Assistant

Windows uchun doim fonda ishlaydigan ovozli desktop yordamchi.
Kompyuter yonganda o'zi ishga tushadi, tray ikonkasida turadi, buyruqni bajaradi
va ovoz bilan javob beradi.

**Hozirgi bosqich: Step 1** — serversiz ishlaydigan to'liq desktop ilova.
On-prem STT, LLM va TTS keyingi steplarda ulanadi (pastga qarang).

---

## Tez boshlash

Windows'da, PowerShell'da:

```powershell
cd C:\venera
powershell -ExecutionPolicy Bypass -File packaging\build.ps1      # .exe yig'ish
powershell -ExecutionPolicy Bypass -File packaging\install.ps1    # o'rnatish + avtostart
```

O'rnatilgandan keyin:

| Nima | Qayerda |
|---|---|
| **O'rnatiladigan dastur** | `%LOCALAPPDATA%\Programs\Venera\Venera.exe` |
| Yig'ilgan fayl (build natijasi) | `dist\Venera\Venera.exe` |
| Sozlamalar | `%APPDATA%\Venera\config.yaml` |
| Dasturlar ro'yxati | `%APPDATA%\Venera\apps.yaml` |
| Loglar | `%LOCALAPPDATA%\Venera\logs\assistant.log` |
| Avtostart | Task Scheduler → `Venera\AI Assistant` |

O'chirish: `powershell -ExecutionPolicy Bypass -File packaging\uninstall.ps1`

Admin huquqi kerak emas.

---

## Boshqa kompyuterlarga tarqatish

Bitta fayl yasash:

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build_setup.ps1
```

Natija: **`dist\Venera-AI-Assistant-Setup.exe`** (~43 MB).

Shu **bitta faylni** boshqa kompyuterga ko'chiring va ikki marta bosing.
Ilova butunlay shu exe ichida, boshqa hech narsa kerak emas.

| | |
|---|---|
| Talab | Windows 10/11, 64-bit |
| Python kerakmi | Yo'q |
| Administrator kerakmi | Yo'q |
| O'rnatiladi | `%LOCALAPPDATA%\Programs\Venera\` |

O'rnatuvchi oynada avtostart va ish stoli yorlig'ini tanlash imkonini beradi,
so'ng ilovani ishga tushiradi.

IT bo'limi uchun ommaviy tarqatish (oynasiz):

```
Venera-AI-Assistant-Setup.exe /S
Venera-AI-Assistant-Setup.exe /S /NOAUTOSTART /NOLAUNCH
Venera-AI-Assistant-Setup.exe /S /DESKTOP
```

O'chirish: **Parametrlar → Ilovalar → Venera AI Assistant → O'chirish**.
Yoki buyruq satridan:

```
"%LOCALAPPDATA%\Programs\Venera\Venera.exe" --uninstall --silent
```

Sozlamalarni saqlab qolish uchun `--keep-settings` qo'shing.

> Fayl raqamli imzolanmagani uchun SmartScreen ogohlantirishi mumkin
> ("More info" → "Run anyway"). Buni yo'qotish uchun bankning code-signing
> sertifikati bilan imzolash kerak.

---

## Yangilanish tizimi

O'zgarish kiritganingizda o'rnatilgan ilovalar yangi versiyani o'zi topadi va
foydalanuvchi bir bosishda yangilaydi.

### Bir marta sozlash

Yangi versiyalar qo'yiladigan joyni tanlang. Uch xil variant ishlaydi:

| Variant | `update.url` namunasi | Qachon qulay |
|---|---|---|
| Tarmoq papkasi (SMB) | `\\fileserver\venera\assistant\version.json` | Bankda eng oson: yangi server kerak emas, kirish AD orqali |
| Ichki HTTP server | `http://10.10.50.9:8000/updates/version.json` | VPN orqali ishlaydigan uzoq foydalanuvchilar uchun |
| Lokal papka | `C:\updates\venera\version.json` | Faqat sinov uchun |

Manzilni har bir kompyuterga qo'lda yozish shart emas, o'rnatishda beriladi:

```
Venera-AI-Assistant-Setup.exe /S /URL=\\fileserver\venera\assistant\version.json
```

Allaqachon o'rnatilgan kompyuterda:

```
"%LOCALAPPDATA%\Programs\Venera\Venera.exe" --set-update-url "\\fileserver\venera\assistant\version.json"
```

### Allaqachon o'rnatilgan kompyuterlarga birinchi marta yetkazish

0.1.0 versiyasida yangilanish tizimi umuman yo'q edi, shuning uchun u kompyuterlar
o'zini yangilay olmaydi. **Bir marta** qo'lda yetkazish kerak, keyin hammasi avtomatik.

Uch yo'l bor, kompyuterlar soniga qarab tanlang:

**1. Bir necha kompyuter: faylni yuborish.**
`Venera-AI-Assistant-Setup-<versiya>.exe` ni pochta yoki Telegram orqali yuboring.
Foydalanuvchi ikki marta bosadi. Eski versiya ustiga o'rnatiladi, sozlamalar saqlanadi.
Yangilanish manzili o'rnatuvchi ichiga yozilgan, shuning uchun keyingi versiyalar
o'zi topiladi.

**2. Ko'p kompyuter: domen siyosati (GPO) orqali logon skripti.** Eng ishonchli yo'l.

```
User Configuration > Policies > Windows Settings > Scripts > Logon
  Script Name:       powershell.exe
  Script Parameters: -ExecutionPolicy Bypass -WindowStyle Hidden -File
                     \\fileserver\venera\assistant\logon_update.ps1
                     -Source \\fileserver\venera\assistant -InstallIfMissing -Quiet
```

`logon_update.ps1` `publish.ps1` tomonidan tarqatish joyiga o'zi qo'yiladi. U:
o'rnatilgan versiyani nashr qilingani bilan solishtiradi, eskiroq bo'lsa jim o'rnatadi,
SHA256 ni tekshiradi, ishni `%LOCALAPPDATA%\Venera\logs\deploy.log` ga yozadi.
Versiyalar teng bo'lsa 0.2 soniyada chiqadi, shuning uchun logonni sekinlashtirmaydi.

**3. Tarmoq papkasiga yorliq.** Eng oddiy: umumiy papkaga
`Venera-AI-Assistant-Setup-<versiya>.exe` yorlig'ini qo'ying va xodimlarga
"bir marta bosing" deb ayting.

> **Nima uchun uzoqdan majburlab o'rnatib bo'lmaydi.** Ilova har bir foydalanuvchi
> profiliga o'rnatiladi (`%LOCALAPPDATA%`, `HKCU`), administrator huquqi talab
> qilmaydi. Shuning uchun PsExec yoki PowerShell remoting bilan SYSTEM nomidan
> ishga tushirish noto'g'ri profilga o'rnatadi. Skript foydalanuvchi nomidan
> ishlashi shart - logon skripti yoki foydalanuvchi kontekstidagi vazifa.

### Har safar yangi versiya chiqarganda

1. Kodni o'zgartiring.
2. Versiyani ko'taring:

   ```powershell
   python tools\sync_version.py 0.3.0
   ```

3. Nashr qiling:

   ```powershell
   powershell -ExecutionPolicy Bypass -File packaging\publish.ps1 `
       -Target "\\fileserver\venera\assistant" -Notes "STT serveri ulandi"
   ```

Skript o'zi test o'tkazadi, `Setup.exe` yig'adi, SHA256 hisoblaydi, `version.json`
yozadi va uchalasini (`Setup.exe`, `version.json`, `logon_update.ps1`) tarqatish
joyiga qo'yadi.

Yangilanish manzili o'rnatuvchi **ichiga yoziladi**. Shuning uchun shu fayldan
o'rnatilgan har bir kompyuter keyingi versiyalarni o'zi topadi, foydalanuvchi
ham, IT ham hech narsa sozlamaydi. Boshqa manzil kerak bo'lsa:
`publish.ps1 ... -UpdateUrl "http://10.10.50.9:8000/updates/version.json"`.

### Foydalanuvchi tomonida nima bo'ladi

Ilova ishga tushgandan 90 soniya keyin va har 6 soatda `version.json` ni o'qiydi.
Yangi versiya bo'lsa tray'da xabar chiqadi, oynada esa panel paydo bo'ladi:
"Yangi versiya 0.3.0 mavjud" va **Yangilash** tugmasi. Bosilganda fayl yuklanadi,
SHA256 tekshiriladi, o'rnatuvchi jim rejimda ishlaydi va ilova qayta ishga tushadi.
Keyingi ishga tushishda "Ilova 0.3.0 versiyasiga yangilandi" deb bildiradi.

Tray menyusida **Yangilanishni tekshirish** bandi ham bor.

### Muhim jihatlar

- **SHA256 majburiy tekshiriladi.** Fayl tarqatish joyida o'zgartirilgan bo'lsa
  o'rnatilmaydi. Sinovda buni ataylab tekshirdim: buzilgan fayl rad etildi va
  versiya o'zgarmadi.
- **Eski config buzilmaydi.** Yangi versiyada yangi sozlama paydo bo'lsa, ilova uni
  foydalanuvchi `config.yaml` iga izohlari bilan qo'shadi va eski qiymatlarga tegmaydi.
  Zaxira nusxa `config.yaml.bak` da qoladi.
- **Korporativ proksi chetlab o'tiladi** (`update.no_proxy: true`), chunki
  `10.10.50.x` ichki manzillar proksi orqali ketmasligi kerak.
- **Majburiy yangilanish**: `publish.ps1 -Mandatory` bayrog'i bilan.
- **Eski versiyadan sakrash**: `-MinVersion 0.5.0` bersangiz, undan eski
  o'rnatmalar avtomatik yangilanmaydi va qo'lda o'rnatish talab qilinadi.
- **IT ommaviy yangilashi**: `Venera.exe --update` buyrug'i skript orqali
  ishlaydi. `update.auto_install: true` qo'yilsa so'ramasdan yangilaydi.

### Alternativ: ZIP arxiv

Agar exe o'rniga papka kerak bo'lsa (masalan tarmoq diskiga qo'yish uchun):

```powershell
powershell -ExecutionPolicy Bypass -File packaging\package.ps1
```

Natija: `dist\Venera-AI-Assistant-0.1.0.zip` — ichida ilova, `install.ps1`
va `uninstall.ps1`. Chiqarilgandan keyin `install.ps1` ishga tushiriladi.

---

## Foydalanish

1. Tray ikonkasini (soat yonida, ko'k "B") bosing — holat oynasi ochiladi.
2. Yoki uyg'otish klavishasini bosing: **Ctrl+Alt+Space**.
   Bu kombinatsiya boshqa dastur tomonidan band bo'lsa, ilova avtomatik
   zaxiraga o'tadi (Ctrl+Alt+B, Ctrl+Shift+Space, Ctrl+Alt+F9...) va haqiqiy
   klavishani oynada hamda tray menyusida ko'rsatadi.
3. Buyruqni yozing va Enter bosing.

### Ishlaydigan buyruqlar

| Buyruq | Natija |
|---|---|
| `chromeni och`, `xromni ishga tushir`, `telegramni och` | dastur ochiladi |
| `venera.uz saytini och` | brauzerda sayt ochiladi |
| `googlda valyuta kursi qidir` | qidiruv natijasi ochiladi |
| `ovozni qirq besh foiz`, `ovozni 30 ga qo'y` | tizim ovozi o'rnatiladi |
| `ovozni ko'tar`, `tovushni pasaytir` | ovoz 10 foizga o'zgaradi |
| `ovozni o'chir`, `ovozni yoq` | mute / unmute |
| `ekranni qulfla` | Windows qulflanadi (javob oldin aytiladi) |
| `skrinshot ol` | `Pictures\Venera` ga saqlanadi |
| `soat necha`, `bugun qaysi kun` | vaqt / sana aytiladi |
| `nima qila olasan` | imkoniyatlar ro'yxati |
| `to'xta`, `bekor qil` | joriy buyruq bekor qilinadi |

Dastur nomlari fonetik yoziladi ham: `krom`, `eksel`, `autluk`, `kalkulator`.
Yangi dastur qo'shish uchun `%APPDATA%\Venera\apps.yaml` ni tahrirlang va tray
menyusidan **Sozlamalarni qayta yuklash** ni bosing.

---

## Step 1 nima qiladi va nima qilmaydi

**Qiladi** — hech qanday serversiz:
tray ilova, logonda avtostart, global hotkey, haqiqiy mikrofon oqimi
(16 kHz mono, jonli daraja ko'rsatkichi), o'zbekcha buyruqlarni qoidalar bilan
tushunish, haqiqiy Windows harakatlari, Windows SAPI bilan ovozli javob,
YAML sozlamalar, aylanuvchi loglar, bitta nusxa kafolati, ekran qulflanganda pauza,
mikrofon uzilganda avtomatik tiklanish.

**Qilmaydi** — keyingi steplarda:

| Step | Nima qo'shiladi | Qaysi fayl | config o'zgarishi |
|---|---|---|---|
| 2 | On-prem STT (ovoz → matn) | `engines/stt_onprem.py` | `engines.stt: onprem` |
| 3 | On-prem LLM (erkin buyruqlar) | `engines/llm_onprem.py` | `engines.llm: onprem` |
| 4 | On-prem TTS (o'zbek ovozi) | `engines/tts_onprem.py` | `engines.tts: onprem` |
| 5 | Wake word "Venera AI Assistant" | `engines/activator_wakeword.py` | `engines.activator: wakeword` |

Har bir stepda **bitta yangi fayl** qo'shiladi va config'da **bitta qator** o'zgaradi.
Orchestrator, harakatlar, NLU, UI, tray, avtostart va packaging tegilmaydi — chunki
hammasi `engines/base.py` dagi interfeyslar orqali ishlaydi.

> SAPI'da o'zbek ovozi yo'q, faqat inglizcha. Step 1 da javob inglizcha talaffuzda
> eshitiladi — bu kutilgan holat, Step 4 buni to'g'irlaydi.

---

## Ishlab chiqish

Loyiha WSL papkasida turadi, lekin **Windows'da ishga tushiriladi** (WSL'da audio
qurilma yo'q). Kodni Windows diskiga ko'chirish:

```powershell
powershell -ExecutionPolicy Bypass -File tools\sync_to_windows.ps1
```

Keyin `C:\venera` da:

```powershell
.venv\Scripts\python.exe -m venera --check      # diagnostika
.venv\Scripts\python.exe -m venera --console    # loglar konsolda
.venv\Scripts\python.exe tools\list_devices.py              # mikrofonlar ro'yxati
.venv\Scripts\python.exe tools\mic_test.py 3                # mikrofonni sinash
.venv\Scripts\python.exe -m pytest tests -q                 # testlar
```

Testlar audio qurilmasiz ham ishlaydi, shuning uchun WSL'da ham o'tadi:

```bash
PYTHONPATH=src python3 -m pytest tests -q
```

### Buyruq satri

```
--check               sozlamalar, mikrofonlar, engine'lar holati
--console             loglarni konsolga ham chiqaradi
--no-tray             tray ikonkasisiz
--no-window           holat oynasisiz
--config PATH         boshqa config.yaml
--install-autostart   avtostartni yoqadi
--remove-autostart    avtostartni o'chiradi
```

---

## Tuzilma

```
src/venera/
  app.py            hamma komponent shu yerda bog'lanadi
  config.py         YAML sozlamalar (noto'g'ri qiymat ilovani yiqitmaydi)
  core/             holat mashinasi va orchestrator
  audio/            mikrofon, WAV, ijro, signal tovushlari
  engines/          ALMASHTIRILADIGAN qism: STT / LLM / TTS / aktivator
  nlu/              o'zbekcha normalizatsiya, sonlar, intent qoidalari
  actions/          intent -> haqiqiy amal
  osadapter/        Windows'ga xos hamma narsa (macOS shu faylni almashtiradi)
  ui/               tray ikonkasi va holat oynasi
```

Thread'lar: asosiy (tray) · core (asyncio) · hotkey (Win32 xabar sikli) ·
audio-callback (PortAudio) · ui-window (tkinter). Ular orasida faqat navbat
orqali gaplashiladi — to'g'ridan-to'g'ri chaqiruv yo'q.

---

## Muhim texnik qarorlar

- **Task Scheduler, Windows Service emas.** Service Session 0 da ishlaydi:
  u yerda mikrofon ham, tray ham, ish stoli ham yo'q.
  Vazifada `ExecutionTimeLimit=PT0S` bo'lishi shart — default 72 soat, aks holda
  ilova uch kundan keyin o'ldiriladi.
- **RegisterHotKey, `keyboard` paketi emas.** Past darajali klaviatura hook'i
  antivirus va DLP tizimlarida keylogger sifatida belgilanadi — bankda bu muammo.
- **WASAPI, exclusive mode'siz.** Exclusive mode mikrofonni Teams'dan tortib oladi.
  MME qurilma nomlarini 31 belgida kesadi, shuning uchun WASAPI afzal ko'riladi.
- **Javob matnlari shablondan, LLM'dan emas** (`resources/phrases.uz.yaml`).
  Shuning uchun o'zbekcha doim to'g'ri va Step 4 da bu iboralarni oldindan
  sintez qilib keshlash mumkin.
- **PyInstaller kirish nuqtasi `packaging/common/entrypoint.py`**, paket ichidagi
  `__main__.py` emas — aks holda nisbiy importlar buziladi.
- **onedir, onefile emas.** Defender onefile'ni ko'proq bloklaydi va u har safar
  `%TEMP%` ga ochiladi.
