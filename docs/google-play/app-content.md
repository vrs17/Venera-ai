# Google Play — App content javoblari (qo'llanma 8-bosqich)

Play Console: **Policy and programs → App content**. Javoblar ilova kodi va backend bo'yicha tekshirilgan
(2026-11-19/20; ruxsatlar 1.3.23 / vc28 manifestida tekshirilgan). Kod o'zgarsa — bu javoblar ham yangilanadi.
Matndagi `~/Barno_AI/...` yo'llari — ega serveridagi fayllar (repoda emas).

## 1. Privacy policy
- URL: **https://llm.brb-tech.uz/privacy** (uz/ru/en, kirishsiz ochiladi; deploydan keyin ishlaydi).

## 2. Ads
- **No** — ilovada reklama ham, reklama SDK'si ham yo'q.

## 3. App access — "All or some functionality is restricted"
Ilova faqat BRB-Tech xodimlari uchun (BRB-Tech ID). Reviewer uchun demo hisob **yaratildi (2026-11-20)**:
- Login: `play.review@brb-tech.uz` (kirish ekranidagi "Login" maydoniga TO'LIQ email yoziladi).
- Parol: serverda, `~/Barno_AI/keys/play-review-account.txt` (600). Uni ega o'z terminalida ochib, Console'ga
  o'zi ko'chiradi. Chatga, Telegram'ga yoki emailga yozilmaydi.
- Hisob `users.yaml` da (`actor_id` 15, roli USER). Uni o'chirmang va parolini o'zgartirmang: hisob har
  yangilanish review'ida kerak.
- Hisobda 3 ta namunaviy yig'ilish bor: TTS'ning ikki ovozi (Dilnoza / Jasur), to'qima mazmun. Spikerlar nomlangan,
  xulosa va vazifalar tayyor, "Yangi yil tadbiri" da bayonnoma va 2 ta chat savoli ham bor.
- Tekshirilgani (2026-11-20): HRM va CRM yopiq (`auth_expired`). **Ichki hujjatlar bo'yicha yordamchi OCHIQ**
  (ichki mehnat tartibi, nizomlar) — ega qarori kutilmoqda. Yopilsa, ko'rsatmaga "The work assistant (internal
  documents) is disabled for the demo account." jumlasini qo'shing.
