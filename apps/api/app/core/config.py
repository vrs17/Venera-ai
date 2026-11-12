"""Sozlamalar - hammasi muhit o'zgaruvchilaridan.

QOIDA: kodda hech qanday manzil, parol yoki kalit QATTIQ YOZILMAYDI.
Sabab oddiy - dev, test va prod bir xil kod bilan ishlashi kerak, va sir
git'ga tushmasligi kerak.

Qiymatlar tartibi: muhit o'zgaruvchisi -> `.env` fayli -> shu yerdagi default.
Default'lar LOKAL ISHLAB CHIQISH uchun xavfsiz bo'lishi kerak, prod uchun emas.
"""

from __future__ import annotations

import re
import threading

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

#: apps/api/ papkasi - config fayllari shunga nisbatan qidiriladi.
BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Barno API"
    #: Frontend `package.json` versiyasi bilan bog'liq emas - bu API versiyasi.
    version: str = "0.1.0"
    debug: bool = False

    # --- xavfsizlik ---
    #: Token imzolash kaliti. PRODUCTION'DA ALBATTA O'ZGARTIRILADI.
    #: Bu default qiymat ataylab "xavfsiz emas" deb ko'rinadi - unutib
    #: qo'yilsa `/health` uni ogohlantirish sifatida ko'rsatadi.
    secret_key: str = "dev-only-insecure-change-me"
    #: HRM ulanishi 10 soat yashaydi va yangilanmaydi (`hrm_token_margin`
    #: izohi). Sessiya undan UZUN bo'lsa "+" menyusida HRM qatori sessiya
    #: tugamasdan "muddati tugagan" bo'lib qoladi - `.env` da 10 tavsiya.
    token_ttl_hours: int = 12
    #: Parol bilan kirish (`POST /auth/login`, `config/users.yaml`) - ZAHIRA:
    #: administrator Keycloak'siz ham kira olsin (Keycloak yiqilganda,
    #: birinchi sozlashda). Asosiy kirish SSO (pastda). Prod'da o'chirish
    #: mumkin - shunda endpoint 403 qaytaradi va kirish sahifasida faqat
    #: SSO tugmasi qoladi.
    local_login_enabled: bool = True
    # --- SSO: Keycloak, brauzer orqali (OpenID Connect, `services/oidc.py`) ---
    #: Realm manzili, masalan `https://myid.brb-tech.uz/auth/realms/brb-realm`
    #: (staging'da `https://test-keycloak.../auth/realms/<realm>`). Tokendagi
    #: `iss` aynan shu bo'lishi kerak. BO'SH bo'lsa SSO o'chiq.
    sso_issuer: str = ""
    #: Keycloak'dagi BIZNING client (Clients -> barno-ai). Rollar ham shu
    #: client'niki: `admin` -> ADMIN, `employee` -> EMPLOYEE, `executive` ->
    #: EXECUTIVE (`services/oidc.ROLE_MAP`). Realm rollari o'qilmaydi.
    sso_client_id: str = "barno-ai"
    #: Client siri (Credentials tab) - FAQAT `.env` da. Bo'sh bo'lsa SSO o'chiq.
    sso_client_secret: str = ""
    #: Ilovaning tashqi manzili, masalan `https://llm.brb-tech.uz`. Undan
    #: Keycloak'ga beriladigan qaytish manzili yasaladi:
    #: `<sso_app_url>/api/v1/auth/sso/callback` - u Keycloak'dagi "Valid
    #: redirect URIs" ro'yxatida AYNAN shunday turishi shart. BO'SH bo'lsa
    #: so'rovning o'zidan (`X-Forwarded-Proto`, `Host`) olinadi - dev'da
    #: (vite proxy, http://10.10.50.4:5174) shu yetadi; prod'da nginx
    #: konteyneri TLS ni ko'rmaydi (`http` deb yuboradi), shuning uchun
    #: prod'da ANIQ yoziladi.
    sso_app_url: str = ""
    #: Mobil ilova uchun ruxsat etilgan qaytish manzili (masalan
    #: `barnoai://sso`). Bo'sh - mobil SSO o'chiq. Boshqa har qanday tashqi
    #: manzil rad etiladi (ochiq yo'naltirish bo'lardi).
    sso_mobile_redirect: str = ""
    sso_timeout: float = 10.0
    #: CRM ulanishini SSO sessiyasidan ochish (2026-11-12, ega so'rovi;
    #: `services/integrations/crm_sso.py`). Yoqilgan bo'lsa: (1) kirishda
    #: `offline_access` ham so'raladi - Keycloak'da client'ning "Optional
    #: client scopes" ro'yxatida `offline_access` bo'lishi kerak (yangi
    #: client'da odatda bor); (2) kirgan odamning sessiyasi CRM da
    #: tekshiriladi (`GET /api/auth/me`) va qabul qilinsa uning CRM ulanishi
    #: bo'ladi - "+" menyusiga kirish shart emas. CRM rad etsa ulanish
    #: ochilmaydi, kirish esa ishlayveradi. `false` - kirish faqat shaxsni
    #: beradi, CRM "+" menyusida qo'lda ulanadi. `CRM_BASE_URL` bo'sh bo'lsa
    #: bu sozlamaning ta'siri yo'q (scope'dan tashqari).
    sso_crm_connect: bool = True
    #: SSO bilan kirganlar: Keycloak `sub` -> `actor_id`
    #: (`services/identities.py`). Sir yo'q, lekin `data/` da, 600.
    identities_file: Path = BASE_DIR / "data" / "identities.json"

    #: Demo foydalanuvchilar fayli. Keyinchalik bu joyni DB egallaydi -
    #: `services/users.py` interfeysi o'zgarmaydi.
    users_file: Path = BASE_DIR / "config" / "users.yaml"

    # --- STT (ovozni matnga o'girish) ---
    #: STT Router manzili. Ichki tarmoqda, VPN ortida.
    stt_base_url: str = "http://10.10.50.4:8006"
    #: BIR urinish uchun timeout. Byudjet zanjiri: brauzer nginx orqali 120 s
    #: kutadi (API_READ_TIMEOUT). Undan uzoq kutish ma'nosiz - javob endi hech
    #: kimga yetib bormaydi, lekin slot va Router ishchisi band turadi.
    stt_timeout: float = 35.0
    #: 503 (navbat to'la) uchun urinishlar. 502/504 QAYTA URINILMAYDI.
    stt_attempts: int = 3
    #: Butun `transcribe()` uchun devor-soat chegarasi - nginx 120 s dan KAM.
    stt_deadline: float = 100.0
    #: BUTUN park uchun Router chegarasi ~10 parallel (o'lchangan: 25 da 503 lar
    #: boshlanadi). Web ilova shuning bir qismini oladi - desktop park va boshqa
    #: klientlarga joy qolsin. Oshsa - kutmasdan 503 "band" qaytaramiz.
    stt_max_concurrent: int = 4
    #: Yuklash chegarasi. Router o'zi ham 25 MB da to'xtatadi, lekin biz
    #: undan OLDIN to'xtatamiz: aks holda katta fayl butun tarmoqni bosib
    #: o'tib, faqat oxirida rad etilardi.
    stt_max_upload_mb: float = 10.0

    # --- STT VARIANTI: qaysi xizmat ishlatiladi ---
    #: `router` - 1-variant, ichki STT Router (yuqorida). `gapi` -
    #: 2-variant, `console.gapi.uz`.
    #:
    #: IKKALASI HAM QOLADI. Qaytarish uchun kod o'zgartirilmaydi: `.env`
    #: dagi `STT_PROVIDER` qatorini o'chirib, xizmatni qayta ishga
    #: tushirish yetadi. Shu sababli KODDAGI default `router` - isbotlangan
    #: yo'l, va sinov `.env` orqali yoqiladi.
    #:
    #: GAPI faqat O'ZBEK tilini biladi va matnni faqat LOTIN yozuvida
    #: qaytaradi. `ru`/`en` uchun unda model yo'q, shuning uchun tanlovchi
    #: (`api/v1/stt.py`) bu tillarni baribir Router'ga yuboradi - ya'ni
    #: GAPI ga o'tish rus yoki ingliz interfeysini buzmaydi.
    stt_provider: str = "router"
    #: UYG'OTISH SO'ZI uchun ALOHIDA tanlov, va default ATAYLAB `router`.
    #:
    #: Sababi o'lchangan. Tinglagich `COOLDOWN_MS = 2500` bilan ishlaydi,
    #: ya'ni tinglab turgan har bir varaq daqiqasiga 24 TAGACHA so'rov
    #: yuborishi mumkin (jim xonada - nol, chunki sukunat brauzerdan
    #: chiqmaydi). GAPI da esa yuklash chegarasi daqiqasiga 60 ta va har
    #: bo'lak PULLIK - holbuki bu bo'laklarning deyarli hammasi "bu
    #: uyg'otish so'zi emas" degan javob beradi. Ichki Router shu ishni
    #: 0.1 sekundda va bepul qiladi.
    #:
    #: Ya'ni bu "tejamkorlik" emas, vazifaning boshqaligi: uyg'otish so'zi
    #: - kalit so'z qidirish, transkripsiya emas.
    stt_wake_provider: str = "router"

    # --- GAPI STT (2-variant) ---
    gapi_base_url: str = "https://console.gapi.uz/v1"
    #: Loyihaga bog'langan token. Bo'sh bo'lsa 2-variant O'CHIQ.
    gapi_api_key: str = ""
    #: IKKINCHI GAPI hisobining tokeni (o'zining kunlik 480 g balansi bilan). Birinchi
    #: kalitning balansi tugasa (`429 insufficient_balance`, yig'ilishda esa yetmasa) shu
    #: kalit ishlatiladi; yarim kechada (Toshkent) to'lgach yana birinchisi. Bo'sh - bitta kalit.
    gapi_api_key2: str = ""
    #: O'lchangan tezlik: mediana 1.2 s, yuklama ostida 3.6 s; 35 s yozuv
    #: 1-3 sekundda.
    #:
    #: 60 EMAS, 20 - va sababi zahira. GAPI yiqilganda so'rov Router'ga
    #: tushadi, ya'ni BITTA so'rov ikki klientning vaqtini ketma-ket yeydi.
    #: 60 s bo'lganda jami 121 s ga chiqardi, nginx esa 120 s da ulanishni
    #: uzadi - Router'ning javobi o'lgan socketga yozilardi. 20 s esa
    #: o'lchangan eng yomon holatdan (3.6 s) besh barobar katta, ya'ni
    #: sog'lom GAPI bunga bemalol sig'adi; sig'masa - Router tezroq
    #: javob beradi.
    gapi_timeout: float = 20.0
    #: Yuklash chegarasi daqiqasiga 60 ta (token uchun) - bu bizning ulush.
    gapi_max_concurrent: int = 2

    # --- UYG'OTISH SO'ZI uchun GAPI byudjeti ---
    #
    # NEGA BU KERAK. Uyg'otish so'zi tinglagichi FONDA ishlaydi va har bir
    # chat varag'ida default YOQIQ. Brauzerdagi `COOLDOWN_MS = 2500` esa
    # bizning YAGONA chegaramiz edi - ya'ni pullik xizmatning tormozi
    # MIJOZDA turgan. O'zgartirilgan sahifa, ochiq qolgan eski varaq yoki
    # bir odamning uchta varag'i hisobni yeb qo'yishi mumkin edi.
    #
    # O'LCHANGAN SONLAR (jonli GAPI, shu loyiha tokeni):
    #   * bitta parcha = 0.03 g, ya'ni 1 g = 1 audio-daqiqa, kunlik 480 g;
    #   * bitta varaq daqiqasiga 24 tagacha parcha yuboradi (2.5 s oraliq);
    #   * tokenning yuklash chegarasi 60/daqiqa - va o'sha tokendan
    #     foydalanuvchining SAVOLI ham o'tadi, ya'ni uch varaq 72 ta qilib
    #     chegaradan oshadi va 429 aynan SAVOLGA tegadi;
    #   * jonli uyg'otish jurnalida parchalarning ~71 foizi uyg'otish
    #     so'zi EMAS - ya'ni pulning katta qismi "bu u emas" javobiga
    #     ketadi.
    #
    # Chegaradan oshganda so'rov RAD ETILMAYDI - 1-variantga (bepul, ichki
    # Router) tushadi. Uyg'otish - kalit so'z qidirish, Router buni
    # baribir 0.1 sekundda bajaradi. Ya'ni bu chegara xizmatni emas,
    # HISOBNI cheklaydi.
    #: Bitta foydalanuvchi uchun daqiqada nechta parcha GAPI ga ketadi.
    #: 30 - bitta halol varaq (24/daqiqa) erkin o'tadi, ikkinchi varaqdan
    #: boshlab esa ortiqchasi Router'ga tushadi.
    wake_gapi_per_actor_min: int = 30
    #: HAMMA foydalanuvchilar uchun jami. 45 - tokenning 60/daqiqa
    #: chegarasidan past, ya'ni foydalanuvchining SAVOLI uchun joy qoladi.
    wake_gapi_total_min: int = 45

    # --- USHLAB TURISH (kutish ovozi) ---
    #
    # MUAMMO. Ovozli suhbatda HRM/CRM javobi darhol kelmaydi: o'lchangan
    # `hrm` 3-4 s, `rules` 15.7 s mediana va 38.7 s p90 (eng yomoni 72.6 s).
    # Shu paytda Venera JIM turadi - odam esa "eshitdimi?" deb o'ylab
    # savolni qaytaradi yoki panelni tashlab ketadi.
    #
    # TARTIB:
    #   t=0    STT matni -> HRM/CRM ga (javob) + PARALLEL -> gemma (tasnif)
    #   t~0.8  gemma: mavzu|ohang -> mos TAYYOR ovoz darhol o'ynaladi
    #   har `hold_repeat_ms` da - javob hali yo'q bo'lsa, keyingi ovoz
    #   javob  joriy ovoz OXIRIGACHA eshittiriladi, keyin javob TTS orqali
    #
    # Model gapni YOZMAYDI, faqat TANLAYDI (`services/hold.py` sababini
    # o'lchovlar bilan yozadi): tayyor ovozda TTS kutilmaydi, va model javobni
    # to'qib qo'ya olmaydi.
    hold_enabled: bool = True
    #: Tasnifni shuncha kutamiz, keyin birinchi ovoz ZAHIRA (kalit so'z)
    #: bilan tanlanadi. O'lchangan tasnif mediana 0.77 s, eng sekini 1.48 s.
    #: Kutish ovozining butun ma'nosi TEZ tan olishda - ya'ni model kechiksa,
    #: undan ko'ra jadval yaxshiroq. Kech kelgan model yorlig'i keyingi
    #: ovozlar uchun baribir ishlatiladi.
    hold_first_ms: int = 1200
    #: Javob hali kelmagan bo'lsa, har shuncha vaqtda keyingi ovoz. Ovozlar
    #: 1.5-3.5 s, ya'ni orada 6 sekunddan ko'p sukunat qoladi: tinimsiz
    #: gapirish ham, uzoq jimlik ham yomon.
    hold_repeat_ms: int = 9000
    #: Bitta savol uchun eng ko'pi. 4 ta: ~27 sekundgacha qoplaydi, ya'ni
    #: `rules` yo'lining ko'p qismini (p90 38.7 s). Undan keyin ham gapirish
    #: suhbat emas, shovqin bo'ladi.
    hold_max: int = 4
    #: Tayyor ovozlar shu papkada. Diskda saqlanadi, chunki 44 ta ovozni
    #: sintez qilish ~50 sekund oladi va har qayta ishga tushganda qaytadan
    #: to'lash bekor.
    hold_voice_dir: Path = BASE_DIR / "data" / "hold"
    #: Ishga tushganda yetishmayotgan ovozlarni sintez qilish. Testlarda
    #: O'CHIRILADI (`conftest.py`): aks holda har test yurishi jonli TTS
    #: serveriga chiqib ketardi.
    hold_warm: bool = True

    # --- Ollama (savolni tasniflaydigan model) ---
    #: Ollama Cloud. Lokal server ISHLATILMAYDI: bu hostda 3.9 GB RAM va GPU
    #: yo'q, ustiga jonli Venera servislari turadi.
    ollama_base_url: str = "https://ollama.com"
    #: Kalit. `.env` da tarixiy sabab bilan `VENERA_API_URL` deb yozilgan
    #: (nomi noto'g'ri - u URL emas, token), shuning uchun IKKI nom ham
    #: o'qiladi: avval `OLLAMA_API_KEY`, keyin `VENERA_API_URL`.
    ollama_api_key: str = ""
    venera_api_url: str = ""
    ollama_model: str = "gemma4:31b"
    #: Tasnif so'rovining o'z chegarasi. Birinchi ovoz uni kutmaydi
    #: (`hold_first_ms`), lekin kechroq kelgan yorliq keyingi ovozlar uchun
    #: ishlatiladi - shuning uchun bu 1.2 sekunddan uzunroq.
    ollama_timeout: float = 2.5
    #: Bir vaqtda nechta tasnif. Har ovozli savolga bittadan, navbatsiz:
    #: to'lgan bo'lsa zahira darhol ishlaydi.
    ollama_max_concurrent: int = 4

    # --- TTS (matnni ovozga o'girish) ---
    #: TTS serveri. Ichki tarmoqda, VPN ortida - STT bilan bir xil hostda,
    #: boshqa portda.
    tts_base_url: str = "http://10.10.50.4:8200"
    #: Klient sirlari TTS serverining `AUTH_CLIENTS` ro'yxatidan keladi.
    #: `tts_client_secret` BO'SH bo'lsa ovoz sintezi o'chiq: endpoint 503
    #: qaytaradi, qolgan hamma narsa ishlaydi. Sir FAQAT `.env` da.
    tts_client_id: str = "frontend"
    tts_client_secret: str = ""
    #: BO'LAKLAR ORASIDAGI kutish - oqim uzunligi EMAS. Bo'laklar odatda
    #: 1-2 s oralab keladi, ya'ni bu chegara faqat server butunlay jim
    #: qolganda ishlaydi. Sintez GPU navbatida turishi mumkin, shuning
    #: uchun birinchi bo'lak uchun ham shu qiymat.
    tts_timeout: float = 60.0
    #: Server 429 qaytarmaydi - navbat cheksiz o'sadi. Chegarani o'zimiz
    #: qo'yamiz: oshsa darhol 503 "band".
    tts_max_concurrent: int = 2
    #: Ovoz profili: `uz_female_calm` (ayol) yoki `uz_male_news` (erkak).
    tts_voice: str = "uz_female_calm"
    #: `null` -> server 0.95 ni oladi. Rasmiy matn uchun 0.90, yangiliklar 1.0.
    tts_speed: float | None = None
    #: Bo'lakning maqsadli davomiyligi (soniya). Hujjat jonli qo'ng'iroq
    #: uchun 1.0-2.0 ni tavsiya qiladi: 3.0 da birinchi bo'lak butun
    #: jumlani qamrab, TTFB ~5x sekinlashadi; 10.0 da streaming umuman
    #: yo'qoladi. Server 0.5-10 dan tashqarisiga 422 beradi.
    tts_chunk_sec: float = 1.5
    #: Talaffuz lug'ati: `{"DVSIB": "Data va sun'iy intellekt bo'limi"}` - CRM
    #: loyiha kodi ovozda NOM bo'lib aytiladi (ekrandagi matn o'zgarmaydi). Fayl
    #: git'da; yo'q bo'lsa lug'at bo'sh; o'zgarsa keyingi sintezda qayta
    #: o'qiladi (`speech_text.SpokenNames`).
    tts_spoken_names_path: Path = BASE_DIR / "config" / "tts_names.json"
    #: Matn chegarasi - ZAXIRA to'siq. Asosiy qisqartirish frontendda, GAP
    #: chegarasida bo'ladi (`VoicePanel.vue`, `SPEAK_LIMIT`); bu yerda esa
    #: so'z chegarasida kesiladi va xato qaytarilmaydi.
    #:
    #: 600 EDI va bu O'QILADIGAN JAVOBNI YARMIDA KESARDI: o'sha qiymat matn
    #: foydalanuvchining bitta AYTGAN GAPI bo'lgan davrdan qolgan edi, javob
    #: esa tabiatan uzunroq (jonli misol: mehnat ta'tili bo'yicha 6 bandli
    #: javob 1016 belgi).
    #:
    #: 3000 jonli o'lchovga asoslangan: server 5000 belgini ham qabul qiladi,
    #: va birinchi bayt UZUNLIKDAN QAT'I NAZAR ~1.37 s da keladi, ya'ni uzun
    #: matn kechikish qo'shmaydi. Narxi boshqa joyda: 3000 belgi ~198 s ovoz
    #: bo'lib, oqim ~41 s davom etadi va shu vaqt ichida `tts_max_concurrent`
    #: slotlaridan bittasini ushlab turadi.
    tts_max_chars: int = 3000

    # --- Uyg'otish so'zi jurnali ---
    #: "Salom Venera" urinishlari yozib boriladi: audio + transkript + qaror.
    #: Muammoni TAXMIN bilan emas, dalil bilan tuzatish uchun - qaysi
    #: aytilish qanday transkribe qilingani ko'rinmasa, moslashtirgichni
    #: sozlash ko'r-ko'rona bo'ladi.
    #:
    #: OVOZ YOZUVLARI SHAXSIY MA'LUMOT. Papka `.gitignore` da. Kerak
    #: bo'lmaganda `WAKE_LOG_ENABLED=false` bilan butunlay o'chiriladi.
    wake_log_enabled: bool = True
    wake_log_dir: Path = BASE_DIR / "data" / "wake"
    #: Shuncha audiodan ortig'i o'chiriladi (eng eskisidan). JSONL qatorlari
    #: qoladi - ular kichkina va statistika uchun kerak.
    wake_log_max_files: int = 500

    # --- HR Assistant (savolga javob beradigan yuqori xizmat) ---
    #: BRB-TECH HR Assistant API: hujjatlar bo'yicha RAG + HRM connector,
    #: bitta `/api/chat/stream` endpointi ortida. Venera uchun BU YAGONA
    #: kirish nuqtasi - HRM ga to'g'ridan-to'g'ri borilmaydi.
    hrm_assistant_base_url: str = "http://10.10.50.4:8080"
    #: ILOVANING kredensiallari (`X-Client-Id` / `X-Client-Secret`). Usiz
    #: xizmat 401 qaytaradi, shuning uchun savol umuman yuborilmaydi -
    #: `/api/health` esa buni ogohlantirish sifatida ko'rsatadi.
    #:
    #: SIR BRAUZERGA HECH QACHON BERILMAYDI: frontend faqat Venera'ning
    #: o'z `/api/v1/chat/stream` yo'liga boradi.
    hrm_assistant_client_id: str = ""
    hrm_assistant_client_secret: str = ""
    #: Kadrlar ORASIDAGI eng uzun tanaffus, butun javob vaqti emas: LLM
    #: javobi bir daqiqadan oshishi normal, bir daqiqa JIMLIK - nosozlik.
    hrm_assistant_timeout: int = 120
    #: Yuqorida bitta LLM turadi. Bu bizning ulushimiz - oshsa xizmatga
    #: bormasdan 503 qaytariladi.
    hrm_assistant_max_concurrent: int = 4
    #: Undan uzun savol yuborilmaydi. Chegara xizmatda ham bor, lekin
    #: 100 KB matnni tarmoqqa chiqarib, keyin rad javobini olish ma'nosiz.
    hrm_assistant_max_question_chars: int = 2000
    #: BITTA javobning eng uzun umri (soniya), kadrlar orasidagi tanaffus
    #: emas. Xat bo'yicha v2 javobi 3-12 s, tashqi modelga borgan "Pro" 10-25 s
    #: - 10 daqiqa katta zahira. Undan oshgan oqim uziladi (504), va shu
    #: chegara navbatning O'ZINI DAVOLASHIGA asos: shundan (+ `timeout`)
    #: eskiroq band joy aniq "oqib ketgan" - tirik oqim bunchalik yashamaydi
    #: (`assistant._SlotPool`).
    hrm_assistant_max_stream_seconds: int = 600
    #: Xotira va platforma kalitlari (`/api/v1/assistant/...`) uchun bitta
    #: o'qish chegarasi (soniya). Bu sozlamalar ekrani - LLM ishlamaydi, javob
    #: millisekundlarda keladi; oqimning 120 s i bu yerda odamni behuda
    #: kuttirardi. Oshsa 504.
    hrm_assistant_settings_timeout: float = 15.0
    #: Yordamchi DVIGATELI (`core/engines.py`): `v1` (barqaror), `v2` (yangi:
    #: LEX.UZ havolalari, "Pro") yoki bo'sh - versiyasiz `/api/chat/stream`
    #: (xizmat default'i, bugun = v1; prod hozir shu yo'lda). Bu shox YANGI
    #: ko'rinish, shuning uchun default `v2`. "Pro" faqat `v2` da ishlaydi.
    #: BOSHLANG'ICH qiymat: admin panel siyosati (`engine_policy`) va odamga
    #: berilgan versiya (`engine_access`) undan ustun -
    #: `services/engine_control.py`.
    hrm_assistant_engine: str = "v2"
    #: Kanal bo'yicha istisno: `miniapp=v1,bot=v1` - ko'rsatilgan kanallar
    #: shu dvigatelda, qolgani `hrm_assistant_engine` da. Kanal nomlari:
    #: web | miniapp | bot | desktop | api. Bo'sh - hamma kanal umumiyda.
    hrm_assistant_engine_by_channel: str = ""

    #: HRM sessiya token'i (JWT) - JONLI HRM ma'lumoti uchun.
    #:
    #: VAQTINCHALIK YECHIM VA BITTA MUHIM OQIBATI BOR. Xizmat bu token'ni
    #: "so'rayotgan odamning O'Z sessiyasi" deb qabul qiladi va hujjatda
    #: aytilganidek, token bilan "men / I" degani TOKEN EGASI hisoblanadi.
    #: Ya'ni bu yerda bitta umumiy token turgan paytda Venera'ning HAR
    #: QANDAY foydalanuvchisi "men bugun kechikdimmi?" deb so'rasa, javob
    #: token EGASI haqida bo'ladi. Shuning uchun `/api/health` bu token
    #: qo'yilganini ogohlantirish sifatida ko'rsatadi.
    #:
    #: Bo'sh bo'lsa jonli HRM savollari `auth_missing` bilan qaytadi, va bu
    #: TO'G'RI xatti-harakat: boshqa odamning huquqi bilan javob berishdan
    #: ko'ra javob bermaslik yaxshi. Hujjatlar bo'yicha savollar ishlaydi.
    #:
    #: Muddati tugagach xizmat yana `auth_missing` qaytaradi - token'ni
    #: `.env` da yangilash kerak. Doimiy yechim: foydalanuvchi o'z HRM
    #: hisobi bilan kirsin va token sessiyadan olinsin.
    #:
    #: BU QIYMAT ISHGA TUSHGANDAGISI. Kod uni TO'G'RIDAN-TO'G'RI
    #: ISHLATMAYDI - `hrm_token_now()` ga qara: token bir necha daqiqada
    #: muddati tugaydi, ya'ni har almashtirishda xizmatni qayta ishga
    #: tushirish ayni vaqtdagi javob oqimlarini kesib yuborardi.
    hrm_token: str = ""
    #: CRM sessiya token'i - HRM tokeni bilan AYNI MANTIQDA.
    #:
    #: Yuqoridagi yordamchi 2026-09-14 dan boshlab CRM ni ham biladi va
    #: `tokens` xaritasida qaysi platforma kerak bo'lsa o'shanisini
    #: ishlatadi. Ikkisi MUSTAQIL: CRM tokenisiz CRM savollari
    #: `auth_missing` qaytaradi ("CRM tizimiga kiring"), HRM savollari
    #: esa ishlab turadi - va teskarisi.
    crm_token: str = ""

    # --- CRM sessiyasi (avtomatik) ---
    #: CRM ning asosiy manzili. BO'SH bo'lsa avtomatik sessiya O'CHIQ va
    #: yuqoridagi qo'lda yozilgan `crm_token` ishlatiladi.
    crm_base_url: str = ""
    #: AGENTNING O'Z CRM hisobi - odamning hisobi EMAS.
    #:
    #: Hujjat talabi, va sababi ikkita: hisobning roli agent nimani
    #: o'qib-o'zgartira olishini belgilaydi (ya'ni zarar doirasi kichik
    #: qoladi), va audit jurnali halol bo'ladi - aks holda agentning har
    #: bir harakati kimning parolini olgan bo'lsa o'sha odamga yozilardi.
    crm_username: str = ""
    #: Parol FAQAT birinchi login uchun. Undan keyin `refresh_token`
    #: ishlatiladi va parolga qaytilmaydi.
    crm_password: str = ""
    crm_timeout: float = 10.0
    #: `refresh_token` shu faylda turadi. `data/` gitignore'da, fayl 600
    #: huquq bilan atomik yoziladi.
    #:
    #: BU DOIMIY KREDENSIAL: `exp` i yo'q, 30 kun ishlatilmasa bekor
    #: bo'ladi. Uni qo'lga kiritgan odam cheksiz muddat agent nomidan
    #: token yasay oladi - paroldan farqi yo'q.
    crm_refresh_file: Path = BASE_DIR / "data" / "crm" / "refresh_token"

    # --- Ulanishlar: foydalanuvchining O'Z HRM / CRM hisobi ---
    #: Yuqoridagi agent sessiyasidan FARQI: u yerda bitta umumiy hisob, bu
    #: yerda har bir odam "+" menyusidan o'z logini va paroli bilan kiradi
    #: va chatga uning O'Z tokeni beriladi. Mantiq:
    #: `services/integrations/connectors.py`.
    #:
    #: HRM API manzili (`POST /api/authenticate`). BO'SH bo'lsa HRM ulanishi
    #: o'chiq - menyuda "serverda sozlanmagan" ko'rinadi.
    hrm_base_url: str = ""
    hrm_timeout: float = 10.0
    #: HRM tokeni 10 SOAT yashaydi va refresh'i YO'Q.
    #:
    #: O'LCHANGAN (2026-09-29, jonli HRM, odamning o'z hisobi bilan):
    #: login so'roviga "meni eslab qol" maydoni uchala yozilishida ham
    #: (`rememberMe`, `remember-me`, `remember_me`) qo'shib ko'rildi -
    #: HRM ularni QABUL QILDI (login ishladi) va tokenni baribir 10.0
    #: soatlik qilib berdi. Ya'ni uzoqroq token so'rashning YO'LI YO'Q:
    #: uni faqat HRM tomonida uzaytirish yoki refresh qo'shish mumkin.
    #: Qayta sinab ko'rishning hojati yo'q.
    #:
    #: Muddati shundan KAM
    #: qolganda u yuqoridagi xizmatga BERILMAYDI va odam qayta kiradi:
    #: savol-javob bir necha daqiqa cho'zilishi mumkin, token esa javob
    #: OXIRIGACHA yaroqli turishi kerak.
    hrm_token_margin: float = 300.0
    #: CRM uchun Keycloak token manzili - parol bilan kirish shu yerda
    #: (`grant_type=password`, `offline_access`). BO'SH bo'lsa CRM
    #: ulanishi o'chiq. `crm_base_url` (yuqorida) esa yangilash uchun
    #: kerak: `POST /api/auth/refresh` CRM ning o'zida.
    crm_idp_token_url: str = ""
    crm_client_id: str = "crm-client"
    #: Ilova siri - FAQAT `.env` da, brauzerga hech qachon bermaydi.
    crm_client_secret: str = ""
    #: CRM `access_token` 300 SEKUND yashaydi. Muddati shundan kam qolgan
    #: bo'lsa savol oldidan `refresh_token` bilan yangilanadi - ya'ni token
    #: olinganidan keyin ko'pi bilan 120 s qayta ishlatiladi, undan keyin
    #: har savolga yangisi. Savol-javob 2-3 daqiqa cho'zilishi mumkin,
    #: shuning uchun 90 s emas (agent sessiyasidagi kabi) - 180 s.
    crm_token_margin: float = 180.0
    #: Foydalanuvchilar tokenlari (HRM token, CRM refresh_token) shu faylda.
    #: `data/` gitignore'da, fayl 600 huquq bilan atomik yoziladi. PAROL BU
    #: YERDA YO'Q - u faqat login so'roviga ketadi.
    connectors_file: Path = BASE_DIR / "data" / "connectors" / "tokens.json"

    # --- Telegram bot: savol-javob Telegram chatining O'ZIDA ---
    #: Mini app'dan FARQI: u yerda sahifa ochiladi, bu yerda odam botga oddiy
    #: xabar yoki ovozli xabar yozadi. Mantiq: `app/bot/`.
    #:
    #: Bot tokeni (@BotFather). BO'SH bo'lsa bot O'CHIQ - mini app va veb
    #: ilova bunga bog'liq emas. SIR: faqat `.env` da, jurnal va xato
    #: matnlariga tushmaydi (`services/integrations/telegram.py`).
    #:
    #: Token mini app `initData` imzosini tekshirish uchun ham kerak: hisobni
    #: ulash aynan shu imzoga tayanadi (`api/v1/telegram.py`).
    telegram_bot_token: str = ""
    #: Tokenni o'chirmasdan botni to'xtatish uchun. Testlarda O'CHIQ
    #: (`conftest.py`): aks holda har test yurishi jonli botga ulanib,
    #: odamlarning xabarlarini "yutib" yuborardi.
    telegram_bot_enabled: bool = True
    #: Xabarlarni olish usuli: `webhook` - Telegram o'zi yuboradi; `polling` -
    #: bot o'zi so'raydi (`getUpdates`).
    #:
    #: JONLI TIZIMDA `polling`, va sababi o'lchangan (2026-09-24). Webhook
    #: sinaldi: Telegram'ning serverimizga (`195.158.16.251`) ulanishi ko'pincha
    #: birinchi urinishda "Connection timed out" bo'lib, xabarlar 20 s - 2
    #: daqiqa kechikdi. Polling'da ulanishni BIZ ochamiz (chiquvchi) - u tez.
    #:
    #: Bitta tokenni boshqa nusxa ham o'qisa (o'sha kuni dev serverda shunday
    #: bo'ldi - xabarlar bo'linib, dev nusxa odamdan qayta kirishni so'radi),
    #: polling ulanishni darhol qaytarib oladi (`runner.poll_error`). To'liq
    #: yechim - @BotFather'da tokenni yangilash va faqat jonli `.env` ga
    #: qo'yish.
    #:
    #: Webhook'ni faqat jonli `.env` da yoqish mumkin (`TELEGRAM_MODE=webhook`):
    #: kod nusxalangan muhit default bilan webhook'ga tegmaydi.
    telegram_mode: str = "polling"
    #: Webhook manzili - ommaviy HTTPS; nginx `/api/` ni API'ga o'tkazadi.
    telegram_webhook_url: str = "https://llm.brb-tech.uz/api/v1/telegram/webhook"
    #: Mini app manzili - "Venera'ni ochish" tugmasi shu yerga.
    telegram_webapp_url: str = "https://llm.brb-tech.uz/tg/"
    #: YANGI mini app - BETA (`/tg-beta/`). Hamma uchun almashtirilguncha
    #: eski ilova `/tg/` da qoladi, sinovchilar esa yangisini botdagi `/beta`
    #: buyrug'i bilan ochadi (`app/bot/runner.py`). Bo'sh - `/beta` yopiq.
    telegram_webapp_beta_url: str = "https://llm.brb-tech.uz/tg-beta/"
    #: `/beta` kimga ochiq: ADMIN rolidagilar VA shu ro'yxat - vergul (yoki
    #: bo'shliq) bilan loginlar, harf registriga qaramaydi. `admin_logins`
    #: dagi qoida: SSO hisobi FAQAT LOGINI bilan (emailni odam Keycloak'da
    #: o'zi o'zgartira oladi), `users.yaml` dagi hisob - emaili bilan. Bu
    #: huquq emas, faqat beta manzili ko'rsatiladi: yangi ilova ham o'sha
    #: Venera kirishini talab qiladi.
    miniapp_beta_logins: str = ""
    #: Telegram hisobi -> Venera hisobi. `data/` gitignore'da, 600, atomik.
    telegram_links_file: Path = BASE_DIR / "data" / "telegram" / "links.json"
    #: Ulanish OXIRGI FAOLLIKDAN shuncha kun yashaydi: mini app ochilishi ham,
    #: botdagi savol ham uni yangilaydi. Odam bir marta kiradi va botdan
    #: foydalanib tursa qayta so'ralmaydi; faqat shuncha kun umuman
    #: ishlatilmagan ulanish tugaydi.
    telegram_link_days: int = 30
    #: Mini app `initData` si shundan eski bo'lsa ulash rad etiladi. Ilova
    #: ochilgan zahoti ulanadi, ya'ni bir kun ochiq turgan varaqqa ham yetadi.
    telegram_init_max_age: int = 86400
    #: Ovozli xabar chegarasi (soniya). STT Router o'zbek tili uchun 300 s
    #: dan keyingisini baribir KESADI.
    telegram_voice_max_sec: int = 300
    #: Shuncha soat jimlikdan keyin keyingi savol YANGI suhbat boshlaydi -
    #: veb ilova tarixida alohida suhbat bo'lib ko'rinadi.
    telegram_chat_idle_hours: float = 6.0
    #: Bir vaqtda nechta xabar ishlanadi. Bitta odamning xabarlari esa
    #: KETMA-KET, navbat bilan.
    telegram_workers: int = 4
    #: "📲 Ilovani yuklab olish" tugmasi (`app/bot/mobile_app.py`): 10.10.50.4 dagi ichki "Barno AI
    #: APK" API - `/latest` (oxirgi versiya) va `/download` (fayl). Unga faqat shu server kira oladi,
    #: telefonlar emas - faylni bot o'zi yuboradi. Bo'sh - tugma "hozir o'chiq" deydi.
    mobile_apk_api: str = "http://10.10.50.4:8097"
    #: Venera ISHLAYDIGAN guruhlar - Telegram chat id lar, vergul yoki
    #: bo'shliq bilan (`-1001234567890`). Bo'sh - hamma guruhda eski xulq:
    #: "faqat shaxsiy chat" izohi. Ro'yxatdagi guruhda bot xabarlarni
    #: saqlaydi va `/summary`, `/askvenera` ga javob beradi (`app/bot/groups.py`).
    #:
    #: `.env` dan JONLI o'qiladi (`telegram_groups_now`): guruh qo'shish uchun
    #: xizmatni qayta ishga tushirish shart emas. Guruh id si jurnalda
    #: ko'rinadi - ro'yxatda yo'q guruhda botga murojaat qilinganda.
    #:
    #: Endi bu - BOSHLANG'ICH ro'yxat: rahbar guruhlarni botda boshqaradi
    #: (`GroupRegistry`, `app/bot/group_admin.py`). Rahbar guruh haqida qaror
    #: qilgach o'sha guruhni bot boshqaradi - bu yerdagi yozuv unga ta'sir qilmaydi.
    telegram_groups: str = ""
    #: Guruh xabarlari ombori. `data/` gitignore'da, fayl 600.
    telegram_groups_db: Path = BASE_DIR / "data" / "telegram" / "groups.db"
    #: Guruh xabarlari shuncha kun saqlanadi, keyin o'chiriladi. 0 - o'chirilmaydi (2026-11-05 ega
    #: qarori: hech narsa o'chmasin); xulosa davri baribir `tg_groups.WINDOW_DAYS` dan oshmaydi.
    telegram_group_days: int = 90
    #: Guruh xulosasini yozadigan model (Ollama Cloud). Bo'sh - `ollama_model`.
    telegram_group_model: str = ""
    #: Guruhdagi so'rovlar chegarasi, `soni/soniya`: bitta odamga va butun
    #: guruhga. `.env` dan JONLI o'qiladi (`telegram_group_limits_now`).
    #: Sinov paytida keng (2026-10-06: guruhda hamma administrator).
    telegram_group_user_limit: str = "10/60"
    telegram_group_limit: str = "120/3600"
    #: Rahbariyat brifi (`app/bot/briefs.py`) kimga ochiq: ADMIN rolidagilar VA
    #: shu loginlar - vergul yoki bo'shliq bilan, harf registriga qaramaydi
    #: (`miniapp_beta_logins` qoidasi: SSO hisobi - logini, `users.yaml` -
    #: emaili). `.env` dan JONLI o'qiladi (`telegram_brief_logins_now`).
    telegram_brief_logins: str = ""

    # --- Slack ilovasi "Barno AI" (`app/slack/`, Socket Mode) ---
    #: Bot tokeni (`xoxb-...`): xabar yozish va fayl o'qish. Ruxsatlar: `im:history`,
    #: `chat:write`, `files:read`, eksport fayli uchun `files:write`; hodisa: `message.im`;
    #: tugmalar - Interactivity (Socket Mode orqali keladi). Ikkala token bo'lmasa ilova
    #: O'CHIQ. SIR - jurnal va javoblarga tushmaydi.
    slack_bot_token: str = ""
    #: Ilova tokeni (`xapp-...`, `connections:write`) - Socket Mode ulanishi. Bitta
    #: token bilan FAQAT BITTA jarayon ulanadi, aks holda Slack hodisalarni ular
    #: orasida tasodifiy taqsimlaydi (`app/slack/__init__.py`).
    slack_app_token: str = ""
    #: Slack'dan kelgan audio QAYSI Venera hisobining yig'ilishi bo'lib saqlanadi
    #: (`actorId`). Hozircha Slack odami o'z hisobiga bog'lanmaydi: hammasi shu
    #: hisobda - uning ro'yxatida ko'rinadi, kunlik limit va soatlik chegara umumiy.
    #: Hisob ADMIN yoki `MEETINGS_LOGINS` da bo'lishi kerak. Bo'sh - sozlanmagan.
    #:
    #: NEGA `str`, `int` EMAS. `SLACK_ACTOR_ID=` bo'sh yoki xato yozilsa `int` maydon
    #: butun `Settings` ni yiqitardi va API restartda umuman ko'tarilmasdi (jonli
    #: `.env` da aynan shunday bo'ldi). Matn ishlatilgan joyda tekshiriladi
    #: (`slack/transcribe.py: account`) - xatoni odam Slack'da ko'radi.
    slack_actor_id: str = ""

    # --- Xodimlar ma'lumotnomasi (kontaktlar) ---
    #: F.I.SH, Telegram, telefon, email - `services/contacts.py`. SHAXSIY
    #: MA'LUMOT: `data/` gitignore'da, fayl 600.
    contacts_db: Path = BASE_DIR / "data" / "contacts" / "contacts.db"

    # --- Analitika va admin panel ---
    #: Har savol-javob izi, tashqi chaqiruvlar hisobi, shikoyatlar va admin
    #: o'zgarishlari - BITTA SQLite faylda (`services/analytics/`). Faylda
    #: savollar va javoblar turadi, ya'ni SHAXSIY MA'LUMOT: `data/`
    #: gitignore'da, papka 700, fayl 600.
    analytics_db_file: Path = BASE_DIR / "data" / "analytics" / "venera.db"
    #: O'chirilsa YANGI yozuvlar to'xtaydi, chat esa odatdagidek ishlaydi -
    #: yozib olish ikkinchi darajali. Admin panel eski yozuvlarni ko'rsataveradi.
    analytics_enabled: bool = True
    #: Shuncha kundan eski savollar, chaqiruvlar va kirish urinishlari har
    #: 6 soatda o'chiriladi. Shikoyatlar va admin auditi SAQLANADI - ular
    #: statistika emas, hujjat. 0 - hech narsa o'chirilmaydi.
    analytics_retention_days: int = 180
    #: Arxiv (`services/archive.py`): Telegram va Slack orqali kelgan va yuborilgan, boshqa joyda
    #: saqlanmaydigan hamma narsa - ovozli savol audiosi, rasm, fayl, Slack matni, yuborilgan Word/PDF.
    #: Muddati YO'Q (ega qarori, 2026-11-05). `data/` gitignore'da, papkalar 700, fayllar 600.
    archive_dir: Path = BASE_DIR / "data" / "archive"
    #: Bundan katta fayl arxivga yozilmaydi (qatori `too_large` bilan qoladi). Telegram botga
    #: baribir 20 MB dan kattasini bermaydi.
    archive_max_file_mb: int = 50
    #: "Tizim xaritasi" (admin panel, `/admin/os-map`) ma'lumoti: oqimlar, qadamlar,
    #: kod parchalari va ICHKI PROMPTLAR so'zma-so'z. Shuning uchun `data/` da
    #: (gitignore) va STATIK FAYL SIFATIDA BERILMAYDI - faqat
    #: `GET /api/v1/admin/osmap` (ADMIN). Fayl xarita yig'uvchisidan (`build.py`)
    #: qo'lda nusxalanadi; yo'q bo'lsa sahifa 404 va tushunarli xabar ko'rsatadi.
    osmap_path: Path = BASE_DIR / "data" / "osmap" / "osmap.json"
    #: Vergul bilan loginlar/emaillar (harf registriga qaramaydi) - ular
    #: HAR DOIM ADMIN, admin paneldan ham olib bo'lmaydi. Birinchi
    #: administratorni tayinlash va "hamma adminlar o'zini bloklab qo'ydi"
    #: holatidan chiqish yo'li shu: rolni faylda emas, `.env` da berish.
    #: SSO hisobi FAQAT LOGINI bilan (`y.mamajonov`) tanlanadi - emailini
    #: Keycloak'da odam o'zi o'zgartira oladi; email faqat `users.yaml` dagi
    #: zahira hisob uchun ishlaydi (`services/admin_users.is_bootstrap`).
    admin_logins: str = ""
    #: (`SSO_TRUSTED_ROLES` OLIB TASHLANDI, 2026-11: SSO rollari endi faqat
    #: bizning Keycloak client'imizniki - `sso_client_id` izohi - va ularga
    #: to'liq ishoniladi; realm rollari umuman o'qilmaydi.)

    # --- Yig'ilish yozuvchisi (Venera Yozuv, `services/meetings/`) ---
    #
    # Mobil ilova yig'ilishni yozadi, GAPI spikerlarni ajratib matnga
    # o'giradi, gemma4:31b esa xulosa yozadi. Spetsifikatsiya:
    # `docs/plans/meeting-recorder.md`.
    #
    #: BO'LIM O'CHIQ - default. Yig'ilish audiosi GAPI ga, matni Ollama
    #: Cloud ga ketadi: bu YANGI ma'lumot turi (1:1, suhbat, mijoz
    #: qo'ng'irog'i), va foydalanuvchi buni alohida tasdiqlamaguncha bo'lim
    #: ko'rinmaydi (404). `.env` dan JONLI o'qiladi (`meetings_enabled_now`):
    #: yoqish/o'chirish uchun restart kerak emas.
    meetings_enabled: bool = False
    #: Sinov guruhi: ADMIN rolidagilar VA shu loginlar (vergul/bo'shliq bilan,
    #: registrga qaramaydi; SSO - logini, `users.yaml` - emaili). JONLI.
    meetings_logins: str = ""
    #: Ombor, audio va yuklanayotgan bo'laklar shu papkada. SHAXSIY
    #: MA'LUMOT: papka 700, fayllar 600, `data/` gitignore'da.
    meetings_dir: Path = BASE_DIR / "data" / "meetings"
    #: Fon ishchisi (transkripsiya, xulosa, tozalash). Testlarda O'CHIQ:
    #: `TestClient` ishga tushishi ip yaratmasin.
    meetings_worker: bool = True
    #: Bir vaqtda nechta yig'ilish ishlanadi. 2: biri GAPI ni kutayotganda
    #: ikkinchisining xulosasi yozilsin; server 4 CPU / 3 GB - ko'pi zarar.
    meetings_worker_threads: int = 2
    #: Eng uzun yozuv (daqiqa). Ilova shundan 10 daqiqa oldin ogohlantiradi.
    meetings_max_minutes: int = 180
    #: Bitta yozuvning eng katta hajmi. 48 kbps ADTS da 3 soat ~65 MB -
    #: 150 MB katta zahira (m4a yuklansa ham sig'adi).
    meetings_max_upload_mb: int = 150
    #: Bo'lak hajmi: nginx'ning `client_max_body_size` (12m deb faraz
    #: qilingan) dan ancha kichik, mobil tarmoqda esa qayta yuborish arzon.
    meetings_chunk_bytes: int = 4 * 1024 * 1024
    #: Bitta odamga kuniga necha audio-daqiqa GAPI da o'giriladi. Oshsa
    #: yozuv RAD ETILMAYDI - navbatda turadi (`waiting_quota`).
    meetings_user_daily_minutes: int = 240
    #: Yig'ilishlar uchun BUTUN xizmatning kunlik ulushi. Balansning
    #: qolgani chat diktovkasi uchun. HAR GAPI KALITI uchun: `GAPI_API_KEY2`
    #: ham bo'lsa ikki barobar.
    meetings_gapi_daily_minutes: int = 180
    #: GAPI balansida doim shuncha daqiqa qolsin - chatdagi ovozli savol
    #: yig'ilish tufayli to'xtab qolmasin.
    meetings_gapi_reserve_minutes: int = 60
    #: Audio shuncha kundan keyin o'chiriladi; matn va xulosa qoladi. 0 - saqlanadi
    #: (2026-11-04 ega qarori: hozircha o'chirilmaydi, ma'lumot ko'paysa qaytariladi).
    meetings_audio_days: int = 30
    #: Butun yig'ilish (matni bilan) shuncha kundan keyin o'chiriladi. 0 - saqlanadi.
    meetings_retention_days: int = 180
    #: Tugallanmagan yuklash oxirgi bo'lakdan shuncha soat keyin o'chiriladi.
    meetings_upload_ttl_hours: int = 72
    #: GAPI ga BITTA HTTP amal (yuklash, so'rash) uchun chegara.
    meetings_stt_timeout: float = 120.0
    #: GAPI vazifasini jami shuncha kutamiz, keyin `stt_timeout` (qayta
    #: urinish o'sha vazifa raqami bilan - pul qayta yechilmaydi).
    meetings_stt_deadline: float = 3600.0
    #: Xulosa modeli. Bo'sh - `ollama_model` (gemma4:31b).
    meetings_llm_model: str = ""
    #: Bitta model chaqiruvi (va o'z navbatimizni kutish) chegarasi. 8K tokenlik
    #: javob ~30-50 tok/s da 160-270 s - 180 s kam edi. Jonli o'lchovdan keyin aniqlanadi.
    meetings_llm_timeout: float = 300.0
    #: Ollama `num_ctx`. 0 - yuborilmaydi: Cloud'dagi kontekst oynasi hali
    #: o'lchanmagan, jonli tekshiruv (`tools/meetings_live_check.py`) dan keyin qo'yiladi.
    meetings_llm_num_ctx: int = 0
    #: Ollama `think`: bo'sh - yuborilmaydi; `false` - model "o'ylash" tokenlarini
    #: sarflamasin (ular `num_predict` dan yeyiladi). Jonli tekshiruv `thinking`
    #: maydoni kelyaptimi - shuni ko'rsatadi, keyin qo'yiladi.
    meetings_llm_think: str = ""
    #: Shundan qisqa matn BITTA chaqiruvda xulosalanadi; uzunrog'i bo'laklab
    #: (map-reduce). ~30 ming belgi ~ 14 ming token kirish va ~5-6 ming token
    #: javob (45 daqiqalik yig'ilish JSON i ~6-7K token - 45K da javob kesilardi).
    meetings_single_pass_chars: int = 30000
    #: Map bosqichida bitta bo'lak hajmi (belgi).
    meetings_map_chars: int = 20000
    #: Javob byudjeti (token): bir o'tish va map bo'lagi. Ollama Cloud chiqish
    #: chegarasi jonli tekshiruvda tasdiqlanadi (`meetings_live_check.py ollama`).
    meetings_extract_num_predict: int = 8192
    meetings_map_num_predict: int = 6144
    #: Vazifa va qarorlarni ikkinchi chaqiruv bilan tekshirish.
    meetings_verify: bool = True
    #: Bitta odamning soatlik chegaralari: savol (Ask) va xulosa tabi. Savol chegarasi yig'ilish CHATI bilan
    #: UMUMIY (bitta hisoblagich): 2026-11-11 dan 60 - suhbatda savol ko'proq, Slack'dagi hamma odam esa
    #: bitta xizmat hisobidan so'raydi.
    meetings_ask_per_hour: int = 60
    meetings_summary_per_hour: int = 10
    #: Mobil ilova yozish manbasi (`voice_recognition` | `mic` | `camcorder`) -
    #: `GET /meetings/config` orqali masofadan A/B sinash uchun.
    meetings_audio_source: str = "voice_recognition"
    #: Model ZANJIRI (`services/meetings/llm.py`): vergul bilan, tartibi - ustunlik.
    #: `v3` - yordamchining "Venera Core" dvigateli, `openai` - OpenAI GPT
    #: (kalit va model berilgandagina), `ollama` - gemma4:31b (oxirgi zahira).
    #: BITTA xulosa BITTA modelda yoziladi: biror qadam yiqilsa yoki JSON tuzatishdan
    #: keyin ham yaroqsiz bo'lsa, butun xulosa keyingi model bilan BOSHIDAN yoziladi
    #: (aralash xulosa - bir bo'lagini bir model, boshqasini boshqasi - bo'lmasin).
    #: Default `ollama`: sozlanmaguncha xulq o'zgarmaydi. Namoyish: `v3,openai,ollama`.
    meetings_llm_chain: str = "ollama"
    #: Savol-javob (Ask) zanjiri. Bo'sh - `meetings_llm_chain` bilan bir xil.
    meetings_ask_chain: str = ""
    #: v3 ga bitta savolning eng katta uzunligi (belgi). Chat qirqimi (2000) bu yerga
    #: TEGISHLI EMAS - yuqoridagi `ChatReq.question` da chegara e'lon qilinmagan. Map
    #: ko'rsatmalarining o'zi ~14 ming belgi (+ sarlavha, meta, shablon ~1.5-2 ming): 20000 da
    #: bitta map chaqiruviga ~2.9 ming belgi transkript sig'adi (`general`; `sales_call` ~2.4
    #: ming), ya'ni 10 daqiqalik (~9 ming belgi) yig'ilish ~3-4 map + yozuvchi + tekshiruv =
    #: 5-6 v3 chaqiruvi, 30 daqiqa ~10-12, 1 soat ~22-27 (byudjetdan oshadi - keyingi model).
    #: Jonli tekshiruvdan keyin 40000: 20 ming belgigacha bitta o'tish (2 chaqiruv).
    meetings_v3_max_chars: int = 20000
    #: v3 oqimida kadrlar ORASIDAGI eng uzun jimlik (soniya): agent katta matnni o'qib,
    #: birinchi so'zni yozguncha chat savolidan ko'proq o'ylaydi.
    meetings_v3_timeout: float = 120.0
    #: Bitta v3 javobining eng uzun umri (soniya).
    meetings_v3_max_stream_seconds: float = 300.0
    #: Yig'ilish ishchisining O'Z v3 navbati: chatdagi odamlar xulosa tufayli kutmasin.
    #: Shuncha xulosa bir vaqtda v3 da yoziladi; qolgani navbatda kutadi (30 s dan keyin).
    meetings_v3_max_concurrent: int = 1
    #: Ishchi ipi v3 slotini shuncha soniya kutadi (ikki chaqiruv orasida boshqa ip olgan bo'lsa).
    meetings_v3_slot_wait: float = 30.0
    #: v3 vaqtinchalik xatosida (503, uzilish, jimlik) shu savol necha marta qayta (5 s, 15 s).
    meetings_v3_retries: int = 2
    #: Zanjirda v3 ga BITTA xulosa uchun ajratilgan vaqt (soniya) va chaqiruvlar soni (0 -
    #: chegarasiz). Oshsa (yoki yig'ilish oldindan sig'masa) - xulosa keyingi model bilan:
    #: sekin, lekin tirik v3 xulosani o'nlab daqiqa ushlab turmasin.
    meetings_v3_summary_budget_sec: float = 600.0
    meetings_v3_summary_max_calls: int = 16
    #: Savol-javob (Ask): odam kutib turgan umumiy muddat (soniya) - hamma model birga.
    #: Oxirgisidan boshqasiga qolgan vaqtning 2/3 qismi beriladi.
    meetings_ask_deadline: float = 90.0
    #: --- Yig'ilish CHATI (2026-11-11, ega so'rovi): bitta audio - bitta suhbat, `services/meetings/chat.py` ---
    #: Mobil ilova, Slack va Telegram'dagi suhbat - BITTA tarix (`questions` jadvalining faol qatorlari).
    #: Zanjir o'sha - `MEETINGS_ASK_CHAIN` (prod'da `claude`); Claude'ga suhbat ko'p navbatli xabarlar bilan
    #: ketadi (`ClaudeChat.converse`), qolgan modellarga - oldingi savol-javoblar matn bloki bilan.
    #: Chat modeli (`rt.ask_claude`). Bo'sh - `meetings_claude_model` (claude-sonnet-5-5).
    meetings_chat_model: str = ""
    #: Chat `output_config.effort`i. Bo'sh - `meetings_claude_effort`.
    meetings_chat_effort: str = ""
    #: Modelga xotira sifatida qaytariladigan oxirgi savol-javoblar soni ("batafsilroq", "u kim edi?").
    meetings_chat_history_turns: int = 10
    #: Xotiradagi savol+javob matni shundan oshsa (belgi) - eng eski navbatlar tashlanadi.
    meetings_chat_history_chars: int = 40000
    #: Transkript Claude'ga shu hajmgacha (belgi) TO'LIQ ketadi; undan uzunida - savol va oxirgi 2 savol
    #: so'zlari bo'yicha tanlangan qatorlar (`ask._select`, shu hajmdagi byudjet bilan).
    meetings_chat_context_chars: int = 400000
    #: Savol-javob / chat Claude klientining (`rt.ask_claude`) bir vaqtdagi so'rovlari (slotlar).
    meetings_chat_concurrency: int = 4
    #: Server tomonidagi rad-zahirasi (`fallbacks: "default"`, beta `server-side-fallback-2026-07-01`): Claude
    #: xavfsizlik klassifikatori savolni rad etsa, xizmat uni o'zi tavsiya etilgan boshqa modelda qayta
    #: yozadi. Xizmat (yoki proksi) zahirani rad etsa (400) - bir marta zahirasiz va keyin yuborilmaydi.
    meetings_chat_fallbacks: bool = True
    #: OpenAI kaliti - `apps/api/.env` dan JONLI o'qiladi (`openai_key_now`); u yerda kalit
    #: bo'lmasa - ishga tushishdagi qiymat (systemd `Environment=`). Jurnalga tushmaydi.
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    #: OpenAI modeli (foydalanuvchi bergan GPT id si). BO'SH - provayder O'CHIQ: default
    #: model ATAYLAB yo'q - qaysi model va qancha narx, foydalanuvchi hal qiladi.
    meetings_openai_model: str = ""
    #: Bitta OpenAI chaqiruvi chegarasi (soniya).
    meetings_openai_timeout: float = 300.0
    #: OpenAI konteksti katta: 1 soatlik yig'ilish (~70 ming belgi) BITTA chaqiruvda -
    #: butun yig'ilishni bir ko'rishda yozilgan xulosa bo'laklardan yig'ilganidan yaxshiroq.
    meetings_openai_single_pass_chars: int = 120000
    meetings_openai_map_chars: int = 60000
    #: `max_completion_tokens`. 0 - yuborilmaydi (modelning o'z chegarasi): "o'ylovchi"
    #: modellarda bu son o'ylash tokenlarini ham o'z ichiga oladi, kichik son javobni kesardi.
    meetings_openai_max_output_tokens: int = 0
    #: `reasoning_effort` (low | medium | high). Bo'sh - yuborilmaydi (oddiy modellar uni rad etadi).
    meetings_openai_reasoning_effort: str = ""
    #: `temperature`. Bo'sh - yuborilmaydi ("o'ylovchi" modellar faqat default'ni qabul qiladi);
    #: oddiy model (gpt-4.1/4o sinfi) uchun 0.1-0.2 - aks holda u 1.0 da yozadi.
    meetings_openai_temperature: str = ""
    #: OpenAI 5xx / tarmoq xatosida xulosa chaqiruvi necha marta qayta (3 s dan keyin).
    meetings_openai_retries: int = 1
    #: Claude (Anthropic) kaliti - `apps/api/.env` dagi `CLAUDE_API_KEY`, JONLI o'qiladi
    #: (`claude_key_now`); jurnalga va health'ga chiqmaydi.
    claude_api_key: str = ""
    #: Anthropic API manzili. Bo'sh - SDK default'i (api.anthropic.com).
    claude_base_url: str = ""
    #: Anthropic workspace id (`wrkspc_...`). Tashkilot darajasidagi kalit (workspace'ga bog'lanmagan)
    #: har so'rovda `anthropic-workspace-id` sarlavhasini talab qiladi (400 "not scoped to a
    #: workspace") - Console -> Settings -> Workspaces dagi id. Workspace'ga bog'langan kalitda shart
    #: emas. `.env` dan JONLI (`claude_workspace_now`).
    claude_workspace_id: str = ""
    #: Claude modeli. EGA QARORI (2026-11-04): yig'ilish xulosasi va bayonnoma gemma4:31b o'rniga
    #: Claude Sonnet 5.5 bilan. Default bor (OpenAI dan farqli): modelni ega o'zi tanladi; kalit
    #: bo'lmasa provayder o'chiq. Zanjirga `claude` bo'g'ini bilan kiradi: `MEETINGS_LLM_CHAIN=claude,ollama`.
    meetings_claude_model: str = "claude-sonnet-5-5"
    #: Bitta Claude chaqiruvi chegarasi (soniya). Javob OQIM bilan olinadi (uzun javobda HTTP
    #: kutish tugamasin), chegara oqimning umumiy umri.
    meetings_claude_timeout: float = 600.0
    #: Bitta javobning eng ko'p tokeni (`max_tokens`): modelning "o'ylash" tokenlari ham shu ichida.
    meetings_claude_max_output_tokens: int = 16000
    #: `output_config.effort` (low | medium | high | xhigh | max): o'ylash chuqurligi va narx.
    #: Xulosa - `medium` (grounded ro'yxatlar uchun yetarli); bayonnoma - `MEETINGS_MINUTES_EFFORT`.
    meetings_claude_effort: str = "medium"
    #: SDK qayta urinishlari (429, 5xx, tarmoq) - eksponensial kutish bilan.
    meetings_claude_retries: int = 2
    #: Claude konteksti katta (1M token): 3 soatlik yig'ilish (~200 ming belgi) BITTA chaqiruvda -
    #: butun yig'ilishni bir ko'rishda yozilgan xulosa bo'laklardan yig'ilganidan yaxshiroq.
    meetings_claude_single_pass_chars: int = 200000
    meetings_claude_map_chars: int = 100000
    #: --- Bayonnoma (rasmiy hujjat, `services/meetings/minutes/`) ---
    #: Hujjatni yozadigan model zanjiri. Default FAQAT `claude`: gemma rasmiy kirill matnini
    #: yozmagan, zahira hujjatni buzardi. Sozlanmagan bo'lsa - 503 `llm_not_configured`.
    meetings_minutes_chain: str = "claude"
    #: Bayonnoma uchun `effort` - uzun rasmiy matn, bandlar va asoslash: `high`.
    meetings_minutes_effort: str = "high"
    #: Bayonnoma javobi (39 band ~ 2,700 so'z ~ 10-12 ming token + o'ylash).
    meetings_minutes_max_output_tokens: int = 32000
    #: Bitta odamga soatiga shuncha bayonnoma (har biri pullik Claude chaqiruvi).
    meetings_minutes_per_hour: int = 6
    #: Vazifani CRM ga yuborish (v3 taklifi): odamga soatiga shuncha so'rov va bitta
    #: so'rovning eng uzun kutishi (agent CRM dan loyiha va odamni qidiradi).
    meetings_crm_per_hour: int = 20
    meetings_crm_timeout: float = 120.0
    #: CRM so'rovi FAQAT odamning O'Z CRM ulanishi bilan (guruhdagi CRM qoidasi): umumiy
    #: `CrmAuth` hisobi va HRM tokeni yuborilmaydi - vazifa so'ragan odam nomidan. `false` -
    #: o'z ulanishi bo'lmasa umumiy CRM hisobi (HRM baribir yuborilmaydi).
    meetings_crm_own_tokens: bool = True
    #: Yig'ilish savol-javobida (Ask, v3) agentga SHU platformalar tokeni ketadi (vergul bilan).
    #: 2026-10-10 (F0 maxfiylik): faqat `crm` - yig'ilish savoliga HR ma'lumoti (maosh,
    #: ta'til) kerak emas, HRM tokeni ortiqcha ochiq eshik edi. `.env` dan JONLI
    #: (`platforms_now`) - qaytarish restartsiz: `MEETINGS_ASK_PLATFORMS=crm,hrm`. CRM
    #: tokeni avvalgidek (`chat._live_tokens`).
    meetings_ask_platforms: str = "crm"
    #: Brifdagi CRM tekshiruvida (`bot/crm_status.agent_ask`) agentga ketadigan platformalar.
    #: Xuddi shu qoida (F0): vazifa holati - faqat CRM. Qaytarish restartsiz:
    #: `BRIEF_CRM_PLATFORMS=crm,hrm` (masalan agent ismni HRM orqali topishi kerak bo'lsa).
    brief_crm_platforms: str = "crm"
    #: To'liq hujjat eksporti (`GET /meetings/{id}/export`: DOCX/PDF/MD/TXT) - odamga soatiga
    #: shuncha fayl. Uzun transkriptli PDF bir necha soniya CPU oladi: tugmani qayta-qayta
    #: bosish serverni band qilmasin.
    meetings_export_per_hour: int = 30
    #: Bir vaqtda chiziladigan eksportlar (butun jarayon) va navbatda kutish (soniya). Endpoint
    #: sync: kutayotgan har so'rov umumiy threadpool ipini band qiladi - navbat qisqa bo'lsin,
    #: oshsa 503 `export_busy`. Bitta odamning ikkinchi parallel eksporti - darhol 429 `export_busy`.
    meetings_export_concurrency: int = 2
    meetings_export_wait_sec: float = 10.0
    #: PDF shrifti papkasi: `DejaVuSans.ttf` (+ `DejaVuSans-Bold.ttf`). reportlab'ning o'z
    #: Helvetica'si kirill va o'zbek `oʻ`/`gʻ` ni chizmaydi ("qora qutilar"). Fayl yo'q bo'lsa
    #: PDF 503 `pdf_unavailable` qaytaradi, qolgan formatlar ishlayveradi.
    meetings_export_font_dir: Path = Path("/usr/share/fonts/truetype/dejavu")
    #: Qurilma tokeni (mobil ilova) - oxirgi ishlatilgandan shuncha kun yashaydi.
    device_token_days: int = 30
    #: Qurilma tokenlari ombori (faqat xeshlar). `data/` gitignore'da, 600.
    devices_db: Path = BASE_DIR / "data" / "devices.db"

    # --- Miya agentga ko'chishi (W0 relslari, `services/brain/`) ---
    #
    # NEGA. Egasining qarori (2026-10-10): serverimiz oxir-oqibat LLM CHAQIRMAYDI -
    # xulosa, ajratish, tasnif va savol-javob agentda ("HR Assistant API", shartnoma
    # `agent-contract.md`, "v4"). Ko'chish funksiyama-funksiya: `local -> shadow ->
    # agent`, har biri o'z flag'i ortida va lokal zahira bilan. Default'lar BUGUNGI
    # xulq: hammasi `local`, agent mijozi O'CHIQ - deploy xulqni o'zgartirmaydi.
    #
    #: AGENT MIJOZINING BOSH KALITI (v4 endpointlari: `complete`, `chat`, `jobs`,
    #: `capabilities`). `false` - flag nima desa ham hamma joy `local`. `.env` dan
    #: JONLI o'qiladi (`agent_v4_enabled_now`): agent yiqilsa restartsiz o'chiriladi.
    agent_v4_enabled: bool = False
    #: Agent manzili. Bo'sh - chat bilan bir xil (`hrm_assistant_base_url`): kalit
    #: (`X-Client-Id/Secret`) ham o'sha. Shartnoma 3.1: prefiks agent jamoasiniki.
    agent_v4_base_url: str = ""
    agent_v4_prefix: str = "/api/v4"
    #: `X-Barno-Contract` sarlavhasi - agent maxfiylik maydonini bajara olmasa 400 qaytaradi.
    agent_v4_contract: str = "4.0"
    #: Interaktiv agent chaqiruvi (`complete`, `chat`) chegarasi va bir vaqtdagi soni.
    #: Chatning 4 ta o'rnidan (`hrm_assistant_max_concurrent`) ALOHIDA navbat.
    agent_v4_timeout: float = 60.0
    agent_v4_max_concurrent: int = 2
    #: Fon ishlari (brif prewarm: `brief_extract*`) - O'Z navbati: interaktiv `/summary` ning
    #: o'rnini egallamasin. Band bo'lsa kutilmaydi - lokal zahira.
    agent_v4_batch_max_concurrent: int = 1
    #: Uzgich (circuit breaker): agent ketma-ket shuncha marta ishlamasa (tarmoq, 5xx, 429) -
    #: `agent_v4_breaker_cooldown` soniya (har safar ikki baravar, 5 daqiqagacha) unga
    #: borilmaydi, hammasi darhol lokal. NEGA: aks holda har chaqiruv 60 s timeout kutardi.
    agent_v4_breaker_failures: int = 3
    agent_v4_breaker_cooldown: float = 30.0
    #: `GET /capabilities` keshi (soniya). Flag `shadow`/`agent` ga faqat kerakli
    #: imkoniyat `true` bo'lsa o'tadi (shartnoma 3.7); kesh bo'sh bo'lsa - `local`.
    agent_capabilities_ttl: float = 300.0
    #: EGASINING QARORI (2026-10-11): GPU server kelguncha agent v4 ishlarini Ollama
    #: Cloud'da (gemma4:31b-cloud) bajaradi - `capabilities` da `in_network_models_only:
    #: false`, `external_models_allowed: true`. Shu kalit `true` bo'lsa himoya bunga ruxsat
    #: beradi va kontekst bloklariga `policy.external_llm: true` yoziladi (agent `false`
    #: ni rad etadi). Bugungi yo'l ham shu ma'lumotni Ollama Cloud'ga yuboradi - yomonroq
    #: emas. JONLI o'qiladi: `false` qilinsa hamma funksiya restartsiz lokalga qaytadi.
    agent_v4_allow_external_models: bool = True
    #: SHADOW: foydalanuvchi lokal natijani oladi, agent esa fonda, O'Z navbatida
    #: (`max_concurrent`, chatning slotlari emas) va namuna bo'yicha ishlaydi. Navbat
    #: to'lsa vazifa TASHLANADI (hisoblanadi) - foydalanuvchi hech qachon kutmaydi.
    agent_shadow_max_concurrent: int = 1
    agent_shadow_queue: int = 8
    #: Namuna: shadow holatidagi chaqiruvlarning qancha qismi agentga ham ketadi (0..1).
    #: Admin flag qatorida funksiya bo'yicha alohida berilishi mumkin.
    agent_shadow_sample_rate: float = 0.2
    agent_shadow_timeout: float = 120.0
    #: `shadow_results` jadvali shuncha kun saqlanadi (xom matn YO'Q - faqat sonlar).
    shadow_results_days: int = 30
    #: Funksiya bo'yicha boshlang'ich holat: `local | shadow | agent`. Admin panel
    #: (`engine_control`, `brain_routing` jadvali) undan ustun. `.env` dan JONLI.
    #: `meeting_ask` ning `local` i - bugungi zanjir (`MEETINGS_ASK_CHAIN`).
    group_summary_engine: str = "local"
    group_ask_engine: str = "local"
    brief_extract_engine: str = "local"
    brief_crm_engine: str = "local"
    meeting_summary_engine: str = "local"
    meeting_ask_engine: str = "local"
    hold_classify_engine: str = "local"
    #: Guruhdagi CRM so'rovi: `local` - bugungi v3 oqimi; `agent` - v4 shakli (kontekst bloki,
    #: `surface` suhbat, guruh auditoriyasi); `shadow` - foydalanuvchi bugungisini oladi, v4 fonda.
    group_crm_engine: str = "local"
    #: Yig'ilish vazifasini CRM ga taklif qilish: `local` - bugungi v3 oqimi; `agent` - v4
    #: (`purpose: meeting_crm`, faqat CRM vositalari va o'z CRM tokeni, shaxsiy xotirasiz).
    meeting_crm_engine: str = "local"
    #: Ovoz uchun matn (o'qib berish, ovozli javob): `agent` - agentning `POST /speech` i
    #: raqam, foiz, mln/mlrd/trln, sana va vaqtni o'zbekcha so'z bilan yozadi (model YO'Q,
    #: ~4 ms); javob kelmasa yoki kechiksa - bugungi yo'l (OmniVoice normalizatori).
    tts_speech_engine: str = "local"
    #: `/speech` uchun kutish: o'qish birinchi ovozgacha shuni kutadi, shuning uchun qisqa.
    tts_agent_speech_timeout: float = 0.5
    #: Ovozli "hold" tasnifi: `keyword` - faqat kalit so'z jadvali: ovozli savol (shaxsiy
    #: HR savoli ham) `ollama.com` ga CHIQMAYDI; `llm` - avvalgidek gemma. `.env` dan JONLI
    #: (`hold_classifier_now`), restartsiz.
    #: DEFAULT `keyword` (2026-10-10): reja W0.5 / D2 (egasining qarori 8.1 #2) - deploy
    #: shu qadamni o'zi bajaradi, `.env` ga yozishni unutib qo'yish xavfi yo'q. Kutish
    #: ovozi baribir aytiladi: `HOLD_FIRST_MS` da jadval bilan (model ulgurmagandagi
    #: bugungi zahira yo'li). Qaytarish: `.env` da `HOLD_CLASSIFIER=llm`.
    hold_classifier: str = "keyword"

    # --- CORS ---
    #: Bo'sh bo'lsa CORS o'chirilgan: frontend nginx orqali BIR XIL originda
    #: turadi (`/api` proxy), ya'ni CORS umuman kerak emas. Faqat frontend
    #: boshqa domenda ishlasa to'ldiriladi.
    cors_origins: list[str] = []

    @property
    def secret_is_default(self) -> bool:
        return self.secret_key == "dev-only-insecure-change-me"


