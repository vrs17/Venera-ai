# Barno konnektori - Claude va ChatGPT uchun (MCP)

Holat: LOYIHA (2026-11-25). Kod hali yo'q; bu hujjat - 1-bosqich rejasi va egasining qarorlari.
Shox: `barno-mcp-connector`.

## Nima va nega

Xodim o'z Claude yoki ChatGPT obunasida (istalgan joydan - web, desktop, telefon) Barno
ma'lumotini o'qiy oladi: "kechagi yig'ilishda nima kelishildi?", "menga qaysi vazifalar
tushdi?". Buning uchun Barno ochiq **MCP serveri** beradi; Claude va ChatGPT uni
"konnektor" (custom connector / app) sifatida qo'shadi va xodim BRB-Tech ID bilan kiradi.

## Egasining qarorlari (2026-11-25)

| Savol | Qaror |
|---|---|
| Ma'lumot qoidasi | **Har kim o'zi yoqadi**: default o'chiq; xodim modul bo'yicha ruxsat beradi; admin hammaga o'chira oladi; har murojaat jurnalda |
| 1-bosqich | **Faqat o'qish**, faqat **Plaud** (yig'ilishlar) moduli |
| Tarqatish | Manzil bilan qo'shish **va** Claude / ChatGPT kataloglariga topshirish |
| Keyingi bosqichlar | CRM, HRM, keyin balki Telegram guruhlari - bittadan |

Eslatma: shu paytgacha qoida "kompaniya ma'lumoti tarmoqdan tashqaridagi modelga faqat
ruxsat bilan" edi. Konnektor - aynan shu ruxsat, lekin ODAM darajasida: ma'lumot xodimning
O'Z obunasidagi modelga, o'zi rozilik bergandan keyin ketadi.

## Manzil

`https://llm.brb-tech.uz/mcp` - sayt allaqachon ochiq va HTTPS. Tizim nginx'i hamma narsani
sayt konteyneriga beradi; konteyner nginx'i (`apps/web/deploy/nginx.container.conf`) bizning
repoda - yangi yo'llar (`/mcp`, `/.well-known/oauth-*`, `/oauth/*`) sudo'siz qo'shiladi.

## 1-bosqich vositalari (Plaud, faqat o'qish)

Hammasi odamning O'Z yig'ilishlari (`services/meetings/service.py` dagi `_owned`): boshqa
xodimning yozuvi hech qachon ko'rinmaydi. Har vosita `readOnlyHint: true`.

