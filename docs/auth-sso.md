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
LOCAL_LOGIN_ENABLED=true                            # users.yaml bilan zahira kirish; prod'da false qilish mumkin
```

`SSO_ISSUER` yoki `SSO_CLIENT_SECRET` bo'sh - SSO o'chiq: kirish sahifasida
faqat parol shakli (`GET /auth/sso/config` shuni aytadi). `.env` ni
o'zgartirgach `systemctl --user restart venera-api`.

Keycloak client'ida (Clients -> barno-ai):
- Client authentication ON, Standard flow ON, Direct access grants OFF;
- Valid redirect URIs: `<SSO_APP_URL>/api/v1/auth/sso/callback` (prod),
  `http://10.10.50.8:5174/api/v1/auth/sso/callback` va
  `http://localhost:5174/...` (dev);
- Valid post logout redirect URIs: `<SSO_APP_URL>/*`;
- Advanced -> PKCE Code Challenge Method: `S256`;
- Roles: `admin`, `employee`, `executive`.

Staging Keycloak'da sinab, keyin prod Keycloak'da (myid.brb-tech.uz,
`brb-realm`) aynan shu client yaratiladi - faqat `SSO_ISSUER` va sir
o'zgaradi.

## Dev'da sinash

```bash
# worktree ichida, apps/api/.env da SSO_* to'ldirilgan (SSO_APP_URL bo'sh qolsin)
cd apps/api && TELEGRAM_BOT_ENABLED=false venv/bin/uvicorn app.main:app --reload --port 8001
cd apps/web && VITE_API_TARGET=http://127.0.0.1:8001 npm run dev -- --port 5174
# brauzerda http://10.10.50.8:5174/login -> "BRB-Tech ID bilan kirish"
```

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
- Natija: HRM/CRM ulanishlari kirishda o'zi ochilmaydi, "+" menyusida
  (Ulanishlar) avvalgidek qo'lda ulanadi. CRM Keycloak'ga ulangan - keyingi
  bosqichda SSO sessiyasidan o'zi ochiladi (Keycloak'da `barno-ai` ga
  `crm-client` audience mapper kerak). HRM Keycloak tokenini QABUL QILMAYDI
  (o'z JWT'si, 2026-09-29 da tekshirilgan) - HRM jamoasi buni qo'shguncha
  HRM qo'lda ulanadi.
- Token imzosi endi TEKSHIRILADI (`PyJWT[crypto]`, Keycloak JWKS).
- `POST /auth/login` faqat zahira (`users.yaml`); `LOCAL_LOGIN_ENABLED=false`
  bo'lsa 403.
- Chiqish Keycloak sessiyasini ham yopadi (`LogoutResponse.ssoLogoutUrl`).

## Keyingi bosqichlar

1. Mobil ilova: tizim brauzeri -> `start?return=barnoai://sso&channel=mobile`
   -> `barnoai://sso?sso=<kod>` -> `exchange` (`SSO_MOBILE_REDIRECT`).
2. Telegram Mini App: Telegram ulanishi (`/telegram/session`) avvalgidek;
   birinchi kirish web'da SSO bilan.
3. CRM ulanishini SSO sessiyasidan ochish; HRM - HRM jamoasi Keycloak
   tokenini qabul qilganda.