settings = Settings()


#: `.env` fayli - `hrm_token_now()` shundan o'qiydi.
_ENV_FILE = BASE_DIR / ".env"

#: Oxirgi o'qish, kalit bo'yicha: {kalit: (fayl belgisi, qiymat)}.
#: Belgi - `mtime_ns` va hajm.
_token_cache: dict[str, tuple[object, str]] = {}
_token_lock = threading.Lock()


def _env_token(key: str, fallback: str = "") -> str:
    """`.env` dan bitta token - HAR SAFAR yangi qiymat bilan.

    NEGA SOZLAMA OBYEKTIDAN EMAS. HRM sessiyasi bir necha daqiqada muddati
    tugaydi, ya'ni token tez-tez almashtiriladi. `Settings` esa faylni
    FAQAT import paytida o'qiydi - yangi qiymatni ko'rish uchun xizmatni
    qayta ishga tushirish kerak bo'lardi, va har necha daqiqada restart
    ayni vaqtda oqib turgan javoblarni kesib yuborardi.

    Diskka odatda BORILMAYDI: fayl o'zgargani `stat` bilan aniqlanadi
    (`mtime_ns` + hajm), o'zgarmagan bo'lsa keshdagi qiymat qaytadi.

    Fayl o'qilmasa - eng oxirgi MA'LUM qiymat qaytadi, bo'sh satr emas:
    tahrirlash o'rtasida qolgan fayl tufayli ishlab turgan chat to'xtab
    qolmasligi kerak. Kalitning O'ZI yo'q bo'lsa esa bo'sh satr qaytadi,
    chunki bu "token olib tashlandi" degani bo'lishi mumkin.
    """
    cached = _token_cache.get(key)
    try:
        info = _ENV_FILE.stat()
        mark: object = (info.st_mtime_ns, info.st_size)
    except OSError:
        return cached[1] if cached else fallback
    if cached is not None and mark == cached[0]:
        return cached[1]
    with _token_lock:
        # Ikkinchi tekshiruv: qulf kutilayotganda boshqa ip allaqachon
        # o'qib bo'lgan bo'lishi mumkin.
        cached = _token_cache.get(key)
        if cached is not None and mark == cached[0]:
            return cached[1]
        value = _read_env_value(_ENV_FILE, key)
        resolved = value if value is not None else ""
        _token_cache[key] = (mark, resolved)
        return resolved


