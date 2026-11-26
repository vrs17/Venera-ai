"""Telefoniya: Barno mijozlarga FreePBX orqali qo'ng'iroq qiladi (1-bosqich - faqat CHIQUVCHI).

    venera (shu paket) --call-live--> FreePBX --> mijoz telefoni
                                          \\--javob bersa--> Barno shlyuzi (Asterisk 20) -> bridge -> Speko
    FreePBX --natija (X-Service-Key)--> POST /api/v1/telephony/call-result

Modullar:
    freepbx  - `call-live.php` klienti: sertifikat barmoq izi bilan, javob kodlarini tushunadi;
    store    - qo'ng'iroqlar ombori (SQLite, `data/telephony/calls.db`) va kelgan har natija qaydi;
    service  - qo'ng'iroq boshlash, natijani qabul qilish, holatlar, bridge qaydini qo'shish.

SHAXSIY MA'LUMOT. FreePBX faqat telefon raqami va `call_id` ni biladi - ism, summa, sana kabi narsalar unga
yuborilmaydi (`metadata` doim bo'sh): ular Barno'da `call_id` bo'yicha turadi. Jurnalga raqam yashirib yoziladi.
"""
