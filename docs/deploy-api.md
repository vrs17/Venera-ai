# Venera API — tarqatish

Backend (`apps/api`) host'da, `apps/api/venv` ichidagi uvicorn bilan ishlaydi,
systemd `--user` xizmati sifatida. Frontend (`apps/web`) esa root'siz podman
konteynerida qoladi.

```
brauzer ──► nginx konteyner (:5173) ──┬─► /          SPA (Vue)
                                      └─► /api/*     uvicorn (127.0.0.1:8000)
```

API porti **tashqariga ochilmagan** — unga faqat nginx murojaat qiladi.

> **Nega backend konteynerda emas.** Kod tez-tez o'zgaradi va har o'zgarishda
> image qayta yig'ish ortiqcha; `git pull` + `restart` yetarli. Frontend esa
> konteynerda qoladi - u yig'ilgan statik fayllarni beradi xolos va nginx
> sozlamasi bilan birga kelishi qulay.

---

## 1. Bir marta: venv

```bash
cd ~/Venera/apps/api
python3 -m venv venv

# Ubuntu ning venv'i eski setuptools bilan keladi (59.6), u esa pyproject.toml
# dagi [project] blokini TUSHUNMAYDI - PEP 621 uchun 61+ kerak. Busiz keyingi
# qator "Multiple top-level packages discovered" deb yiqiladi.
venv/bin/pip install -U pip setuptools

venv/bin/pip install -e ".[dev]"
```

> `python3 -m venv` ishlashi uchun `python3.10-venv` paketi kerak
> (`sudo apt install python3.10-venv`). Bu host'da o'rnatilgan.

## 2. Bir marta: sozlama fayllari

```bash
cd ~/Venera/apps/api

cp .env.example .env
cp config/users.example.yaml config/users.yaml

# SECRET_KEY ni ALBATTA o'zgartiring (kamida 32 belgi):
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
# chiqqan qiymatni .env dagi SECRET_KEY= ga qo'ying
```

Ikkalasi ham git'ga tushmaydi. Unutilsa `/api/health` `degraded` qaytaradi
va sababini yozadi.

**Parollarni ham ALBATTA almashtiring.** `users.example.yaml` git'da turadi,
ya'ni undagi parolni repo'ni ko'ra oladigan har kim biladi - nusxani
o'zgartirmasdan qoldirish parolni e'lon qilish bilan barobar:

```bash
venv/bin/python -m app.tools.hash_password    # har bir hisob uchun
# chiqqan `password_hash` ni config/users.yaml ga qo'ying
chmod 600 config/users.yaml .env
```

`/api/health` namuna xeshlari qolganini aniqlaydi va qaysi hisob ekanini
aytadi.

## 3. Bir marta: Swagger fayllari


```bash
cd ~/Venera/apps/api && mkdir -p app/static
V=5.17.14
curl -fsSL -o app/static/swagger-ui-bundle.js \
  "https://cdn.jsdelivr.net/npm/swagger-ui-dist@$V/swagger-ui-bundle.js"
curl -fsSL -o app/static/swagger-ui.css \
  "https://cdn.jsdelivr.net/npm/swagger-ui-dist@$V/swagger-ui.css"
```

`app/static/swagger-init.js` git'da keladi - uni yuklab olish shart emas.

Bu qadam **tashlab ketilsa ham server ko'tariladi**, lekin `/api/docs`
**503** va yetishmayotgan fayllar ro'yxatini qaytaradi. CDN ga qaytish
ataylab olib tashlangan: CSP tashqi manbani baribir bloklaydi, ya'ni
foydalanuvchi sababsiz oq ekran ko'rardi.

## 4. Xizmatni o'rnatish

```bash
mkdir -p ~/.config/systemd/user
cp ~/Venera/apps/api/deploy/venera-api.service \
   ~/.config/systemd/user/venera-api.service

systemctl --user daemon-reload
systemctl --user enable --now venera-api.service

# Sessiyadan chiqqanda ham ishlab tursin.
# BUSIZ logout qilganingizda xizmat O'CHADI.
loginctl enable-linger $USER
```

## 5. Frontend

```bash
cp ~/Venera/apps/web/deploy/venera-frontend.user.service \
   ~/.config/systemd/user/venera-frontend.service
systemctl --user daemon-reload
systemctl --user restart venera-frontend.service
```

---

## STT (ovozni matnga o'girish)

Backend brauzerdan kelgan audioni STT Router'ga (`10.10.50.4:8006`) uzatadi.
Sozlamalar `.env` da, hammasi ixtiyoriy:

| O'zgaruvchi | Default | Izoh |
|---|---|---|
| `STT_BASE_URL` | `http://10.10.50.4:8006` | Router manzili (ichki tarmoq) |
| `STT_TIMEOUT` | `35` | BIR urinish uchun, soniya |
| `STT_ATTEMPTS` | `3` | FAQAT 503 (navbat to'la) da qayta urinish, jitter bilan. 502/504 qayta urinilmaydi |
| `STT_DEADLINE` | `100` | butun so'rov uchun devor-soat. nginx 120 s dan KAM bo'lishi shart - undan keyin javob brauzerga yetmaydi |
| `STT_MAX_CONCURRENT` | `4` | shu ilovaning Router'dagi ulushi |
| `STT_MAX_UPLOAD_MB` | `10` | brauzerdan qabul qilinadigan maksimal audio |

**`STT_MAX_CONCURRENT` ni oshirishdan oldin.** Router BUTUN park uchun ~10
parallel so'rov ko'taradi (o'lchangan: 25 da 503 lar boshlanadi). Web ilova,
desktop park va boshqa klientlar shu 10 ni bo'lishadi. Chegaradan oshgan
so'rov Router'ga bormasdan 503 oladi - frontend "band, keyinroq" deb
ko'rsatadi.

**Ovoz faqat UI tilida.** Foydalanuvchi tizimda qaysi tilni tanlagan bo'lsa
(uz / uz-Cyrl / ru / en), STT ham shu tilda. Router hujjati
`language_mismatch` da `detected_language` bilan qayta yuborishni tavsiya
qiladi - bu ATAYLAB qilinmaydi (mahsulot qarori: tizim tilni o'zi
almashtirmaydi). Mismatch faqat log'ga tushadi. `zh` tizimda yo'q, 400.

`low_confidence` - matn chatga AVTOMATIK yuborilmaydi; panel foydalanuvchiga
ko'rsatib, tasdiq so'raydi (hujjat: bunday matnda WER 60-70%).

**Audio formati.** Router'ning `uz` backend'i faqat `.wav .ogg .opus .mp3
.flac` qabul qiladi, brauzer (Chrome/Edge) esa faqat WebM yozadi. Shuning
uchun brauzer yozuvni O'ZI 16 kHz mono WAV ga aylantirib yuboradi
(`src/api/wav.ts`) - 30 s ≈ 960 KB. nginx `client_max_body_size 12m`,
API 10 MB. Backend fayl nomini klientdan olmaydi - kontent turidan yasaydi.

Tekshirish:

```bash
curl -s http://10.10.50.4:8006/health | python3 -m json.tool | head    # Router va backend'lar
journalctl --user -u venera-api.service -o cat | grep 'STT '           # qaysi backend ishlagani
```

## TTS (matnni ovozga o'girish)

Backend matnni TTS serverining **`/api/v1/tts/stream`** iga yuboradi va
kelgan baytlarni o'sha zahoti brauzerga uzatadi. Javob - `audio/L16` xom PCM
(sarlavhasiz, 16-bit LE mono, 8000 Hz), JSON emas.

**`/tts/generate` ISHLATILMAYDI.** U butun xabar tayyor bo'lgunicha jim
turadi, faylni serverda qoldiradi (`{user_id}__{uuid}.wav`, hech qachon
o'chirilmaydi) va uni ikkinchi so'rov bilan olib kelish kerak. Jonli
o'lchov (351 belgi, ~24 s audio):

| | Foydalanuvchi qancha kutadi |
|---|---|
| `/generate` | **2.93 s** jim |
| `/stream` | **1.11 s** da birinchi ovoz |

`/stream` da `user_id` maydoni umuman yo'q - ya'ni bizning foydalanuvchimiz
haqida TTS serverida hech narsa qolmaydi.

| O'zgaruvchi | Default | Izoh |
|---|---|---|
| `TTS_BASE_URL` | `http://10.10.50.4:8200` | TTS serveri (ichki tarmoq) |
| `TTS_CLIENT_ID` | `frontend` | serverdagi `AUTH_CLIENTS` dan |
| `TTS_CLIENT_SECRET` | *(bo'sh)* | **sir.** Bo'sh bo'lsa ovoz o'chiq (501), qolgan hamma narsa ishlaydi |
| `TTS_TIMEOUT` | `60` | BO'LAKLAR ORASIDAGI kutish, soniya - oqim uzunligi emas |
| `TTS_MAX_CONCURRENT` | `2` | bir vaqtda nechta sintez |
| `TTS_VOICE` | `uz_female_calm` | yoki `uz_male_news` (erkak) |
| `TTS_SPEED` | *(bo'sh -> 0.95)* | rasmiy 0.90, yangiliklar 1.0 |
| `TTS_CHUNK_SEC` | `1.5` | bo'lakning maqsadli davomiyligi (server 0.5-10 talab qiladi) |
| `TTS_MAX_CHARS` | `600` | undan uzun matn so'z chegarasida qisqartiriladi |

**`TTS_CLIENT_SECRET` ga FAQAT sirning o'zi yoziladi.** TTS serverining
`AUTH_CLIENTS` o'zgaruvchisi yozuvlarni `client_id:sir` ko'rinishida saqlaydi.
Butun yozuvni ko'chirib qo'yish oson va oqibati chalg'ituvchi: server
`401 client_id yoki client_secret noto'g'ri` qaytaradi, bizning tomonda esa
hammasi joyida ko'rinadi. `:` dan KEYINGI qism olinadi:

```bash
# AUTH_CLIENTS=frontend:AbCd1234...,user:XyZ...
#                       ^^^^^^^^^^^ faqat shu qism
grep -c ':' <<< "$SIR"    # 0 bo'lishi kerak
```

Tekshirish (sirni ochmasdan): serverga token so'rovi 200 va `scope: tts`
qaytarsa, qiymat to'g'ri.

**Sir brauzerga hech qachon bermaydi.** Frontend `/api/v1/tts/speak` ga
matn yuboradi, tokenni backend oladi va keshlaydi (24 soat). Agar frontend
o'zi token olsa, `client_secret` JS bundle'ida va har bir tarmoq log'ida
ochiq turardi.

**Hozircha faqat o'zbek (lotin).** `uz-Cyrl` ATAYLAB yo'q - kirill matn lotin
o'quvchiga berilsa harf-baharf noto'g'ri o'qiladi, translit esa alohida ish.
`ru`/`en` uchun bu serverda ovoz umuman yo'q. Boshqa til so'ralsa 400, va
frontend bunday tilda tugmani umuman ko'rsatmaydi (`TTS_LOCALES`).

**Birinchi bosqich - aks-sado.** Ovoz paneli STT tanigan matnning O'ZINI
o'qib beradi (suhbat javobini emas). Bu ikkala zanjirni bitta gap bilan
tekshirish uchun; keyingi bosqichda o'qiladigan matn LLM javobiga almashadi.

**Raqamlar - eng nozik joy.** Serverning `normalize_numbers` i ba'zi
naqshlarda YIQILADI (jonli tekshirilgan):

| Kirish | Serverda | Bizda |
|---|---|---|
| `8600123456789012` (16+ xona: karta, hisob) | HTTP 500 | oldindan tanib, normalizatsiyasiz yuboriladi |
| `1.000.000`, `10.10.50.4`, `v1.2.3` | HTTP 422 | shu kabi |
| `2450000 som` | `ikki million tort yuz ellik ming som` ✅ | tegilmaydi |

Ya'ni `app/services/tts.py` dagi `risky_for_normalizer()` shu ikki naqshni
qidiradi va topsa normalizatsiyani o'chiradi - xato javobdan ko'ra raqamni
model o'zicha o'qigani afzal.

**Sana, vaqt, qisqartma - normalizatorga BERILMAYDI.** Ular yomon o'qiladi
(jonli, TTS ovozi STT bilan qayta matnga o'girilib tekshirilgan), shuning
uchun `app/services/speech_text.py` ularni oldinroq o'zbekcha so'z bilan
yozadi. Ekrandagi javob o'zgarmaydi - faqat TTS'ga ketadigan nusxa:

| Matnda | Normalizator bilan eshitilardi | Endi |
|---|---|---|
| `09.09.2025dan` | HTTP 422 - javob OVOZSIZ | "ikki ming yigirma beshinchi yil to'qqizinchi sentabrdan" |
| `2026-10-21` | "ikki ming yigirma olti o'n yigirma bir" | "yigirma birinchi oktabr" (joriy yil aytilmaydi) |
| `25.09.2026-30.09.2026` | "... yil, yil o'ttizinchi ..." | "yigirma beshinchi sentabrdan o'ttizinchi sentabrgacha" |
| `09:00-18:00` | "to'qqiz nol o'n sakkiz nol" | "soat to'qqizdan o'n sakkizgacha" |
| `“BRB-TECH” MCHJ` | "b chepche" | "BRB-TECH mas'uliyati cheklangan jamiyati" |

Normalizator baribir yangi naqshda 422 bersa, matn bir marta
normalizatsiyasiz qayta yuboriladi va jurnalga WARNING yoziladi: javob jim
qolmaydi, naqsh esa `speech_text.py` ga qo'shilishi kerak.

**Nega `l16`, `wav` emas.** Oqim boshida umumiy uzunlik hali noma'lum,
shuning uchun server `format=wav` da WAV sarlavhasidagi ikkala hajm maydoniga
`0xFFFFFFFF` yozadi: audio to'g'ri, lekin pleyerlar davomiylikni **74 soat**
deb ko'rsatadi. Brauzer PCM ni `<audio>` bilan ocholmaydi, lekin u baribir
ocholmasdi: `<audio src>` GET yuboradi va `Authorization` sarlavhasini
tashiy olmaydi, MediaSource esa PCM/WAV ni umuman qabul qilmaydi (faqat
segmentlangan mp4/webm). Shuning uchun frontend PCM ni Web Audio bilan
bo'lak-bo'lak rejalashtiradi (`api/tts.api.ts`).

**`TTS_CHUNK_SEC` ni oshirmang.** Ta'siri matnga bog'liq: birinchi jumla uzun
bo'lsa, 3.0 da birinchi bo'lak butun jumlani qamrab oladi va TTFB ~5x
sekinlashadi; 10.0 da streaming umuman yo'qoladi.

**nginx BUFERLASHI O'CHIQ bo'lishi SHART.** nginx sukut bo'yicha butun
javobni yig'ib, keyin bir yo'la beradi - bu streaming'ni butunlay bekor
qiladi. `deploy/nginx.container.conf` da shu yo'l uchun alohida `location`
bor (`proxy_buffering off`). Tekshirish: javobda `Transfer-Encoding: chunked`
bo'lishi va `Content-Length` BO'LMASLIGI kerak.

```bash
curl -s -N -X POST http://127.0.0.1:5173/api/v1/tts/speak \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"text":"Salom, bu sinov.","language":"uz"}' \
  -o /dev/null -w 'birinchi bayt %{time_starttransfer}s | jami %{time_total}s\n'
# birinchi bayt ~1.1 s bo'lishi kerak. Agar u jami vaqtga teng bo'lsa -
# kimdir buferlayapti.
```

**Timeout byudjeti.** `TTS_TIMEOUT` (60 s) endi BO'LAKLAR ORASIDAGI kutish -
oqim uzunligi emas. Bo'laklar odatda 1-2 s oralab keladi, ya'ni chegara
faqat server butunlay jim qolganda ishlaydi. Umumiy oqim audio davomiyligiga
bog'liq va nginx `proxy_read_timeout` ham bo'laklar orasida hisoblanadi.

**Server bitta GPU'da KETMA-KET ishlaydi** va 429 qaytarmaydi - navbat
cheksiz o'sadi. Shuning uchun chegara `TTS_MAX_CONCURRENT` bilan bu tomonda
qo'yiladi: oshsa darhol 503 "band".

**nginx CSP.** `media-src 'self' blob:` MAJBURIY. WAV `URL.createObjectURL()`
orqali `<audio>` ga beriladi, `default-src 'self'` esa `blob:` ni qamramaydi.
Usiz ovoz FAQAT ishlab chiqarishda, jimgina bloklanadi (Vite dev-serverda CSP
yo'q, ya'ni lokalda ishlaydigandek ko'rinadi).

Tekshirish:

```bash
curl -s http://10.10.50.4:8200/health | python3 -m json.tool      # model, GPU, ovozlar
journalctl --user -u venera-api.service -o cat | grep 'TTS'       # sintez va token log'i
```

## Uyg'otish so'zi: "Salom Venera"

Suhbat sahifasi mikrofonni ochiq tutadi va "Salom Venera" eshitilganda ovoz
paneli o'zi ochilib, salomlashib, tinglashni boshlaydi. **Sukut bo'yicha
YOQIQ** - tizimga kirgan zahoti ishlaydi, hech narsa bosish shart emas.

Yon paneldagi tugma qoladi (mikrofonning O'CHIRISH tugmasi har doim bo'lishi
kerak), lekin faqat aniq `'0'` uni o'chiradi: yangi login, yangi brauzer,
tozalangan xotira - hammasi tinglagan holda ochiladi. Mikrofon ochiqligi
yon paneldagi pulsatsiyalanuvchi nuqta bilan ko'rinib turadi.

Brauzer ruxsatni rad etsa, sozlama O'CHIRILMAYDI - faqat shu sessiyada
qayta urinilmaydi. Aks holda bir marta tasodifan "Block" bosilsa, funksiya
sayt sozlamalarida ruxsat tiklangandan keyin ham abadiy o'chiq qolardi.

**Panel HAR DOIM tanishtirish bilan ochiladi** - uyg'otish so'zi bilan ham,
tugma bilan ham. Ovoz paneli ochilib jim turishi buzuq ko'rinadi va odam
gapirish kerakmi-yo'qmi deb taxmin qilishga majbur bo'ladi; kim javob
berayotganini eshitish buni hal qiladi. Yozuv tayyor bo'lgani uchun ikkala
yo'lda ham kutish yo'q.

**Salomlashish OLDINDAN tayyorlangan.** Matn o'zgarmas, sintez esa ~2 s
oladi va bitta GPU navbatida turadi - "Salom Venera" degan odam shuncha
kutmasligi kerak. Fayl bir marta yasaladi:

```bash
cd ~/Venera/apps/api && venv/bin/python tools/make_greeting.py
# -> apps/web/src/assets/greeting-uz.wav
```

Matn (`voiceGreeting`) o'zgarsa shu buyruq qayta bajariladi - ekrandagi va
yangraydigan matn bir xil bo'lishi kerak. Fayl topilmasa jonli sintezga
tushadi: yo'qolgan resurs kechikish beradi, salomlashishni yo'qotmaydi.

**nginx MIME tuzog'i.** nginx'ning standart `mime.types` ida `.wav` UMUMAN
yo'q (u yerdagi yagona "wav" - `x-shockwave-flash`), ya'ni audio
`application/octet-stream` bo'lib ketardi. `X-Content-Type-Options: nosniff`
bilan birga bu `<audio>` ni ijrodan bosh tortishga majbur qilardi.
`/assets/` blokida `types` ro'yxati bor - u `types` ni KENGAYTIRMAYDI,
ALMASHTIRADI, shuning uchun u yerda beriladigan hamma kengaytma sanalgan.

**Nega STT parki yiqilmaydi.** Router BUTUN park uchun ~10 parallel so'rov
ko'taradi. Ochiq qolgan bir nechta brauzer butun call-center'ni to'sib
qo'yishi mumkin edi. Shuning uchun tarmoqqa chiqish OXIRGI chora, oldida
uchta lokal filtr bor (`src/composables/useWakeWord.ts`):

| Filtr | Nima qiladi |
|---|---|
| Energiya (RMS) | sukunat brauzerdan UMUMAN chiqmaydi |
| Uzunlik 350-3000 ms | nutqning o'zi o'lchanadi (jimlik kesib tashlangach). "Salom Venera" ~1 s; undan uzun - oddiy suhbat, so'rovsiz TASHLANADI |
| Sovish 2.5 s | uzluksiz gap-so'z ham daqiqasiga ~24 so'rovdan oshmaydi |

Ya'ni jim xonada nol so'rov. Uyg'otish tekshiruvi 503 da QAYTA URINMAYDI -
navbatni haqiqatan kutayotgan odamdan slot olmaslik uchun.

**Nega xom PCM va `MediaRecorder` emas.** Uyg'otish so'zi qisqa, va RMS
chegarasi kesilganda "Sa-" allaqachon o'tib ketgan bo'ladi. Halqasimon bufer
0.45 s oldingi tovushni saqlaydi, ya'ni yozuv gapiruvchidan OLDIN boshlanadi.
Turn 1.4 s jimlikdan keyin tugaydi - odamlar "Salom" dan keyin qisqa pauza
qiladi, va qisqaroq kutish nomni keyingi turnga tashlab yuborardi.

**Yozuv sozlamalari ovoz paneliniki bilan BIR XIL** (`echoCancellation`,
`noiseSuppression`, `autoGainControl` - uchalasi yoqiq; `AudioContext` tabiiy
tezlikda, har parcha `OfflineAudioContext` bilan 16 kHz ga keltiriladi -
`toWav16k` bilan bitta yo'l). Bu ATAYLAB: panel - transkript qilishi
isbotlangan yagona yo'l, va Firefox 16 kHz kontekstga jonli oqim ulashni rad
etadi.

**Buzilgan yozuv - kod tuzata olmaydigan holat.** Bitta Windows/Chrome
mashinada past ovozda aytilgan ibora DARVOZA bilan kesilgan holda keldi:
nutq alohida impulslarga bo'lingan, orasi AYNAN NOL (unli ichidagi
namunalarning 22-59% i, toza nutqda 0-6%). Odam buni "juda shovqinli" deb
eshitdi, model esa hech narsa tanimadi. Bu brauzer sozlamalari yoqiq va
o'chiq holda ham takrorlandi, baland ovozda esa yo'qoldi - ya'ni darvoza
brauzerdan YUQORIDA (Windows "Audio enhancements", mikrofon drayveri,
garnitura dasturi), va `getUserMedia` ning hech bir sozlamasi unga yetmaydi.
Shuning uchun:

* Server har parchada `flat` (hisobotda `tekis`) ni o'lchaydi - nutq
  ichidagi tekis nol ulushi. 15% dan yuqorisi "buzilgan yozuv": bunday
  holatda moslashtirgichni sozlash foydasiz.
* `/stt/wake` javobida `distorted: true` qaytadi, brauzer esa yon panelda
  uyg'otish qatori ostida nima qilish kerakligini ko'rsatadi (mikrofon
  "audio enhancements" ni o'chirish yoki yaqinroq gapirish). Darvozani
  faqat foydalanuvchi o'chira oladi - jim turish uni "aniq aytmadim" deb
  o'ylashga majbur qilardi.

**Nega eskirgan `ScriptProcessorNode`.** Uning o'rnini bosuvchi `AudioWorklet`
protsessorni alohida modul URL'idan yuklaydi, odatdagi usul esa `blob:` URL.
Bizning CSP `script-src 'self'` - u `blob:` ni bloklaydi, va FAQAT ishlab
chiqarishda, jimgina. Eskirgan tugun bu muammodan xoli.

**Moslashtirgich** qoidalari:

* Nom Levenshtein masofasi <=2 bilan taqqoslanadi - model bir xil tovushni
  "venera", "vinera", "venira" deb yozadi. Nomzod so'z uzunligi >=5 bo'lishi
  shart, aks holda "vera", "era" ham nom deb qabul qilinardi.
* Nom uzun so'z ICHIDA ham qidiriladi: model so'zlarni qo'shib yuboradi
  ("salomvenera") yoki bo'g'inni noto'g'ri joyda ajratadi - jonli o'lchovda
  "Salom Venera, qalaysan" `salom, vener aqlaysan` bo'lib qaytdi.
* Salom + nom -> uyg'onadi.
* 2 yoki undan kam so'z bo'lsa NOMNING O'ZI yetarli. Salomni MAJBURIY qilish
  amalda ko'p o'tkazib yuborishga olib keldi: VAD salomning boshini kesib
  qoladi yoki model uni yutib yuboradi. Uzun gap baribir o'tmaydi.
* 5 so'zdan uzun gap chaqiriq emas: "Venera tizimi haqida ayting" da ham nom
  bor, lekin panelni ochish kerak emas.

### Urinishlar yozib boriladi

Har bir urinish diskka tushadi: **audio + STT transkripti + qaror + SABAB**.
Sababsiz jurnal foydasiz - "uyg'onmadi" degan yozuv nimani tuzatish
kerakligini aytmaydi, "nom topildi, lekin salom yo'q" esa aytadi.

```
apps/api/data/wake/
  wake.jsonl              # har qator - bitta urinish
  audio/<id>.wav          # o'sha urinishning ovozi
```

| O'zgaruvchi | Default | Izoh |
|---|---|---|
| `WAKE_LOG_ENABLED` | `true` | `false` - hech narsa yozilmaydi |
| `WAKE_LOG_DIR` | `apps/api/data/wake` | |
| `WAKE_LOG_MAX_FILES` | `500` | eski audiolar o'chiriladi; JSONL qatorlari qoladi |

> **Bu odamlarning ovozi - shaxsiy ma'lumot.** Papka `.gitignore` da va u
> yerda email emas, ichki `actor_id` saqlanadi. Kerak bo'lmaganda
> `WAKE_LOG_ENABLED=false` bilan butunlay o'chiring.

```bash
cd ~/Venera/apps/api
venv/bin/python tools/wake_report.py             # umumiy: nechta, qaysi sabablar
venv/bin/python tools/wake_report.py --misses    # faqat uyg'onmaganlar
venv/bin/python tools/wake_report.py --play <id> # o'sha urinishni eshitish
venv/bin/python tools/wake_report.py --replay    # HOZIRGI qoidalar bilan qayta baholash
```

Jurnalda transkriptdan tashqari AUDIO O'LCHOVI ham bor - `speech_sec`
(jimliksiz nutq uzunligi), `peak`, `rms`, `flat` (nutq ichidagi tekis nol
ulushi - yozuv brauzerdayoq buzilganini ko'rsatadi, yuqoriga qarang). Aynan shular birinchi haqiqiy
muammoni ochib berdi: muvaffaqiyatsiz urinishlarda nutq 0.65-0.85 s,
muvaffaqiyatlilarda 1.05-1.70 s edi - ya'ni yozuv "Salom Venera" ning
o'rtasida kesilardi, va model past qolgan ikkinchi so'z o'rniga
"assalomu alaykum" ni qo'yardi. Transkriptning o'zi buni hech qachon
ko'rsatmasdi.

`--replay` eng foydalisi: qoidani o'zgartirgach, jurnaldagi HAQIQIY
matnlarni yangi qoidalarga yuritadi va nechta holat tuzalgani hamda nechta
yangi noto'g'ri uyg'onish paydo bo'lganini ko'rsatadi. Sozlashni taxmindan
o'lchovga aylantiradi.

**Qaror SERVERDA** (`app/services/wake.py`), brauzerda emas: u audio va matn
bilan bir joyda yozilishi kerak, qoidalarni o'zgartirish frontend obrazini
qayta yig'ishni talab qilmasligi kerak, va ikki tilda ikki nusxa vaqt o'tib
albatta ajralib ketardi.

Jonli o'lchangan (TTS -> STT aylanmasi orqali):

| Aytilgan | STT qaytargani | Uyg'otadimi |
|---|---|---|
| Salom Venera (ayol ovozi) | `salom, venera.` | ha |
| Salom Venera (erkak ovozi) | `salom venera.` | ha |
| Assalomu alaykum Venera | `assalomu alaykum venera.` | ha |
| Venera | `venera.` | ha - qisqa chaqiriq |
| Salom Venera, qalaysan | `salom, vener aqlaysan.` | ha |
| Bugun havo issiq | `bugun havo issiq.` | yo'q - nom yo'q |
| Venera tizimi haqida ayting | `generat tizimi haqida ayting.` | yo'q |

Faqat `uz` va `uz-Cyrl` tillarida ko'rinadi: so'zning o'zi o'zbekcha.

## Savol-javob: HR Assistant

Chat javobi Venera ichida yasalmaydi. U yuqoridagi **BRB-TECH HR Assistant
API** dan keladi (`10.10.50.4:8080`): o'sha xizmat hujjatlar bo'yicha RAG va
HRM connector'ini o'z ichida birlashtiradi, ya'ni Venera uchun bu BITTA
endpoint.

```
brauzer -> /api/v1/chat/stream (Venera)  ->  POST /api/{v1|v2|v3}/chat/stream (Assistant)
                                              |-> hujjatlar (RAG, Qdrant)
                                              |-> qonunchilik (LEX.UZ, v2)
                                              `-> HRM connector (hrm-mcp)
```

**Nega brauzer to'g'ridan-to'g'ri bormaydi.** Uch sabab, har biri yetarli:

1. `X-Client-Secret` - ILOVANING siri. Frontend o'zi yuborsa, sir JS
   bundle'ida va tarmoq panelida ochiq turardi.
2. `10.10.50.4` ichki manzil - brauzer unga umuman yetib bormaydi
   (foydalanuvchi `llm.brb-tech.uz` orqali keladi).
3. Kimlik: `user_id` server tomonidan Venera token'idan qo'yiladi. Klient
   uni o'zi yuborsa, boshqa xodimning suhbat tarixiga kirardi - xizmatda
   xotira `(user_id, chat_id)` bo'yicha saqlanadi.

**Sozlash** (`.env`):

```
HRM_ASSISTANT_BASE_URL=http://10.10.50.4:8080
HRM_ASSISTANT_CLIENT_ID=<ilova kredensiali>
HRM_ASSISTANT_CLIENT_SECRET=<ilova siri>
```

Bo'sh qolsa `/api/health` `degraded` bo'lib, "CHAT ISHLAMAYDI" deb aytadi va
savol umuman yuborilmaydi - xizmat 401 qaytarardi va u foydalanuvchiga
"sessiyangiz tugadi" bo'lib ko'rinardi.

### Dvigatel: v1 / v2 (2026-10-02 dan)

Xizmat versiyali - so'rov va javob shakli bir xil, yo'l boshqa:

| `HRM_ASSISTANT_ENGINE` | Yo'l | Nima |
|---|---|---|
| `v2` (default) | `/api/v2/chat/stream` | yangi: javobni model yozadi, Mehnat kodeksi moddalari LEX.UZ havolasi bilan, **"Pro"** |
| `v1` | `/api/v1/chat/stream` | barqaror: 29-sentabrgacha bo'lgan javoblar |
| `v3` | `/api/v3/chat/stream` | **"Venera Core"** (2026-10-08, API 3.3): hamma imkoniyat bitta vazifa-siklida, vazifa holati xabarlar orasida saqlanadi, yozishdan oldin nomlar aniqlanadi; "Pro" bor. `done` ga `trace_id` va vazifa holati (`task`) keladi - admin panel savol izida. Avval odamga ALOHIDA (Versiyalar sahifasi), sinovdan keyin hammaga |
| bo'sh | `/api/chat/stream` | versiyasiz - xizmat default'i (bugun = v1). **Hozirgi prod shu yo'lda** |

Kanal bo'yicha istisno: `HRM_ASSISTANT_ENGINE_BY_CHANNEL=miniapp=v1,bot=v1`
(kanallar: `web`, `miniapp`, `bot`, `desktop`, `api`; kanal `X-Venera-Client`
sarlavhasidan). Tarix (`/api/chats`), amallar, fayllar, hujjatlar va
`/api/pro/quota` VERSIYASIZ - ikkala dvigatel uchun bitta. Noto'g'ri qiymat
server'ni yiqitmaydi: `/api/health/detail` dagi `warnings` va
`assistant.engine.problems` da ko'rinadi, o'rniga `v2` (yoki umumiy qiymat)
ishlaydi. Qaysi kanal qaysi dvigatelda - `assistant.engine.byChannel`.

**"Pro" faqat `v2` da.** Boshqa dvigatelda `mode: "pro"` yuqoriga
YUBORILMAYDI (javob standart rejimda), `done` da `pro` bloki bo'lmaydi, savol
izida esa "Pro: berilmadi, sabab `engine`". `GET /api/v1/pro/quota` javobida
`engine` (so'rovchi kanalining dvigateli) va `available` (`v2` va byudjet
o'qildi): `v2` bo'lmasa 200, `available: false`, yuqoriga borilmaydi.

**Orqaga qaytarish:** `HRM_ASSISTANT_ENGINE=v1` (yoki bo'sh) va restart - kod
o'zgarmaydi. Analitika omboridagi `turns.engine` ustuni (sxema v2) qoladi;
eski kod uni e'tiborsiz qoldiradi.

**Javob NDJSON oqimi**: har qatorda bitta kadr, kelishi bilan uzatiladi.

| Kadr | Nima |
|---|---|
| `stage` | o'tkinchi holat ("Hujjatlar qidirilmoqda") - kutish paytida ko'rsatiladi |
| `sources` | iqtiboslar (`[1]`) va HRM chaqiruvlari (`[T1]`). DIQQAT: jonli xizmat ro'yxatni `items` kalitida yuboradi, hujjatdagi bir martalik javobda esa `sources` - ikkalasi ham o'qiladi. v2: `kind: "law"` - LEX.UZ dagi modda (`url`, `title`, `doc_id: null`) |
| `artifact` | yaratilgan ariza fayli (DOCX/PDF) |
| `token` | javob matni bo'laklari |
| `done` | yakun: `route` (`rules`/`hrm`/`both`/`clarify`); versiyalangan yo'lda `engine`, "Pro" so'ralganda `pro` |
| `error` | tokenlar o'rniga: `code` va foydalanuvchiga xavfsiz `text` |

**Qonunchilik havolasi tekshiriladi.** `kind: "law"` manbaning `url` i
brauzerda havola bo'lib ochiladi, shuning uchun Venera FAQAT `https://` ni
o'tkazadi: `javascript:`, `data:`, login-parolli va boshqa `http://` manzil
`null` ga aylanadi (manbaning nomi qoladi), `http://lex.uz` esa `https` ga
ko'tariladi. LEX.UZ dan boshqa `https` domen o'tadi, lekin jurnalga yoziladi
("Manba havolasi LEX.UZ emas"). Qonun manbasi hujjat ko'ruvchisiga
(`/api/v1/chat/doc/...`) HECH QACHON yo'naltirilmaydi.

### Navbat: "Savol-javob xizmati band" (503)

Venera yordamchiga bir vaqtda ko'pi bilan `HRM_ASSISTANT_MAX_CONCURRENT` ta
oqim ochadi; oshsa savol yordamchiga BORMASDAN 503 oladi. 29-sentabrda prod
shu navbat "oqib ketgani" sababli bir soatdan ko'p har savolga 503 berdi -
yordamchiga birorta so'rov bormagan holda (klient tanadan oldin uzilsa oqim
yopilmay, joy abadiy band qolardi). Endi:

* joy oqim yopilganda, `AnswerStream.close()` da va oqim obyekti yig'ilganda
  qaytadi (uchalasi ham idempotent);
* navbat TO'LGANDA o'zini davolaydi: avval `gc.collect()` (yetib bo'lmaydigan
  oqimlar halol yopiladi), keyin `HRM_ASSISTANT_TIMEOUT` + 30 s o'qilmagan
  yoki `HRM_ASSISTANT_MAX_STREAM_SECONDS` + `TIMEOUT` + 30 s dan qari joylar
  majburan qaytariladi - jurnalda ERROR: "N ta oqib ketgan joy qaytarib olindi";
* bitta javob `HRM_ASSISTANT_MAX_STREAM_SECONDS` (600) dan uzoq yashamaydi (504).

Sababi foydalanuvchiga bir xil ("xizmat band"), lekin jurnal va savol izida
(`turns.error_code`) ALOHIDA:

| `error_code` | Ma'nosi | Nima qilish |
|---|---|---|
| `queue_full` | BIZNING navbat to'la - yordamchiga borilmagan | `/api/health/detail` -> `assistant.slots` (band, eng eski joy, `reclaimed`) |
| `upstream_unreachable` | yordamchiga ulanib bo'lmadi | tarmoq / `10.10.50.4:8080` / firewall |
| `upstream_busy` | yordamchining O'ZI 503 qaytardi | yordamchi jamoasi |
| `open_failed` | boshqa ochilish xatosi (401, 422, 5xx) | `http_status` va `error_text` ga qarang |

Yordamchi holati uchun keshlangan "o'chiq" belgisi (circuit breaker) Venera'da
YO'Q: har savol yordamchiga qayta urinadi, ya'ni u qaytishi bilan chat ham
qaytadi. `UpstreamHealth` (STT/TTS) 30 s keshlanadi, lekin faqat tashxis
uchun - so'rovlarni to'smaydi.

`nginx` da alohida `location = /api/v1/chat/stream` bor: **buferlash va gzip
o'chirilgan**. Aks holda nginx butun javobni yig'ib, oxirida bir yo'la
berardi - ya'ni odam javob yozilayotganini ko'rmaydi va oqimning ma'nosi
qolmaydi.

**O'LCHANGAN (2026-09-10, `rules` yo'nalishi).** Birinchi ikki `stage` kadri
**0.00 s** da keladi, keyin ~15 s jimlik (xizmat o'ylaydi), so'ng qolgan
hamma narsa birdan. Ya'ni:

* Transport buferlamaydi - aks holda birinchi kadr ham 15 s kutardi.
* **Tokenlarni xizmatning O'ZI birdan yuboradi**: 57 token 0.02 s ichida.
  To'g'ridan-to'g'ri `10.10.50.4:8080` ga borilganda ham AYNAN shunday
  (15.24 s, 0.02 s cho'zilish), ya'ni bu bizning qatlamimizdan emas.
  Venera qo'shadigan ustama ~0.4 s.
* Shu sababli hozir ko'zga ko'rinadigan foyda - **jonli `stage` matni**
  ("Savol turi aniqlanmoqda..."), harf-harf yozilish emas. Xizmat
  tokenlarni sekinlashtira boshlasa (kadrlarda `paced: true` bor), UI
  hech qanday o'zgarishsiz darhol shundan foydalanadi.

Buni tekshirish oson: birinchi kadr qancha vaqtda kelganini qarash kifoya.
Agar u ham oxirgisi bilan birga kelsa - buferlash yoqilib qolgan.

**Fayl havolalari qayta yoziladi.** Xizmat bergan `docx_url` ichki manzilni
ko'rsatadi; Venera uni `/api/v1/chat/artifact/{token}/{kind}` ga o'giradi va
faylni o'zi olib beradi. Iqtibos qilingan hujjat uchun
`/api/v1/chat/doc/{doc_id}`. Ikkalasi ham Venera sessiyasini talab qiladi,
shu sababli frontend ularni `<a href>` bilan emas, token bilan `fetch`
qilib yuklab oladi.

**Telegram mini app uchun istisno - imzolangan havola.** U yerda faylni
Telegram ilovasining o'zi yuklaydi (`WebApp.downloadFile`) va sessiya
tokenini yubora olmaydi. Shuning uchun `POST /api/v1/chat/artifact/{token}/
{docx,pdf}/link` (sessiya bilan) 10 daqiqalik havola beradi, fayl esa
`GET /api/v1/chat/file/{imzo}` dan SESSIYASIZ olinadi. Imzo `SECRET_KEY`
bilan, lekin boshqa `aud` (`venera:file`) bilan: havola API'ga kira olmaydi,
sessiya tokeni esa havola o'rnida ishlamaydi. `SECRET_KEY` almashtirilsa,
berilgan havolalar ham bekor bo'ladi.

### Jonli HRM ma'lumoti va `HRM_TOKEN`

"Men bugun kechikdimmi?" kabi savol uchun xizmat foydalanuvchining HRM
sessiyasini (`hrm_token`) talab qiladi va boshqa odamning huquqi bilan hech
qachon javob bermaydi. Venera kimligi (`config/users.yaml`) esa HRM
kimligidan alohida - ya'ni sessiyadan olinadigan token bizda yo'q.

**Hozirgi bosqich: `.env` da bitta umumiy token.**

```
HRM_TOKEN=<HRM JWT>
```

Buning OCHIQ oqibati bor va u xizmat hujjatida yozilgan: *"With a token, the
token's own account is the default"* - ya'ni token bilan **"men" degani
TOKEN EGASI**. Venera'ning qaysi foydalanuvchisi so'rasa ham, jonli javob
o'sha bitta odam haqida bo'ladi. Shuning uchun:

* `/api/health` bu token qo'yilganini **ogohlantirish** sifatida ko'rsatadi
  (`degraded`) - vaqtinchalik yechim unutilib ketmasligi uchun.
* Har so'rov jurnalga KIM so'raganini yozadi (`Assistant javobi
  (email): request_id=...`), ya'ni audit izida mos kelmaslik ko'rinadi.
* Boshqa odam nomidan so'rash kerak bo'lsa `hrmEmployee` maydoni bor -
  lekin HRM huquqlari baribir token egasining huquqlari bo'lib qoladi.

#### Token'ni almashtirish - QAYTA ISHGA TUSHIRISH KERAK EMAS

HRM sessiyasi bir necha daqiqada tugaydi, ya'ni token kuniga o'n marta
almashadi. Shuning uchun API uni `.env` dan **har so'rovda** o'qiydi
(`core/config.py`, `hrm_token_now`): fayl o'zgargani `stat` bilan
aniqlanadi, o'zgarmagan bo'lsa diskka borilmaydi ham. Har almashtirishda
restart qilish ayni vaqtda oqib turgan javoblarni kesib yuborardi.

```bash
cd ~/Venera/apps/api

# Yozish (token ekranga chiqmaydi, faqat muddati ko'rsatiladi)
venv/bin/python tools/set_hrm_token.py 'eyJhbGciOi...'

# Yoki nusxadan / fayldan
cat /tmp/token.txt | venv/bin/python tools/set_hrm_token.py -

# Hozirgi holat
venv/bin/python tools/set_hrm_token.py --show
```

Vosita `.env` ni ATOMIK yozadi (yonidagi vaqtinchalik fayl + `os.replace`),
huquqlarini (600) saqlaydi, takroriy `hrm_token` qatorlarini tozalaydi va
`Bearer ` prefiksi, qo'shtirnoq, yangi qator kabi nusxa-ko'chirishda
yopishadigan narsalarni oladi.

`.env` ni qo'lda tahrirlash ham ishlaydi - registr (`hrm_token` /
`HRM_TOKEN`) va qo'shtirnoq muhim emas.

**TUZOQ: `hrm_token` qisqa shakli ISHLAMAYDI.** Xizmat hujjati
*"hrm_token is the shorthand for tokens['hrm']"* deb aytadi, lekin jonli
o'lchovda (2026-09-11) faqat XARITA shakli ishlaydi:

```jsonc
{"tokens": {"hrm": "<jwt>"}}   // ishlaydi
{"hrm_token": "<jwt>"}          // auth_missing, AYNAN bir xil token bilan
```

Buni topish oson emas edi, chunki xato token yaroqsiz bo'lgandagi xato
bilan bir xil ko'rinadi. Ajratish usuli: token'ni HRM ning o'ziga
sinash - `curl https://hrm-api.brb-tech.uz/api/account -H "Authorization:
Bearer <jwt>"`. 200 kelsa token joyida, demak muammo shaklda.

Ikkalasini birga yuborish YO'Q: buzuq yo'l ustun kelib qolsa muammo
qaytardi.

**`exp` HAQIQIY umr emas.** `/api/health` va vosita token aytgan muddatni
ko'rsatadi, lekin HRM sessiyani undan oldin ham bekor qiladi: jonli
o'lchovda `exp` 10 soat ko'rsatgan token amalda bir necha daqiqada
yaroqsiz bo'ldi. Shuning uchun "hali 9 soat bor" degan xulosaga
ishonmang - `auth_missing` kelsa token'ni almashtiring.

`HRM_TOKEN` bo'sh bo'lsa jonli savollar `auth_missing` bilan qaytadi va
frontend "HRM hisobingiz ulanmagan" deb aytadi. Bu TO'G'RI xatti-harakat:
boshqa odamning huquqi bilan javob berishdan ko'ra javob bermaslik yaxshi.
**Hujjatlar va qoidalar bo'yicha savollar har holatda ishlaydi.**

**Doimiy yechim** (hali qilinmagan): foydalanuvchi o'z HRM hisobi bilan
kirsin va token sessiyadan olinsin. Ikki yo'l bor - Venera'ga kirishning
o'zi HRM orqali bo'lishi, yoki HRM hisobi alohida ulanishi. Kod tomonida
ikkalasi ham bitta joyni o'zgartiradi: `api/v1/chat.py` dagi
`hrm_token=settings.hrm_token or None`.

**Tekshirish** (soxta xizmat bilan, kredensialsiz ham ishlaydi):

```bash
cd ~/Venera/apps/api
venv/bin/python -m pytest -q tests/test_assistant.py     # 58 test, tarmoqsiz
```

Jonli tekshirish:

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"...","password":"..."}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')

curl -s -N -X POST http://127.0.0.1:8000/api/v1/chat/stream \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"question":"Yillik ta'\''til necha kun?","chatId":"c-1"}'
```

Kadrlar BIR-BIR kelishi kerak. Hammasi birdan kelsa - buferlash yoqilib
qolgan (nginx `location` ini tekshiring).

## Avtomatik qayta ishga tushish

| Holat | Xulq |
|---|---|
| Jarayon yiqildi (crash, OOM, SIGKILL) | 3 soniyadan keyin qayta ishga tushadi |
| Xato kod bilan chiqdi | qayta ishga tushadi |
| Server qayta yuklandi | `enable` + `linger` tufayli avtomatik |

Sozlama `Restart=always`, `RestartSec=3`, `StartLimitBurst=0`.

**`StartLimitBurst=0` muhim:** default qiymat (10 soniyada 5 marta) bilan
xizmat qayta-qayta yiqilsa systemd taslim bo'lib uni butunlay **o'chirib
qo'yadi** va keyin **qo'lda** yoqish kerak bo'ladi. Tungi soat 3 da
ma'lumotlar bazasi kech ko'tarilsa aynan shu bo'ladi.

**Tiklanish ~5 soniya**, 3 emas. `Type=exec` systemd ga jarayon *ishga
tushgani* haqida xabar beradi, lekin uvicorn portni biroz keyinroq band
qiladi. O'sha oraliqda nginx 502 qaytaradi. Bu o'lchangan, kutilgan xulq.

## Kundalik buyruqlar

```bash
systemctl --user status venera-api.service      # holat
systemctl --user restart venera-api.service     # qayta ishga tushirish
journalctl --user -u venera-api.service -f      # jonli log
journalctl --user -u venera-api.service -n 100  # oxirgi 100 qator
```

## Kodni yangilash

```bash
cd ~/Venera && git pull
systemctl --user restart venera-api.service
```

Bog'liqliklar `pyproject.toml` da o'zgargan bo'lsa qo'shimcha:

```bash
cd ~/Venera/apps/api && venv/bin/pip install -e ".[dev]"
```

Frontend uchun image qayta yig'iladi:

```bash
cd ~/Venera/apps/web
podman build -t localhost/venera-frontend:latest .

# Orqaga qaytish nuqtasi. Busiz obraz faqat `latest` tegida qoladi:
# keyingi build tegni tortib oladi, eskisi `<none>` bo'lib qoladi va
# `podman image prune` uni butunlay o'chiradi - ya'ni rollback yo'li yo'q.
podman tag localhost/venera-frontend:latest \
  "localhost/venera-frontend:$(date +%F)-$(git rev-parse --short HEAD)"

systemctl --user restart venera-frontend.service
```

Rollback kerak bo'lsa - `podman images localhost/venera-frontend` bilan
kerakli tegni toping, uni `latest` ga qayting va xizmatni qayta ko'taring:

```bash
podman tag localhost/venera-frontend:<teg> localhost/venera-frontend:latest
systemctl --user restart venera-frontend.service
```

---

## Tekshirish

```bash
# 1. Xizmat ko'tarildimi
systemctl --user is-active venera-api.service

# 2. API javob beryaptimi (host'dan)
curl -s http://127.0.0.1:8000/api/health

# 3. nginx orqali o'tyaptimi   <- ENG MUHIMI
curl -s http://127.0.0.1:5173/api/health

# 4. Login ishlayaptimi
curl -s -X POST http://127.0.0.1:5173/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@venera.uz","password":"SIZNING-PAROLINGIZ"}'

# 5. Port TASHQARIGA ochilmaganini tasdiqlash
ss -ltn | grep 8000     # 127.0.0.1:8000 bo'lishi kerak, *:8000 EMAS
```

`status: "ok"` — hammasi joyida. `"degraded"` — ishlayapti, lekin
`warnings` ni o'qing (odatda `SECRET_KEY` o'zgartirilmagan).

**2-qadam ishlaydi, 3-qadam 502 beradi** — eng ko'p uchraydigan holat,
pastdagi birinchi tuzoqqa qarang.

---

## Ovoz ishlamay qolsa - birinchi qadam

```bash
curl -s http://127.0.0.1:8000/api/health | python3 -m json.tool
```

`/api/health` yuqoridagi ovoz xizmatlarini ham tekshiradi va nima
ishlamayotganini oddiy til bilan aytadi. Bu qo'shilgan sabab: STT ning
o'zbek backend'i o'chib qolganida ilova o'zi butunlay sog'lom ko'rinardi,
uyg'otish so'zi esa jimgina ishlamay qo'yardi - buni faqat log'ni ochib
ko'rgandagina bilish mumkin edi.

```json
{
  "status": "degraded",
  "upstream": {
    "stt": { "status": "degraded", "broken": ["uzbek_stt"] },
    "tts": { "status": "ok" }
  },
  "warnings": ["STT: o'zbek backend'i o'chgan (10.10.50.4 dagi 8002) - ..."]
}
```

| Ogohlantirish | Qayerda tuzatiladi |
|---|---|
| `o'zbek backend'i o'chgan` | `10.10.50.4` da o'zbek STT xizmatini qayta ko'taring (port 8002) |
| `STT Router javob bermayapti` | `10.10.50.4` da Router (port 8006) |
| `TTS javob bermayapti` | `10.10.50.4` da TTS (port 8200) |

Tekshiruv 30 soniya keshlanadi - `/api/health` monitoring tomonidan tez-tez
so'raladi, har safar ikkita tashqi so'rov yuborish ularni ortiqcha bezovta
qilardi.

Uyg'otish tinglagichi ham buni sezadi: tekshirib bo'lmasa (`checked: false`)
urinishlar oralig'i har nosozlikda ikkilanadi, 60 soniyagacha. O'chgan
backend'ni har ikki soniyada urib turishning ma'nosi yo'q, tuzalganini esa
bir daqiqa ichida sezadi.

## Ma'lum tuzoqlar

**`/api/*` da 502, API o'zi esa ishlayapti.** Frontend xizmatida
`--network slirp4netns:allow_host_loopback=true` yo'q. Root'siz podman
konteynerdan **host loopback'ga yo'lni default holda yopadi**, backend esa
ataylab `127.0.0.1:8000` da turadi. Log'da:

```bash
podman logs venera-frontend | grep 'Network is unreachable'
```

Sayt ochiladi va SPA yuklanadi — faqat login ishlamaydi, shuning uchun
buzilish darhol ko'zga tashlanmaydi.

**Swagger sahifasi BO'SH ochiladi, curl esa 200 qaytaradi.** Eng aldamchi
xato. Frontend nginx butun saytga `script-src 'self'` CSP qo'yadi, FastAPI
ning tayyor `get_swagger_ui_html()` funksiyasi esa sahifaga INLINE
`<script>` yozadi. Brauzer uni bloklaydi: `swagger-ui-bundle.js` yuklanadi,
lekin uni ISHGA TUSHIRADIGAN kod bajarilmaydi va `<div id="swagger-ui">`
bo'sh qoladi. `curl` JS ishlatmaydi, shuning uchun 200 ko'radi va muammoni
UMUMAN sezmaydi.

Yechim `app/main.py` da: sahifa qo'lda yig'iladi, ishga tushirish kodi
`app/static/swagger-init.js` da - inline skript yo'q. CSP ni
bo'shashtirish (`'unsafe-inline'` qo'shish) KERAK EMAS va zararli bo'lardi:
u butun sayt uchun ochilardi.

Buni `tests/test_docs.py` qo'riqlaydi - u status kodni emas, sahifa
TARKIBINI tekshiradi.

**Xizmat ko'tarilmadi, `Address already in use`.** 8000-portni boshqa
jarayon band qilgan (odatda qo'lda qoldirilgan `uvicorn`):

```bash
ss -ltnp | grep 8000
```

**`ModuleNotFoundError` restart'dan keyin.** venv yangi bog'liqliksiz qolgan:
`cd ~/Venera/apps/api && venv/bin/pip install -e ".[dev]"`.

**Xizmat logout'da o'chadi.** `loginctl enable-linger $USER` bajarilmagan.

**`/api/docs` 503 qaytardi.** `app/static/` da fayllar yo'q — 3-qadamni
bajaring. Javobda qaysi fayl yetishmayotgani yozilgan.

## Telegram bot (chatning o'zida savol-javob)

Odam `@venera_ai_brb_bot` ga oddiy xabar yoki **ovozli xabar** yozadi va javobni
**matn** bilan oladi (ovoz sintezi yo'q). Imkoniyatlari veb chat bilan bir xil:
HRM/CRM savollari, yozuv amalini tasdiqlash (tugmalar), ariza fayli (DOCX
chatga keladi, PDF tugma bilan), manba hujjati (`📄 [1]` tugmasi - PDF chatga
keladi). Suhbatlar veb ilova va mini app tarixida ham ko'rinadi.

**Qayerda ishlaydi.** API jarayoni ichida (`app/bot/`), long polling bilan
(`TELEGRAM_MODE=polling`) - nginx ga tegilmaydi. Alohida xizmat EMAS: bot
`api/v1/chat.py` dagi AYNI klientlarni ishlatadi (CRM sessiyasi
`refresh_token` ni rotatsiya qiladi - ikkinchi nusxa uni bekor qilardi).
Bitta xostda ikkinchi API nusxasi botni o'qimaydi: `data/telegram/poll.lock`.

**Bitta token - bitta o'quvchi.** 2026-09-24 da boshqa muhitdagi (dev) server
shu token bilan ishga tushdi: xabarlar ikkiga bo'lindi va dev nusxa - unda
ulanishlar yo'q - odamdan qayta kirishni so'radi. Endi bot 409 ni ko'rishi
bilan ulanishni DARHOL qaytarib oladi (u nusxa ~30 s kutadi), `/api/health/
detail` esa `conflicts_10min` va ogohlantirishni ko'rsatadi. To'liq yechim:
@BotFather'da `/revoke`, yangi tokenni faqat shu `.env` ga qo'yish.

**Webhook** (`TELEGRAM_MODE=webhook`, `/api/v1/telegram/webhook`, sir
sarlavhasi bilan) kodda bor, lekin jonli tizimda O'CHIQ: sinovda Telegram'ning
`195.158.16.251` ga ulanishi ko'pincha birinchi urinishda "Connection timed
out" bo'ldi va ovozli savol ~80 s kechikdi (GAPI 1.6 s, javob 7 s). Tarmoq
tuzatilsa - bitta qator bilan yoqiladi. Polling'ga qaytishda webhook qo'lda
o'chiriladi (`deleteWebhook`), aks holda `getUpdates` 409 oladi.

**Hisobni ulash - faqat mini app orqali.** Odam botdagi "Venera" tugmasi bilan
mini app'ni ochib kiradi; ilova `POST /api/v1/telegram/link` ga Telegram
imzolagan `initData` ni yuboradi. Isbot ikkita: sessiya (kim kirgan) va
imzo (kim ochgan) - `user.id` klientdan olinmaydi. Botda parol so'ralmaydi.
Ulanish oxirgi faollikdan 30 kun yashaydi: mini app ochilishi ham, botdagi
har savol ham uni yangilaydi - faol odamdan qayta kirish so'ralmaydi. Mini
app'dan chiqish (`/unlink`) va botdagi `/logout` uni uzadi. Hisob
`users.yaml` dan o'chirilsa - keyingi xabarda ulanish uziladi.

Saqlanadigan narsa: `data/telegram/links.json` (600, atomik) - faqat
Telegram `id`, `actor_id`, vaqtlar va joriy suhbat kaliti.

**Kirish - faqat matn va ovoz (mikrofon).** Video (kamera: dumaloq video,
video yoki video fayl) qabul qilinmaydi: yuklab olinmaydi va chatdan darhol
o'chiriladi. Kamera tugmasini Telegram ilovasi boshqaradi - bot uni yashira
olmaydi (shaxsiy chatda media cheklovi yo'q). Rasm, fayl, stiker - faqat izoh.

**Buyruqlar** (bot ishga tushganda menyu o'zi yangilanadi): `/new` yangi
suhbat, `/app` mini app, `/help`, `/logout`. Faqat SHAXSIY chat - guruhda
bot jim (javoblarda shaxsiy HR ma'lumoti bor).

**Holat:** `/api/health/detail` (FAQAT ADMIN - `ADMIN_LOGINS` yoki admin panel
orqali berilgan rol) -> `telegram` (ishlayaptimi, rejimi, oxirgi muvaffaqiyatli
so'rov, xato, ulanganlar soni); admin panelning "Tizim" sahifasi ham shu
tashxisdan botning HAQIQIY rejimini (`polling` / `webhook`) ko'rsatadi. 409
xatosi = boshqa nusxa shu botni o'qiyapti. O'chirish: `.env` da `TELEGRAM_BOT_ENABLED=false` + restart.

## Xodimlar ma'lumotnomasi (kontaktlar)

F.I.SH, Telegram, telefon, email - `apps/api/data/contacts/contacts.db` (SQLite,
gitignore'da, 600). Shaxsiy ma'lumot: jurnalga qiymatlar yozilmaydi, tashqi
LLM ga yuborilmaydi - qidiruv Venera'ning o'zida (`services/contacts.py`).

**Chatda ISHLATILMAYDI (2026-10-07 dan).** Avval `services/contacts_chat.py`
har savolni yordamchidan OLDIN kalit so'zlar bilan tekshirib, kontakt savoliga
o'zi javob berar va tahrir kartasini ko'rsatar edi. Bu "CRMga task kiritib ber ...
telegram ... <ism>" kabi savollarni kontakt tahririga aylantirib, yordamchiga
umuman yetkazmadi - olib tashlandi. Endi kontakt savollari ("...ning telegrami",
"@username kim?") yordamchiga ketadi, u ularni HRM orqali biladi (so'raganning
HRM sessiyasi kerak). Ro'yxatning o'zi va quyidagi yuklash vositasi qoldi.

**Ommaviy yuklash / nusxa** (jadvaldan nusxalangan TSV yoki CSV, birinchi qator
sarlavha):

```bash
cd ~/Venera/apps/api
venv/bin/python -m app.tools.contacts_import royxat.tsv --dry-run
venv/bin/python -m app.tools.contacts_import royxat.tsv
venv/bin/python -m app.tools.contacts_import --export nusxa.csv
```

Qayta yuklash xavfsiz: email yoki F.I.SH bo'yicha topilgan xodimning faqat
TO'LDIRILGAN maydonlari yangilanadi, bo'sh katak mavjud qiymatni o'chirmaydi,
faylda yo'q xodim o'chirilmaydi. Birinchi yuklash: 2026-09-25, 77 xodim.