def ollama_key_now() -> str:
    """Ollama kaliti - IKKI nomdan.

    `.env` da kalit `VENERA_API_URL` deb yozilgan, holbuki u URL emas,
    token (shakli `<32 hex>.<24 belgi>`). Nomni `.env` da tuzatish jonli
    xizmatni buzadi, shuning uchun kod ikkalasini ham qabul qiladi va
    to'g'ri nom BIRINCHI o'rinda turadi - keyin `.env` ni bemalol
    tozalash mumkin.
    """
    return _env_token("ollama_api_key", settings.ollama_api_key) or \
        _env_token("venera_api_url", settings.venera_api_url)


def openai_key_now() -> str:
    """OpenAI kaliti - `apps/api/.env` dan JONLI: kalit qo'yilgach yig'ilish xulosasi
    restartsiz OpenAI ga o'ta oladi (model - `MEETINGS_OPENAI_MODEL` - esa restart bilan).
    `.env` da kalit yo'q bo'lsa - ishga tushishdagi qiymat: systemd `Environment=` bilan
    berilgan kalit jim e'tiborsiz qolmasin. Qiymat hech qayerga (jurnal, health) chiqmaydi."""
    return _env_token("openai_api_key", settings.openai_api_key) or settings.openai_api_key


def claude_key_now() -> str:
    """Claude (Anthropic) kaliti - `apps/api/.env` dagi `CLAUDE_API_KEY`, JONLI (`openai_key_now`
    kabi): kalit almashsa restart shart emas. Qiymat hech qayerga chiqmaydi."""
    return _env_token("claude_api_key", settings.claude_api_key) or settings.claude_api_key


