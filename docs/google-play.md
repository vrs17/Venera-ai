# Barno — Google Play'ga chiqarish (Android dasturchi uchun topshiriq)

Holat: 2026-11-20. Kod: `main`, commit `75e951e`, tag `mobile-v1.3.23`. Mobil ilova `apps/mobile`
papkasida (Expo SDK 57, React Native). Store materiallari: [`docs/google-play/`](google-play/).

## Qisqacha

- Bu Google Play'dagi **yangi ilova**: package **`uz.brbtech.barno`**, nomi **«Barno»**. Package birinchi
  AAB yuklanganda qotadi, keyin uni o'zgartirib bo'lmaydi.
- Ichki APK kanali (`uz.brbtech.venera.meetings`: APK yuklab olish serveri va Telegram bot) alohida
  ilova bo'lib qoladi. Play ishlari unga tegmaydi.
- **Play App Signing:** ilova imzo kalitini Google yaratadi va saqlaydi. Biz AAB'ni faqat **upload key**
  bilan imzolaymiz.
- Akkaunt kompaniyaniki (Organization), shuning uchun shaxsiy akkauntlardagi "12 tester × 14 kun"
  talabi yo'q.
- Birinchi release fayli: **`barno-ai-play-1.3.23-vc28-75e951e.aab`** (75 MB). U git'da yo'q, egadan olasiz.

## 1. Qilingan ishlar

