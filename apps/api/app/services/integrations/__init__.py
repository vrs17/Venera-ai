"""Tashqi tizim klientlari.

`services/pipeline.py` ning kengayadigan nuqtasi shu papka: har tizim
BITTA modul, va u faqat o'z protokolini biladi. HTTP qatlami (`api/v1/`)
bu modullarni chaqiradi, lekin ularning ichida FastAPI haqida hech narsa
yozilmaydi - shu tufayli mantiqni test qilish uchun server ko'tarish
kerak emas.

Qoida: sir (`client_secret`, token) BU YERDAN TASHQARIGA CHIQMAYDI.
Xato xabarlarida ham ichki host va sir bo'lmaydi - `_redact` ga qara.
"""