def claude_workspace_now() -> str:
    """Anthropic workspace id - `.env` dagi `CLAUDE_WORKSPACE_ID`, JONLI: id qo'yilgach restartsiz."""
    return _env_token("claude_workspace_id", settings.claude_workspace_id) or settings.claude_workspace_id


def hrm_token_now() -> str:
    """HRM sessiya token'i."""
    return _env_token("hrm_token", settings.hrm_token)


def crm_token_now() -> str:
    """CRM sessiya token'i."""
    return _env_token("crm_token", settings.crm_token)


def _rate(raw: str, default: str) -> tuple[int, float]:
    """`"10/60"` -> (10, 60.0). Noto'g'ri yozilgan bo'lsa - `default`."""
    for value in (raw, default):
        count, _, seconds = (value or "").strip().partition("/")
        try:
            parsed = (int(count), float(seconds))
        except ValueError:
            continue
        if parsed[0] >= 1 and parsed[1] > 0:
            return parsed
    return 1, 60.0


def telegram_group_limits_now() -> tuple[tuple[int, float], tuple[int, float]]:
    """(odamga, guruhga) so'rov chegarasi - `.env` dan JONLI."""
    return (
        _rate(_env_token("telegram_group_user_limit"), settings.telegram_group_user_limit),
        _rate(_env_token("telegram_group_limit"), settings.telegram_group_limit),
    )


