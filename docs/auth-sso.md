# Kirish: BRB-Tech SSO (Keycloak), brauzer orqali

2026-yil noyabrdan Barno AI ga kirish korporativ SSO (Keycloak) orqali.
Barno parolni KO'RMAYDI: odam Keycloak'ning o'z sahifasida kiradi, Barno
faqat imzolangan tasdiqni oladi. Bitta hisob, bitta parol - Keycloak'ga
ulangan hamma tizim uchun.

## Oqim (nima bo'ladi)

```
brauzer                    Barno API (apps/api)              Keycloak
  |  "BRB-Tech ID bilan kirish"  |                              |
  |----- GET /auth/sso/start --->|  state, nonce, PKCE saqlanadi |
  |<---- 302 Keycloak manzili ---|                              |
  |------------------------------------------- kirish sahifasi ->|
  |                               (login + parol FAQAT shu yerda) |
  |<------------------ 302 /auth/sso/callback?code&state --------|
  |----- GET /auth/sso/callback ->|--- code + client siri + PKCE ->|
  |                               |<-- id_token + access_token ---|
  |                               |  imzo (JWKS), iss, aud, nonce, exp |
  |                               |  shaxs -> identities.json (actor_id) |
  |                               |  Barno JWT -> bir martalik kod        |
  |<---- 303 /login?sso=<kod> ----|                              |
  |----- POST /auth/sso/exchange >|                              |
  |<---- LoginResponse (token) ---|                              |
```

Kod: `apps/api/app/services/oidc.py` (Keycloak bilan gaplashish, token
tekshiruvi), `apps/api/app/api/v1/auth.py` (endpointlar),
`apps/web/src/views/LoginView.vue` + `composables/useAuth.ts` (tugma, qaytish).

Nega server orqali (brauzerdagi kutubxona emas): client siri va PKCE
verifier brauzerga chiqmaydi, token tekshiruvi bir joyda, mobil ilova va
Telegram Mini App ham xuddi shu endpointlarni ishlatadi (keyingi bosqich).

## Rollar

Keycloak'da Barno'ning O'Z client'i bor (`barno-ai`) va rollar shu
client'niki: `admin` -> `ADMIN`, `employee` -> `EMPLOYEE`, `executive` ->
`EXECUTIVE`, `rag-admin` -> `RAG_ADMIN` (`services/oidc.ROLE_MAP`; ro'yxatda
yo'q rol katta harfda o'tadi). Realm rollari va boshqa client'larning
rollari O'QILMAYDI - ularni boshqa tizimlar uchun kim ham berishi mumkin.
Rolni Keycloak administratori beradi: Users -> odam -> Role mapping ->
Assign role -> Filter by clients -> `barno-ai`.

Barno tomonida qolgan ikki yo'l o'zgarmadi: `.env` dagi `ADMIN_LOGINS`
(zaxira kalit, har doim ADMIN) va admin paneldagi qaror (`user_admin`,
rollar / bloklash / hamma joydan chiqarish). Eski `SSO_TRUSTED_ROLES`
olib tashlandi - endi kerak emas.

## Sozlama (`apps/api/.env`)

```
SSO_ISSUER=https://<keycloak>/auth/realms/<realm>   # tokendagi `iss` aynan shu
SSO_CLIENT_ID=barno-ai
SSO_CLIENT_SECRET=<Clients -> barno-ai -> Credentials>
SSO_APP_URL=https://llm.brb-tech.uz                 # prod'da ANIQ; dev'da bo'sh qolsa so'rovdan olinadi
# SSO_MOBILE_REDIRECT=barnoai://sso                 # mobil ilova tayyor bo'lganda
# SSO_CRM_CONNECT=true                              # default: CRM ulanishi SSO sessiyasidan (pastda)
# SLACK_LINK_REQUIRED=true                          # default: Slack'da har kim o'z hisobini ulaydi (pastda)
# SLACK_LINK_DAYS=30                                # Slack ulanishi oxirgi faollikdan shuncha kun yashaydi
LOCAL_LOGIN_ENABLED=true                            # users.yaml bilan zahira kirish; prod'da false qilish mumkin
```

