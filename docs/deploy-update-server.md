# Yangilanishni ccs.venera.uz orqali tarqatish

Kompyuterlar ochiq internetda, shuning uchun yangilanish manzili public HTTPS
bo'ladi. Server tomonda o'rnatiladigan dastur yo'q - nginx faqat ikkita
statik faylni beradi.

## 1. Server tomonda (bir marta, IT bajaradi)

```bash
sudo mkdir -p /var/www/venera/assistant
sudo chown -R www-data:www-data /var/www/venera
```

`infra/nginx/venera-updates.conf` ichidagi blokni `ccs.venera.uz` ning
`server { }` blokiga qo'shing, keyin:

```bash
sudo nginx -t && sudo systemctl reload nginx
```

Tekshirish (fayllar hali yo'q, shuning uchun **404 kutiladi** - HTML emas):

```bash
curl -sI https://ccs.venera.uz/assistant/version.json | head -1
# kutilgan:  HTTP/2 404
# noto'g'ri: HTTP/2 200   <- blok qo'shilmagan, SPA hali ham javob beryapti
```

## 2. Har safar yangi versiya chiqarilganda

Windows'da:

```powershell
powershell -ExecutionPolicy Bypass -File packaging\publish.ps1 `
    -Target "C:\publish\assistant" `
    -UpdateUrl "https://ccs.venera.uz/assistant/version.json" `
    -Notes "Nima o'zgardi"
```

`C:\publish\assistant` ichida ikkita fayl paydo bo'ladi:

| Fayl | Hajm |
|---|---|
| `version.json` | ~400 bayt |
| `Venera-AI-Assistant-Setup-<versiya>.exe` | ~45 MB |

Ikkalasini serverdagi `/var/www/venera/assistant/` ga yuklang (scp/WinSCP/CI).
**Tartib muhim:** avval `.exe`, keyin `version.json`. Aks holda manifest
hali yuklanmagan faylga ishora qilib turadi va kompyuterlar xato oladi.

```bash
scp Venera-AI-Assistant-Setup-0.2.3.exe  srv:/var/www/venera/assistant/
scp version.json                            srv:/var/www/venera/assistant/
```

Tekshirish:

```bash
curl -s https://ccs.venera.uz/assistant/version.json
curl -sI https://ccs.venera.uz/assistant/Venera-AI-Assistant-Setup-0.2.3.exe | head -3
# Content-Type: application/octet-stream   <- text/html BO'LMASLIGI kerak
```

Shundan keyin har bir kompyuter 6 soat ichida (yoki qayta ishga tushganda
90 soniyadan so'ng) yangilanishni o'zi ko'radi.

## 3. Eski fayllarni saqlab qoling

`version.json` faqat oxirgi versiyaga ishora qiladi, lekin eski `.exe`
fayllarni o'chirmang: yangilanish yarim yo'lda uzilgan kompyuter qayta
urinishi mumkin.

## Xavfsizlik eslatmasi

Bu yo'l ochiq internetda - havolani bilgan har kim 45 MB o'rnatuvchini
yuklab olishi mumkin. O'rnatuvchi ichida parol yoki ichki manzil yo'q, lekin
bank ichki vositasini butun internetga ochib qo'ymaslik ma'qul. Eng arzon
himoya - yo'lni topib bo'lmaydigan qilish:

    /assistant/            ->   /a7f3c91e-assistant/

Manzil o'rnatuvchi ichiga yopishtiriladi, foydalanuvchi uni qo'lda
yozmaydi - shuning uchun uzun yo'l hech kimga noqulaylik tug'dirmaydi.
Bunga qaror qilsangiz ayting, `infra/nginx/venera-updates.conf` va publish buyrug'ini
shunga moslayman.

Kuchliroq variant - IP bo'yicha cheklash yoki HTTP Basic Auth, lekin ikkinchisi
o'rnatuvchi ichida parol saqlashni talab qiladi va u yerda parol maxfiy emas.