def telegram_brief_logins_now() -> frozenset[str]:
    """Brif ochiq loginlar (`telegram_brief_logins`) - `.env` dan JONLI, kichik harfda."""
    raw = _env_token("telegram_brief_logins", settings.telegram_brief_logins)
    return frozenset(part.strip().lower() for part in re.split(r"[,\s;]+", raw or "") if part.strip())


def _env_flag(key: str, default: bool) -> bool:
    """`.env` dagi mantiqiy qiymat - JONLI. Kalit yo'q bo'lsa `default`
    (sozlama obyekti: muhit o'zgaruvchisi yoki koddagi default)."""
    raw = (_env_token(key, "") or "").strip().lower()
    if not raw:
        return bool(default)
    return raw in ("1", "true", "yes", "on")


def meetings_enabled_now() -> bool:
    """Yig'ilishlar bo'limi yoqilganmi - `.env` dan JONLI.

    Yoqish ham, o'chirish ham restartsiz: bo'lim maxfiy ma'lumot bilan
    ishlaydi, va "darhol yopish" kerak bo'lib qolsa xizmatni qayta ishga
    tushirish ayni paytda yuklanayotgan yozuvlarni uzib qo'yardi.
    """
    return _env_flag("meetings_enabled", settings.meetings_enabled)