`SSO_ISSUER` yoki `SSO_CLIENT_SECRET` bo'sh - SSO o'chiq: kirish sahifasida
faqat parol shakli (`GET /auth/sso/config` shuni aytadi). `.env` ni
o'zgartirgach `systemctl --user restart venera-api`.

Keycloak client'ida (Clients -> barno-ai):
- Client authentication ON, Standard flow ON, Direct access grants OFF;
- Valid redirect URIs: `<SSO_APP_URL>/api/v1/auth/sso/callback` (prod),
  `http://10.10.50.4:5174/api/v1/auth/sso/callback` va
  `http://localhost:5174/...` (dev; 2026-11-10 dan Venera 10.10.50.4 da);
- Valid post logout redirect URIs: `<SSO_APP_URL>/*`;
- Advanced -> PKCE Code Challenge Method: `S256`;
- Client scopes: `offline_access` "Optional" ro'yxatida (yangi client'da
  odatda bor) - `SSO_CRM_CONNECT` uchun;
- Roles: `admin`, `employee`, `executive`.

Ikki Keycloak (2026-11-12 holati):
- **Staging** `https://test-keycloak.brb-tech.uz/auth/realms/brb-realm`. Oldidagi
  proksi admin konsolida faqat YARATISHga ruxsat beradi: o'zgartirish, o'chirish
  va PAROL o'rnatish (konsoldagi "Set password" ham, parol bilan yaratish ham)
  403. Shuning uchun u yerda sinov foydalanuvchisiga parol berib bo'lmaydi -
  paroli bor hisobni Keycloak administratorlari beradi. Client'lar: `barno-ai`
  (`https://llm.brb-tech.uz/...`) va `barno-ai-dev` (`http://barno-dev:5174/...`).
- **Prod** `https://myid.brb-tech.uz/auth/realms/brb-realm` (eski konsol).
  Dev sinovi uchun `barno-ai-dev` client'i shu yerda ham bor (2026-11-12):
  confidential, faqat Standard flow, PKCE S256, Valid Redirect URIs
  `http://barno-dev:5174/*`, Web Origins `+`. Jonli sayt uchun `barno-ai`
  client'i hali YARATILMAGAN.

## Dev'da sinash

Dev client'ining yagona qaytish manzili `http://barno-dev:5174/...` - IP emas,
NOM: dev stack qaysi serverda tursa ham Keycloak'ga tegilmaydi. Brauzer turgan
kompyuterning hosts fayliga bir qator qo'shiladi: `10.10.50.4 barno-dev`.

```bash
# worktree ichida (venera/.worktrees/sso). apps/api/.env.dev: SSO_ISSUER, SSO_CLIENT_ID=barno-ai-dev,
# SSO_CLIENT_SECRET, SSO_APP_URL=http://barno-dev:5174 - ishga tushirishda .env ga nusxalanadi.
# TELEGRAM_BOT_ENABLED=false va SLACK_APP_TOKEN= SHART: .env prod nusxasi bo'lsa, dev jarayon prod botning
# Telegram yangilanishlarini (409) va Slack hodisalarini (socket mode ikki ulanishga bo'linadi) olib qo'yadi.
# HRM_ASSISTANT_BASE_URL - dev chat agentiga BORMASIN: dev o'z actor_id larini beradi, agent esa suhbat
# tarixini `venera:<actor_id>` bo'yicha saqlaydi - dev foydalanuvchi boshqa odam tarixiga tushib qolardi.
# SECRET_KEY - dev tokenlari prod kaliti bilan imzolanmasin.
cd apps/api && cp .env.dev .env && TELEGRAM_BOT_ENABLED=false SLACK_APP_TOKEN= \
  HRM_ASSISTANT_BASE_URL=http://127.0.0.1:9 SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')" \
  venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8001
# Vite begona Host'ni rad etadi (403) - `barno-dev` ga ruxsat shu o'zgaruvchi bilan:
cd apps/web && __VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS=barno-dev VITE_API_TARGET=http://127.0.0.1:8001 \
  npm run dev -- --port 5174 --strictPort
# brauzerda http://barno-dev:5174/login -> "BRB-Tech ID bilan kirish"
# testlardan OLDIN apps/api/.env ni o'chiring (prod qiymatlari testga sizadi).
```

