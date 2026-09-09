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