def agent_v4_enabled_now() -> bool:
    """Agent mijozining bosh kaliti (`AGENT_V4_ENABLED`) - `.env` dan JONLI: agent
    noto'g'ri ishlasa hamma funksiya restartsiz lokal yo'lga qaytadi."""
    return _env_flag("agent_v4_enabled", settings.agent_v4_enabled)


def agent_v4_external_models_now() -> bool:
    """`AGENT_V4_ALLOW_EXTERNAL_MODELS` - `.env` dan JONLI (egasining 2026-10-11 qarori)."""
    return _env_flag("agent_v4_allow_external_models", settings.agent_v4_allow_external_models)


#: `HOLD_CLASSIFIER` qiymatlari.
HOLD_CLASSIFIERS = ("llm", "keyword")


def hold_classifier_now() -> str:
    """`llm` | `keyword` - `.env` dan JONLI.

    Bo'sh - sozlama obyekti (default `llm`, bugungi xulq). Tanilmagan qiymat
    `keyword`: egasi bu kalitni tashqi egress'ni TO'XTATISH uchun yozadi - imlo
    xatosi ovozli savollarni jimgina `ollama.com` ga yuboraverishi xavfliroq."""
    raw = (_env_token("hold_classifier", "") or "").strip().lower()
    value = raw or str(settings.hold_classifier or "llm").strip().lower()
    return value if value in HOLD_CLASSIFIERS else "keyword"