Portlar (10.10.50.4): 8000 - `ai-chat-mcp`, 8010 - prod `venera-api`, 5173 - prod sayt; dev uchun 8001 va 5174
(ufw: `sudo ufw allow 5174/tcp`, 2026-11-11 da ochilgan).
Ma'lumot: dev jarayon worktree'ning o'z `apps/api/data/` papkasiga yozadi - prod bazalariga tegmaydi.

Kirmasdan tekshirish (client va sir to'g'riligini): `start` bergan manzil Keycloak'da kirish sahifasini ochsa -
client va qaytish manzili qabul qilingan; `callback?code=<o'ylab topilgan>&state=<start dagi>` jurnalda
`invalid_grant Code not valid` bersa - sir TO'G'RI (`unauthorized_client` bo'lsa sir yoki client noto'g'ri).

Keycloak'da xato bo'lsa: Realm -> Events -> Event configs -> Save events ON;
"User events" da har urinish sababi bilan ko'rinadi. Barno tomonida
`journalctl --user -u venera-api` (`SSO kirish bajarilmadi (<sabab>)`) va
admin panel -> auth events (`method=sso`, `reason=sso:<sabab>`).

Kirish sahifasidagi sabablar (`?sso_error=`): `denied` (odam Keycloak'da
bekor qildi), `blocked` (Barno admin paneli bloklagan), `expired` (10
daqiqadan oshdi yoki "orqaga" bosilib kod ikki marta ishlatildi), `network`
(Keycloak javob bermadi), `config` (client siri noto'g'ri - `.env`),
`failed` (token tekshiruvi: boshqa realm/client, nonce, imzo - jurnalga
qarang).

## Nima o'zgardi (2026-11)

- Oldingi "login + parolni Keycloak'ga ilovaning o'zi yuborishi" (parol
  granti, `services/sso.py`) OLIB TASHLANDI. U parolni ko'rar va o'sha
  parol bilan HRM ga ham kirar edi - SSO ning ma'nosiga zid.
- Natija: HRM ulanishi kirishda o'zi ochilmaydi - "+" menyusida (Ulanishlar)
  qo'lda ulanadi (SSO sessiyasidan ulash hali qurilmagan - "Keyingi bosqichlar",
  3-band: HRM Keycloak tokenini tekshiradi, eski "o'z JWT'si" yozuvi noto'g'ri edi). HRM tokeni
  10 soatlik; parol faqat xotirada turadi, API qayta ishga tushsa odam HRM ni
  qayta ulaydi.
- CRM ulanishi SSO sessiyasidan O'ZI ochiladi (2026-11-12, pastdagi bo'lim) va
  odamga ko'rinmaydi: «Ulanishlar» da faqat HRM qoldi ("Ulanishlar: odam faqat
  HRM ni boshqaradi" bo'limi).
- Token imzosi endi TEKSHIRILADI (`PyJWT[crypto]`, Keycloak JWKS).
- `POST /auth/login` faqat zahira (`users.yaml`); `LOCAL_LOGIN_ENABLED=false`
  bo'lsa 403.
- Chiqish Keycloak sessiyasini ham yopadi (`LogoutResponse.ssoLogoutUrl`).

## Keyingi bosqichlar

1. Mobil ilova: tizim brauzeri -> `start?return=barnoai://sso&channel=mobile`
   -> `barnoai://sso?sso=<kod>` -> `exchange` (`SSO_MOBILE_REDIRECT`).
2. Telegram Mini App: kirish ekraniga SSO tugmasi (hozir u yerda faqat parol
   shakli - pastdagi "Ma'lum cheklovlar").
