"""Kutish ovozlari: tayyor gaplar, ularning oldindan sintez qilingan ovozi
va mavzuni tanlashning zahira yo'li.

ISHLASH TARTIBI (ovozli suhbat):

    t=0     STT matni -> HRM/CRM ga (javob)  +  PARALLEL -> gemma (tasniflash)
    t≈0.8   gemma: "kechikish|shoshilinch" -> mos TAYYOR ovoz o'ynaladi
    t≈9     javob hali yo'q -> keyingi tayyor ovoz (javob kelguncha)
    javob   joriy ovoz OXIRIGACHA eshittiriladi, keyin javob TTS orqali

NEGA MODEL GAP YOZMAYDI, FAQAT TANLAYDI. Avvalgi versiyada gemma gapni
o'zi yozardi. Ikki muammo o'lchandi:
  * ovozgacha 2.0 s: model 0.9 s + TTS 1.1 s. Tayyor ovoz bilan esa model
    0.77 s va TTS nol - chunki ovoz oldindan sintez qilingan;
  * TO'QIMA XAVFI. "Foydalanuvchini ushlab tur" deb so'ralgan model javobni
    o'zi to'qib qo'yishga moyil ("Mahmud uch marta kechikkan") va odam buni
    HRM ma'lumoti deb qabul qiladi. Gap yozganda himoya faqat TEKSHIRGICH
    edi. Ro'yxatdan TANLAGANDA esa model javobni to'qiy olmaydi - imkoniyatning
    o'zi yo'q. To'r emas, devor.

Ustiga har bir gapni odam BIR MARTA eshitib tekshirishi mumkin - model yozgan
matnni esa TTS hech kim eshitmagan holda o'qirdi.

GAPLARDA FAKT YO'Q. Kutish gapi javob emas, kutish haqida: mavzuga ishora
qiladi ("kechikishlar bo'yicha ma'lumotlarni tekshirayapman"), lekin ism,
raqam, sana yoki natija aytmaydi. "Hozir tayyor bo'ladi" ham YO'Q - bu
va'da, va u 30 sekundlik kutishda yolg'on chiqadi. Buni test qo'riqlaydi.

OVOZ FAQAT O'ZBEKCHA: TTS serverida faqat o'zbek ovozlari bor. Rus va ingliz
interfeysida kutish ovozi yo'q.
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
from pathlib import Path

log = logging.getLogger(__name__)

#: Mavzu yorliqlari. Tasniflagich FAQAT shulardan birini qaytara oladi.
MAVZULAR: dict[str, str] = {
    "kechikish": "kechikish, davomat, kim kech qoldi, kim kelmadi, ishga kelish vaqti",
    "tatil": "ta'til, dam olish, dekret, kasallik varaqasi, otpusk",
    "hujjat": "qoida, nizom, hujjat, tartib, reglament, qonun, buyruq",
    "mijoz": "mijoz, klient, bitim, savdo, shartnoma, CRM",
    "vazifa": "vazifa, topshiriq, task, muddat, bajarilishi",
    "xodim": "xodim, kim ishda, bo'lim, lavozim, telefon, kontakt",
    "hisobot": "hisobot, statistika, yig'ma, jami ko'rsatkichlar",
    "umumiy": "boshqa hamma narsa, yoki ishonchsiz bo'lsang",
}
#: Ohang. "shoshilinch" - buyruq ohangi yoki shoshayotgan odam: gap qisqa va
#: ishchan bo'ladi. Ishonchsiz bo'lsa - "oddiy": shoshilmagan odamga qo'pol
#: gapirish, shoshayotganga xushmuomala gapirishdan YOMONROQ.
OHANGLAR: tuple[str, ...] = ("shoshilinch", "oddiy")

#: (mavzu, ohang, bosqich) -> variantlar.
#:
#: `ilk` - birinchi gap, tasnif kelishi bilan. QISQA bo'lishi kerak: tez
#: javobda (HRM 3-4 s) javob shu gap tugashini kutadi.
#: `davom` - kutish cho'zilganda. Variantlar TARTIB bilan aytiladi, ya'ni bitta
#: kutish ichida gap takrorlanmaydi.
#:
#: Topilmagan kalit `umumiy` ga tushadi (`pick`), ya'ni har mavzu uchun
#: `davom` yozish shart emas - faqat mazmunli farq bo'lgan joyda.
_GAPLAR: dict[tuple[str, str, str], tuple[str, ...]] = {
    # --- ilk, oddiy ----------------------------------------------------------
    ("kechikish", "oddiy", "ilk"): (
        "Kechikishlar bo'yicha ma'lumotlarni tekshirayapman.",
        "Davomat yozuvlarini ko'rib chiqayapman.",
    ),
    ("tatil", "oddiy", "ilk"): (
        "Ta'til ma'lumotlarini tekshirayapman.",
        "Ta'til bo'yicha yozuvlarni ko'rib chiqayapman.",
    ),
    ("hujjat", "oddiy", "ilk"): (
        "Qoidalarni hujjatlardan qidiryapman, biroz vaqt ketadi.",
        "Tegishli hujjatlarni ko'rib chiqayapman.",
    ),
    ("mijoz", "oddiy", "ilk"): (
        "Mijozlar bo'yicha ma'lumotlarni tekshirayapman.",
        "CRM dagi yozuvlarni ko'rib chiqayapman.",
    ),
    ("vazifa", "oddiy", "ilk"): (
        "Vazifalar ro'yxatini tekshirayapman.",
        "Vazifalar bo'yicha ma'lumotlarni ko'rib chiqayapman.",
    ),
    ("xodim", "oddiy", "ilk"): (
        "Xodimlar ma'lumotlarini tekshirayapman.",
        "Xodimlar bo'yicha yozuvlarni ko'rib chiqayapman.",
    ),
    ("hisobot", "oddiy", "ilk"): (
        "Hisobot uchun ma'lumotlarni tekshirayapman.",
        "Ko'rsatkichlarni ko'rib chiqayapman.",
    ),
    ("umumiy", "oddiy", "ilk"): (
        "Bir soniya, tekshirayapman.",
        "Hozir ko'rib chiqayapman.",
    ),
    # --- ilk, shoshilinch: juda qisqa va ishchan ---------------------------
    ("kechikish", "shoshilinch", "ilk"): ("Kechikishlarni tekshirayapman.", "Davomatni ko'rayapman."),
    ("tatil", "shoshilinch", "ilk"): ("Ta'tilni tekshirayapman.", "Hozir ko'raman."),
    ("hujjat", "shoshilinch", "ilk"): ("Hujjatlarni qidiryapman.", "Qoidalarni ko'rayapman."),
    ("mijoz", "shoshilinch", "ilk"): ("Mijozlarni tekshirayapman.", "Hozir ko'raman."),
    ("vazifa", "shoshilinch", "ilk"): ("Vazifalarni tekshirayapman.", "Hozir ko'raman."),
    ("xodim", "shoshilinch", "ilk"): ("Xodimlarni tekshirayapman.", "Hozir ko'raman."),
    ("hisobot", "shoshilinch", "ilk"): ("Ko'rsatkichlarni tekshirayapman.", "Hozir ko'raman."),
    ("umumiy", "shoshilinch", "ilk"): ("Tekshirayapman.", "Hozir ko'raman."),
    # --- davom: kutish cho'zilganda ---------------------------------------
    # Progress haqida VA'DA YO'Q ("deyarli tayyor", "hozir bo'ladi"): 30
    # sekundlik kutishda bu yolg'on chiqadi. Faqat rost gaplar: hali
    # ishlayapman, kuting, kechirasiz cho'zildi.
    ("umumiy", "oddiy", "davom"): (
        "Hali tekshirayapman, ozgina kutib turing.",
        "Ma'lumotlarni ko'rib chiqish davom etmoqda.",
        "Kechirasiz, biroz uzoqroq ketyapti.",
    ),
    ("umumiy", "shoshilinch", "davom"): (
        "Hali tekshirayapman.",
        "Bir oz kutasiz.",
        "Kechirasiz, biroz cho'zildi.",
    ),
    # Hujjat qidiruvi eng sekin yo'l (o'lchangan: `rules` 15.7 s mediana,
    # 38.7 s p90) - ya'ni aynan shu yerda ikkinchi va uchinchi gap eng ko'p
    # eshitiladi. Shuning uchun alohida.
    ("hujjat", "oddiy", "davom"): (
        "Hujjatlarni hali ko'rib chiqayapman, tashlab ketmang.",
        "Qoidalar bo'yicha qidiruv davom etmoqda.",
        "Kechirasiz, hujjat qidiruvi biroz uzoq ketyapti.",
    ),
    ("hujjat", "shoshilinch", "davom"): (
        "Hujjatlarni hali qidiryapman.",
        "Bir oz kutasiz.",
        "Kechirasiz, biroz cho'zildi.",
    ),
}

#: `ilk` variantlari so'rovdan so'rovga ALMASHADI: kun bo'yi bitta gapni
#: eshitish tez zeriktiradi. Tasodif emas, navbat: test takrorlanadigan
#: bo'lsin.
_navbat: dict[tuple[str, str], int] = {}
_navbat_lock = threading.Lock()


def clip_key(mavzu: str, ohang: str, bosqich: str, n: int, matn: str) -> str:
    """Ovoz kaliti. Oxiridagi xesh MATNDAN olinadi, va bu muhim.

    Ovoz brauzerda `immutable` bilan keshlanadi (bir kun). Kalit faqat
    joydan yasalsa, gap matni o'zgartirilganda brauzer ESKI ovozni bir kun
    davomida o'ynatib turardi - va diskdagi kesh ham eskisini berardi. Xesh
    bilan esa matn o'zgarsa kalit ham o'zgaradi: yangi ovoz o'z-o'zidan
    sintez qilinadi, eskisi esa tozalanadi.
    """
    xesh = hashlib.sha1(matn.encode("utf-8")).hexdigest()[:8]
    return f"{mavzu}-{ohang}-{bosqich}-{n}-{xesh}"


def _variantlar(mavzu: str, ohang: str, bosqich: str) -> tuple[str, str, tuple[str, ...]]:
    """(amaldagi mavzu, amaldagi ohang, variantlar) - zahira zanjiri bilan."""
    for kalit in ((mavzu, ohang, bosqich), (mavzu, "oddiy", bosqich),
                  ("umumiy", ohang, bosqich), ("umumiy", "oddiy", bosqich)):
        if kalit in _GAPLAR:
            return kalit[0], kalit[1], _GAPLAR[kalit]
    raise KeyError(bosqich)


def pick(mavzu: str, ohang: str, bosqich: str, orin: int | None = None) -> tuple[str, str]:
    """(matn, ovoz kaliti).

    `orin` - `davom` gaplari uchun kutish ichidagi TARTIB (0, 1, 2...), ya'ni
    bitta kutishda gap takrorlanmaydi. `None` - `ilk` uchun: variant
    so'rovdan so'rovga navbat bilan almashadi.
    """
    m, o, gaplar = _variantlar(mavzu, ohang, bosqich)
    if orin is None:
        with _navbat_lock:
            orin = _navbat.get((m, o), 0)
            _navbat[(m, o)] = orin + 1
    n = orin % len(gaplar)
    matn = gaplar[n]
    return matn, clip_key(m, o, bosqich, n, matn)


def all_clips() -> list[tuple[str, str]]:
    """Barcha (kalit, matn) - oldindan sintez qilish ro'yxati.

    `ilk` birinchi: xizmat qayta ishga tushgandan keyin eng tez kerak
    bo'ladigani shular, `davom` esa kamida 9 sekund keyin kerak bo'ladi.
    """
    out: list[tuple[str, str]] = []
    for bosqich in ("ilk", "davom"):
        for (mavzu, ohang, b), gaplar in _GAPLAR.items():
            if b != bosqich:
                continue
            for n, matn in enumerate(gaplar):
                out.append((clip_key(mavzu, ohang, b, n, matn), matn))
    return out


# --- ZAHIRA tasniflagich: kalit so'zlar --------------------------------------
#
# Model o'chganda, kvota tugaganda yoki 1.2 sekundda ulgurmaganda ishlatiladi.
# O'lchangan: mavzuda yaxshi (8/12), 0.17 ms, bepul. OHANGDA ESA YOMON - va
# xavfli tomonga: "hozir kim ishda yo'q" (hozir = shoshilinch?) va "DVSIB
# bo'yicha qoida" (bosh harflar = qichqiriq?) ikkalasi ham "shoshilinch" deb
# o'qildi. Ya'ni jadval shoshilmagan odamga Venera'ni QO'POL qilib qo'yardi.
# Shuning uchun jadval FAQAT mavzuni aniqlaydi, ohang esa doim "oddiy".
_KALIT_SOZLAR: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("kechikish", re.compile(r"kech(ik|\s*qol)|davomat|kelmadi|kelmagan")),
    ("tatil", re.compile(r"ta'?til|tatil|dam\s*ol|dekret|otpusk|kasallik")),
    ("hujjat", re.compile(r"qoida|hujjat|nizom|tartib|reglament|qonun|buyruq")),
    ("vazifa", re.compile(r"vazifa|topshiriq|task|muddat")),
    ("mijoz", re.compile(r"mijoz|klient|bitim|savdo|shartnoma|crm")),
    ("xodim", re.compile(r"xodim|ishda\s*yo'?q|kim\s*ishda|bo'?lim|lavozim")),
    ("hisobot", re.compile(r"hisobot|statistik|yig'?ma|ko'rsatkich")),
)


def keyword_topic(savol: str) -> str:
    """Kalit so'z bo'yicha mavzu. Topilmasa - `umumiy`."""
    s = (savol or "").lower()
    for mavzu, naqsh in _KALIT_SOZLAR:
        if naqsh.search(s):
            return mavzu
    return "umumiy"


class HoldVoices:
    """Tayyor ovozlar: diskda va xotirada.

    NEGA DISKDA HAM. Sintez bir ovoz uchun ~1 sekund oladi, 44 tasi esa ~50
    sekund. Xizmat har qayta ishga tushganda shuni qaytadan to'lash - bekor
    sarf, ustiga qayta ishga tushgandan keyingi birinchi savollar ovozsiz
    qolardi.

    NEGA FON IPIDA. Sintez so'rov ichida qilinsa javobni to'sib qo'yardi va
    TTS ning ikki slotidan birini olardi.
    """

    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir
        self._lock = threading.Lock()
        self._clips: dict[str, bytes] = {}
        self._warmed = False
        self._pruned = False

    def get(self, key: str) -> bytes | None:
        if not key:
            return None
        with self._lock:
            if key in self._clips:
                return self._clips[key]
        try:
            data = (self.cache_dir / f"{key}.wav").read_bytes()
        except OSError:
            return None
        with self._lock:
            self._clips[key] = data
        return data

    def ready(self, key: str) -> bool:
        return bool(key) and self.get(key) is not None

    def warm(self, clips: list[tuple[str, str]], synth) -> None:
        """Yetishmayotgan ovozlarni sintez qiladi, eskilarini tozalaydi.

        `synth(matn) -> bytes` - TTS chaqiruvi. Xato JIM o'tadi: ovozi yo'q
        gap shunchaki aytilmaydi, javob esa baribir keladi.
        """
        if self._warmed:
            return
        self._warmed = True
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            log.info("Kutish ovozlari: papka yaratilmadi (%s)", exc)
            return
        kerak = {key for key, _ in clips}
        self.prune(kerak)
        yasalgan = 0
        for key, matn in clips:
            if self.ready(key):
                continue
            try:
                data = synth(matn)
            except Exception as exc:                          # noqa: BLE001
                log.info("Kutish ovozi yasalmadi (%s): %s", key, exc)
                continue
            if not data:
                continue
            if not self.put(key, data):
                continue
            yasalgan += 1
        log.info("Kutish ovozlari tayyor: %d ta yangi, jami %d/%d",
                 yasalgan, sum(1 for k in kerak if self.ready(k)), len(kerak))

    def prune(self, kerak: set[str]) -> None:
        """ESKI ovozlarni tozalaydi - har nusxada BIR MARTA.

        Gap matni o'zgarsa kaliti ham o'zgaradi (`clip_key` dagi xesh), ya'ni
        eski fayl endi hech qachon ishlatilmaydi. Papka FAQAT shu kesh uchun -
        boshqa narsa yo'q. Faqat shu papkaning o'zi (`*.wav`, ichki papkalar
        EMAS): boshqa ovozlarning keshi uning ichida turadi (`<papka>/<ovoz>/`)
        va ular o'z nusxasida tozalanadi.
        """
        with self._lock:
            if self._pruned:
                return
            self._pruned = True
        for fayl in self.cache_dir.glob("*.wav"):
            if fayl.stem not in kerak:
                try:
                    fayl.unlink()
                except OSError:
                    pass

    def put(self, key: str, data: bytes) -> bool:
        """Ovozni diskka (atomar) va xotiraga yozadi. `False` - saqlanmadi.

        ATOMAR: avval `.part`, keyin `replace`. To'g'ridan-to'g'ri yozilsa,
        o'sha paytda kelgan so'rov yarim faylni o'qib, uni xotirada
        keshlab qo'yardi - va xizmat qayta ishga tushguncha buzuq ovoz
        berardi. `.part` `*.wav` ga mos kelmaydi, ya'ni tozalash unga
        tegmaydi.

        Disk xatosida xotiraga ham YOZILMAYDI (`warm` dagi avvalgi tartib):
        `ready()` faqat diskda turgan ovoz uchun rost bo'lsin.
        """
        tmp = self.cache_dir / f".{key}.part"
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            tmp.write_bytes(data)
            tmp.replace(self.cache_dir / f"{key}.wav")
        except OSError as exc:
            log.info("Kutish ovozi saqlanmadi (%s): %s", key, exc)
            return False
        with self._lock:
            self._clips[key] = data
        return True

    def snapshot(self, clips: list[tuple[str, str]]) -> dict[str, int]:
        return {"tayyor": sum(1 for key, _ in clips if self.ready(key)), "jami": len(clips)}