def platforms_now(key: str) -> frozenset[str]:
    """`meetings_ask_platforms` / `brief_crm_platforms` - `.env` dan JONLI, kichik harfda.
    Kalit `.env` da yo'q - sozlama obyekti (default `crm`). NEGA JONLI: bu maxfiylik
    tuzatishining qaytarish kaliti - agent biror savolga HRM kerak deb chiqsa, egasi
    restartsiz (oqimdagi javoblarni uzmasdan) qaytara olsin."""
    raw = (_env_token(key, "") or "").strip() or str(getattr(settings, key, "") or "")
    return frozenset(p.strip().lower() for p in raw.split(",") if p.strip())


def brain_engine_now(feature: str) -> str:
    """Funksiyaning `.env` dagi holati (`<FEATURE>_ENGINE`) - JONLI, kichik harfda.
    Bo'sh - sozlama obyekti; u ham bo'lmasa bo'sh satr (chaqiruvchi `local` qiladi)."""
    key = f"{feature}_engine"
    raw = (_env_token(key, "") or "").strip().lower()
    return raw or str(getattr(settings, key, "") or "").strip().lower()


def meetings_logins_now() -> frozenset[str]:
    """Yig'ilishlar bo'limi ochiq loginlar - `.env` dan JONLI, kichik harfda."""
    raw = _env_token("meetings_logins", "") or settings.meetings_logins
    return frozenset(part.strip().lower() for part in re.split(r"[,\s;]+", raw or "") if part.strip())