| Vosita | Manba (`service.*`) | Natija |
|---|---|---|
| `search_meetings` | `list_meetings(q=..., limit, offset, origin)` | id, nomi, sanasi, davomiyligi, holati |
| `get_meeting` | `detail` | yig'ilish kartasi |
| `get_summary` | `summaries` + `get_summary` / `export_summary(md)` | eng so'nggi (yoki tanlangan) xulosa, markdown |
| `get_transcript` | `transcript` (matn, so'zlovchi nomlari bilan) | uzun bo'lsa bo'laklab (`cursor`) |
| `list_action_items` | `action_items` / `my_action_items` | vazifalar: kim, muddat, holat |
| `get_minutes` | `minutes` | bayonnoma (bo'lsa) |
| `search` / `fetch` | yuqoridagilar ustidan | ChatGPT "deep research" kutadigan ikki vosita |

## Kirish va ruxsat

Tekshirildi 2026-11-25 (rasmiy hujjatlar: claude.com/docs/connectors, developers.openai.com/apps-sdk,
modelcontextprotocol.io - avtorizatsiya 2026-07-28, keycloak.org - MCP qo'llanmasi).

**Barno - o'zining kichik OAuth serveri, kirish esa BRB-Tech ID orqali.** Keycloak'ni to'g'ridan-to'g'ri
avtorizatsiya serveri qilmaymiz: uning yangi MCP talablari (CIMD, RFC 8707) hali "experimental"
flag'lar ortida, ChatGPT va Claude Desktop bilan ma'lum nosozliklari bor, va bizga baribir
o'z rozilik ekranimiz kerak (modul bo'yicha ruxsat - egasining qarori). Keycloak'da hech narsa
o'zgarmaydi: odam bugungi sayt kirishidan (SSO) foydalanadi.

Oqim:

1. Claude / ChatGPT `/mcp` ga tokensiz keladi -> `401` va
   `WWW-Authenticate: Bearer resource_metadata=".../.well-known/oauth-protected-resource/mcp"`.
2. Metadata: `/.well-known/oauth-protected-resource` (RFC 9728, `authorization_servers` =
   `https://llm.brb-tech.uz`) va `/.well-known/oauth-authorization-server` (RFC 8414):
   `code_challenge_methods_supported: [S256]`, `token_endpoint_auth_methods_supported: [none]`,
   `client_id_metadata_document_supported: true`, `authorization_response_iss_parameter_supported: true`.
3. Mijoz kimligi: **CIMD** (Claude: "published identity", ChatGPT: `https://chatgpt.com/oauth/client.json`,
   Claude Code: `https://claude.ai/oauth/claude-code-client-metadata`) - faqat ruxsat ro'yxatidagi
   hostlardan (`claude.ai`, `chatgpt.com`) yuklanadi. Zaxira - **DCR** (`/oauth/register`), lekin
   faqat ma'lum qaytish manzillari bilan (`https://claude.ai/api/mcp/auth_callback`,
   `https://chatgpt.com/connector_platform_oauth_redirect`, `https://chatgpt.com/connector/oauth/*`,
   Claude Code uchun `http://localhost|127.0.0.1:<port>/callback`); boshqasi rad etiladi.
4. `/oauth/authorize`: `client_id`, aniq `redirect_uri`, `code_challenge` (S256), `resource` =
   `https://llm.brb-tech.uz/mcp`, `scope` tekshiriladi -> so'rov serverda saqlanadi -> sayt
   sahifasi `/connect?request=...`. Odam kirmagan bo'lsa - bugungi BRB-Tech ID kirishi, keyin shu
   sahifaga qaytadi.
5. Rozilik sahifasi: "Claude sizning Plaud yig'ilishlaringizni o'qimoqchi" + modul belgilari +
   ogohlantirish (pastga qara). "Ruxsat berish" -> server bir martalik kod beradi (odamning
   Barno tokeni bilan, cookie emas - CSRF yo'q) -> `redirect_uri?code=&state=&iss=`.
6. `/oauth/token`: kod + `code_verifier` (PKCE) -> access token (1 soat) + refresh token
   (aylanadi, 30 kun). Tokenlar shaffof emas (tasodifiy), serverda HASH bo'lib, `resource` ga
   bog'langan - bekor qilish darhol ishlaydi. `/oauth/revoke` ham bor.

Rozilik ekranidagi ogohlantirish (qisqa): ma'lumot sizning Claude / ChatGPT hisobingizga ketadi;
shaxsiy (Free/Plus/Pro) rejalarda model o'qitishga ruxsat sozlamasini o'chiring; istalgan
payt Barno -> Sozlamalar -> "Ulangan ilovalar" dan uzasiz.

Kim ishlata oladi (2026-11 holati): **Claude** - hamma rejalar (Free - bitta konnektor; Team /
Enterprise da konnektorni tashkilot egasi qo'shadi), web, desktop, telefon va Claude Code.
**ChatGPT** - to'liq: Business / Enterprise / Edu; Pro - faqat o'qish; Plus - aniq emas; faqat web.
Bizning 1-bosqich faqat o'qish, ya'ni Pro ham yetadi.

MCP o'zi: Streamable HTTP, holatsiz, `POST /mcp` JSON javob bilan (SSE yo'q); `initialize`,
`tools/list`, `tools/call`, `ping`; `Origin` tekshiriladi; protokol versiyalari 2025-03-26 ...
2025-11-25. Tashqi kutubxona (`mcp` SDK) qo'shilmaydi - kerakli qism kichik va to'liq testlanadi.

## Xavfsizlik

- Token faqat shu konnektor uchun (audience = `https://llm.brb-tech.uz/mcp`), qisqa umrli;
  Barno'ning oddiy kirish tokeni MCP da ishlamaydi va aksincha.
- Har vosita qamrovni (`plaud.read`) tekshiradi; modul o'chirilgan bo'lsa - 403.
- Bloklangan hisob, o'chirilgan modul yoki admin "o'chirish" tugmasi - darhol (keyingi
  chaqiruvda) ishlamaydi.
- Jurnal: kim, qaysi ilova (Claude / ChatGPT), qaysi vosita, qachon, natija hajmi -
  matnning o'zi jurnalga tushmaydi.
- Chegaralar: daqiqasiga N chaqiruv, javob hajmi chegarasi (transkript bo'laklab).

## Kataloglarga topshirish

**Claude katalogi** (claude.com/docs/connectors/building/submission): har vosita `title` va
`readOnlyHint` bilan, nomi <= 64 belgi, o'qish va yozish alohida vositalar; hujjat sahifasi,
maxfiylik siyosati, yordam manzili, ikonka va 7 ta siyosat tasdig'i. Avval "Community",
keyin "Verified" (sinov hisobi bilan tekshiruv). Topshiradi: Team/Enterprise da tashkilot egasi.

**ChatGPT katalogi** (developers.openai.com/apps-sdk/deploy/submission): tasdiqlangan kompaniya
hisobi, sayt / yordam / maxfiylik / **foydalanish shartlari** sahifalari, domen tasdig'i
(`/.well-known/openai-apps-challenge`), **MFA siz sinov hisobi**, 5 ijobiy va 3 salbiy sinov
holati, video. Izohlar aniq bo'lsin (`readOnlyHint`, `destructiveHint`, `openWorldHint`).

Egadan kerak bo'ladi: BRB-Tech ID da sharhlovchi uchun sinov hisobi (MFA siz) va unda namuna
yig'ilishlar (Google Play sharhlovchisi kabi); foydalanish shartlari matni; yordam manzili;
OpenAI va Anthropic tashkilot hisoblarida topshirish. Bizda: `/privacy` ga konnektor bo'limi,
`/connector` hujjat sahifasi, ikonka.

Diqqat: ikkala katalogda ham faqat BRB-Tech xodimlari kira oladi - katalog faqat qo'shishni
osonlashtiradi (manzilni yozish o'rniga ro'yxatdan tanlash).

## Ish tartibi (1-bosqich)

1. OAuth eshigi: metadata, CIMD/DCR, authorize, token, revoke, saqlash, testlar.
2. MCP: `/mcp` protokoli, Plaud vositalari, qamrov va jurnal, testlar.
3. Sayt: `/connect` rozilik sahifasi, Sozlamalar -> "Ulangan ilovalar", admin o'chirgichi.
4. Konteyner nginx: `/mcp`, `/oauth/`, `/.well-known/oauth-*` - bufersiz, API ga.
5. Sinov: avval egasining o'zi Claude va ChatGPT da (manzil bilan), keyin kataloglar.
6. Hujjatlar: `/privacy` bo'limi, `/connector` sahifasi, katalog materiallari.

Yoqish: `.env` da `MCP_CONNECTOR_ENABLED=true` (jonli o'qiladi; o'chiq bo'lsa hamma yo'l 404).

## Qilinmaydi (1-bosqich)

Yozish (nomini o'zgartirish, vazifa tahriri, CRM ga yuborish), audio fayl, boshqa modullar.
