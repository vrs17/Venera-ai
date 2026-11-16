# Barno AI (mobil ilova)

> Mahsulot nomi 2026-10-09 dan **Barno AI** (avval "Venera AI"). Texnik nomlar
> o'zgarmaydi: paket `uz.brbtech.venera.meetings`, sxema `venera-rec`, `VENERA_*` env,
> `X-Venera-Client` sarlavhasi, `venera-entry` moduli.

**Asosiy ekran - Barno bilan NATIVE chat** (React Native; sayt WebView'da EMAS).
Dizayn va mantiq Telegram Mini App'niki bilan bir xil: javob oqim bilan keladi
(NDJSON, `src/api/chat.ts` - XHR `onprogress`), Markdown (jadval, ro'yxat, kod,
`[1]` manba belgilari - `markdown-it`), manbalar oynasi, ariza (DOCX/PDF) havolasi,
CRM taklif kartasi (tasdiqlash), suhbatlar tarixi (nomini o'zgartirish, o'chirish),
"Pro" kaliti, Claude uslubidagi yozish maydoni va diktovka (✕ bekor, ■ to'xtatib
tahrirlash, ↑ darhol yuborish). So'rovlar `X-Venera-Client: mobile` bilan ketadi -
server mobil kanalni AI dvigatel v3 ("Barno Core") ga yo'naltiradi
(`HRM_ASSISTANT_ENGINE_BY_CHANNEL=mobile=v3`, deploy'da).

**Ikkinchi bo'lim - yig'ilish yozuvlari (native).** Yig'ilishni telefonda yozib
oladi, Barno AI serveriga yuklaydi va natijani ko'rsatadi: spikerlar bo'yicha
ajratilgan transkript (chat ko'rinishida), xulosa (vazifalar, qarorlar, ochiq
savollar, xavflar, raqamlar, sanalar va boshqalar; ostida qaysi model yozgani -
"Xulosa: Barno Core" / "GPT (...)" / "Gemma"), vazifalar ro'yxati va **Chat** tabi -
shu bitta yozuv bo'yicha Barno bilan suhbat (`/meetings/{id}/chat`, javobni Claude yozadi,
suhbatni eslab qoladi; Telegram'dagi savollar bilan bitta suhbat, Slack'da esa har odamning suhbati
alohida; "Yangi suhbat" eskisini arxivlaydi; har xabar o'z `clientId` kaliti bilan ketadi - javob yo'lda
yo'qolsa ham "Qayta yuborish" takror savol-javob yaratmaydi). Vazifani **CRMga qo'shish** - Barno (v3) CRM vazifasi TAKLIFINI
tayyorlaydi, ilova uni kartada ko'rsatadi va faqat "Tasdiqlash" dan keyin CRM ga
yoziladi (chatdagi taklif kartalari bilan aynan bir yo'l: `/api/v1/actions`). Unga Sozlamalardagi
**"Yig'ilish yozuvlari"** qatori va yon tugma (`venera-rec://record`, 6-bo'lim)
olib keladi. To'liq shartnoma: `docs/plans/meeting-recorder.md` (7-bo'lim - mobil).

- Stek: Expo SDK 57, React Native 0.86, TypeScript (strict), expo-router.
- Android birinchi (iOS keyin). `android/` va `ios/` papkalari **generatsiya
  qilinadi** (`expo prebuild`) va gitga tushmaydi.
- Expo Go ishlamaydi (o'zimizning native modul bor) - `expo-dev-client` yoki
  release APK.

## Tuzilma

```
app.config.ts            ilova nomi, paket, ruxsatlar, plaginlar (APP_VARIANT, VENERA_API_URL)
modules/venera-entry/    Kotlin: "Yozish" launcher belgisi, Quick Settings plitkasi
plugins/                 config plugin: release imzosi (withReleaseSigning.js)
src/app/                 ekranlar (expo-router): index = chat, meetings = ro'yxat,
                         yozish, yig'ilish, vazifalar, sozlamalar, login
src/api/                 server shartnomasi (types.ts), har bir endpoint (meetings.ts), takliflar (actions.ts)
src/features/chat/       chat: holat (chatStore - oqim, to'xtatish, tarix), tarix ro'yxati,
                         Pro, klaviatura; ui/ - yozish maydoni, xabar, Markdown, oynalar
src/features/recorder/   yozuvchi (expo-audio, ADTS), holat mashinasi, belgilar
src/features/upload/     oflayn navbat (SQLite) va rezyumli bo'lakli yuklash
src/features/auth/       sessiya: login, qurilma tokeni (SecureStore), JWT o'qish
src/features/entry/      deep link, ishonchli kalit, ilova yorlig'i
src/features/meeting/    xulosa modeli, transkript pufakchalari, tablar, pleer
src/features/crm/        vazifa -> CRM taklifi: jarayon (crmStore), taklif kartasi, holat modeli
src/i18n/                uz (asosiy), ru, en
__tests__/               Jest testlari
```

## 1. Kompyuterga nima kerak

Bu qadamlar **dasturchi kompyuterida** bajariladi (Barno AI serverida emas -
u yerda JDK/Android SDK yo'q va xotira yetmaydi).

| Narsa | Versiya |
|---|---|
| Node.js | 22.x (`node -v`) |
| JDK | 17 (Android Studio ichidagi JBR ham bo'ladi) |
| Android Studio | oxirgi barqaror; SDK Manager'da **Android SDK Platform 36**, **Build-Tools 36**, **Platform-Tools**, **NDK** (Studio so'rasa) |
| RAM | kamida 8 GB (16 GB tavsiya) |
| Telefon | Samsung Galaxy (Android 10+), USB debugging yoqilgan |

Muhit o'zgaruvchilari (Linux/macOS misoli, Windows'da "Environment Variables"):

```bash
export ANDROID_HOME=$HOME/Android/Sdk          # macOS: $HOME/Library/Android/sdk
export PATH=$PATH:$ANDROID_HOME/platform-tools
export JAVA_HOME=/path/to/jdk-17               # Android Studio: .../jbr
```

Telefonda USB debugging: Sozlamalar > Telefon haqida > Dastur ta'minoti
ma'lumotlari > "Build raqami" ni 7 marta bosing > Dasturchi parametrlari > USB
orqali nosozliklarni tuzatish. Kabel bilan ulang va `adb devices` telefonni
ko'rsatishini tekshiring.

## 2. Kodni olish

```bash
git clone <repo> && cd Venera
git checkout venera-meeting-recorder
cd apps/mobile
npm ci
```

## 3. Dev client (dev API bilan, kod o'zgarishi darhol ko'rinadi)

Dev API serverda `:8001` portda ishlaydi. Dev `.env` da `MEETINGS_ENABLED=true`
bo'lishi kerak (bo'lim kirgan har bir xodimga ochiq).

**Muhim:** `app.config.ts` har Expo buyrug'ida (`prebuild`, `run:android`,
`start`) qayta o'qiladi va dev client API manzilini Metro bergan manifestdan
oladi. O'zgaruvchilar faqat `prebuild` ga berilsa, dev client **prod**
(`https://llm.brb-tech.uz`, bayroq o'chiq) ga ulanadi va faqat "Bu funksiya siz
uchun hali yoqilmagan" ko'rinadi. Shuning uchun ularni bir marta faylga yozing
(Expo CLI `.env` fayllarini o'zi yuklaydi; `.env.*` gitga tushmaydi):

```bash
cat > .env.local <<'ENV'
APP_VARIANT=development
VENERA_API_URL=http://<SERVER-LAN-IP>:8001
ENV
npx expo prebuild -p android --clean
npx expo run:android      # yig'adi, telefonga o'rnatadi va kompyuterda Metro'ni ishga tushiradi
# keyingi safar faqat JS o'zgarsa:
npx expo start --dev-client
```

(`.env.local` siz: o'zgaruvchilarni HAR buyruqqa yozing -
`APP_VARIANT=development VENERA_API_URL=http://<SERVER-LAN-IP>:8001 npx expo run:android`,
`... npx expo start --dev-client`.) Tekshirish: ilovada Sozlamalar > Hisob
ostida `Server: http://<SERVER-LAN-IP>:8001` ko'rinishi kerak.

- `APP_VARIANT=development` faqat dev build'da oddiy HTTP'ga ruxsat beradi
  (`usesCleartextTraffic`). Prod build doim HTTPS.
- Telefon va kompyuter bitta tarmoqda bo'lsin (Metro uchun).
- Faqat Gradle bilan debug APK kerak bo'lsa: `cd android && ./gradlew assembleDebug`
  -> `android/app/build/outputs/apk/debug/app-debug.apk`. Bu dev client - u ham
  Metro'ga ulanadi.
- Pilot APK yig'ishdan oldin `.env.local` ni o'chiring yoki
  `APP_VARIANT=production` qiling (4-bo'lim).

## 4. Pilot uchun release APK (prod API, Metro'siz)

**Avval imzo kaliti (birinchi pilot APK'dan OLDIN, majburiy).** Expo shabloni
release'ni *debug* kalit bilan imzolaydi - bunday APK o'rnatiladi, lekin u
pilotga ketsa keyingi to'g'ri imzolangan yangilanish "imzo mos emas" bilan
o'rnatilmaydi, o'chirib qayta o'rnatish esa telefondagi hali yuklanmagan
yozuvlarni o'chiradi. Shuning uchun `plugins/withReleaseSigning.js` (app.config.ts
da ulangan, `prebuild --clean` dan keyin ham qoladi) release'ni faqat shu kalit
bilan imzolaydi, kalit bo'lmasa `assembleRelease` xato bilan to'xtaydi.

Bir marta kalit yarating (**hech qachon gitga qo'shmang**, zaxira nusxasini
xavfsiz joyda saqlang - yo'qolsa ilovani yangilab bo'lmaydi):

```bash
keytool -genkeypair -v -keystore venera-yozuv.jks -alias venera -keyalg RSA -keysize 2048 -validity 10000
```

`~/.gradle/gradle.properties` ga (repo ichidagi faylga EMAS):

```
VENERA_STORE_FILE=/absolute/path/venera-yozuv.jks
VENERA_STORE_PASSWORD=...
VENERA_KEY_ALIAS=venera
VENERA_KEY_PASSWORD=...
```

Keyin:

```bash
rm -f .env.local                      # yoki undagi APP_VARIANT=production
APP_VARIANT=production npx expo prebuild -p android --clean
cd android && ./gradlew assembleRelease
# natija: android/app/build/outputs/apk/release/app-release.apk (venera-yozuv.jks bilan imzolangan)
apksigner verify --print-certs app/build/outputs/apk/release/app-release.apk   # SHA-256 ni yozib qo'ying
```

Faqat o'zingiz sinash uchun (pilotga BERILMAYDI): `./gradlew assembleRelease
-PveneraAllowDebugSigned=true` - debug kalit bilan imzolanadi.

**Tarqatishdan oldin - majburiy tekshiruv** (har bir APK, arm64 va universal ham):

```bash
python3 scripts/check_apk.py android/app/build/outputs/apk/release/app-release.apk --expect-cert <SHA-256>
```

Chiqish kodi 0 bo'lmasa APK'ni APK API'ga / Telegram botga BERMANG. Skript to'xtatadi:
debug kalit (ayniqsa React Native shablonidagi ochiq kalit), boshqa kalit (`--expect-cert` -
birinchi release'da yozib qo'yilgan SHA-256; kalit almashsa o'rnatilgan ilova yangilanmaydi),
Play Protect sideload'da to'sadigan ruxsat yoki xizmat (SMS, qo'ng'iroqlar jurnali, Accessibility,
bildirishnoma tinglovchi - 2026-11-06 da 1.3.5 aynan Accessibility tufayli "App not installed"
bo'lgan), debuggable/testOnly, eski targetSdk, siqilgan resources.arsc yoki .so. Faqat standart
Python - build serverga hech narsa o'rnatilmaydi.

**Tarqatish.** Reliz APK 10.10.50.4 build serverida yig'iladi (`~/Barno_AI`, `scripts/build-barno.sh`):
`check_apk.py` dan o'tmagan APK saqlanmaydi va tarqatilmaydi. Foydalanuvchilarga Telegram bot orqali
beriladi: «📲 Ilovani yuklab olish» tugmasi (`apps/api/app/bot/mobile_app.py`) APK'ni .4 dagi APK API'dan
(`MOBILE_APK_API`, arm64 variant) oladi. Release kalit sertifikati (1.3.6 dan boshlab) SHA-256
`EF710FF1662C7D792889A76B0608D745288632CC61F8A79B2A72C9ACCFD970BB`. 1.3.5 va eskiroq versiyalar debug kalit
bilan imzolangan, ular o'rnatilgan telefonda avval eski ilovani o'chirish kerak (yuborilmagan yozuvlar ham
o'chadi - avval hammasi yuklanganini tekshiring). EAS Build
(`npx eas-cli build -p android --profile preview`) ham mumkin, lekin unda kod
kompaniyadan tashqariga chiqadi - lead ruxsati kerak.

## 5. APK'ni telefonga o'rnatish

- Kabel bilan: `adb install -r android/app/build/outputs/apk/release/app-release.apk`
- Yoki faylni telefonga yuboring va oching: "Noma'lum manbalardan o'rnatish"ga
  shu ilova (Fayllar/Telegram) uchun ruxsat bering.

Birinchi ochilishda: kirish ekrani (HRM/CRM login va paroli, Telegram'dagi bilan
bir xil) -> keyingi safar avtomatik kiradi (qurilma tokeni 30 kun - yig'ilishlar
bo'limi yoqilgan odamlarda; boshqalarda JWT muddati, 12 soat). Yozishda mikrofon
va bildirishnoma ruxsatini bering (bildirishnomasiz Android ekran o'chganda
yozuvni to'xtatadi). Chatdagi diktovka ham shu RECORD_AUDIO ruxsatini so'raydi.
Samsung'da: Sozlamalar > Batareya > Fon rejimidagi cheklovlar > "Hech qachon
uxlamaydigan ilovalar" ro'yxatiga **Barno AI** ilovasini qo'shing.

## 5a. Chat qanday ishlaydi

- **Oqim.** `POST /api/v1/chat/stream` - NDJSON kadrlar (stage, sources, artifact,
  proposal, token, error, done). RN `fetch` tanani oqim qilib bermaydi, shuning uchun
  XHR: `onprogress` da o'sgan `responseText` qatorlarga bo'linadi (`createNdjsonParser`).
  401 - token bir marta yangilanadi (faqat hali hech narsa kelmagan bo'lsa).
- **Mantiq Mini App'niki** (`apps/web/src/tg/chat/useTgChat.ts`): xato kadri tokenlardan
  keyin kelsa javob saqlanadi (izoh bilan), "Pro" savol yuborilgan paytda qotiriladi,
  tarixdan ochilgan suhbat 404 bo'lsa - yangi suhbat. HRM/CRM ulanmagan
  (`auth_missing`/`auth_expired`) - "Qayta ulash" (qayta kirish ulanishlarni yangilaydi).
- **Diktovka:** yig'ilish yozuvi bilan bir xil format (AAC ADTS, 16 kHz) ->
  `POST /api/v1/stt/transcribe` (Gapi). Matn maydonga tushadi; ↑ bosilgan bo'lsa o'zi
  yuboriladi. Yig'ilish yozilayotganda diktovka ishlamaydi (mikrofon band).
- **Klaviatura:** edge-to-edge Android'da oyna qisqarmaydi - ekran pastiga klaviatura
  balandligicha bo'shliq qo'shiladi (`src/features/chat/keyboard.ts`).

## 6. Yon tugma bilan tez yozish (Samsung)

Quvvat tugmasini ikki marta bosishni hech bir ilova ushlay olmaydi (Android
buni tizim uchun saqlaydi). Shuning uchun Samsung'ning o'z sozlamasidan
foydalanamiz - u istalgan ilova belgisini ochadi:

1. Barno AI > Sozlamalar > **Tez yozish** > `"Yozish" belgisini yoqish`.
   Ilovalar ro'yxatida alohida **Yozish** belgisi paydo bo'ladi.
2. Telefon Sozlamalari > Qo'shimcha funksiyalar > **Yon tugma** >
   **Ikki marta bosish** ni yoqing > **Ilovani ochish** > **Yozish**.
3. Endi yon tugmani ikki marta bosish = yozish darhol boshlanadi (telefon
   qulfdan chiqarilgan bo'lishi kerak; qulflangan bo'lsa Samsung avval PIN/barmoq
   izini so'raydi). Yana ikki marta bosish = yozuv to'xtaydi va saqlanadi
   (almashtirgich, plitka kabi).

Boshqa yo'llar:
- **Pixel:** Sozlamalar > Tizim > Imo-ishoralar > Quick Tap > Ilovani ochish > Yozish.
- **Istalgan telefon:** tezkor panelni tushiring > Tahrirlash > **Yozish**
  plitkasini sudrab qo'ying (Android 13+ da ilova o'zi "plitka qo'shish" oynasini
  ko'rsatadi). Plitka yozish paytida bosilsa - yozuvni to'xtatadi.
- Ilova belgisini bosib turing > **Yozishni boshlash** (bosh ekranga sudrash mumkin).
- Yozish bildirishnomasidagi **Stop** yozuvni saqlab to'xtatadi. Qulflangan
  ekranda bu tugma ko'rinmaydi (expo-audio bildirishnomasi `VISIBILITY_SECRET`):
  telefonni oching yoki plitkani bosing (u qulfdan chiqarishni so'raydi).
  O'zbekcha bildirishnoma va qulf ekranidagi Stop - M3 (o'z servisimiz).
- Yozuv 3 soat limitga yetsa ekran o'chiq bo'lsa ham o'zi to'xtaydi va saqlanadi
  (native fayl hajmi chegarasi, limitdan ~1 daqiqa oldin).

Xavfsizlik: bu kirish nuqtalari `venera-rec://record?...&k=<kalit>` havolasini
ochadi. Yozish faqat kalit to'g'ri bo'lsa avtomatik boshlanadi; begona havola
faqat Yozish ekranini ochadi.

## 7. Agar Kotlin modul kompilyatsiya bo'lmasa

`modules/venera-entry` (plitka + launcher belgisi) shu serverda kompilyatsiya
qilinmagan. Birinchi build'da xato bersa, `package.json` ga qo'shing:

```json
"expo": { "autolinking": { "exclude": ["venera-entry"] } }
```

va qayta `prebuild`. Ilova to'liq ishlaydi (deep link va ilova yorlig'i
qoladi), faqat plitka va "Yozish" belgisi bo'lmaydi. Xatoni lead'ga yuboring.

## 8. Tekshirish (serverda ham ishlaydi - Gradle/Metro'siz)

```bash
npm ci
npx tsc --noEmit
npx eslint .
npx jest --maxWorkers=2
# ixtiyoriy: plaginlar natijasini ko'rish (fayl yozmaydi)
EXPO_OFFLINE=1 npx expo config --type introspect
```

Testlar haqiqiy tarmoq, mikrofon yoki Gapi/Ollama'ga murojaat qilmaydi -
hammasi soxta (fake) servis va mock'lar bilan (`jest.setup.js`; chat oqimi -
soxta XHR, `__tests__/chatStream.test.ts`).

## 9. Maxfiylik

Audio GAPI (console.gapi.uz) ga, transkript Ollama Cloud (gemma4:31b) ga
yuboriladi. Bu yangi ma'lumot turi: prod'da `MEETINGS_ENABLED` foydalanuvchi
(rahbar) aniq rozilik bermaguncha `false` qoladi. Yozishdan oldin
ishtirokchilarni ogohlantiring. Telefondagi audio server qabul qilgani zahoti
o'chiriladi (yoki sozlamaga ko'ra 7 kundan keyin); chiqishda yozuvlar, navbat
va tokenlar tozalanadi.