def telegram_groups_now() -> frozenset[int]:
    """Venera ishlaydigan guruhlar (`telegram_groups`) - `.env` dan JONLI.

    Noto'g'ri yozilgan qism (son emas) tashlab ketiladi: bitta xato butun
    ro'yxatni o'chirib qo'ymasin.
    """
    raw = _env_token("telegram_groups", settings.telegram_groups)
    ids: set[int] = set()
    for part in re.split(r"[\s,;]+", raw or ""):
        try:
            ids.add(int(part))
        except ValueError:
            continue
    return frozenset(ids)


#: `tokens` xaritasidagi nomlar -> `.env` kalitlari. Yuqoridagi xizmat
#: tanimagan nomni E'TIBORSIZ qoldiradi, ya'ni yangi platforma qo'shilsa
#: shu yerga bitta qator yetadi.
_PLATFORMS = (("hrm", "hrm_token"), ("crm", "crm_token"))


def platform_tokens() -> dict[str, str]:
    """Odamning BARCHA platforma token'lari - `tokens` xaritasi uchun.

    Hujjat talabi: "Send every token the user has. The assistant decides
    per question which platform it needs." Ya'ni tanlashga urinmaymiz -
    savol HRM haqidami yoki CRM haqidami, buni yuqoridagi xizmat o'zi
    hal qiladi.

    BO'SH token YUBORILMAYDI. Bo'sh satr yuborilsa xizmat uni "sessiya
    bor, lekin yaroqsiz" deb qabul qilishi mumkin edi; yo'qligi esa
    aniq `auth_missing` beradi va foydalanuvchi tushunarli xabar oladi
    ("CRM tizimiga kiring").
    """
    return {name: token for name, key in _PLATFORMS if (token := _env_token(key))}


def _read_env_value(path: Path, key: str) -> str | None:
    """`.env` dan bitta kalitni o'qiydi. Butun faylni qayta tahlil
    QILMAYDI: bizga faqat shu kalit kerak, qolganini o'zgartirish esa
    ishlab turgan sozlamani kutilmaganda almashtirib qo'yardi.

    `pydantic-settings` kabi harf registriga qaramaydi, va qiymat
    atrofidagi qo'shtirnoqni oladi.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    wanted = key.lower()
    found: str | None = None
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        if name.strip().lower() != wanted:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        # Oxirgi mos qator ustun - `.env` da takroriy kalit bo'lsa muhit
        # o'zgaruvchilari ham shunday ishlaydi.
        found = value
    return found