3. HRM - SSO sessiyasidan o'zi ulanishi (CRM kabi). HRM jamoasi kod bo'yicha ko'rsatdi
   (2026-11-12): HRM Keycloak `brb-realm` tokenini Bearer sifatida tekshiradi (`iss`, `aud` =
   `account`, imzo), `/api/authenticate` ham Keycloak tokenini (`smart-office-client`) qaytaradi.
   Ya'ni "HRM o'z JWT'sini beradi" degan eski yozuv (2026-09-29) noto'g'ri. Barno'ning `barno-ai`
   tokeni bilan jonli sinov (`GET /api/account` -> 200) hali qilinmagan; o'tsa - HRM ham kirishda
   o'zi ulanadi va «Ulanishlar» dagi login + parol olib tashlanadi.
4. Jonli sayt uchun prod Keycloak'da `barno-ai` client'i, `SSO_*` prod `.env` da,
   `pip install -e .` (`cryptography`), `venera-api` ni qayta ishga tushirish.

## Himoya qo'shimchalari (2026-11-12, jonli chiqishdan oldingi ko'rib chiqish)

- **Kirish uni boshlagan brauzerga bog'langan.** `start` HttpOnly, SameSite=Lax
  cookie qo'yadi (HTTPS da `__Host-barno_sso`, Path=/ - qo'shni `*.brb-tech.uz`
  sayti uni "tashlab" qo'ya olmaydi; `http` dev'da `barno_sso`, yo'li
  `/api/v1/auth/sso`; muddati kutish + bir martalik kod = 690 s). Uning SHA-256 i
  `state` va bir martalik kod bilan birga serverda turadi. `callback` va
  `exchange` cookie mos kelmasa rad etadi - birovga yuborilgan havola uni
  yuboruvchining hisobiga kiritib qo'ymaydi (login CSRF). Boshqa brauzerda
  sinalgan bir martalik kod YONADI. Ikki varaqda boshlansa oxirgisi ishlaydi.
- **Sayt boshqa host bilan ochilgan bo'lsa** (domen o'rniga server IP si) `start`
  kirishni `SSO_APP_URL` da qaytadan boshlaydi (`?_c=1`, faqat bir marta) - aks
  holda cookie Keycloak qaytaradigan manzilga yetmasdi.
