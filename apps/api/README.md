# Venera API

Web ilova (`apps/web`) uchun backend. FastAPI, Python 3.10+.

## Tez boshlash

```bash
cd apps/api

python3 -m venv .venv && source .venv/bin/activate     # ixtiyoriy
pip install -e ".[dev]"

cp .env.example .env
cp config/users.example.yaml config/users.yaml

uvicorn app.main:app --reload --port 8000
```

Hujjat: <http://localhost:8000/docs> — avtomatik generatsiya qilinadi, qo'lda yozilmaydi.
Holat: <http://localhost:8000/health>

Frontend bilan birga ishga tushirish:

```bash
# 1-terminal
cd apps/api && uvicorn app.main:app --reload --port 8000

# 2-terminal
cd apps/web && npm run dev
```

`apps/web/.env` dagi `VITE_API_TARGET` shu backend'ga qaraydi, ya'ni Vite
`/api/*` so'rovlarini unga uzatadi va brauzerda CORS umuman kerak bo'lmaydi.

## Demo hisoblar

`config/users.example.yaml` dagi ikkita hisob:

| Email | Parol | Rollar |
|---|---|---|
| `admin@venera.uz` | `venera2026` | ADMIN, RAG_ADMIN |
| `demo@venera.uz` | `demo2026` | USER |

Yangi foydalanuvchi qo'shish:

```bash
python -m app.tools.hash_password      # parol so'raydi, xesh beradi
# chiqqan `password_hash` ni config/users.yaml ga qo'ying
```

Parol **hech qachon** ochiq saqlanmaydi — faqat PBKDF2 xeshi (600 000 iteratsiya).

## Tuzilma

```
app/
  main.py          ilova nuqtasi: router'lar, CORS, xato handler'lari
  core/
    config.py      sozlamalar (muhit o'zgaruvchilari + .env)
    security.py    parol xeshi va JWT token
    errors.py      YAGONA xato shakli
  api/
    deps.py        Depends(...) uchun: current_user, get_user_store
    v1/
      __init__.py  router'lar shu yerda yig'iladi
      auth.py      login, me, logout
      chat.py      ask
  schemas/         so'rov/javob modellari
    auth.py
    chat.py
  services/        ⬅ MANTIQ SHU YERDA
    users.py       foydalanuvchilar ombori
    pipeline.py    chat quvuri — CRM/HRM shu yerga ulanadi
  tools/
    hash_password.py
tests/
config/
  users.example.yaml
```

**Asosiy qoida:** router'da mantiq yozilmaydi, `services/` da HTTP haqida
bilinmaydi. Shu tufayli mantiqni test qilish uchun HTTP kerak emas va
integratsiya qo'shganda router'ga tegilmaydi.

## Endpointlar

| Metod | Yo'l | Auth | Izoh |
|---|---|---|---|
| POST | `/api/v1/auth/login` | — | email + parol → token |
| GET | `/api/v1/auth/me` | ✅ | tokenni tekshiradi |
| POST | `/api/v1/auth/logout` | ✅ | tasdiq (JWT holatsiz) |
| POST | `/api/v1/auth/signup` | — | 501 — demo uchun yopiq |
| POST | `/api/v1/auth/change-password` | — | 501 — demo uchun yopiq |
| POST | `/api/v1/chat/ask` | ✅ | savol → quvur → javob |
| GET | `/health` | — | holat va ogohlantirishlar |

## Frontend shartnomasi

`app/schemas/` dagi modellar `apps/web/src/types.ts` dagi interfeyslarning
**aynan nusxasi**. Maydon nomi yoki turi farq qilsa frontend **jimgina**
buziladi: TypeScript serverdan kelgan JSON ni ishga tushish paytida
tekshirmaydi, va foydalanuvchi ekranida `undefined` ko'rinadi.

Shuni `tests/test_contract.py` qo'riqlaydi. Sxemani o'zgartirsangiz
`types.ts` ni ham o'zgartiring — va aksincha.

Eng ko'p unutiladigan detal: FastAPI default holda `{"detail": "..."}`
qaytaradi, frontend esa `message` maydonini o'qiydi. Shuning uchun
`core/errors.py` uchala handler'ni ham almashtiradi.

## Yangi tizim qo'shish (CRM, HRM, ...)

Butun kengayish `app/services/pipeline.py` da:

1. `app/services/integrations/<tizim>.py` — o'sha tizimning klienti
2. `pipeline.py` dagi `_ROUTES` ga bitta qator: qaysi intent → qaysi modul
3. `_dispatch()` ga shox qo'shing

Boshqa hech qayerga tegilmaydi: `schemas/` ham, `api/` ham, frontend ham.
Quvur javobining shakli o'zgarmagani uchun UI avtomatik ishlaydi.

## Testlar

```bash
pytest -q
```

`tests/test_contract.py` — eng muhimi: frontend bilan shartnoma.

## Ishlab chiqarish uchun

- `SECRET_KEY` ni **albatta** o'zgartiring:
  `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`.
  Unutilsa `/health` `degraded` qaytaradi va ogohlantiradi.
- `config/users.yaml` va `.env` git'ga tushmaydi.
- CORS odatda kerak emas: nginx frontend va `/api` ni bir xil originda
  ko'rsatadi.
