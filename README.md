# Venera

Ovozli yordamchi platformasi. Ikkita mahsulot bitta repozitoriyada (monorepo).

| Mahsulot | Nima | Texnologiya | Papka |
|---|---|---|---|
| **Desktop** | Windows'da fonda ishlaydigan ovozli yordamchi | Python 3.11, tkinter, pystray | [apps/desktop/](apps/desktop/) |
| **Web** | Brauzerdagi chat interfeysi | Vue 3, TypeScript, Vite | [apps/web/](apps/web/) |

---

## Papkalar

```
Venera/
├── apps/                  Ishga tushadigan mahsulotlar
│   ├── desktop/           Windows ovozli yordamchi (Python)
│   └── web/               Vue 3 SPA
│
├── packages/              O'zi ishga tushmaydigan, ulashiladigan kod
│   └── design-tokens/     Ranglar - desktop va web uchun yagona manba
│
├── infra/                 Server sozlamalari (koddan mustaqil)
│   └── nginx/             Yangilanish serveri
│
├── docs/                  Umumiy hujjatlar
└── release/               Chiqarilgan .exe va version.json — sayt shu yerdan tarqatadi
```

> CI hozircha yo'q. Qo'shilganda har bir app o'z `.gitlab-ci.yml` faylini saqlaydi
> va root'dagi fayl ularni `include: local:` bilan chaqiradi. `local:` yo'llari
> HAR DOIM repo ildizidan hisoblanadi, va har bir job'da `rules: changes:` bo'lishi
> kerak — aks holda desktop'ga tegadigan commit web'ni ham qayta yig'adi.

### Nega shunday

**Har bir app o'zicha to'liq.** `apps/desktop/` ichida o'z `pyproject.toml`, o'z
testlari, o'z build skriptlari bor. `cd apps/desktop && pytest` boshqa hech narsaga
tegmaydi. Shuning uchun yangi mahsulot qo'shish — `apps/` ga bitta papka qo'shish.

**`packages/` — ulashiladigan narsalar uchun.** Bitta qoida: `apps/` dagi ikkitadan
ko'p joyda kerak bo'lgan narsa `packages/` ga chiqadi. Bittasida kerak bo'lsa, o'sha
app ichida qoladi.

**`infra/` — koddan ajratilgan.** nginx sozlamasi qaysi appga tegishli ekani
noaniq bo'lganda (masalan, desktop yangilanishlarini tarqatadigan server), u shu
yerga tushadi.

---

## Tez boshlash

### Desktop (Windows)

```powershell
cd apps\desktop
powershell -ExecutionPolicy Bypass -File packaging\build.ps1      # .exe yig'ish
powershell -ExecutionPolicy Bypass -File packaging\install.ps1    # o'rnatish
```

Testlar (istalgan OS'da):

```bash
cd apps/desktop
pip install -r requirements.txt -r requirements-dev.txt
pytest
```

Batafsil: [apps/desktop/README.md](apps/desktop/README.md)

### Web

```bash
cd apps/web
npm ci
npm run dev        # http://localhost:5173
npm run build      # dist/ ga yig'adi
```

Batafsil: [apps/web/README.md](apps/web/README.md)

### Dizayn tokenlari

Rangni o'zgartirish kerak bo'lsa — `apps/` ichida emas, shu yerda:

```bash
# packages/design-tokens/tokens.json ni tahrirlang, keyin:
python3 packages/design-tokens/build.py
```

Batafsil: [packages/design-tokens/README.md](packages/design-tokens/README.md)

---

## Hujjatlar

| Fayl | Nima haqida |
|---|---|
| [docs/deploy-linux-server.md](docs/deploy-linux-server.md) | Desktop yangilanishlarini Linux serverdan tarqatish |
| [docs/deploy-update-server.md](docs/deploy-update-server.md) | Yangilanish serverini nginx bilan sozlash |
| [docs/deploy-desktop-download.md](docs/deploy-desktop-download.md) | Saytdagi "Yuklab olish" tugmasini ishga tushirish |
| [docs/web-origin.md](docs/web-origin.md) | Web app qayerdan kelgani (tarixiy ma'lumot) |

---

## Yangi mahsulot qo'shish

Backend (Spring Boot API) hozircha bu repozitoriyada emas — u alohida serverda
ishlaydi va web app unga `/api/` orqali murojaat qiladi. Uni bu yerga
ko'chirmoqchi bo'lsangiz:

1. `apps/backend/` papkasini yarating — ichida o'z build fayli va testlari bilan
2. CI qo'shsangiz, `apps/backend/.gitlab-ci.yml` da `rules: changes: [apps/backend/**/*]`
3. Uni root `.gitlab-ci.yml` dagi `include:` ro'yxatiga qo'shing

Uchala qadam ham boshqa apps'ga tegmaydi — struktura aynan shuning uchun shunday.
