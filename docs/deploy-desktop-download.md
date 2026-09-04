# Saytdagi "Yuklab olish" tugmasini ishga tushirish

`/welcome` sahifasidagi Windows kartasi ishlashi uchun serverda bitta papka
sozlanadi. macOS kartasi "yaqinda" holatida turadi — u hech narsa talab qilmaydi.

## Qanday ishlaydi

```
release/version.json  ──┐
release/Venera-...exe ──┤  serverga nusxalanadi
                        ▼
        /var/www/venera/assistant/          ← diskdagi YAGONA nusxa
                        │
        ┌───────────────┴────────────────┐
        ▼                                ▼
  konteyner :ro mount              update serveri (nginx)
  /download/version.json           ccs.venera.uz/assistant/version.json
  /download/Venera-...exe          ← desktop ilova auto-update shu yerdan o'qiydi
        ▲
   sayt shu yerdan tarqatadi
```

Bitta fayl, ikkita yo'l. Shuning uchun saytda ko'rsatilgan versiya auto-update
ko'radigan versiyadan **farq qila olmaydi** — sinxrondan chiqish imkoni yo'q.

Sayt versiyani `/download/version.json` dan o'qiydi, ya'ni yangi `.exe` qo'yilganda
frontend'ni qayta yig'ish **shart emas**.

---

## 0-qadam (MAJBURIY): `.exe` ni qaytadan yig'ing

`release/` dagi hozirgi `Venera-AI-Assistant-Setup-0.2.3.exe` **nom
o'zgarishidan oldin** yig'ilgan. Uning ichida hali eski brending bor: u
`%LOCALAPPDATA%\Programs\BRB-Tech` ga o'rnatadi, tray'da "B" harfi chiqadi.

Faylning nomi Venera bo'lgani bilan **ichi hali Venera emas.** Windows
mashinasida qaytadan yig'ing:

```powershell
cd C:\Venera\apps\desktop
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
powershell -ExecutionPolicy Bypass -File packaging\build_setup.ps1
```

Natija: `apps\desktop\dist\Venera-AI-Assistant-Setup-<versiya>.exe`.

Keyin manifest yarating (SHA256 va hajmni o'zi hisoblaydi):

```bash
python3 apps/desktop/tools/make_manifest.py \
    apps/desktop/dist/Venera-AI-Assistant-Setup-0.2.4.exe \
    --notes "Venera nomiga o'tildi"
```

Ikkala faylni (`.exe` va `version.json`) `release/` ga qo'ying.

## 1-qadam: serverda papka yarating

```bash
sudo mkdir -p /var/www/venera/assistant
sudo chown -R ymamajonov:ymamajonov /var/www/venera/assistant
sudo chmod 755 /var/www/venera /var/www/venera/assistant
```

Egasi konteynerni ishga tushiradigan foydalanuvchi bo'lishi kerak — aks holda
rootless podman faylni o'qiy olmaydi va nginx 403 qaytaradi.

## 2-qadam: fayllarni yuklang

```bash
scp release/Venera-AI-Assistant-Setup-0.2.4.exe  srv:/var/www/venera/assistant/
scp release/version.json                          srv:/var/www/venera/assistant/
```

Tartib muhim: **avval `.exe`, keyin `version.json`.** Manifest yangi versiyani
e'lon qilgan payt fayl allaqachon joyida bo'lishi kerak, aks holda tugmani
bosgan foydalanuvchi 404 oladi.

## 3-qadam: konteynerni qayta ishga tushiring

Papka `venera-frontend.user.service` da read-only mount qilinadi:

```
-v /var/www/venera/assistant:/usr/share/nginx/downloads:ro,z
```

Unit fayli yangilangan bo'lsa:

```bash
cp apps/web/deploy/venera-frontend.user.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user restart venera-frontend.service
```

Bu qadam **faqat bir marta** kerak. Keyinchalik yangi `.exe` qo'yganda konteynerga
tegish shart emas — mount jonli papkani ko'rsatadi.

## 4-qadam: tekshiring

```bash
# Manifest ochiladimi va keshlanmayaptimi
curl -sS -i https://llm.venera.uz/download/version.json | head -8
# Kutilgan: HTTP 200, Content-Type: application/json, Cache-Control: no-cache

# .exe to'liq keladimi
curl -sS -o /dev/null -w '%{http_code} %{size_download}\n' \
    https://llm.venera.uz/download/Venera-AI-Assistant-Setup-0.2.4.exe
# Kutilgan: 200 va version.json dagi `setup.size` bilan bir xil son

# Papka ro'yxati YOPIQ bo'lishi kerak
curl -sS -o /dev/null -w '%{http_code}\n' https://llm.venera.uz/download/
# Kutilgan: 404
```

Keyin `/welcome` ni brauzerda oching — Windows kartasida versiya va hajm
ko'rinishi kerak.

---

## Xavfsizlik: nima ochiq, nima yopiq

`apps/web/deploy/nginx.container.conf` da uchta alohida `location` bor va faqat
ikkita narsa ochiq:

| Yo'l | Holat |
|---|---|
| `/download/version.json` | Ochiq, `Cache-Control: no-cache` |
| `/download/<nom>.exe` | Ochiq, 30 kun kesh, `Content-Disposition: attachment` |
| `/download/` (papka ro'yxati) | **404** |
| `/download/` ostidagi boshqa har qanday fayl | **404** |

`.exe` nomi `[A-Za-z0-9._-]+` bilan cheklangan, shuning uchun `/` yoki `..`
orqali papkadan chiqib bo'lmaydi.

`.exe` location'ida `add_header` ishlatilgani uchun server darajasidagi
sarlavhalar meros bo'lmaydi — `X-Content-Type-Options`, `X-Frame-Options` va
`Referrer-Policy` o'sha yerda qayta e'lon qilingan. CSP ataylab qo'shilmagan:
u yuklab olinadigan binar faylga taalluqli emas.

## Lokalda sinash

Server umuman kerak emas — Vite dev-server `release/` papkasini `/download/`
ostida ko'rsatadi (`apps/web/vite.config.ts`, `releaseDownloads` plugini):

```bash
cd apps/web && npm run dev     # http://localhost:5173/welcome
```

Bu plugin `apply: 'serve'` bilan cheklangan, ya'ni `vite build` paytida
ishlamaydi va 45 MB `.exe` hech qachon `dist/` ga tushmaydi.

## Nosozliklar

| Belgi | Sabab |
|---|---|
| Kartada "Yuklab olish vaqtincha ishlamayapti" | `/download/version.json` 404 yoki JSON buzuq. `curl` bilan tekshiring. |
| 403 Forbidden | Papka egasi noto'g'ri, yoki SELinux. Mount'da `:z` borligini va `chown` qilinganini tekshiring. |
| Tugma eski versiyani ko'rsatadi | Manifest keshlangan. `Cache-Control: no-cache` kelayotganini tekshiring. |
| `.exe` o'rniga HTML keladi | `location /download/ { return 404; }` bloki yo'q — so'rov SPA fallback'ga tushyapti. |
| Yuklandi, lekin BRB nomi bilan o'rnatildi | 0-qadam bajarilmagan — `.exe` eski build. |