- Instruction (inglizcha, Console'ga; `<password>` o'rniga fayldagi parolni qo'ying):
  > This is an internal app for BRB-Tech employees. On the sign-in screen use the Login/password form below
  > the "Sign in with BRB-Tech ID" button (do not use that button). Login: `play.review@brb-tech.uz`,
  > password: `<password>`, then tap "Sign in".
  > Open the menu (☰) → "Plaud" to see three sample meetings with transcript, named speakers, summary, tasks
  > and minutes; the meeting chat answers questions about a recording. To test recording, tap the red "Record"
  > button in the menu, allow microphone and notifications, speak, and tap "Stop"; the transcript and summary
  > appear in 1–3 minutes. Recording continues in the background (ongoing notification).
  > HR and CRM data are not available to the demo account.

## 4. Content rating (IARC)
- Email: `ai@brb-tech.uz`. Category: **All Other App Types** (yoki "Utility, Productivity, Communication, or Other").
- Zo'ravonlik, qo'rqinchli kontent, jinsiy kontent, so'kinish, giyohvand moddalar, qimor: **No**.
- Foydalanuvchilar bir-biri bilan muloqot qiladimi / kontent almashadimi: **No** (har kim faqat o'z yozuvlarini ko'radi).
- Foydalanuvchi joylashuvini ulashadimi: **No**. Raqamli xaridlar: **No**.
- Ilova internetga cheklanmagan kirish beradimi (brauzer): **No** (faqat o'z xizmatimiz sahifalari).
- AI tomonidan yaratilgan kontent so'ralsa: **Yes** — matnli xulosa/javoblar; foydalanuvchining o'z ish ma'lumotlari asosida.
- Kutilgan natija: Everyone / 3+ (IARC o'zi hisoblaydi).

## 5. Target audience and content
- Yosh guruhi: **18 and over** (faqat 18+). Bolalarga mo'ljallanmagan, Families dasturida emas.
- "Appeal to children": **No**.

## 6. News apps — **No**. Government app — **No**. Financial features — **No** (to'lov, kredit, investitsiya yo'q). Health — **No**.

## 7. Data safety
**Data collection and security:**
- Does your app collect or share required user data types? — **Yes**.
- Is all user data encrypted in transit? — **Yes** (HTTPS).
- Do you provide a way for users to request that their data be deleted? — **Yes** (yozuvlar ilovada o'chiriladi; hisob va qolgan ma'lumot — `ai@brb-tech.uz` orqali).

**Data types** (hammasi: *Collected* — Yes, *Shared* — No¹, *Optional/Required* — ko'rsatilgandek):

| Kategoriya → tur | Maqsad | Majburiy? | Izoh |
|---|---|---|---|
| Personal info → Name | App functionality, Account management | Required | BRB-Tech ID'dan |
| Personal info → Email address | App functionality, Account management | Required | Ish emaili |
| Personal info → User IDs | App functionality, Account management | Required | Xodim ID, hisob ID |
| Audio → Voice or sound recordings | App functionality | Required | Yig'ilish yozuvi, ovozli savol, ovoz namunasi (spiker tanish) |
| Audio → Other audio files | App functionality | Optional | Yuklangan audio, qo'ng'iroq yozuvlarini import (yoqilsa) |
| Photos and videos → Videos | App functionality | Optional | Yuklangan video — **ephemeral**: audio ajratilgach video o'chiriladi |
| App activity → Other user-generated content | App functionality | Required | Chat savollari, bayonnoma ko'rsatmalari |
| App activity → App interactions | Analytics, App functionality | Required | Server so'rovlar jurnali (xizmat sifati, xarajat hisobi) |
| App info and performance → Diagnostics | App functionality | Required | Server xatolar jurnali |

Yig'ilmaydi: joylashuv, kontaktlar, SMS, qo'ng'iroqlar jurnali, rasmlar, kalendar, moliya, salomatlik, Advertising ID, Device IDs.

¹ *Shared — No*: GAPI (nutq → matn, spiker tanish), Anthropic va Ollama (matnli AI) — biz nomimizdan ishlaydigan **xizmat ko'rsatuvchilar** (service providers). Play ta'rifiga ko'ra ularga uzatish "sharing" hisoblanmaydi; ular privacy policy'da nomi bilan yozilgan.

## 8. Advertising ID
- **No** — `com.google.android.gms.permission.AD_ID` manifestda yo'q, ishlatilmaydi.

## 9. Foreground service permissions (Android 14+) — ⚠️ video kerak
- Turi: **Microphone** (`FOREGROUND_SERVICE_MICROPHONE`, `expo-audio` AudioRecordingService).
- Tavsif (inglizcha):
  > Barno records meetings. When the user taps Record, a foreground service with an ongoing
  > notification keeps the microphone recording while the screen is off or the user switches apps,
  > so a long meeting is not cut off. Recording only starts after an explicit user action and stops
  > when the user taps Stop; the notification is visible the whole time.
- Video (YouTube unlisted yoki Drive havolasi, 30–60 s): ilovada yozishni boshlash → Home, boshqa ilovaga
  o'tish → bildirishnomada yozuv davom etayotgani → bildirishnoma orqali qaytish (taymer to'xtamagan) →
  "To'xtatish" → yozuv ro'yxatda paydo bo'lishi. Ekranni bloklamang: ko'p telefonlarda ekran yozuvi to'xtaydi.

## 10. Sensitive permissions
- SMS, Call Log, All files access, Accessibility, background location, rasm/video ruxsatlari — **ishlatilmaydi**
  (SMS, call log, install packages, query all packages ruxsatlari manifestdan majburan olib tashlangan).
- `READ_MEDIA_AUDIO` (+ `READ_EXTERNAL_STORAGE` faqat Android ≤12): faqat foydalanuvchi o'zi yoqqan
  "qo'ng'iroq yozuvlarini import qilish" uchun — telefonning o'z yozuvchisi saqlagan qo'ng'iroq
  yozuvlarini o'qish. Ilova qo'ng'iroqni o'zi yozmaydi. (Bu ruxsat Play'da alohida deklaratsiya talab qilmaydi.)
- `RECORD_AUDIO`, `POST_NOTIFICATIONS` — yozuv va uning bildirishnomasi.

## 11. Account deletion
- Ilovada hisob ochib bo'lmaydi — hisoblarni kompaniya ochadi (BRB-Tech ID). Play so'rasa:
  "Users cannot create accounts in the app"; o'chirish so'rovi — `ai@brb-tech.uz`.

## 12. Countries / regions va narx (9-bosqich)
- Free. Hudud: **Uzbekistan** (boshqalari shart emas).
