# Venera - Telegram Mini App (`/tg/`)

Telegram bot'ining Mini App sahifasi. Ikkita fayl, build qadami YO'Q:

```
index.html    belgilash va uslublar
app.js        butun mantiq (API, ovoz, suhbat)
```

Manzil: `https://llm.brb-tech.uz/tg/`

## Nega alohida ilova, veb ilovaning o'zi emas

Veb ilova (`apps/web`, Vue + Vite) Telegram WebView uchun og'ir va uning
qattiq CSP si (`frame-ancestors 'none'`) Mini App'ni umuman ochtirmaydi.
Bu sahifa esa bitta ekran: doira, mikrofon, javob. Shuning uchun u vanilla
JS - yig'ish ham, `node_modules` ham kerak emas.

Lekin MANTIQ qayta ixtiro qilinmagan: `app.js` dagi har bir bo'lim
`apps/web/src` dagi jonli sinalgan kodning nusxasi va manbasi izohda
ko'rsatilgan. Ayniqsa quyidagilar - ular tanlanmagan, **o'lchangan**:

| Joy | Manba | Nega tegmaslik kerak |
|---|---|---|
| WAV 16 kHz ga o'girish | `api/wav.ts` | STT backend WebM ni dekodlay olmaydi, Chrome esa faqat WebM yozadi |
| PCM pleyer | `api/tts.api.ts` | `/tts/speak` xom `audio/L16` qaytaradi - `<audio>` bilan ochib bo'lmaydi |
| `answerBody` / `forSpeech` / `SPEAK_LIMIT` | `components/VoicePanel.vue` | javobni o'qishga tayyorlash - markerlar, HRM audit izi, 3000 belgi chegarasi |
| VAD ostonalari (0.045 / 1400 ms) | `components/VoicePanel.vue` | qisqarog'i gapni yarmida kesadi |

## Ekran tuzilishi

```
 Venera ✦        [Tayyor] [🔊] [☰]     <- yuqori qator
 ┌───────────────────────────────┐
 │                               │
 │   S U H B A T   (flex: 1)     │      <- asosiy maydon, scroll
 │                               │
 └───────────────────────────────┘
            Gapirish uchun bosing      <- bitta status qatori
 ┌───────────────────────────────┐
 │ Veneradan so'rang…   (➤) (◉) │      <- kiritish paneli
 └───────────────────────────────┘
```

### Kiritish paneli

Savolni IKKI yo'l bilan berish mumkin: yozib yoki gapirib. Ikkalasi ham
`ask()` ning AYNI O'ZIGA boradi - farq faqat boshida (ovozda STT qadami
bor). Shuning uchun turn raqami, bekor qilgich va holat mashinasi bitta
joyda qoladi.

Veb ilovadagi `InputDock.vue` dan farqlar ATAYLAB:

* `+` (biriktirish) va dok ichidagi mikrofon ikonkasi YO'Q. Veb'da ular
  o'chirilgan holda turadi (`comingSoon`); tor ekranda ishlamaydigan tugma
  joy egallab, chalg'itardi.
* Ovoz uchun alohida "suhbat" tugmasi ham yo'q - doiraning O'ZI o'sha
  tugma.

Yuborish tugmasi band paytda TO'XTATISH bo'ladi. Alohida tugma qo'shilsa,
ikkalasi ham deyarli doim o'chiq turardi.

Matn maydoni 16px - kichikroq bo'lsa iOS Safari fokuslanganda sahifani
kattalashtiradi va Mini App ichida uni qaytarib bo'lmaydi. Enter yuboradi,
Shift+Enter yangi qator; IME so'z terayotganda (`isComposing`) Enter
yuborMAYDI - u yerda Enter tanlash uchun bosiladi.

KLAVIATURA BALANDLIGI qo'lda boshqariladi: `100dvh` Telegram WebView'da
klaviatura chiqqanda yangilanmaydi va kiritish paneli klaviatura ostida
qolardi. `viewportChanged` hodisasida `tg.viewportStableHeight` body ga
yoziladi (`viewportHeight` EMAS - u animatsiya davomida tebranadi).