- **Mobil qaytish kodini brauzer almashtira olmaydi** (`Sec-Fetch-Site` /
  `Origin` bor so'rov rad etiladi) - u cookie bilan bog'lanmagan, uni faqat ilova
  ishlatadi. Mobil SSO yoqilganda ilova o'z PKCE juftini beradi.
- **Eski kirish yozgan rollarga ishonilmaydi.** Rollar `identities.json` da
  faqat `client_roles` kalitidan o'qiladi - uni faqat yangi oqim yozadi. Eski
  `roles` maydoni (realm va `crm-client` rollari; rollback'da eski kod uni qayta
  yozishi mumkin) o'qilmaydi - odam veb'da SSO bilan bir marta kirguncha rollari
  bo'sh.
- **CRM ni uzish faqat Barno ruxsatini bekor qiladi** (`/revoke`, RFC 7009).
  `/logout` ishlatilmaydi: u odamni shu brauzerdagi CRM va boshqa SSO
  tizimlaridan ham chiqarib yuborardi. Uzish endi faqat admin panelda
  (foydalanuvchi varag'i) - odamning o'zida CRM qatori yo'q.
- **Chiqishda Keycloak manzili faqat brauzer SSO sessiyasiga beriladi** (Barno
  tokenidagi `sso` belgisi). Telegram, qurilma va zahira sessiyalari Keycloak'ga
  yuborilmaydi - Telegram WebView Mini App'dan chiqib ketmasin.
- **Mini App'da "ulanmagan" tugmasi** endi sessiyani yopmaydi: veb ilovani ochadi
  (HRM u yerda "+" menyusidan ulanadi).
- CRM tokenini yangilash shu orada o'zgargan ulanishni (uzish, qayta kirish)
  buzmaydi - ombordagi yozuv bitta qulf ostida tekshirib yoziladi
  (`ConnectorStore.replace_if`); "uzish" avval ombordan o'chiradi,
  keyin tokenni bekor qiladi. JWKS so'rovi yiqilsa keyingi kirish darhol qayta
  so'raydi; `offline_access` berilmasa kirish sahifasi "sozlama" sababini
  ko'rsatadi; kirish sahifasi sozlamani o'qiy olmasa o'zi qayta so'raydi.

Testlar: `tests/test_sso_hardening.py`.

## Ma'lum cheklovlar (jonli chiqishda bilish kerak)

- **Mobil ilova va Telegram Mini App**: ularning kirish ekrani hali login +
  parolni `POST /auth/login` ga yuboradi, u esa endi faqat `users.yaml` ni
  taniydi - Keycloak hisobi bilan u yerda KIRIB BO'LMAYDI. Ishlayveradi: zahira
  (`users.yaml`) hisoblar, qurilma tokeni bor telefonlar (`/auth/devices/session`)
  va Telegram'ga allaqachon ulangan hisoblar (`/telegram/session`, bot). Yangi
  Telegram foydalanuvchisi yoki "Chiqish" bosgan odam Mini App'ga qayta kira
  olmaydi (veb'dagi SSO sessiyasi Telegram WebView'ga o'tmaydi).
- **HRM** Mini App va botdan qayta ulanmaydi (u yerda "+" yo'q, "Qayta ulash"
  qayta kirishga yuborardi): HRM veb'da "+" menyusidan ulanadi, token o'sha
  odamning hamma kanaliga xizmat qiladi; API qayta ishga tushsa yana ulash kerak.
- **CRM faqat VEB'dagi SSO kirishida ulanadi** - boshqa yo'l yo'q (qo'lda ulash
  olib tashlangan). Vebga BRB-Tech ID bilan hech kirmagan odamning (faqat
  Telegram, mobil ilova yoki `users.yaml` hisobi) O'Z CRM ulanishi bo'lmaydi -
  ilgari qo'lda ulangan eski yozuvi qolgan bo'lmasa. Unda chatdagi CRM savoliga
  umumiy agent hisobi javob beradi (sozlangan bo'lsa, `CRM_USERNAME`), guruhdagi
  CRM va "yig'ilishdan CRM ga" (`MEETINGS_CRM_OWN_TOKENS=true`) esa ishlamaydi.
  Yechim bitta: vebga BRB-Tech ID bilan kirish - bot ham shuni aytadi. Ulanish
  yo'qligini (CRM sessiyani rad etdi, offline sessiya o'ldi,
  `SSO_CRM_CONNECT=false`) odam ilovada ko'rmaydi - admin panel (foydalanuvchi
  varag'i), `/api/health/detail` va jurnal ko'rsatadi.
- **Yordamchidagi eski CRM kaliti.** Odam bir paytlar "Manbalar" da CRM ni
  o'chirgan bo'lsa, bu tanlov yordamchining O'Z omborida turadi (Barno'da emas)
  va uni Barno tozalamaydi: yordamchi o'sha odamga CRM savolida "o'chirilgan"
  deb javob berishi mumkin, ilovada esa endi kalit yo'q. Yechim yordamchi
  tomonda (`crm` ni kalitsiz qilish va saqlangan qatorlarni o'chirish).
  2026-11-12 da yordamchi omborida o'chirilgan qator YO'Q edi (bitta odam,
  hammasi yoqiq). HRM uchun bunday holat yuz bermaydi: eski mobil ilova
  `PUT /assistant/platforms/hrm` bilan o'chirishni so'rasa ham yordamchiga
  `enabled: true` ketadi.
- **Keycloak'dagi rol - kirish paytidagi nusxa.** Rol olib tashlansa yoki hisob
  o'chirilsa, bu odamning keyingi VEB kirishigacha Barno'ga yetmaydi (Telegram
  va qurilma sessiyalari saqlangan nusxadan yashaydi). Darhol to'xtatish:
  admin panel -> bloklash yoki "hamma joydan chiqarish".
- **"Hamma joydan chiqarish" Keycloak sessiyasini yopmaydi**: o'sha brauzerda
  "BRB-Tech ID bilan kirish" parolsiz qayta kiritadi. Odamni to'xtatish uchun -
  bloklash.
- **Birinchi kirishda `users.yaml` hisobi bilan bog'lash** email bo'yicha,
  bo'lmasa login == email'ning `@` gacha qismi bo'yicha (`_legacy_match`).
  Keycloak'da shunday nomli yangi hisob o'sha zahira hisobning `actor_id` sini
  oladi - `users.yaml` da keraksiz hisob qoldirilmasin.

## Ulanishlar: odam faqat HRM ni boshqaradi (2026-11-12, ega qarori)

- **HRM** - «Ulanishlar» dagi yagona qator: ulash (login + parol), holat,
  muddati tugasa qayta ulash, uzish. HRM hali SSO sessiyasini qabul qilmaydi.
- **CRM odamga ko'rinmaydi va uni odam boshqarmaydi.** U SSO kirishida o'zi
  ulanadi (pastdagi bo'lim) va HAR DOIM ishlatiladi: chat, Telegram bot,
  guruhdagi CRM, "yig'ilishdan CRM ga".
- **Kalit (yoqish / o'chirish) yo'q**: ulangan = ishlatiladi. Ombordagi eski
  `enabled: false` o'qilmaydi (`ConnectorHub.tokens`, `chat.has_own_crm`).
- **DWH, Biznes 24/7, Superapp, "Biznes 24/7 qo'llanmalari", "Biznes Help"** -
  vaqtinchalik namoyish manbalari edi; endi taklif qilinmaydi (qator ham,
  kalit ham yo'q). Javob manbalari filtri (`services/answer_sources.py`) bu
  turlarni ATAYLAB hali taniydi: yordamchi ularni yana bir muddat yuborishi
  mumkin va eski suhbatlar tarixida ular bor - jonli so'rov yashiriladi,
  `[n]` raqamli qo'llanma maqolasi ko'rsatiladi (veb unga umumiy yorliq beradi).

Kod: `services/integrations/connectors.py` (`USER_PLATFORMS` - odamniki,
`PLATFORMS` - ombor va admin panel), `api/v1/connectors.py`,
`api/v1/assistant_extras.py`. Testlar: `tests/test_connectors.py`,
`tests/test_sso_crm.py`, `tests/test_assistant_extras.py`.

| Yo'l | Javob |
|---|---|
| `GET /api/v1/connectors` | `{"connectors": [...]}` - FAQAT HRM qatori (shakli o'zgarmagan) |
| `POST /api/v1/connectors/hrm/connect`, `DELETE /api/v1/connectors/hrm` | avvalgidek |
| `PATCH /api/v1/connectors/hrm` `{"enabled": bool}` | eski klientlar (mobil ilova, eski Mini App) uchun qabul qilinadi, lekin hech narsani o'zgartirmaydi: javobda `enabled: true`, token ishlatilaveradi; ulanmagan bo'lsa 409 |
| `POST /api/v1/connectors/crm/connect`, `PATCH` / `DELETE /api/v1/connectors/crm` | 404 - notanish platforma bilan bir xil |
| `GET /api/v1/assistant/platforms` | faqat `hrm` qatori (yordamchi nechta qaytarsa ham) |
| `PUT /api/v1/assistant/platforms/{id}` | `hrm` - qabul qilinadi, lekin yordamchiga HAR DOIM `enabled: true` ketadi (eski klient HRM ni o'chirib qo'ya olmaydi, ilgari o'chirilgani qayta yoqiladi); boshqa har qanday `id` - 404 `platform_not_found`, yordamchiga BORMASDAN |
| `DELETE /api/v1/admin/users/{actorId}/connectors/{hrm\|crm}` | o'zgarmagan: admin panel CRM qatorini ko'radi va uza oladi |

CRM ulanmagan bo'lsa yechim - vebga BRB-Tech ID bilan kirish: bot (guruhdagi
CRM, brif, `auth_missing` zaxira matni) shuni aytadi. `/api/health/detail` da
`connectors.crm` endi "SSO kirishida CRM ulanishi ochila oladimi" degani (SSO
sozlangan + `CRM_BASE_URL` + `SSO_CRM_CONNECT=true`); yo'q bo'lsa `warnings`
da sababi turadi.

Eski klientlar buzilmaydi, lekin farqni ko'rsatadi: yangilanmagan klient
(e'lon qilingan mobil ilova, eski Mini App) CRM qatorini o'zi chizishi mumkin -
u "ulanmagan" ko'rinadi, ulash yoki kalit urinishi 404 oladi; CRM esa
ishlayveradi. Namoyish manbalari kaliti ham 404 oladi - eski ilova kalitni
joyiga qaytaradi.

## Slack: «Connect Barno AI account» (2026-11-12, ega qarori)

Avval Slack'dagi hamma odam bitta umumiy hisobda edi (`SLACK_ACTOR_ID`). Endi har kim o'z hisobini
BIR MARTA ulaydi (Slack'dagi Claude agentidagi kabi):

1. Ulanmagan odam Barno AI ga yozadi (matn, audio, thread'dagi savol, `/plaud`, tugma) - Barno ishni
   BAJARMAYDI, faqat o'ziga ko'rinadigan xabar: "Barno AI hisobingizni ulang" va «Connect Barno AI
   account» tugmasi. Chat birinchi ochilganda - yo'riqnoma va shu tugma; "Home" varag'ida ham bor.
2. Tugma - havola `<SSO_APP_URL>/link/slack?t=<chipta>`. Chipta tasodifiy, bir martalik, 30 daqiqa,
   faqat API jarayoni xotirasida; Slack id'lari havolada YO'Q - chiptaning serverdagi yozuvida (ular
   faqat Slack yetkazgan hodisadan olinadi).
3. Brauzerda Barno: kirmagan bo'lsa TO'G'RI kirish sahifasi (BRB-Tech ID yoki login + parol), kirgach
   tasdiq sahifasi: "Slack hisobi - <ism>, Barno hisobi - <siz>" va ogohlantirish. Ulanish FAQAT
   «Ulash» bosilganda (`POST /api/v1/slack/link`): havolani boshqaga yuborib, uning hisobiga o'z
   Slack'ini bog'lab olish (havola-hujum) shu bilan yopiladi. Slack'ka "ulandi" xabari keladi.
4. Shundan keyin audio va savollar odamning O'Z hisobida: yozuv uniki, Slack'dagi savollari
   ilovadagi suhbati bilan bitta (so'rovchi yo'q), chegaralar shaxsiy. Plaud ulangan har bir
   xodimga ochiq (ega qarori) - `MEETINGS_LOGINS` Slack'da tekshirilmaydi.

ESKI yozuvlar (ulashdan oldin kelganlari) umumiy hisobda qoladi: kartalari, thread savollari va
chatdagi savol ishlayveradi (avval odamning o'z hisobidan, topilmasa umumiy hisobdan qidiriladi;
u yerda suhbat avvalgidek `slack:<user id>` bo'yicha). Shuning uchun `SLACK_ACTOR_ID` ni o'chirmang.

Ulanish `data/slack/links.json` da (`<team>:<user>` -> actor_id va vaqtlar; ism, token YO'Q; 600),
oxirgi faollikdan `SLACK_LINK_DAYS` yashaydi. Uzish: Slack "Home" varag'idagi «Uzish», veb'da
`POST /api/v1/slack/unlink`, admin panelidagi "hamma joydan chiqarish" (audit'da `slackLinks`).
Hisob o'chirilsa - keyingi xabarda ulanish ham o'chadi; bloklansa - Slack'da sababi aytiladi.

Majburiylik: `SLACK_LINK_REQUIRED=true` (default) VA `SSO_APP_URL` to'ldirilgan bo'lsa. Aks holda
Slack eskicha umumiy hisobda ishlaydi (dev'da `SSO_APP_URL` http bo'lsa ham ishlaydi, lekin dev'da
Slack o'chiq - sinov faqat jonli serverda).

MA'LUM: ilovadagi (veb, mobil) Plaud bo'limi hali faqat ADMIN va `MEETINGS_LOGINS` ga ochiq.
Ro'yxatda yo'q odam Slack'dagi yozuvlarini faqat Slack'da ko'radi (ilovada 403).

## CRM ulanishi SSO sessiyasidan (2026-11-12)

Kod: `services/integrations/crm_sso.py`, `ConnectorHub` (`via: "sso"`),
`api/v1/auth.py` (`_connect_crm`), testlar `tests/test_sso_crm.py`.

Kirishda (`SSO_CRM_CONNECT=true`, default):
1. Keycloak'dan `offline_access` ham so'raladi - usiz sessiya 30 daqiqa
   harakatsizlikda o'lardi va CRM kuniga bir necha marta uzilardi.
2. Odamning access tokeni bilan CRM dan so'raladi: `GET <CRM_BASE_URL>/api/auth/me`.
3. CRM QABUL QILSA - sessiya odamning CRM ulanishi bo'ladi (odam buni
   ko'rmaydi; admin panelda "ulangan"), eski qo'lda ulangan sessiya CRM da
   bekor qilinadi. Yozuv har doim `enabled: true` bilan saqlanadi - bir
   paytlar o'chirib qo'yilgan CRM qayta kirishdan keyin o'chiq qolmaydi.
4. CRM RAD ETSA (401/403) yoki javob bermasa - ulanish ochilmaydi, mavjud
   ulanishga tegilmaydi, KIRISH BARIBIR ISHLAYDI. Jurnalda:
   `SSO: CRM sessiyani RAD ETDI (...) Token: azp=... aud=[...] clientlar=[...]`.

Oldingi (parol bilan) CRM ulanishidan farqi: access tokenni CRM emas, KEYCLOAK
yangilaydi (`POST <CRM>/api/auth/refresh` faqat `crm-client` ga berilgan tokenni
yangilay oladi), "uzish" ham sessiyani Keycloak'da bekor qiladi. Qayta kirganda
oldingi SSO sessiyasi bekor QILINMAYDI: brauzerdagi Keycloak sessiyasi tirik
bo'lsa ikkala token bitta offline sessiyani bo'lishadi.

Parol bilan (qo'lda) CRM ga ulanish OLIB TASHLANGAN - yangi bunday ulanish
ochilmaydi. Ilgari shunday ulangan odamlarning saqlangan yozuvlari (`via` siz)
ishlayveradi: ularni CRM o'zi yangilaydi, odam vebga SSO bilan kirganda esa
SSO sessiyasiga almashadi. Shart avvalgidek: `CRM_IDP_TOKEN_URL`,
`CRM_CLIENT_ID`, `CRM_CLIENT_SECRET` va `CRM_BASE_URL` to'liq bo'lishi kerak
(bu qiymatlar endi hech qayerga yuborilmaydi - faqat shart; ularni `.env` dan
olib tashlash eski yozuvlarni keyingi SSO kirishigacha tokensiz qoldiradi).

CRM rad etsa nima qilinadi: jurnaldagi `aud` da `crm-client` bo'lmasa -
Keycloak'da bizning client'ga mapper qo'shiladi (Clients -> client -> Mappers ->
Create -> Mapper Type "Audience" -> Included Client Audience `crm-client`, Add to
access token ON). `aud` da bor bo'lib, baribir rad etsa - CRM `azp` ni
tekshiradi: bu CRM jamoasi bilan hal qilinadi.

Holat (2026-11-12): jonli sinovdan o'tdi - prod Keycloak (`barno-ai-dev`) va
prod CRM bilan uch marta kirildi, har safar CRM sessiyani QABUL QILDI va
ulandi (`Ulanish: <actor> -> crm (sso)`); Audience mapper kerak bo'lmadi.
HALI SINALMAGAN: access token muddati tugagach Keycloak orqali yangilash va
chat orqali haqiqiy CRM javobi - dev stack'da chat o'chiq.