| Nima | Holat | Qayerda |
|---|---|---|
| Play build: `BARNO_PLAY=1` → package `uz.brbtech.barno` | ✅ | `apps/mobile/app.config.ts` |
| Upload key bilan imzo: `-PbarnoPlayUpload=true` + `BARNO_UPLOAD_*` | ✅ | `apps/mobile/plugins/withReleaseSigning.js` |
| Upload key | ✅ yaratilgan, **faqat ega serverida** (ega qarori). Sertifikat SHA-256 pastda | — |
| AAB 1.3.23 / versionCode 28 | ✅ imzo tekshirilgan (jarsigner), minSdk 26, targetSdk 36, Advertising ID yo'q | egada |
| Maxfiylik siyosati | ✅ https://llm.brb-tech.uz/privacy — ochiq sahifa (uz/ru/en, login talab qilmaydi). Ilova ichida havola bor: kirish ekrani va Sozlamalar (1.3.22+) | `apps/web/src/views/PrivacyView.vue`, `apps/mobile/src/lib/privacy.ts` |
| Ilovada AI model nomi ko'rsatilmaydi, doim «Barno» (1.3.23) | ✅ | `apps/mobile/src/features/meeting/provenance.ts` |
| Store matnlari (uz/ru/en) va release notes | ✅ | `docs/google-play/listing.md` |
| Ikonka 512×512, banner 1024×500 | ✅ | `docs/google-play/store-icon.png`, `feature-graphic.png` |
| 7 ta telefon screenshoti (720×1437, demo hisobdan, tizim panellarisiz) | ✅ | `docs/google-play/screenshots/` |
| App content javoblari: Data safety, Content rating, Target audience, Foreground service, Account deletion va boshqalar | ✅ qoralama | `docs/google-play/app-content.md` |
| Reviewer uchun demo hisob `play.review@brb-tech.uz` (3 ta namunaviy yig'ilish) | ✅ | parolni ega beradi |

Upload key sertifikati (SHA-256):
`BA:6D:30:19:FD:00:F6:35:81:E0:24:70:93:43:F0:BE:9F:B2:7A:01:59:C6:69:29:4F:AB:5B:E9:16:1D:C8:3F`

Manifestdagi ruxsatlar:
- `RECORD_AUDIO`, `FOREGROUND_SERVICE`, `FOREGROUND_SERVICE_MICROPHONE`, `POST_NOTIFICATIONS`;
- `READ_MEDIA_AUDIO`, `READ_EXTERNAL_STORAGE` (faqat Android ≤ 12);
- `INTERNET`, `ACCESS_NETWORK_STATE`, `ACCESS_WIFI_STATE`;
- `MODIFY_AUDIO_SETTINGS`, `RECEIVE_BOOT_COMPLETED`, `VIBRATE`, `WAKE_LOCK`.

SMS, qo'ng'iroqlar jurnali, joylashuv, kontaktlar va Advertising ID yo'q.

## 2. Siz qiladigan ishlar (shu tartibda)

### 2.1. Ilovani yaratish — All apps → Create app
- **App name:** `Barno`
- **Default language:** ro'yxatda o'zbek tili bo'lsa, shuni tanlang. Bo'lmasa **English (United States) – en-US**
  (Google'ning rasmiy tillar ro'yxatida o'zbek tili topilmadi).
- **App or game:** App. **Free or paid:** Free. Keyin pullik qilib bo'lmaydi.
- Declarations → **Create app**.

### 2.2. Store listing
**Grow users → Store presence → Main store listing:**
- App name, Short description, Full description — `listing.md` dan. Default til English bo'lsa,
  "English (en)" bo'limini oling.
- App icon: `store-icon.png`. Feature graphic: `feature-graphic.png`.
- Phone screenshots: `screenshots/01…07`, shu tartibda.
- **Manage translations** → Russian (ru-RU) uchun ruscha matnlar. O'zbek tili bo'lsa, o'zbekchasini ham qo'ying.

**Store settings:**
- Category: **Business**
- Email: `ai@brb-tech.uz`
- Website: `https://llm.brb-tech.uz`

### 2.3. App content — Policy and programs → App content
Har bir karta `app-content.md` dagi bo'lim bo'yicha to'ldiriladi:

| Karta | Javob |
|---|---|
| Privacy policy | `https://llm.brb-tech.uz/privacy` |
| Ads | No |
| App access | "All or some functionality is restricted" → Add instructions. Login `play.review@brb-tech.uz`, parolni ega beradi, inglizcha matn §3 da |
| Content rating | §4 |
| Target audience | §5 |
| News, Government, Financial features, Health | No (§6) |
| Data safety | §7 |
| Advertising ID | No (§8) |
| Foreground service permissions | Microphone, tavsifi §9 da. Shakl video havolasini so'raydi (30–60 s, ssenariy §9 da, YouTube Unlisted yoki Drive). Ega videoni hozircha qoldirgan. Console Internal testing'ni to'xtatsa, video yozib olinadi |
| Account deletion | §11: ilovada hisob ochib bo'lmaydi, o'chirish so'rovi `ai@brb-tech.uz` ga yuboriladi |

### 2.4. Internal testing — Test and release → Testing → Internal testing
1. **Testers** → email ro'yxati: xodimlarning Google akkauntlari.
2. **Create new release** → Play App Signing so'ralsa, Google yaratadigan kalitni tanlang (default).
3. App bundles → `barno-ai-play-1.3.23-vc28-75e951e.aab` ni yuklang.
4. Release name: `1.3.23`. Release notes `listing.md` ning "Release notes" bo'limidan.
5. **Next → Save → Start rollout**. Keyin Testers → **Copy link** → havolani xodimlarga yuboring.
6. **Albatta tekshiring:** Test and release → App integrity → App signing bo'limidagi "Upload key certificate"
   SHA-256 yuqoridagi `BA:6D:…:C8:3F` bilan bir xil bo'lishi kerak. Farq qilsa, davom etmang va egaga xabar bering.

### 2.5. Qurilmada sinov (ilovani Play'dan o'rnatib)
- [ ] BRB-Tech ID (SSO) bilan kirish ishlaydi. Zaxira "login + parol" shakli ham ishlaydi.
- [ ] Yozish ekran o'chganda va boshqa ilovaga o'tilganda ham davom etadi, bildirishnoma ko'rinib turadi.
- [ ] To'xtatilgach yozuv yuklanadi, transkript va xulosa 1–3 daqiqada chiqadi.
- [ ] Audio va video yuklash, yozuv chati, bayonnoma (Word/PDF), CRM'ga vazifa yuborish ishlaydi.
- [ ] Kirish ekranidagi va Sozlamalardagi «Maxfiylik siyosati» havolasi sahifani ochadi.
- [ ] Pre-launch report ogohlantirishlari ko'rib chiqildi.

⚠️ APK kanalidagi ilova ham «Barno» deb nomlangan va SSO'dan qaytish sxemasi bir xil (`venera-rec://`).
Ikkalasi bir telefonda tursa, SSO'dan keyin ikkita bir xil «Barno» ichidan tanlash oynasi chiqadi.
Sinovchilar Play versiyasini o'rnatishdan oldin APK versiyasini o'chirgani ma'qul. O'chirishdan oldin hamma yozuvlar
yuklanganini tekshirsin: o'chirilganda yuklanmagan yozuvlar ham ketadi.

### 2.6. Production (keyinroq)
Shartlar:
1. **Reviewer HRM va CRM'ni ko'rishi uchun BRB-Tech ID test xodimi.** HRM va CRM faqat SSO orqali ulanadi,
   zaxira login hisobida ular yo'q. Hisobni Keycloak, HRM va CRM adminlari yaratadi:
   - 2FA yo'q, parol muddati cheksiz;
   - HRM'da faqat o'z (soxta) ma'lumoti ko'rinadi;
   - CRM'da bitta demo loyiha bor.

   Test xodimning emaili `play.review@brb-tech.uz` bo'lsa, u birinchi kirishda demo hisobning namunaviy
   yig'ilishlarini oladi. Shundan keyin App access ko'rsatmasi "Sign in with BRB-Tech ID" ga o'zgartiriladi.
2. `llm.brb-tech.uz` va BRB-Tech ID kirish sahifasi chet eldan ham ochiladi. Bu tarmoq jamoasining ishi.
3. Foreground service deklaratsiyasi video bilan to'ldirilgan.
4. Dashboard'dagi hamma vazifalar "Completed" bo'lgach: Production → Create new release (Internal'dan promote) →
   Countries/regions: Uzbekistan → Send for review. Natijani Publishing overview'da kuzating.

## 3. Keyingi versiyalar

- Upload key faqat ega serverida turadi, shuning uchun yangi AAB'ni ega serverda yig'ib, sizga beradi:
  - buyruq: `~/Barno_AI/scripts/play/build-aab.sh [git-ref]` (default `origin/main`);
  - natija: `~/Barno_AI/aab/barno-ai-play-<versiya>-vc<kod>-<commit>.aab`;
  - skript toza worktree'da yig'adi, keyin `applicationId`, AAB ichidagi `app.config` va imzoni tekshiradi.
- Har yangi yuklashda `apps/mobile/app.config.ts` dagi `android.versionCode` oshishi shart, chunki Play bir xil
  kodni qayta qabul qilmaydi. Hozirgisi: `version: '1.3.23'`, `versionCode: 28`.
- AAB'ni o'zingiz yig'ishingiz kerak bo'lsa, upload key sizning kalitingizga o'tkaziladi: Play Console → App integrity →
  **Request upload key reset**. Bu faqat ega qarori bilan qilinadi. Yig'ish buyruqlari:

  ```bash
  cd apps/mobile
  npm ci
  # BARNO_PLAY butun build davomida kerak: expo-constants gradle bosqichida app.config ni qayta o'qiydi
  export BARNO_PLAY=1 APP_VARIANT=production
  npx expo prebuild -p android --clean --no-install
  grep -E "applicationId ['\"]uz\.brbtech\.barno['\"]" android/app/build.gradle   # tekshiruv
  cd android && ./gradlew bundleRelease -PbarnoPlayUpload=true
  # natija: android/app/build/outputs/bundle/release/app-release.aab
  ```

  `~/.gradle/gradle.properties` da `BARNO_UPLOAD_STORE_FILE`, `BARNO_UPLOAD_STORE_PASSWORD`,
  `BARNO_UPLOAD_KEY_ALIAS`, `BARNO_UPLOAD_KEY_PASSWORD` bo'lishi kerak. `BARNO_PLAY` siz yig'ilsa package
  `uz.brbtech.venera.meetings` (APK kanali) bo'lib qoladi va Play bunday AAB'ni qabul qilmaydi.
- **O'zgartirmang:**
  - package nomini;
  - SSO sxemasi `venera-rec` ni;
  - SSO/Keycloak bilan bog'liq kod va sozlamalarni (ega qarori: hozircha o'zgartirilmaydi).

## 4. Kimdan nima olinadi

| Nima | Kimdan |
|---|---|
| AAB fayli va demo hisob paroli | Egadan, shaxsan. Messenjer yoki email orqali yuborilmaydi |
| BRB-Tech ID test xodimi | Keycloak, HRM va CRM adminlaridan |
| Chet eldan ochilish tasdig'i | Tarmoq jamoasidan |
