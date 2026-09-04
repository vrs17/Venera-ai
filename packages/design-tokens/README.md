# Venera — dizayn tokenlari

Ikkala mahsulot (desktop va web) ulashadigan rang qiymatlarining **yagona manbasi**.

```
tokens.json          ← FAQAT shuni tahrirlang
build.py             ← generatsiya qiladi
   ├─→ apps/desktop/src/venera/ui/tokens.py    (generatsiya qilingan)
   └─→ apps/web/src/tokens.css                 (generatsiya qilingan)
```

## Ishlatish

```bash
# tokens.json ni tahrirlagandan keyin:
python3 packages/design-tokens/build.py
```

Tashqi kutubxona kerak emas. Generatsiya qilingan ikkala fayl ham git'da saqlanadi —
shuning uchun `npm run build` yoki PyInstaller uchun qo'shimcha qadam yo'q.

**Generatsiya qilingan fayllarni qo'lda tahrirlamang** — keyingi `build.py` ularni
qayta yozadi va o'zgarishingiz yo'qoladi.

## Nima ulashiladi, nima yo'q

| | Ulashiladimi | Qayerda |
|---|---|---|
| Holat ranglari (idle, thinking, speaking…) | **Ha** | `state` bo'limi |
| Natija ranglari (ok / warn / error) | **Ha** | `semantic` bo'limi |
| Brend harfi (tray ikonkasidagi `V`) | **Ha** | `brand.mark` |
| Desktop palitrasi (fon, accent, maydon) | Yo'q — faqat desktop | `desktop` bo'limi |
| Web mavzusi (och/qorong'i, `--accent`, `--bg`) | Yo'q — faqat web | `apps/web/src/index.css` |

## Ochiq dizayn savoli

Hozir ikkala mahsulot **turli palitrada** ishlaydi:

| | Fon | Accent |
|---|---|---|
| Desktop (tkinter) | `#12151B` qora-ko'k | `#2F6FED` ko'k |
| Web (och mavzu) | `#FCFBFA` issiq oq | `#E11900` qizil |
| Web (qorong'i mavzu) | `#131314` | `#FF453A` |

Bu **ataylab shunday qoldirilgan** — struktura o'zgarishi paytida mahsulotning
ko'rinishini o'zgartirish alohida qaror, va u dizayn qarorini talab qiladi.

Ikkalasini bir brendga keltirmoqchi bo'lsangiz, tanlash kerak: desktop web'ning
qizil accent'iga o'tadimi, yoki web desktop'ning ko'kiga? Qaror qilinganda
`tokens.json` ga `brand.accent` qo'shiladi va ikkala tomon o'shanga ulanadi.
Hozircha ikkalasi o'z bo'limida yashaydi va bir-birini buzmaydi.

## Nega bu papka bor

`window.py` da `ACCENT = "#2F6FED"`, `index.css` da `--accent: #E11900` — bular bir
joyda emas edi. Brend rangi o'zgarganda ikki faylni qo'lda tahrirlash kerak bo'lardi
va bir kuni ular sezdirmasdan farq qilib qolardi. Endi umumiy qiymatlar bitta
`tokens.json` da: bir marta o'zgartirasiz, `build.py` ikkala tarafga tarqatadi.