Ovozli javob kaliti YUQORI O'NG burchakda, menyudan oldin. U har turnda
emas, bir marta sozlanadigan narsa - pastda, mikrofonning yonida turgani
uni tasodifan bosishga yaqinlashtirardi. Yozuvsiz, faqat karnay ikonkasi:
"Ovozli javob" matni pill va menyu bilan birga tor telefonga sig'masdi.
Holat `aria-pressed` da saqlanadi (skrin-riderlar ham o'qiydi), o'chiq
bo'lsa ikonka chizib tashlanadi.

AVVAL TESKARI EDI: katta doira (`min(62vw, 300px)`) ekranning yarmini olib,
suhbat `max-height: 30dvh` ga siqilardi - uzun javobni telefonda o'qib
bo'lmasdi.

Doira YO'Q QILINMADI, KICHRAYTIRILDI: uning gradienti endi mikrofon
tugmasining foni, va u hamon `--lvl` ga qarab tebranadi. Bu "men sizni
eshityapman" degan yagona ko'rinadigan signal - uni oddiy tugmaga
almashtirish foydalanuvchini mikrofon ishlayaptimi-yo'qmi bilmay qoldirardi.

Tugma ichidagi ikonka holatga qarab almashadi va bu FAQAT CSS bilan
bo'ladi: mikrofon - odatda; to'rtburchak - javob kutilayotganda yoki
o'qilayotganda, ya'ni bosish TO'XTATADI.

Sarlavha + tavsif (3 qator) olib tashlandi - holat yuqoridagi pill'da va
tugma ustidagi bitta qatorda ko'rinadi.

## Ishlatiladigan API

Hammasi bir xil originda (`/api/`), ya'ni CORS yo'q va `connect-src 'self'`
yetarli. Kimlik HAR DOIM `Authorization: Bearer <token>` da.

| Endpoint | Qayerda ishlatiladi |
|---|---|
| `POST /api/v1/auth/login` | kirish oynasi |
| `GET /api/v1/auth/me` | ochilishda sessiyani tiklash |
| `POST /api/v1/auth/logout` | menyudagi "Chiqish" |
| `POST /api/v1/auth/signup` | kirish oynasidagi havola (server hozircha **501**) |
| `POST /api/v1/auth/change-password` | menyudagi forma (server hozircha **501**) |
| `POST /api/v1/stt/transcribe` | yozilgan savolni matnga o'girish |
| `POST /api/v1/tts/speak` | javobni ovoz bilan o'qish |
| `POST /api/v1/chat/stream` | savol -> javob (NDJSON oqimi) |

`/api/v1/chat/ask` ATAYLAB **ishlatilmaydi**: u quvur skeleti
(`services/pipeline.py`, `_ROUTES` bo'sh) va HR Assistant'ga umuman
bormaydi - har qanday savolga bir xil "Venera hozircha sozlanmoqda..."
matnini qaytaradi. Uni zaxira yo'l qilish foydalanuvchiga javob berilgandek
ko'rsatib, aslida hech narsa aytmaslik bo'lardi.

### Javob ekranga qanday chiqadi: `forScreen()`

Xom javob EKRANGA SHUNDAYLIGICHA CHIQMAYDI. Ikki narsa olib tashlanadi:

**1. Audit izi.** Javob oxirida shunday quyruq keladi:

```
Tekshirilgan HRM ma'lumotlari (14.09.2026 07:48):
[T1] hrm_today_late - date=2026-09-14 -> count=9, data=9 rows, status=200
```

Bu xodim uchun emas, tizim uchun yozilgan: `status=200` va `9 rows` savol
bergan odamga hech narsa aytmaydi, lekin javobdan uzunroq bo'lishi mumkin.
Jonli misolda 463 belgilik javobning 141 tasi shu iz edi.

Iz ketgach `[T1]` markerlari ham hech qayerga ishora qilmaydi - ular ham
olib tashlanadi. `[1]`, `[2]` esa QOLADI: ular pastdagi "Manbalar"
ro'yxatiga ishora qiladi va o'sha ro'yxat ko'rinib turadi.

**2. Markdown belgilari.** Sahifa matnni oddiy matn sifatida ko'rsatadi
(`white-space: pre-wrap`), ya'ni `**bo'lim:**` yulduzchalari bilan
ko'rinardi. Ro'yxat belgisi `•` ga aylanadi, qatorlar saqlanadi.

VEB ILOVADAN FARQ ATAYLAB: u izni ekranda QOLDIRADI - u yerda alohida
yig'iladigan bo'lim bor va bank auditi uni talab qiladi. Telegram'da esa
bitta tor ustun, va iz javobni ko'mib yuboradi.

### Manbalar

Javob ostida FAQAT hujjatlar ko'rsatiladi: "[1] ichki mehnat tartibi
qoidalari, 22-bet". Bu texnik iz emas - javob qayerdan olingani, va bank
muhitida xodim javobga ishonmasa aynan shu qatorga qaraydi.

Jonli so'rovlar (`LOOKUP_KINDS = ['hrm', 'crm']`) ekranga CHIQMAYDI: ular
yuqoridagi audit izining ayni o'zi, boshqa shaklda. Izni matndan olib
tashlab, o'sha ma'lumotni pastda qayta ko'rsatish ma'nosiz bo'lardi.

`crm` `hrm` ga 2026-09-14 da qo'shildi; undan oldin CRM manbasi hujjatlar
ro'yxatiga tushib, mavjud bo'lmagan fayl kabi ko'rsatilardi.

### Xato kadri: xizmatning O'Z matni yutadi

`error` kadrida HAR QANDAY kod uchun `frame.text` ko'rsatiladi -
`auth_missing` ham. Avval `auth_missing` uchun o'zimizning "HRM ulanmagan"
gapimiz qo'yilardi va CRM qo'shilganda bu NOTO'G'RI bo'lib qoldi: CRM
savoliga xizmat "CRM tizimiga kiring" deb javob berardi, biz esa odamni
boshqa tizimga yo'naltirardik. Savol qaysi platformani talab qilganini
xizmat biladi, biz bilmaymiz.

Xato kadri TOKENLARDAN KEYIN ham kelishi mumkin. Shunda kelgan javob
saqlanadi va xato faqat IZOH bo'lib ko'rsatiladi - qisman javob baribir
o'qishga arziydi. Faqat hech narsa kelmagan bo'lsa xatoning o'zi javob
o'rniga chiqadi.

### Ovozli javob

Javob **butun holicha, bitta so'rovda** o'qiladi. Bo'laklash YO'Q va bu
ataylab: TTS serverida birinchi bayt matn uzunligidan qat'i nazar ~1.37 s da
keladi, ya'ni bo'laklash hech narsa tejamaydi - faqat har bo'lak uchun yangi
navbat kutilardi.

O'qishdan oldin matn `forSpeech()` dan o'tadi (`VoicePanel.vue` dan aynan
ko'chirilgan): markdown belgilari, `[T1]`/`[HR_045]` iqtibos markerlari,
`(e4)` dalil markerlari va **HRM audit izi** olib tashlanadi. Iz ekranda
qoladi (bank talabi), lekin o'qilmaydi - jonli o'lchovda javobning o'zi
87 belgi, iz bilan birga 614 belgi edi.

Chegara 3000 belgi va u GAP chegarasida kesiladi; backenddagi
`tts_max_chars` (u ham 3000) so'z chegarasida kesadi va zaxira bo'lib
qoladi. Qisqartirilsa foydalanuvchi "Javobning boshi o'qildi - to'lig'i
ekranda" izohini ko'radi.

`signup` va `change-password` ATAYLAB ulangan: server ularni yoqqanda bu
yerda o'zgartirish kerak bo'lmaydi, hozir esa foydalanuvchi serverning o'z
xabarini ko'radi ("Ro'yxatdan o'tish hozircha yopiq...") - jim tugmadan
aniqroq.

## Joylashtirish

Fayllar nginx obraziga **kirmaydi**: frontend qayta yig'ilganda
`/usr/share/nginx/html` butunlay almashadi va obraz ichiga qo'yilgan fayllar
yo'qolardi. Ular host'dan read-only mount qilinadi
(`venera-frontend.service`):

```
~/.local/share/venera-tg  ->  /usr/share/nginx/tg   (ro)
```

Shuning uchun yangilash = nusxalash:

```bash
cp apps/tg/index.html apps/tg/app.js ~/.local/share/venera-tg/
```

Xizmatni qayta ishga tushirish **shart emas** - nginx faylni har so'rovda
diskdan o'qiydi, va `/tg/` javobida `Cache-Control: no-cache` turadi.

Tekshirish:

```bash
curl -si https://llm.brb-tech.uz/tg/ | head -1
curl -s  https://llm.brb-tech.uz/tg/app.js | md5sum
md5sum apps/tg/app.js
```

## Sarlavhalar (nginx)

`/tg/` location'i `apps/web/deploy/nginx.container.conf` da. Ikkita ataylab
qilingan farq bor va ularni **yo'qotib qo'ymang**:

* `script-src ... https://telegram.org` - Mini App SDK shu yerdan keladi.
* `frame-ancestors ...telegram.org` (`'none'` o'rniga) - Telegram Web va
  Desktop Mini App'ni iframe'da ochadi. `X-Frame-Options` ataylab YO'Q: unda
  origin ro'yxati yo'q, ya'ni DENY ham, SAMEORIGIN ham Telegram'ni to'sardi.

Mikrofon uchun `Permissions-Policy: microphone=(self)` bor. **Diqqat:**
Telegram **Web** (brauzerdagi `web.telegram.org`) sahifani iframe'da ochadi,
va u yerda mikrofon ota-sahifa `allow="microphone"` bergandagina ishlaydi -
bu bizning qo'limizda emas. Telefondagi Telegram esa WebView ishlatadi va
u yerda cheklov yo'q. Ovoz bilan ishlashni **telefonda** sinang.

## Sessiya qayerda saqlanadi

`localStorage`, kalit `venera_token` - veb ilova bilan **bir xil**. Ikkala
sahifa ham `llm.brb-tech.uz` originida, ya'ni storage bo'linmagan brauzerda
bir marta kirgan odam ikkinchi marta kirmaydi.

Telegram'ning `CloudStorage` API si ATAYLAB ishlatilmagan: u qulayroq
(qurilmalar orasida saqlanadi), lekin bank ichki tizimining sessiya tokenini
Telegram serveriga yozib qo'yardi.

## Uyg'otish so'zi bu yerda YO'Q

Veb ilovada "Salom Venera" bor, Mini App'da ATAYLAB yo'q va
`POST /api/v1/stt/wake` chaqirilmaydi. Sabab: Telegram'da savol har doim
ilovani ochib, doirani bosishdan boshlanadi - ya'ni mikrofonni doim ochiq
tutib, har 2.5 soniyada STT routerga parcha yuborishning sababi yo'q.
Router butun park uchun ~10 ta bir vaqtli so'rov ko'taradi, va bu byudjet
haqiqiy savollarga qoladi.

Kerak bo'lsa manba `apps/web/src/composables/useWakeWord.ts` da turibdi.

## Hali yo'q narsalar

* **Bot yo'q.** Bu sahifa BotFather'da Mini App sifatida ulangan bo'lishi
  kerak; `/start`, buyruqlar, push xabarlar uchun bot kodi kerak - u hali
  yozilmagan.
* **`initData` tekshirilmaydi.** Telegram foydalanuvchisi va Venera hisobi
  bog'lanmagan, shuning uchun kirish oddiy email + parol bilan. Bog'lash
  uchun serverda `initData` ning HMAC imzosini tekshiradigan endpoint kerak.
* **Hujjat yuklab olish** (`/chat/artifact/...`, `/chat/doc/...`) ulanmagan:
  Telegram WebView ichida yuklab olish ishonchsiz. Oqimda `artifact` kadri
  kelsa, sahifa faqat nomini aytadi.
