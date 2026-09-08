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

Backend matnni TTS serveriga (`10.10.50.4:8200`) yuborib, WAV olib qaytaradi.
Javob `audio/wav` (8000 Hz, mono - telefoniya sifati), JSON emas.

| O'zgaruvchi | Default | Izoh |
|---|---|---|
| `TTS_BASE_URL` | `http://10.10.50.4:8200` | TTS serveri (ichki tarmoq) |
| `TTS_CLIENT_ID` | `frontend` | serverdagi `AUTH_CLIENTS` dan |
| `TTS_CLIENT_SECRET` | *(bo'sh)* | **sir.** Bo'sh bo'lsa ovoz o'chiq (501), qolgan hamma narsa ishlaydi |
| `TTS_TIMEOUT` | `60` | BIR so'rov uchun, soniya |
| `TTS_DEADLINE` | `100` | BUTUN `/speak` uchun devor-soat. nginx 120 s dan KAM bo'lishi shart |
| `TTS_MAX_CONCURRENT` | `2` | bir vaqtda nechta sintez |
| `TTS_VOICE` | `uz_female_calm` | yoki `uz_male_news` (erkak) |
| `TTS_SPEED` | *(bo'sh -> 0.95)* | rasmiy 0.90, yangiliklar 1.0 |
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

**`download_url` ISHLATILMAYDI.** U `user_id` bo'yicha ENG SO'NGGI faylni
beradi: ikki foydalanuvchi bir vaqtda so'rasa, biri boshqasining audiosini
eshitardi. Fayl `audio_path` dagi unikal nom bo'yicha `/api/v1/tts/file/{nom}`
dan olinadi.

**Timeout byudjeti.** `/speak` IKKITA ketma-ket so'rov qiladi: `generate`,
keyin faylni yuklab olish. `TTS_TIMEOUT` faqat bittasiga tegishli, ya'ni
`TTS_DEADLINE` bo'lmasa jami 60+60=120 s ga yetib, nginx chegarasiga aynan
urilardi - javob brauzerga yetib bormasdi, slot esa band turaverardi.
Zanjir: bir so'rov 60 s < butun `/speak` 100 s < nginx 120 s.

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
