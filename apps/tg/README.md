# Venera - Telegram Mini App (`/tg/`) - ESKI, ISHLATILMAYDI

> **2026-10: `/tg/` endi yangi Mini App'ni beradi** - web kod bazasida
> (`apps/web/tg-app.html`, `apps/web/src/tg/`), frontend image ichida yig'iladi
> (`apps/web/deploy/nginx.container.conf`, `location /tg/`). Bu papka faqat QAYTARISH
> (rollback) uchun saqlanadi: host mount `~/.local/share/venera-tg` hali systemd
> unit'da turibdi. Barqaror davrdan keyin papka ham, mount ham olib tashlanadi.
> Quyidagi matn - eski ilova qanday ishlagani haqida.

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

* Dok ichidagi alohida mikrofon ikonkasi YO'Q - doiraning O'ZI mikrofon.
  Ovoz uchun alohida "suhbat" tugmasi ham yo'q.
* `+` menyusi BOR (2026-09-16 dan) - veb'dagi bilan bir xil: "Rasm
  qo'shish" (tez orada, bosilmaydi) va "Ulanishlar" (HRM, CRM). Avval u
  ataylab yo'q edi: veb'da ikkala qator ham o'chiq turardi va tor ekranda
  ishlamaydigan tugma chalg'itardi. Endi unda ishlaydigan narsa bor.
  Menyu panel USTIDA ochiladi (sheet emas - u ikki qator xolos), ro'yxat
  esa "Ulanishlar" qatori OSTIDA - veb ilovaning mobil ko'rinishi kabi
  (yon panel tor ekranga sig'maydi). Qarang: "Ulanishlar" bo'limi.

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
| `POST /api/v1/chat/artifact/{token}/{docx,pdf}/link` | "DOCX/PDF yuklab olish" - 10 daqiqalik imzolangan havola |
| `GET /api/v1/chat/file/{imzo}` | faylni Telegram'ning O'ZI oladi (sessiyasiz) |
| `GET /api/v1/chats` | "Suhbatlar" varag'i - har ochilishda |
| `GET /api/v1/chats/{id}` | suhbatni ochish, ilova ochilganda oxirgi suhbat |
| `PATCH /api/v1/chats/{id}` | qatordagi "Nomini o'zgartirish" |
| `DELETE /api/v1/chats/{id}` | qatordagi "O'chirish" (yumshoq) |
| `POST /api/v1/chats/{id}/restore` | "Bekor qilish" |
| `GET /api/v1/connectors` | "+" menyusi ochilganda - HRM/CRM holati |
| `POST /api/v1/connectors/{hrm,crm}/connect` | ulanish oynasi (login + parol) |
| `PATCH /api/v1/connectors/{hrm,crm}` | qatordagi kalit (chatda ishlatish) |
| `DELETE /api/v1/connectors/{hrm,crm}` | hisob oynasidagi "Uzish" (tasdiq bilan) |
| `POST /api/v1/actions/{token}/confirm` | taklif kartasidagi "Tasdiqlash" |
| `POST /api/v1/actions/{token}/cancel` | taklif kartasidagi "Rad etish" |

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

**Qonunchilik manbasi** (yordamchining v2 dvigateli, 2026-10-02): `kind:
"law"` - LEX.UZ dagi modda, `url` bor, `doc_id` yo'q. Ro'yxatda "[2] LEX.UZ ·
qonunchilik: Mehnat kodeksi, 160-modda — ..." bo'lib chiqadi, modda nomi -
HAVOLA. Bosilsa `Telegram.WebApp.openLink` bilan Telegram'ning tashqi
brauzerida ochiladi (Mini App yopilmaydi); Telegram'dan tashqarida -
`window.open(..., 'noopener')`. Hujjat ko'ruvchisiga (`/chat/doc/...`) HECH
QACHON yuborilmaydi. Havola faqat `https://` va login-parolsiz bo'lsa
(`lawUrl`): server ham tekshiradi, lekin manbalar `localStorage` dan ham
qayta chiqadi. Qaysi dvigatel ishlatilishi serverda (`HRM_ASSISTANT_ENGINE`,
`HRM_ASSISTANT_ENGINE_BY_CHANNEL=miniapp=...`) - Mini App buni bilmaydi.

**"Pro" Mini App'da YO'Q** (tugma ham, `mode` maydoni ham): u faqat web
ilovada. Mini App `mode` yubormaydi, ya'ni har savol standart rejimda.

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

## Suhbatlar tarixi

Yuqori qatordagi soat belgisi "Suhbatlar" varag'ini ochadi: kunlar bo'yicha
guruhlangan ro'yxat (Bugun, Kecha, Oxirgi 7 kun, Oldinroq), "+ Yangi suhbat",
qatorda nomini o'zgartirish va o'chirish ("Bekor qilish" 8 soniya turadi).
`app.js` 12b-bo'lim - veb ilovadagi `useChats.ts` + `ChatHistory.vue` ning
nusxasi.

* **Veb bilan bitta ro'yxat.** Suhbatlar yuqoridagi xizmatda `chatId` bo'yicha
  saqlanadi, kimlikni esa backend TOKEN'DAN qo'yadi (`venera:{actorId}`).
  Bir hisob = bir ro'yxat: vebda boshlangan suhbat shu yerda ochiladi va
  davom ettiriladi, teskarisi ham.
* **Ilova ochilganda oxirgi suhbat ekranga qaytadi.** Kalit (`venera_tg_chat`)
  avval ham saqlanardi va xizmat suhbatni eslab turardi, lekin ekran bo'sh
  edi.
* **O'chirilgan suhbat kaliti ishlatilmaydi.** Ochishda 404 (boshqa qurilmada
  o'chirilgan) bo'lsa, yangi kalit olinadi: eski kalit bilan savol berish
  o'chirilgan suhbatni qayta tiriltirardi.
* Suhbatdan **200** xabar olinadi (`LOG_LIMIT`), ekranda esa **240** tagacha
  turadi (`LOG_KEEP`; avval 20 edi). Farq ataylab: teng bo'lsa 200 xabarli
  suhbat ochilgach birinchi yangi savoldanoq eski xabarlar qirqilardi.
* **Xabar vaqti** har pufakchada, DOIM ko'rinadi (sensorli ekranda "ustiga
  olib borish" yo'q): bugungi uchun "11:39", eskisi "18-sentabr, 11:39",
  o'tgan yilniki yil bilan. O'zbek oy nomlari QO'LDA - `Intl` o'zbek uchun
  "M09 18" beradi (`apps/web/src/time.ts` bilan bir xil). Tarixdan ochilgan
  xabarda vaqt SERVERNIKI (`created_at`); yo'q bo'lsa ko'rsatilmaydi. Javobga
  vaqt oqim TUGAGACH qo'yiladi.
* **Manbalar xotirasi.** Server manbalarni (`[1]` hujjatlar) xabar bilan
  saqlamaydi. Shuning uchun ular SHU qurilmada eslab qolinadi
  (`venera_tg_sources`, suhbat kaliti + javob boshining 120 belgisi,
  60 suhbatgacha) va suhbat qayta ochilganda qaytariladi -
  `apps/web/src/sourcesCache.ts` nusxasi. Boshqa qurilmada ochilgan suhbatda
  manbalar bo'lmaydi. "Chiqish" xotirani o'chiradi (hujjat nomlari keyingi
  odamga qolmasin); sessiya tugashi o'chirmaydi.
* Nom tahrirlanayotganda fon yangilanishi ro'yxatni QAYTA CHIZMAYDI (aks holda
  yozilayotgan nom yo'qolardi); qayta chizilganda fokus o'sha qatorga qaytadi.
* Varaq ochiq turganda javob kelsa, ro'yxat yangilanadi - yangi suhbat darhol
  ko'rinadi.

## Hujjatni yuklab olish

Javob ariza yaratsa (`artifact` kadri), "Hujjat tayyorlandi" qatori ostida
"DOCX yuklab olish" va "PDF yuklab olish" tugmalari chiqadi (`app.js`,
12c-bo'lim).

**Nega `<a download>` emas (vebdagi kabi).** Telegram WebView ichida `blob:`
havola bilan yuklab olish ishonchsiz - iOS uni umuman bajarmaydi.
`WebApp.downloadFile` (Bot API 8.0) faylni Telegram ilovasining O'ZI yuklaydi
va saqlashni taklif qiladi, lekin u bizning `Authorization` sarlavhamizni
yubora olmaydi. Shuning uchun:

1. tugma `POST .../artifact/{token}/{kind}/link` ni SESSIYA bilan chaqiradi;
2. server 10 daqiqalik imzolangan havola beradi (`/api/v1/chat/file/{imzo}`);
3. `tg.downloadFile({url, file_name})` - Telegram faylni shu havoladan oladi.

Eski Telegram'da (8.0 dan past) havola `tg.openLink` bilan tashqi brauzerda
ochiladi va u faylni `Content-Disposition: attachment` bo'yicha o'zi saqlaydi.

**Havola - kirish tokeni emas.** U boshqa `aud` (`venera:file`) bilan
imzolanadi: API'ga kira olmaydi, sessiya tokeni esa havola o'rnida
ishlamaydi. Faqat bitta fayl, bitta tur, 10 daqiqa. Javobda Telegram hujjati
talab qilgan `Access-Control-Allow-Origin: https://web.telegram.org` bor
(Telegram Web faylni brauzer ichida `fetch` bilan oladi).

## Ulanishlar (HRM, CRM)

`apps/web` dagi `useConnectors.ts` + `ComposerMenu.vue` + `ConnectorList.vue`
+ `ConnectorDialog.vue` ning nusxasi (`app.js`, 15-bo'lim). Bir xil
so'rovlar, bir xil matnlar (`i18n.ts` dagi o'zbekcha lotin satrlari).

MANBA - SERVER. Tokenlar `apps/api` da turadi (`data/connectors/`), sahifa
faqat holatni ko'radi: ulanmagan / ulangan (login bilan) / muddati tugagan.
Parol `POST .../connect` bilan serverga ketadi va hech qayerda saqlanmaydi.
Ro'yxat har ochilishda qaytadan so'raladi - HRM sessiyasi 10 soatda
tugaydi, CRM refresh rad etilishi mumkin.

Qator: nom + izoh (bosilsa oyna), ulanganida tishli g'ildirak (hisob
oynasi: uzish) va kalit (chatda ishlatish, optimistik - server rad etsa
qaytadi); ulanmaganida "+" (ulanish oynasi). Oyna: login + parol; xato
bo'lsa serverning O'Z xabari ("Login yoki parol noto'g'ri"). 401 bu yerda
VENERA sessiyasi - platforma paroli xato bo'lsa server 400 qaytaradi.
Uzish ikki bosqichli: "Uzish" -> "HRM dan uzilasizmi?" (Yo'q / Ha, uzish).

Chiqishda holat unutiladi, menyu va oyna yopiladi.

## Taklif kartasi (yozuv amallari)

`ActionCard.vue` ning nusxasi (`app.js`, 16-bo'lim). Oqimda `proposal`
kadri kelsa (maydonlar `proposal` ichida yoki kadrning o'zida - `artifact`
kabi) javob pufakchasi ichida karta chiziladi: xulosa, obyekt, maydonlar
(eski -> yangi), ogohlantirishlar, "Rad etish" / "Tasdiqlash". HECH NARSA
O'ZGARMAGAN: faqat "Tasdiqlash" bosilganda `POST /actions/{token}/confirm`
ketadi. Natija kartada qoladi: Bajarildi (platforma qaytargan kalit bilan)
/ Rad etildi / Muddati tugagan / Bajarilmadi (sabab bilan); tugmalar
yo'qoladi. Ovoz taklifni O'QIMAYDI - faqat javob matnini.

## Dev serverda ko'rish

Vite (`apps/web/vite.config.ts`, `tgMiniApp` plugini, faqat `serve`)
`apps/tg/` ni `/tg/` ostida beradi - production'dagi nginx kabi:

```
http://10.10.50.8:5174/tg/
```

`/api` o'sha proxy orqali dev API ga ketadi. Mikrofon LAN manzilida
ishlamaydi (HTTPS kerak), lekin kirish, chat, "+" menyusi va ulanishlar
sinaladi. Production bundle'ga ta'sir yo'q - fayllar dist/ ga tushmaydi.

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

> **DIQQAT - repodagi fayl jonlidan OLDINDA.** Ulanishlar ("+" menyusi,
> HRM/CRM hisobini ulash, `app.js` 15-bo'lim) hali CHIQARILMAGAN. Yuqoridagi
> to'liq nusxalash ularni ham jonliga olib chiqadi. Hozircha jonli faylga
> o'zgarishlar ALOHIDA, faqat o'zi kiritiladi. 2026-09-23 da shunday
> kiritilganlar: suhbatlar tarixi (12b), hujjatni yuklab olish (12c), taklif
> kartasi (16 + karta uchun 16a yordamchilar). Har biridan oldin zahira:
> `~/.local/share/venera-tg/*.bak-<sana>-<nom>`.
>
> 2026-09-29 holati: jonli nusxa (2026-09-23 12:29) = shu fayl MINUS 15-bo'lim
> (va "+" uslublari) MINUS xabar vaqti va manbalar xotirasi (12b, ular
> `venera-ui-2026-backup` tegidagi f2cb86e/833d333 dan keyin qo'shildi).
> Jonlida repoda yo'q funksiya YO'Q - farq faqat ayirish, izoh matni va
> 13-bo'limning joyi. Keyingi joylashtirish to'liq nusxalash bo'lsa, "+"
> menyusi ham chiqadi - bu alohida qaror.

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
* **Iqtibos qilingan hujjatlar** (`/chat/doc/...`, "Manbalar: [1] ...")
  hali ochilmaydi - faqat nomi ko'rinadi. Yaratilgan ariza esa yuklab
  olinadi (pastda, "Hujjatni yuklab olish").

## Bot chati (Telegram'ning o'zi)

Mini app ochilganda (`enterApp`) Telegram `initData` si bilan
`POST /api/v1/telegram/link` chaqiriladi - shundan keyin odam botga oddiy
xabar yoki ovozli xabar yozsa, javob shu hisob nomidan keladi. Chiqishda
(`logout`) avval `/unlink`. Xato jim: bot o'chiq bo'lsa ham ilova to'liq
ishlaydi. Tafsilot: `docs/deploy-api.md`, "Telegram bot".
