# Venera API — tarqatish

Backend (`apps/api`) host'da, `apps/api/.venv` ichidagi uvicorn bilan ishlaydi,
systemd `--user` xizmati sifatida. Frontend (`apps/web`) esa root'siz podman
konteynerida qoladi.

```
brauzer ──► nginx konteyner (:5173) ──┬─► /          SPA (Vue)
                                      └─► /api/*     uvicorn (127.0.0.1:8000)
```

API porti **tashqariga ochilmagan** — unga faqat nginx murojaat qiladi.

> **Nega backend konteynerda emas.** Kod tez-tez o'zgaradi va har o'zgarishda
> image qayta yig'ish ortiqcha; `git pull` + `restart` yetarli. Frontend esa
> konteynerda qoladi - u yig'ilgan statik fayllarni beradi xolos va nginx
> sozlamasi bilan birga kelishi qulay.

---

## 1. Bir marta: venv

Bu host'da **`python3 -m venv` ISHLAMAYDI** — `ensurepip` yo'q va uni
o'rnatish uchun `sudo apt install python3.10-venv` kerak. `virtualenv` esa
o'z pip'ini olib keladi, ya'ni sudo kerak emas:

```bash
pip3 install --user virtualenv

cd ~/Venera/apps/api
python3 -m virtualenv .venv
.venv/bin/pip install -e ".[dev]"
```

## 2. Bir marta: sozlama fayllari

```bash
cd ~/Venera/apps/api

cp .env.example .env
cp config/users.example.yaml config/users.yaml

# SECRET_KEY ni ALBATTA o'zgartiring (kamida 32 belgi):
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
# chiqqan qiymatni .env dagi SECRET_KEY= ga qo'ying
```

Ikkalasi ham git'ga tushmaydi. Unutilsa `/api/health` `degraded` qaytaradi
va sababini yozadi.

## 3. Bir marta: Swagger fayllari


```bash
cd ~/Venera/apps/api && mkdir -p app/static
V=5.17.14
curl -fsSL -o app/static/swagger-ui-bundle.js \
  "https://cdn.jsdelivr.net/npm/swagger-ui-dist@$V/swagger-ui-bundle.js"
curl -fsSL -o app/static/swagger-ui.css \
  "https://cdn.jsdelivr.net/npm/swagger-ui-dist@$V/swagger-ui.css"
```

Bu qadam **tashlab ketilsa ham server ko'tariladi**, lekin ichki tarmoqda
(internetsiz) Swagger sahifasi **bo'sh** ochiladi: FastAPI fayllarni
`cdn.jsdelivr.net` dan yuklashga urinadi. Fayllar joyida bo'lsa
`app/main.py` ularni lokal beradi.

## 4. Xizmatni o'rnatish

```bash
mkdir -p ~/.config/systemd/user
cp ~/Venera/apps/api/deploy/venera-api.service \
   ~/.config/systemd/user/venera-api.service

systemctl --user daemon-reload
systemctl --user enable --now venera-api.service

# Sessiyadan chiqqanda ham ishlab tursin.
# BUSIZ logout qilganingizda xizmat O'CHADI.
loginctl enable-linger $USER
```

## 5. Frontend

```bash
cp ~/Venera/apps/web/deploy/venera-frontend.user.service \
   ~/.config/systemd/user/venera-frontend.service
systemctl --user daemon-reload
systemctl --user restart venera-frontend.service
```

---

## Avtomatik qayta ishga tushish

| Holat | Xulq |
|---|---|
| Jarayon yiqildi (crash, OOM, SIGKILL) | 3 soniyadan keyin qayta ishga tushadi |
| Xato kod bilan chiqdi | qayta ishga tushadi |
| Server qayta yuklandi | `enable` + `linger` tufayli avtomatik |

Sozlama `Restart=always`, `RestartSec=3`, `StartLimitBurst=0`.

**`StartLimitBurst=0` muhim:** default qiymat (10 soniyada 5 marta) bilan
xizmat qayta-qayta yiqilsa systemd taslim bo'lib uni butunlay **o'chirib
qo'yadi** va keyin **qo'lda** yoqish kerak bo'ladi. Tungi soat 3 da
ma'lumotlar bazasi kech ko'tarilsa aynan shu bo'ladi.

**Tiklanish ~5 soniya**, 3 emas. `Type=exec` systemd ga jarayon *ishga
tushgani* haqida xabar beradi, lekin uvicorn portni biroz keyinroq band
qiladi. O'sha oraliqda nginx 502 qaytaradi. Bu o'lchangan, kutilgan xulq.

## Kundalik buyruqlar

```bash
systemctl --user status venera-api.service      # holat
systemctl --user restart venera-api.service     # qayta ishga tushirish
journalctl --user -u venera-api.service -f      # jonli log
journalctl --user -u venera-api.service -n 100  # oxirgi 100 qator
```

## Kodni yangilash

```bash
cd ~/Venera && git pull
systemctl --user restart venera-api.service
```

Bog'liqliklar `pyproject.toml` da o'zgargan bo'lsa qo'shimcha:

```bash
cd ~/Venera/apps/api && .venv/bin/pip install -e ".[dev]"
```

Frontend uchun image qayta yig'iladi:

```bash
cd ~/Venera/apps/web
podman build -t localhost/venera-frontend:latest .
systemctl --user restart venera-frontend.service
```

---

## Tekshirish

```bash
# 1. Xizmat ko'tarildimi
systemctl --user is-active venera-api.service

# 2. API javob beryaptimi (host'dan)
curl -s http://127.0.0.1:8000/api/health

# 3. nginx orqali o'tyaptimi   <- ENG MUHIMI
curl -s http://127.0.0.1:5173/api/health

# 4. Login ishlayaptimi
curl -s -X POST http://127.0.0.1:5173/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@venera.uz","password":"venera2026"}'

# 5. Port TASHQARIGA ochilmaganini tasdiqlash
ss -ltn | grep 8000     # 127.0.0.1:8000 bo'lishi kerak, *:8000 EMAS
```

`status: "ok"` — hammasi joyida. `"degraded"` — ishlayapti, lekin
`warnings` ni o'qing (odatda `SECRET_KEY` o'zgartirilmagan).

**2-qadam ishlaydi, 3-qadam 502 beradi** — eng ko'p uchraydigan holat,
pastdagi birinchi tuzoqqa qarang.

---

## Ma'lum tuzoqlar

**`/api/*` da 502, API o'zi esa ishlayapti.** Frontend xizmatida
`--network slirp4netns:allow_host_loopback=true` yo'q. Root'siz podman
konteynerdan **host loopback'ga yo'lni default holda yopadi**, backend esa
ataylab `127.0.0.1:8000` da turadi. Log'da:

```bash
podman logs venera-frontend | grep 'Network is unreachable'
```

Sayt ochiladi va SPA yuklanadi — faqat login ishlamaydi, shuning uchun
buzilish darhol ko'zga tashlanmaydi.

**Xizmat ko'tarilmadi, `Address already in use`.** 8000-portni boshqa
jarayon band qilgan (odatda qo'lda qoldirilgan `uvicorn`):

```bash
ss -ltnp | grep 8000
```

**`ModuleNotFoundError` restart'dan keyin.** venv yangi bog'liqliksiz qolgan:
`cd ~/Venera/apps/api && .venv/bin/pip install -e ".[dev]"`.

**Xizmat logout'da o'chadi.** `loginctl enable-linger $USER` bajarilmagan.

**Swagger sahifasi bo'sh.** `app/static/` bo'sh — 3-qadamni bajaring.
