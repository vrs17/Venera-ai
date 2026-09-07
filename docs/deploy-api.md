# Venera API — tarqatish

Backend (`apps/api`) root'siz podman konteynerida, systemd `--user` xizmati
sifatida ishlaydi. Frontend ham aynan shunday (`apps/web`), ya'ni ikkala
xizmat bir xil naqsh bilan boshqariladi.

```
brauzer ──► nginx konteyner (:5173) ──┬─► /          SPA (Vue)
                                      └─► /api/*     API konteyner (127.0.0.1:8000)
```

API porti **tashqariga ochilmagan** — unga faqat nginx murojaat qiladi.

---

## 1. Bir marta: sozlama fayllari

```bash
cd ~/Venera/apps/api

cp .env.example .env
cp config/users.example.yaml config/users.yaml

# SECRET_KEY ni ALBATTA o'zgartiring:
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
# chiqqan qiymatni .env dagi SECRET_KEY= ga qo'ying
```

Ikkalasi ham git'ga tushmaydi. Unutilsa `/api/health` `degraded` qaytaradi
va sababini yozadi.

## 2. Image yig'ish

```bash
cd ~/Venera/apps/api
podman build -t localhost/venera-api:latest .
```

Build paytida internet kerak (Swagger UI fayllari yuklab olinadi).
Foydalanuvchi tarmog'ida internet kerak emas.

## 3. Xizmatni o'rnatish

```bash
mkdir -p ~/.config/systemd/user
cp ~/Venera/apps/api/deploy/venera-api.user.service \
   ~/.config/systemd/user/venera-api.service

systemctl --user daemon-reload
systemctl --user enable --now venera-api.service

# Sessiyadan chiqqanda ham ishlab tursin.
# BUSIZ logout qilganingizda xizmat O'CHADI.
loginctl enable-linger $USER
```

## 4. Frontend'ni yangi backend'ga qaratish

`deploy/venera-frontend.user.service` da `API_UPSTREAM` allaqachon
o'zgartirilgan. Xizmatni yangilang:

```bash
cp ~/Venera/apps/web/deploy/venera-frontend.user.service \
   ~/.config/systemd/user/venera-frontend.service
systemctl --user daemon-reload
systemctl --user restart venera-frontend.service
```

---

## Avtomatik qayta ishga tushish

Xizmat quyidagi holatlarda **o'zi ko'tariladi**:

| Holat | Xulq |
|---|---|
| Jarayon yiqildi (crash, OOM) | 3 soniyadan keyin qayta ishga tushadi |
| Xato kod bilan chiqdi | qayta ishga tushadi |
| Server qayta yuklandi | `enable` + `linger` tufayli avtomatik |
| Konteyner o'chirildi | qayta yaratiladi |

Sozlama `Restart=always`, `RestartSec=3`, `StartLimitBurst=0`.

**`StartLimitBurst=0` muhim:** default qiymat (10 soniyada 5 marta) bilan
xizmat qayta-qayta yiqilsa systemd taslim bo'lib uni butunlay **o'chirib
qo'yadi** va keyin **qo'lda** yoqish kerak bo'ladi. Tungi soat 3 da
ma'lumotlar bazasi kech ko'tarilsa aynan shu bo'ladi.

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
cd apps/api
podman build -t localhost/venera-api:latest .
systemctl --user restart venera-api.service
```

Frontend uchun xuddi shunday, `apps/web` ichida.

---

## Tekshirish

```bash
# 1. Konteyner ko'tarildimi
systemctl --user is-active venera-api.service

# 2. API javob beryaptimi (host'dan)
curl -s http://127.0.0.1:8000/api/health | python3 -m json.tool

# 3. nginx orqali o'tyaptimi
curl -s http://127.0.0.1:5173/api/health | python3 -m json.tool

# 4. Login ishlayaptimi
curl -s -X POST http://127.0.0.1:5173/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@venera.uz","password":"venera2026"}'
```

`status: "ok"` — hammasi joyida. `"degraded"` — ishlayapti, lekin
`warnings` ni o'qing (odatda `SECRET_KEY` o'zgartirilmagan).

---

## Ma'lum tuzoqlar

**`host.containers.internal` topilmasa.** Eski podman versiyalarida bu nom
yo'q. Frontend xizmatidagi `API_UPSTREAM` ni host'ning podman ko'prigidagi
manziliga o'zgartiring:

```bash
ip -4 addr show podman0 | grep inet    # odatda 10.88.0.1
```

**Xizmat logout'da o'chadi.** `loginctl enable-linger $USER` bajarilmagan.

**Swagger sahifasi bo'sh.** Image eski — Swagger fayllarisiz yig'ilgan.
Qayta yig'ing (build paytida internet bo'lishi shart).

**403 yoki config o'qilmadi.** SELinux yoqilgan host'da bind-mount'larda
`:z` bayrog'i bo'lishi kerak — xizmat faylida u bor.
