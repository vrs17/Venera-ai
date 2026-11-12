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
  qo'lda ulanadi. HRM Keycloak tokenini QABUL QILMAYDI (o'z JWT'si, 2026-09-29
  da tekshirilgan) - HRM jamoasi buni qo'shguncha shunday qoladi. HRM tokeni
  10 soatlik; parol faqat xotirada turadi, API qayta ishga tushsa odam HRM ni
  qayta ulaydi.
- CRM ulanishi SSO sessiyasidan O'ZI ochiladi (2026-11-12, pastdagi bo'lim).
- Token imzosi endi TEKSHIRILADI (`PyJWT[crypto]`, Keycloak JWKS).
- `POST /auth/login` faqat zahira (`users.yaml`); `LOCAL_LOGIN_ENABLED=false`
  bo'lsa 403.
- Chiqish Keycloak sessiyasini ham yopadi (`LogoutResponse.ssoLogoutUrl`).

## Keyingi bosqichlar

1. Mobil ilova: tizim brauzeri -> `start?return=barnoai://sso&channel=mobile`
   -> `barnoai://sso?sso=<kod>` -> `exchange` (`SSO_MOBILE_REDIRECT`).
2. Telegram Mini App: Telegram ulanishi (`/telegram/session`) avvalgidek;
   birinchi kirish web'da SSO bilan.
3. HRM - HRM jamoasi Keycloak tokenini qabul qilganda (unga qadar qo'lda).
4. Jonli sayt uchun prod Keycloak'da `barno-ai` client'i, `SSO_*` prod `.env` da,
   `pip install -e .` (`cryptography`), `venera-api` ni qayta ishga tushirish.

## CRM ulanishi SSO sessiyasidan (2026-11-12)

Kod: `services/integrations/crm_sso.py`, `ConnectorHub` (`via: "sso"`),
`api/v1/auth.py` (`_connect_crm`), testlar `tests/test_sso_crm.py`.

Kirishda (`SSO_CRM_CONNECT=true`, default):
1. Keycloak'dan `offline_access` ham so'raladi - usiz sessiya 30 daqiqa
   harakatsizlikda o'lardi va CRM kuniga bir necha marta uzilardi.
2. Odamning access tokeni bilan CRM dan so'raladi: `GET <CRM_BASE_URL>/api/auth/me`.
3. CRM QABUL QILSA - sessiya odamning CRM ulanishi bo'ladi ("+" menyusida
   "ulangan"), eski qo'lda ulangan sessiya CRM da bekor qilinadi.
4. CRM RAD ETSA (401/403) yoki javob bermasa - ulanish ochilmaydi, mavjud
   ulanishga tegilmaydi, KIRISH BARIBIR ISHLAYDI. Jurnalda:
   `SSO: CRM sessiyani RAD ETDI (...) Token: azp=... aud=[...] clientlar=[...]`.

Oldingi (parol bilan) CRM ulanishidan farqi: access tokenni CRM emas, KEYCLOAK
yangilaydi (`POST <CRM>/api/auth/refresh` faqat `crm-client` ga berilgan tokenni
yangilay oladi), "uzish" ham sessiyani Keycloak'da bekor qiladi. Qayta kirganda
oldingi SSO sessiyasi bekor QILINMAYDI: brauzerdagi Keycloak sessiyasi tirik
bo'lsa ikkala token bitta offline sessiyani bo'lishadi.

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
