// Venera Telegram Mini App.
//
// Sahifa HTML dan AJRATILGAN: `/tg/` location'i `script-src 'self'
// https://telegram.org` ostida ishlaydi, ya'ni `<script>` ichiga yozilgan kod
// HECH QACHON ishga tushmaydi.
//
// BU FAYL VEB ILOVANING NUSXASI, QAYTA IXTIROSI EMAS. `apps/web/src/api/*` va
// `components/VoicePanel.vue` jonli mashinalarda sinalgan va ularning
// izohlarida qimmat o'lchovlar yozilgan (qaysi ostona, nega aynan shu
// millisekund). Bu yerda o'sha yechimlar vanilla JS ga ko'chirilgan; bironta
// sonni "chiroyliroq" qilib o'zgartirmang - ular tanlanmagan, O'LCHANGAN.
//
// UYG'OTISH SO'ZI ("Salom Venera") BU YERDA ATAYLAB YO'Q. Veb ilovada u bor,
// lekin Mini App'da savol har doim doirani bosishdan boshlanadi - ya'ni
// mikrofonni doim ochiq tutishning sababi yo'q.
//
// ORIGIN BITTA: sahifa `https://llm.brb-tech.uz/tg/` da, API esa o'sha
// originning `/api/` yo'lida. Shuning uchun `connect-src 'self'` yetadi va
// CORS umuman yo'q.
(() => {
  'use strict';

  // =========================================================================
  // 0. Telegram qobig'i - MAJBURIY EMAS
  // =========================================================================
  // `window.Telegram` bo'lmasa (oddiy brauzer, yoki SDK yuklanmadi) sahifa
  // to'liq ishlaydi. Telegram faqat ko'rinish va tebranishni yaxshilaydi.
  const tg = (window.Telegram && window.Telegram.WebApp) ? window.Telegram.WebApp : null;
  if (tg) {
    try {
      tg.ready();
      tg.expand();
      tg.setHeaderColor('#050409');
      tg.setBackgroundColor('#050409');
      // Doirani bosish ilovani pastga surib yubormasin.
      if (tg.disableVerticalSwipes) tg.disableVerticalSwipes();
    } catch (e) { /* eski klientlar */ }
  }
  const haptic = (kind) => {
    try { if (tg && tg.HapticFeedback) tg.HapticFeedback.impactOccurred(kind); } catch (e) {}
  };

  // =========================================================================
  // 1. HTTP qatlami - `apps/web/src/api/http.ts` ning nusxasi
  // =========================================================================

  // Veb ilova bilan BIR XIL kalit, ataylab: ikkala sahifa ham
  // `llm.brb-tech.uz` originida, ya'ni storage bo'linmagan brauzerda sessiya
  // umumiy bo'ladi - bir marta kirgan odam ikkinchi marta kirmaydi.
  //
  // TELEGRAM CLOUDSTORAGE ATAYLAB ISHLATILMAYDI. U qulayroq (qurilmalar
  // orasida saqlanadi), lekin bank ichki tizimining sessiya tokenini
  // Telegram serveriga yozib qo'yardi. Token shu qurilmada qoladi.
  const TOKEN_KEY = 'venera_token';
  const CHAT_KEY = 'venera_tg_chat';
  const VOICE_KEY = 'venera_tg_voice';

  // localStorage maxfiy rejimda va ba'zi WebView'larda OTADI (throw), shuning
  // uchun har o'qish-yozish qo'riqlangan.
  function store(key) {
    try { return localStorage.getItem(key); } catch (e) { return null; }
  }
  function keep(key, value) {
    try { localStorage.setItem(key, value); } catch (e) { /* storage yo'q */ }
  }
  function drop(key) {
    try { localStorage.removeItem(key); } catch (e) { /* storage yo'q */ }
  }

  const getToken = () => store(TOKEN_KEY);
  const setToken = (t) => keep(TOKEN_KEY, t);
  const clearToken = () => drop(TOKEN_KEY);

  class ApiError extends Error {
    constructor(message, body) {
      super(message);
      this.name = 'ApiError';
      this.body = body;
      this.status = body && body.status;
      this.code = body && body.error;
    }
  }

  /** Xato javobini o'qiydi. Muvaffaqiyat yo'li audio yoki NDJSON bo'lsa ham
   *  XATO yo'li HAR DOIM JSON envelopi - `core/errors.py` shuni kafolatlaydi. */
  async function apiError(response) {
    let body;
    try { body = await response.json(); } catch (e) { /* nginx 502/504 sahifasida envelop yo'q */ }
    return new ApiError((body && body.message) || `So'rov bajarilmadi (${response.status})`, body);
  }

  function authHeaders(extra) {
    const token = getToken();
    const headers = Object.assign({ Accept: 'application/json', 'Accept-Language': 'uz' }, extra || {});
    if (token) headers.Authorization = `Bearer ${token}`;
    return headers;
  }

  async function apiFetch(path, options) {
    const opts = options || {};
    const headers = authHeaders(opts.headers);
    // FormData o'z chegarasini (boundary) o'zi qo'yadi - Content-Type ni
    // qo'lda yozsak chegara yo'qoladi va server tanani o'qiy olmaydi.
    if (opts.body && !(opts.body instanceof FormData)) {
      headers['Content-Type'] = 'application/json; charset=utf-8';
    }
    const response = await fetch(path, Object.assign({}, opts, { headers }));
    if (!response.ok) throw await apiError(response);
    const type = response.headers.get('content-type') || '';
    if (!type.includes('application/json')) return undefined;   // logout tanasiz qaytishi mumkin
    return response.json();
  }

  // =========================================================================
  // 2. WAV - `apps/web/src/api/wav.ts` ning nusxasi
  // =========================================================================
  // NEGA KERAK: STT router'ining o'zbek backend'i .wav/.ogg/.opus/.mp3/.flac
  // ni oladi va WebM ni UMUMAN dekodlay olmaydi, Chrome esa faqat WebM yoza
  // oladi. O'girish brauzerda bo'ladi - serverda transkoder yo'q.

  const TARGET_RATE = 16000;

  function encodeWavBytes(samples, sampleRate) {
    const dataSize = samples.length * 2;
    const buffer = new ArrayBuffer(44 + dataSize);
    const view = new DataView(buffer);
    const ascii = (at, text) => {
      for (let i = 0; i < text.length; i++) view.setUint8(at + i, text.charCodeAt(i));
    };
    ascii(0, 'RIFF');
    view.setUint32(4, 36 + dataSize, true);
    ascii(8, 'WAVE');
    ascii(12, 'fmt ');
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);            // PCM
    view.setUint16(22, 1, true);            // mono
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    ascii(36, 'data');
    view.setUint32(40, dataSize, true);
    let at = 44;
    for (let i = 0; i < samples.length; i++, at += 2) {
      // Dekodlangan audio [-1,1] dan bir oz chiqib ketishi mumkin.
      const s = Math.max(-1, Math.min(1, samples[i]));
      view.setInt16(at, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    }
    return new Uint8Array(buffer);
  }

  const AudioCtor = window.AudioContext || window.webkitAudioContext;

  /** Har qanday AudioBuffer ni mono 16 kHz ga chiqaradi. Qayta namunalashni
   *  OfflineAudioContext ning O'Z filtri bajaradi - qo'lda yozilgan
   *  interpolyatsiyadan ancha yaxshi. */
  async function renderTo16k(buffer, offline) {
    const frames = Math.max(1, Math.ceil(buffer.duration * TARGET_RATE));
    const ctx = offline || new OfflineAudioContext(1, frames, TARGET_RATE);
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(ctx.destination);
    source.start(0);
    const rendered = await ctx.startRendering();
    return rendered.getChannelData(0);
  }

  async function toWav16k(blob) {
    if (!AudioCtor) throw new Error('AudioContext yo\'q');
    const ctx = new AudioCtor();
    let decoded;
    try {
      decoded = await ctx.decodeAudioData(await blob.arrayBuffer());
    } finally {
      try { ctx.close(); } catch (e) {}
    }
    return new Blob([encodeWavBytes(await renderTo16k(decoded), TARGET_RATE)], { type: 'audio/wav' });
  }

  // =========================================================================
  // 3. API: auth
  // =========================================================================

  const api = {
    login: (email, password) =>
      apiFetch('/api/v1/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }),
    me: () => apiFetch('/api/v1/auth/me'),
    logout: () => apiFetch('/api/v1/auth/logout', { method: 'POST' }),
    // Server hozircha 501 qaytaradi (`app/api/v1/auth.py`). Chaqiruv ATAYLAB
    // bor: serverda yoqilganda bu yerda o'zgartirish kerak bo'lmaydi, va
    // hozir foydalanuvchi serverning o'z xabarini ko'radi ("Ro'yxatdan o'tish
    // hozircha yopiq...") - jim tugmadan aniqroq.
    signup: (data) =>
      apiFetch('/api/v1/auth/signup', { method: 'POST', body: JSON.stringify(data) }),
    changePassword: (currentPassword, newPassword) =>
      apiFetch('/api/v1/auth/change-password', {
        method: 'POST',
        body: JSON.stringify({ currentPassword, newPassword }),
      }),
  };

  // =========================================================================
  // 4. API: STT
  // =========================================================================

  /** Mikrofon XAVFSIZ KONTEKST talab qiladi: HTTPS yoki localhost. LAN
   *  manzilida (`http://10.10.50.8:5173`) `navigator.mediaDevices` shunchaki
   *  `undefined` bo'ladi - so'rov ham, xato ham yo'q. Shuning uchun buni
   *  OLDIN tekshiramiz, aks holda nosozlik bizning kod xatosiga o'xshaydi. */
  function micAvailable() {
    return !!(navigator.mediaDevices &&
      typeof navigator.mediaDevices.getUserMedia === 'function' &&
      window.isSecureContext);
  }

  /** Sahifaning Permissions-Policy sarlavhasi mikrofonni taqiqlaganmi.
   *  Bunda getUserMedia so'rovsiz NotAllowedError beradi va brauzerdagi
   *  hech qanday sozlama yordam bermaydi - tuzatish faqat serverda. */
  function micBlockedByPolicy() {
    const policy = document.permissionsPolicy || document.featurePolicy;
    if (!policy) return false;
    try { return !policy.allowsFeature('microphone'); } catch (e) { return false; }
  }

  const sleep = (ms, signal) => new Promise((resolve, reject) => {
    const id = setTimeout(resolve, ms);
    if (signal) signal.addEventListener('abort', () => {
      clearTimeout(id);
      reject(new DOMException('aborted', 'AbortError'));
    }, { once: true });
  });

  async function transcribe(audio, signal) {
    // HAR DOIM WAV yuboriladi: uz backend WebM ni kengaytmasi bo'yicha rad
    // etadi va dekodlay olmaydi. Xom blob'ga faqat brauzerning o'zi yozgan
    // narsasini dekodlay olmasa qaytamiz.
    // ZAXIRA YO'L ATAYLAB YO'Q. Veb ilova brauzer o'z yozuvini dekodlay
    // olmasa xom blob'ni yuboradi, lekin uz backend uni (webm/mp4) baribir
    // rad etadi - ya'ni zaxira yo'l xatoni aniqdan noaniqqa aylantirardi.
    // Shuning uchun bu yerda aniq xabar beriladi.
    let upload;
    try {
      upload = await toWav16k(audio);
    } catch (e) {
      throw new ApiError('Yozuvni o\'girib bo\'lmadi - boshqa brauzerda sinab ko\'ring');
    }
    if (signal && signal.aborted) throw new DOMException('aborted', 'AbortError');

    // Tashqi (edge) nginx ~1 MiB da to'sadi va u HTML 413 qaytaradi, JSON
    // envelop EMAS. O'zimiz oldindan aytganimiz aniqroq.
    if (upload.size > MAX_UPLOAD_BYTES) {
      throw new ApiError('Yozuv juda uzun - qisqaroq savol bering');
    }

    // 503 = "navbat to'la, birozdan keyin" (router kontrakti). Bitta JIM
    // qayta urinish odatdagi holatni yopadi; foydalanuvchi xatoni faqat
    // shundan keyin ham band bo'lsa ko'radi.
    for (let attempt = 0; ; attempt++) {
      const form = new FormData();
      form.append('file', upload, 'speech.wav');
      form.append('language', 'uz');
      try {
        return await apiFetch('/api/v1/stt/transcribe', { method: 'POST', body: form, signal });
      } catch (err) {
        if (attempt === 0 && err instanceof ApiError && err.status === 503) {
          await sleep(1500, signal);
          continue;
        }
        throw err;
      }
    }
  }

  // =========================================================================
  // 5. API: TTS - `apps/web/src/api/tts.api.ts` ning nusxasi
  // =========================================================================
  // NEGA XOM PCM VA QO'LDA YOZILGAN PLEYER. Eng oddiy yo'l - `<audio src>` -
  // bu yerda ISHLAMAYDI: u GET yuboradi va Authorization sarlavhasini
  // ko'tara olmaydi, MediaSource esa PCM/WAV ni umuman qabul qilmaydi.
  // Serverdan `format=wav` so'rash ham yordam bermaydi: oqim ochilganda u
  // umumiy uzunlikni bilmaydi va sarlavhaga 0xFFFFFFFF yozadi, natijada
  // pleyerlar 74 soatlik fayl ko'rsatadi. Shuning uchun baytlar sarlavhasiz
  // 16-bit PCM bo'lib keladi va AudioContext'da qo'lda rejalashtiriladi -
  // unga aynan shu format kerak.

  const FALLBACK_RATE = 8000;   // server aytmasa; joriy o'rnatma 8 kHz (telefoniya)
  const LEAD_S = 0.12;          // birinchi bo'lakdan oldingi kichik zaxira

  /** Ijro uchun BITTA, umumiy AudioContext - va u foydalanuvchi bosgan paytda
   *  ochiladi.
   *
   *  NEGA UMUMIY. Telegram WebView ning avtomatik ijro siyosati brauzernikidan
   *  FARQ QILADI: jestdan tashqarida yaratilgan kontekst 'suspended' bo'lib
   *  qoladi va ovoz HECH QANDAY XATOSIZ, jimgina chiqmaydi. TTS javobi esa
   *  har doim tarmoq so'rovidan KEYIN keladi, ya'ni bosish stek'idan chiqib
   *  bo'lgan bo'ladi. Shuning uchun kontekst har bosishda "ochib" qo'yiladi va
   *  sessiya davomida yopilmaydi. */
  let playCtx = null;
  function audioContext() {
    if (!playCtx || playCtx.state === 'closed') playCtx = new AudioCtor();
    if (playCtx.state === 'suspended') playCtx.resume().catch(() => {});
    return playCtx;
  }
  document.addEventListener('pointerdown', () => { try { audioContext(); } catch (e) {} });

  function deferred() {
    let resolve, reject;
    const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
    return { promise, resolve, reject };
  }

  function rateOf(response) {
    const header = Number(response.headers.get('X-Venera-Sample-Rate'));
    if (Number.isFinite(header) && header > 0) return header;
    const fromType = /rate=(\d+)/.exec(response.headers.get('Content-Type') || '');
    return fromType ? Number(fromType[1]) : FALLBACK_RATE;
  }

  /**
   * Kelayotgan PCM ni AudioContext'da ketma-ket rejalashtiradi.
   *
   * Har bo'lak o'z AudioBuffer'iga aylanadi va MUTLAQ vaqtda boshlanadi
   * ("kelganda ijro et" emas): `start(when)` namuna aniqligida ishlaydi,
   * shuning uchun qo'shni bo'laklar chirt etmasdan ulanadi.
   */
  function playPcmStream(body, rate, signal, onLevel) {
    // Umumiy kontekst - yaratilmaydi ham, yopilmaydi ham (yuqoridagi izoh).
    const ctx = audioContext();

    const reader = body.getReader();
    const sources = new Set();
    let nextAt = 0;
    let stopped = false;
    let last = null;
    let odd = null;             // 16-bit namuna ikki bo'lak orasida qolsa, bitta bayt

    const doneGate = deferred();

    function stop() {
      if (stopped) return;
      stopped = true;
      try { reader.cancel(); } catch (e) {}
      for (const source of sources) {
        source.onended = null;
        try { source.stop(); } catch (e) {}
      }
      sources.clear();
      // ctx YOPILMAYDI: u umumiy va keyingi javob uchun ham kerak.
      if (onLevel) onLevel(0);
      doneGate.resolve();
    }
    if (signal) signal.addEventListener('abort', stop, { once: true });

    function schedule(pcm) {
      if (!pcm.length || stopped) return;
      const buffer = ctx.createBuffer(1, pcm.length, rate);
      const channel = buffer.getChannelData(0);
      let sum = 0;
      for (let i = 0; i < pcm.length; i++) {
        const v = pcm[i] / 32768;
        channel[i] = v;
        sum += v * v;
      }
      const source = ctx.createBufferSource();
      source.buffer = buffer;
      source.connect(ctx.destination);
      const at = Math.max(nextAt, ctx.currentTime + (nextAt === 0 ? LEAD_S : 0));
      source.start(at);
      nextAt = at + buffer.duration;
      sources.add(source);
      source.onended = () => sources.delete(source);
      last = source;
      // Doira ovoz bilan birga tebransin: bo'lakning o'rtacha quvvatini
      // ijro BOSHLANADIGAN paytga qo'yamiz, kelgan paytga emas.
      if (onLevel) {
        const rms = Math.sqrt(sum / pcm.length);
        const delay = Math.max(0, (at - ctx.currentTime) * 1000);
        setTimeout(() => { if (!stopped) onLevel(Math.min(1, rms * 4)); }, delay);
      }
    }

    (async () => {
      try {
        for (;;) {
          const step = await reader.read();
          if (step.done || stopped) break;
          const value = step.value;
          if (!value || !value.length) continue;

          // Ikki bo'lakka bo'linib qolgan namunani qayta ulaymiz. Toq baytni
          // tashlab yuborish keyingi HAMMA namunani bir baytga surib
          // yuborardi va oqimning qolgani shovqinga aylanardi.
          let bytes = value;
          if (odd) {
            const merged = new Uint8Array(odd.length + value.length);
            merged.set(odd, 0);
            merged.set(value, odd.length);
            bytes = merged;
            odd = null;
          }
          const usable = bytes.length - (bytes.length % 2);
          if (usable < bytes.length) odd = bytes.slice(usable);
          if (!usable) continue;

          // Nusxa, ko'rinish EMAS: `bytes` reader qayta ishlatadigan buferni
          // baham ko'rishi mumkin.
          schedule(new Int16Array(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + usable)));
        }
        if (stopped) return;
        if (!last) {                      // oqim bitta namunasiz tugadi
          if (onLevel) onLevel(0);
          doneGate.resolve();
          return;
        }
        last.onended = () => {
          if (onLevel) onLevel(0);
          doneGate.resolve();
        };
      } catch (err) {
        if (stopped) return;
        if (last) {
          // Bir qismi allaqachon ijro etilmoqda - odam qo'lidan hech narsa
          // kelmaydigan xato uchun gapni yarmida kesmaymiz.
          last.onended = () => {
            if (onLevel) onLevel(0);
            doneGate.resolve();
          };
        } else {
          if (onLevel) onLevel(0);
          doneGate.reject(err);
        }
      }
    })();

    return { done: doneGate.promise, stop };
  }

  /**
   * Matnni ovozga o'giradi va birinchi baytlar kelishi bilan ijro qiladi.
   *
   * Qaytishi javob SARLAVHALARI kelganda bo'ladi - bu ayni paytda serverdagi
   * har qanday xato allaqachon yuzaga chiqqan nuqta: TTS xizmati birinchi
   * bo'lakni sarlavhalarni yuborishdan OLDIN sintez qiladi.
   */
  async function speakStream(text, signal, onLevel) {
    const response = await fetch('/api/v1/tts/speak', {
      method: 'POST',
      signal,
      headers: authHeaders({ 'Content-Type': 'application/json; charset=utf-8', Accept: 'audio/L16, */*' }),
      body: JSON.stringify({ text, language: 'uz' }),
    });
    if (!response.ok) throw await apiError(response);
    const rate = rateOf(response);
    // ZAXIRA YO'L, iOS UCHUN. Eski WKWebView (Telegram iOS shu yerdan
    // yuradi) `fetch` da `response.body` ni bermaydi - oqim o'qish umuman
    // yo'q. Unda butun PCM ni bir marta olib, bir bo'lak qilib ijro etamiz:
    // birinchi baytning afzalligi yo'qoladi, lekin OVOZ CHIQADI.
    if (!response.body) {
      const bytes = new Uint8Array(await response.arrayBuffer());
      const usable = bytes.length - (bytes.length % 2);
      const once = new ReadableStream({
        start(controller) { controller.enqueue(bytes.subarray(0, usable)); controller.close(); },
      });
      return playPcmStream(once, rate, signal, onLevel);
    }
    return playPcmStream(response.body, rate, signal, onLevel);
  }

  //: O'qiladigan belgilar chegarasi. Backend ham shu qiymatda kesadi
  //: (`tts_max_chars`), lekin u SO'Z chegarasida kesadi, ya'ni gap yarmida
  //: to'xtaydi. Shuning uchun qisqartirishni o'zimiz, GAP chegarasida
  //: qilamiz - backenddagisi zaxira bo'lib qoladi.
  //:
  //: 600 EDI va bu javobni yarmida kesardi: mehnat ta'tili bo'yicha 6 bandli
  //: javob 1016 belgi bo'lib, ovoz 3-band oxirida to'xtab qolardi.
  //:
  //: 3000 jonli o'lchovga asoslangan: TTS serveri 5000 belgini ham qabul
  //: qiladi va birinchi bayt UZUNLIKDAN QAT'I NAZAR ~1.37 s da keladi, ya'ni
  //: uzun matn kechikish qo'shmaydi. Ovoz esa real vaqtdan ~4.7x tez
  //: yetkaziladi (3000 belgi = ~198 s ovoz, ~41 s oqim), shuning uchun ijro
  //: hech qachon oqimdan o'zib ketmaydi.
  //:
  //: SHUNING UCHUN BO'LAKLASH YO'Q. Avval bu yerda matn 560 belgilik
  //: bo'laklarga bo'linib ketma-ket yuborilardi; endi bitta so'rov ketadi -
  //: bo'laklash hech narsa tejamas, faqat har bo'lak uchun yangi navbat
  //: kutilardi va TTS slotlari behuda band bo'lardi.
  const SPEAK_LIMIT = 3000;

  /**
   * Javobning O'QILADIGAN qismi: audit izidan oldingi hammasi.
   *
   * Javob IKKI qismdan iborat bo'lib keladi - avval javobning O'ZI, keyin
   * "Tekshirilgan HRM ma'lumotlari:" va `[T1] hrm_search_employees - ... ->`
   * ko'rinishidagi iz. Iz EKRAN uchun kerak: bank muhitida xodim javob qaysi
   * so'rovdan chiqqanini ko'rishi shart. Lekin O'QILGANDA u javobdan bir
   * necha barobar uzun: jonli o'lchangan savolda javobning o'zi 87 belgi,
   * iz bilan birga 614 belgi.
   *
   * Ajratish NAQSH bo'yicha, matn bo'yicha EMAS: iz qatorlari `[T1]` kabi
   * marker bilan BOSHLANADI, javob ichidagi iqtibos esa gap OXIRIDA turadi
   * (`... kech qolmagan [T3].`). Izni tanishtirgan qator (`:` bilan tugaydi)
   * ham tashlanadi - uning MATNI yuqoridagi modelning tilidan kelib chiqadi
   * va o'zgarishi mumkin, shakli esa yo'q.
   */
  function answerBody(markdown) {
    const lines = markdown.split(/\r?\n/);
    let at = lines.findIndex((line) => /^\s*\[[A-Za-z]{1,4}[_-]?\d{1,6}\]\s/.test(line));
    if (at < 0) return markdown;
    while (at > 0 && (!lines[at - 1].trim() || lines[at - 1].trim().endsWith(':'))) at--;
    const body = lines.slice(0, at).join('\n').trim();
    // Hammasi iz bo'lib chiqdi (javobning o'zi yo'q): boricha o'qiymiz -
    // jim qolgandan ko'ra afzal.
    return body || markdown;
  }

  /**
   * Javob matnini O'QISHGA tayyorlaydi.
   *
   * Javob markdown bo'lib keladi: `**bo'lim:**`, `* ro'yxat`, `[T1]` iqtibos
   * markerlari, ba'zan jadval. O'qigichga shundayligicha berilsa, u
   * yulduzchani ham, `T1` ni ham gap deb o'qiydi - ya'ni javob eshitilmaydi,
   * "yulduzcha yulduzcha dasturlash bo'limi" eshitiladi.
   *
   * Ro'yxat va jadval qatorlari NUQTAGA aylanadi: aks holda hamma qator bitta
   * uzun gap bo'lib qolib, ovoz nafas olmay o'qiydi.
   */
  function forSpeech(markdown) {
    const text = answerBody(markdown)
      .replace(/```[\s\S]*?```/g, ' ')
      .replace(/`([^`]*)`/g, '$1')
      // Havola va rasm: ko'rinadigan matn qoladi, URL ketadi. Iqtibos
      // qoidalaridan OLDIN bo'lishi shart - aks holda `[matn](url)` ning
      // birinchi qismi marker deb o'chirilardi.
      .replace(/!?\[([^\]]*)\]\([^)]*\)/g, '$1')
      // Iqtibos markerlari: `[T1]`, `[HR_045]`, `[1]`, `[1, 2]`. Ular EKRAN
      // uchun - hujjatga havola, va o'qilganda faqat shovqin. Naqsh ATAYLAB
      // tor: `[eslatma]` kabi oddiy qavsli so'z matnning o'zi bo'lishi mumkin.
      .replace(/\[[A-Za-z]{1,4}[_-]?\d{1,6}\]/g, ' ')
      .replace(/\[\d{1,3}(?:\s*,\s*\d{1,3})*\]/g, ' ')
      // Qavs ichidagi dalil markerlari: `(e4)`, `(e1, e2)`. Ular hujjat
      // ichidagi parchaga ishora qiladi va `sources` kadrida UMUMAN yo'q,
      // ya'ni ekranda ham tushuntirilmaydi - o'qilganda esa "e to'rt" bo'lib
      // chiqadi. Naqsh harf+raqam TALAB qiladi: "(lavozimi)" va "(sentyabr)"
      // javobning o'z matni, "(21)" esa band raqami bo'lishi mumkin.
      .replace(/\((?:[A-Za-z]{1,2}\d{1,3})(?:\s*,\s*[A-Za-z]{1,2}\d{1,3})*\)/g, ' ')
      .replace(/^#{1,6}\s*/gm, '')
      // Jadval ajratgich qatori (`|---|---|`) - butunlay ketadi.
      .replace(/^[ \t]*\|?[\s:|-]{3,}\|?[ \t]*$/gm, ' ')
      // Ro'yxat belgisi -> gap chegarasi. `*` ni olib tashlashdan OLDIN.
      .replace(/^[ \t]*[-*+•][ \t]+/gm, '. ')
      .replace(/\|/g, ', ')
      .replace(/\*\*|__|~~/g, '')
      .replace(/\*/g, '')
      .replace(/\r?\n+/g, '. ')
      .replace(/\s+/g, ' ')
      // Yuqoridagi almashtirishlardan qolgan bo'shliq va takror tinish
      // belgilari: "kechikdi [T1]:" -> "kechikdi :" -> "kechikdi:".
      .replace(/\s+([,.;:!?])/g, '$1')
      // Ro'yxat va jadval qatorlaridan qolgan qo'shaloq tinish belgilari.
      // TARTIB MUHIM: avval takroriy nuqta bittaga tushadi, keyingina
      // ":." / ",." juftliklari tuzatiladi. Teskari tartibda ":.." ning
      // faqat yarmi tuzalib, ":." qolib ketardi.
      .replace(/(?:\.\s*){2,}/g, '. ')
      .replace(/,\s*\./g, '.')           // "3," + qator oxiri -> "3."
      .replace(/([;:])\s*\./g, '$1')     // "kechikdi:" + ro'yxat -> "kechikdi:"
      .replace(/([.:;])\s*,\s*/g, '$1 ') // gap boshidagi ortiqcha vergul
      .replace(/^[\s.,;:]+/, '')
      .replace(/[\s,;:|-]+$/, '')
      .trim();

    if (text.length <= SPEAK_LIMIT) return { text: text, shortened: false };
    const cut = text.slice(0, SPEAK_LIMIT);
    const stop = Math.max(cut.lastIndexOf('. '), cut.lastIndexOf('! '), cut.lastIndexOf('? '));
    // Gap chegarasi juda boshida bo'lsa ishlatilmaydi: javobning uchdan biri
    // o'qilib to'xtagandan ko'ra so'z chegarasida kesish tushunarliroq.
    if (stop > SPEAK_LIMIT / 2) return { text: cut.slice(0, stop + 1), shortened: true };
    const space = cut.lastIndexOf(' ');
    return { text: (space > 0 ? cut.slice(0, space) : cut).replace(/[\s,;:-]+$/, ''), shortened: true };
  }

  // =========================================================================
  // 6. API: chat - `apps/web/src/api/chat.api.ts` ning nusxasi
  // =========================================================================
  // NEGA EventSource EMAS. U faqat GET va Authorization sarlavhasini yubora
  // olmaydi, ya'ni savol ham, token ham manzil qatoriga tushardi - proksi
  // jurnallariga va brauzer tarixiga. fetch() + ReadableStream o'sha oqimni
  // POST bilan o'qiydi va token o'z joyida - sarlavhada - qoladi.

  /** Suhbat kaliti. Bir xil kalitli savollar bir-birini ESLAYDI, ya'ni
   *  "va o'tgan oyda?" degan savol ishlaydi. `user_id` ni server token'dan
   *  qo'yadi, shuning uchun bu kalit boshqa odamning suhbatiga tushirmaydi. */
  function chatId() {
    let id = store(CHAT_KEY);
    if (!id) {
      id = (window.crypto && crypto.randomUUID)
        ? crypto.randomUUID()
        : 'tg-' + Math.random().toString(36).slice(2) + Date.now().toString(36);
      keep(CHAT_KEY, id);
    }
    return id;
  }

  /**
   * Savol yuboradi va har NDJSON qatori uchun `onFrame` ni chaqiradi.
   *
   * `error` KADRI uchun OTMAYDI: u tugagan so'rovning odatiy natijasi
   * (assistant "javob berolmayman" dedi), va uni qanday ko'rsatishni
   * chaqiruvchi hal qiladi. Faqat transport/HTTP xatosi otiladi.
   */
  /** Savol chegarasi serverda: bo'sh yoki 2000 belgidan uzun bo'lsa 400
   *  "Savol qabul qilinmadi" - va bu ODDIY javob, oqim umuman ochilmaydi.
   *  Oldindan kesish aniqroq xabar beradi. */
  const MAX_QUESTION_CHARS = 2000;

  async function streamAsk(question, onFrame, signal) {
    const text = (question || '').trim().slice(0, MAX_QUESTION_CHARS);
    if (!text) throw new ApiError('Savol bo\'sh');
    const response = await fetch('/api/v1/chat/stream', {
      method: 'POST',
      signal,
      headers: authHeaders({ 'Content-Type': 'application/json; charset=utf-8', Accept: 'application/x-ndjson' }),
      body: JSON.stringify({ question: text, chatId: chatId() }),
    });
    if (!response.ok) throw await apiError(response);

    const decoder = new TextDecoder();
    let buffer = '';
    const emit = (line) => {
      const text = line.trim();
      if (!text) return;
      let frame;
      try { frame = JSON.parse(text); } catch (e) { return; }   // buzilgan kadrni tashlash butun javobni buzishdan yaxshi
      if (frame && typeof frame.type === 'string') onFrame(frame);
    };

    // ZAXIRA YO'L, iOS UCHUN: eski WKWebView `response.body` bermaydi. Unda
    // javob to'liq kelganda bir yo'la o'qiymiz - javob "yozilayotgandek"
    // ko'rinmaydi, lekin KELADI.
    if (!response.body) {
      const whole = await response.text();
      for (const line of whole.split('\n')) emit(line);
      return;
    }

    const reader = response.body.getReader();
    try {
      for (;;) {
        const step = await reader.read();
        // `stream: true` MUHIM: ko'p baytli harf ikki bo'lakka bo'linishi
        // mumkin, va har bo'lakni alohida dekodlash uni ikkiga bo'lardi.
        if (step.value) buffer += decoder.decode(step.value, { stream: true });
        let cut = buffer.indexOf('\n');
        while (cut >= 0) {
          emit(buffer.slice(0, cut));
          buffer = buffer.slice(cut + 1);
          cut = buffer.indexOf('\n');
        }
        if (step.done) break;
      }
      emit(buffer + decoder.decode());    // oxirgi kadr `\n` siz kelishi mumkin
    } finally {
      // Javob o'rtasida to'xtatilsa: ulanishni AJRATAMIZ, aks holda u
      // assistant navbatida joyni band qilib turadi.
      try { reader.cancel(); } catch (e) {}
    }
  }

  // `/chat/ask` ATAYLAB ISHLATILMAYDI. U quvur SKELETI: `services/pipeline.py`
  // dagi `_ROUTES` bo'sh, ya'ni u HR Assistant'ga umuman bormaydi va HAR
  // QANDAY savolga bir xil "Venera hozircha sozlanmoqda..." matnini qaytaradi.
  // Uni zaxira yo'l qilib qo'yish foydalanuvchiga javob berilgandek ko'rsatib,
  // aslida hech narsa aytmaslik bo'lardi. `/stream` 501 bersa, serverning
  // o'z xabari ("Savol-javob xizmati hali sozlanmagan") ko'rsatiladi.

  // =========================================================================
  // 7. DOM
  // =========================================================================
  const $ = (id) => document.getElementById(id);
  const root = document.documentElement.style;

  const bootView = $('bootView'), authView = $('authView'), appView = $('appView');
  const bootText = $('bootText');
  const loginForm = $('loginForm'), emailInput = $('email'), passwordInput = $('password'),
        loginBtn = $('loginBtn'), authError = $('authError'),
        signupLink = $('signupLink'), forgotLink = $('forgotLink');
  const orbWrap = $('orbWrap'), ripple = $('ripple'), logEmpty = $('logEmpty'),
        statusEl = $('status'), statusText = $('statusText'), note = $('note'), log = $('log'),
        modePill = $('modePill'), voiceToggle = $('voiceToggle'),
        confirmRow = $('confirmRow'), confirmYes = $('confirmYes'), confirmNo = $('confirmNo');
  const menuBtn = $('menuBtn'), menuSheet = $('menuSheet'), menuClose = $('menuClose'),
        whoName = $('whoName'), whoMeta = $('whoMeta'), logoutBtn = $('logoutBtn'),
        pwOpen = $('pwOpen'), pwBox = $('pwBox'), curPw = $('curPw'), newPw = $('newPw'),
        pwSubmit = $('pwSubmit'), pwNote = $('pwNote');

  function show(view) {
    for (const v of [bootView, authView, appView]) v.hidden = v !== view;
  }
  function setNote(text, kind) {
    note.textContent = text || '';
    note.className = 'note' + (kind ? ' ' + kind : '');
    note.hidden = !text;
  }
  function setPill(text, kind) {
    modePill.textContent = text;
    modePill.className = 'pill' + (kind ? ' ' + kind : '');
  }

  function addMsg(who, text) {
    const el = document.createElement('div');
    el.className = 'msg ' + who;
    if (who !== 'system') {
      const w = document.createElement('span');
      w.className = 'who';
      w.textContent = who === 'you' ? 'Siz' : 'Venera';
      el.appendChild(w);
    }
    el.appendChild(document.createTextNode(text));
    log.appendChild(el);
    logEmpty.hidden = true;
    log.scrollTop = log.scrollHeight;
    while (log.children.length > 20) log.removeChild(log.firstChild);
    return el;
  }

  /** Xato matni. Proksi yo'lidagi xatolarda (nginx 413/504) envelop bo'lmaydi,
   *  shuning uchun status bo'yicha xaritalash - foydalanuvchi hech qachon
   *  "So'rov bajarilmadi (504)" ko'rmasin. */
  function errorText(err) {
    if (err instanceof ApiError) {
      switch (err.status) {
        case 401: return 'Sessiya tugadi, qayta kiring';
        case 413: return 'Yozuv juda katta - qisqaroq gapiring';
        case 415: return 'Bu audio formati qabul qilinmadi';
        case 503: return 'Xizmat band, biroz kutib qayta urinib ko\'ring';
        case 504: return 'Juda uzoq cho\'zildi - qisqaroq gapirib ko\'ring';
      }
      return err.message;
    }
    if (err && err.message) return err.message;
    return 'Tarmoq xatosi';
  }

  // =========================================================================
  // 8. Doira - daraja va tebranish
  // =========================================================================
  let level = 0, smooth = 0, target = 0;

  /** Taymer, requestAnimationFrame EMAS: rAF sahifa ko'rinmay qolganda yoki
   *  fonga o'tganda TO'XTAYDI, va bu holat mashinasini yarmida muzlatardi.
   *  30 Hz bu yerda yetarli. */
  setInterval(() => {
    const now = performance.now();
    // Tez ko'tarilish, sekin tushish - "tirik" tuyg'uni aynan shu beradi.
    smooth = target > smooth ? smooth + (target - smooth) * 0.55 : smooth + (target - smooth) * 0.12;
    level = smooth;
    const w = level * 9;
    root.setProperty('--lvl', level.toFixed(3));
    root.setProperty('--r1', (50 + Math.sin(now / 61) * w) + '%');
    root.setProperty('--r2', (50 + Math.cos(now / 47) * w) + '%');
    root.setProperty('--r3', (50 + Math.sin(now / 53 + 2) * w) + '%');
    root.setProperty('--r4', (50 + Math.cos(now / 71 + 1) * w) + '%');
    root.setProperty('--jx', (Math.sin(now / 23) * level * 5).toFixed(2) + 'px');
    root.setProperty('--jy', (Math.cos(now / 29) * level * 5).toFixed(2) + 'px');
  }, 33);

  // =========================================================================
  // 9. Holat mashinasi
  // =========================================================================
  // idle -> listening -> transcribing -> thinking -> speaking -> idle
  //                                  \-> confirm -> thinking
  let state = 'idle';
  let user = null;

  function setState(next) {
    state = next;
    orbWrap.className = 'orb-wrap ' + next;
    statusEl.classList.toggle('live', next === 'speaking' || next === 'listening');
    confirmRow.hidden = next !== 'confirm';
    // Matn BITTA qator: avval sarlavha + tavsif + status uch qator joy olib,
    // suhbatdan o'g'irlardi - holat esa yuqoridagi pill'da ham ko'rinadi.
    switch (next) {
      case 'idle':
        statusText.textContent = 'Gapirish uchun bosing';
        setPill('Tayyor');
        target = 0;
        break;
      case 'listening':
        statusText.textContent = 'Tinglayapman — to\'xtaganingizda javob beraman';
        setPill('Yozilmoqda', 'live');
        break;
      case 'transcribing':
        statusText.textContent = 'Tanib olinmoqda…';
        setPill('STT');
        target = 0;
        break;
      case 'thinking':
        statusText.textContent = 'O\'ylayapman — bosish bekor qiladi';
        setPill('Javob');
        target = 0;
        break;
      case 'speaking':
        statusText.textContent = 'Ovoz chiqmoqda — bosish to\'xtatadi';
        setPill('Ovoz', 'live');
        break;
      case 'confirm':
        statusText.textContent = 'Tasdiqlang yoki qayta ayting';
        setPill('Tasdiq', 'warn');
        target = 0;
        break;
    }
  }

  // =========================================================================
  // 10. Yozuv (MediaRecorder) va turn
  // =========================================================================
  const SPEECH_RMS = 0.045;     // shundan yuqorisi - nutq
  const SILENCE_MS = 1400;      // nutqdan keyingi shu qadar sukunat turnni tugatadi

  /** Yozuvning qattiq chegarasi. Veb ilovada 30 s, BU YERDA 25 s - va bu
   *  farq ataylab.
   *
   *  O'LCHANGAN: llm.brb-tech.uz oldidagi TASHQI (edge) nginx yuklash hajmini
   *  ~1 MiB da to'sadi (1040000 bayt o'tdi, 1100000 bayt 413 oldi), holbuki
   *  konteynerdagi nginx 12 MB beradi. Telegram HAR DOIM ommaviy manzildan
   *  yuradi, ya'ni /tg/ uchun amaldagi shift 12 MB EMAS, ~1 MiB.
   *  16 kHz mono 16-bit WAV = 32000 bayt/soniya, ya'ni 30 s = ~960 KB va
   *  multipart qo'shimchasi bilan chegaraga juda yaqin. 25 s = ~800 KB. */
  const MAX_TURN_MS = 25000;
  /** Yuborishdan oldingi qattiq tekshiruv - yuqoridagi hisob xato bo'lsa ham
   *  foydalanuvchi HTML 413 o'rniga tushunarli xabar ko'rsin. */
  const MAX_UPLOAD_BYTES = 1000000;

  /**
   * BITTA, UMUMIY mikrofon oqimi - va u har turnda YOPILMAYDI.
   *
   * Bu veb ilovadan ATAYLAB farq qiladi (`VoicePanel.vue` har turndan keyin
   * `track.stop()` qiladi). Sabab Android Telegram WebView dagi ma'lum
   * nuqson: uning `WebChromeClient` ruxsat boshqaruvi tufayli BIR SESSIYA
   * ichida har `getUserMedia` chaqiruvida ruxsat oynasi QAYTA chiqadi
   * (DrKLO/Telegram#1947). Ya'ni "bosib gapirish" naqshida odam har savol
   * oldidan dialog ko'rardi - bu ilovani ishlatib bo'lmas holga keltiradi.
   *
   * Narxi: oqim tirik turganda brauzer yozuv indikatorini yoqiq tutadi.
   * Shuning uchun sahifa ko'rinmay qolganda va chiqishda oqim BO'SHATILADI -
   * mikrofon hech qachon fonda ochiq qolmaydi.
   */
  let micStream = null;
  async function getMic() {
    if (micStream && micStream.getTracks().some((t) => t.readyState === 'live')) return micStream;
    micStream = await navigator.mediaDevices.getUserMedia({
      // VoicePanel.vue dagi bilan AYNAN BIR XIL va shunday qolsin. Bu
      // qatordan chekinishlar sinab ko'rilgan va jonli yozuvlarga qarab
      // o'lchangan: brauzer ishlovini o'chirish yozuv buzilishini
      // yo'qotmadi, avtomatik kuchaytirishni o'chirish esa tinchroq
      // aytilgan so'zni ko'mib yubordi.
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    return micStream;
  }
  function releaseMic() {
    if (!micStream) return;
    micStream.getTracks().forEach((t) => t.stop());
    micStream = null;
  }

  let recorder = null, meterCtx = null, analyser = null, meterBuf = null;
  let chunks = [], speechSeen = false, silenceSince = 0, turnId = 0;
  let meterTimer = 0, turnTimer = 0;
  let aborter = null, speechAborter = null, stopSpeech = null;
  let pendingQuestion = '';

  /** Brauzer haqiqatan yoza oladigan konteynerni tanlaydi. Safari'da (ya'ni
   *  iOS Telegram WebView'ida) webm YO'Q - u yerda mp4 tanlanadi. */
  function pickMime() {
    const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4'];
    for (const type of candidates) {
      if (typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported(type)) return type;
    }
    return '';
  }

  function teardown() {
    clearInterval(meterTimer); meterTimer = 0;
    clearTimeout(turnTimer); turnTimer = 0;
    if (recorder) { recorder.ondataavailable = null; recorder.onstop = null; recorder = null; }
    if (analyser) analyser = null;
    if (meterCtx) { if (meterCtx.state !== 'closed') try { meterCtx.close(); } catch (e) {} meterCtx = null; }
    // Mikrofon oqimi ATAYLAB to'xtatilmaydi - yuqoridagi `getMic` izohiga
    // qarang. Uni `releaseMic()` bo'shatadi: sahifa ko'rinmay qolganda va
    // chiqishda.
    target = 0;
  }

  function fail(message, hint) {
    teardown();
    stopSpeaking();
    setState('idle');
    setNote(hint ? message + ' — ' + hint : message, 'err');
  }

  function meter() {
    meterBuf = new Float32Array(analyser.fftSize);
    meterTimer = setInterval(() => {
      if (!analyser) return;
      analyser.getFloatTimeDomainData(meterBuf);
      let sum = 0;
      for (let i = 0; i < meterBuf.length; i++) sum += meterBuf[i] * meterBuf[i];
      const rms = Math.sqrt(sum / meterBuf.length);
      target = Math.max(Math.min(rms * 6, 1), target * 0.9);
      if (state !== 'listening') return;
      const now = performance.now();
      if (rms > SPEECH_RMS) {
        speechSeen = true;
        silenceSince = now;
      } else if (speechSeen && now - silenceSince > SILENCE_MS) {
        stopListening();
      }
    }, 33);
  }

  async function startListening() {
    if (state !== 'idle' && state !== 'confirm') return;
    if (!micAvailable()) {
      fail('Mikrofon uchun HTTPS kerak', 'sahifani https manzilda oching');
      return;
    }
    setNote('');
    chunks = [];
    speechSeen = false;
    silenceSince = performance.now();
    clearTimeout(turnTimer);
    if (aborter) aborter.abort();
    aborter = new AbortController();
    const turn = ++turnId;

    let stream;
    try {
      stream = await getMic();
    } catch (err) {
      const name = err && err.name;
      if (name === 'NotAllowedError' || name === 'SecurityError') {
        // "Foydalanuvchi Bloklash bosdi" va "server sarlavhasi taqiqlaydi"
        // uchun bir xil nom keladi - lekin ikkinchisida so'rov ham chiqmaydi
        // va brauzerdan tuzatib bo'lmaydi.
        if (micBlockedByPolicy()) fail('Mikrofon server siyosati bilan taqiqlangan', 'IT xodimiga ayting');
        else fail('Mikrofonga ruxsat berilmadi', 'Telegram sozlamalarida ruxsat bering');
      } else if (name === 'NotFoundError' || name === 'OverconstrainedError') {
        fail('Mikrofon topilmadi');
      } else {
        fail('Mikrofon ochilmadi');
      }
      return;
    }

    try {
      meterCtx = new AudioCtor();
      analyser = meterCtx.createAnalyser();
      analyser.fftSize = 1024;
      meterCtx.createMediaStreamSource(stream).connect(analyser);

      const mimeType = pickMime();
      recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      recorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
      recorder.onstop = () => { handleRecorded(turn); };
      recorder.start();

      ripple.classList.remove('go'); void ripple.offsetWidth; ripple.classList.add('go');
      haptic('light');
      setState('listening');
      meter();
      // Turn raqami bilan qo'riqlangan: oldingi turndan qolgan taymer
      // keyingisini kesib qo'ymasin.
      turnTimer = setTimeout(() => {
        if (turn === turnId && state === 'listening') stopListening();
      }, MAX_TURN_MS);
    } catch (e) {
      fail('Yozuv boshlanmadi');
      }
  }

  function stopListening() {
    if (state !== 'listening' || !recorder) return;
    setState('transcribing');
    clearInterval(meterTimer); meterTimer = 0;
    clearTimeout(turnTimer);
    haptic('medium');
    try { recorder.stop(); } catch (e) { fail('Yozuv to\'xtamadi'); }
  }

  async function handleRecorded(turn) {
    const type = (recorder && recorder.mimeType) || 'audio/webm';
    const blob = new Blob(chunks, { type });
    chunks = [];
    teardown();

    // Butun turn davomida ostonadan oshgan narsa bo'lmadi (30 s taymer jim
    // xonada ishladi): YUBORMAYMIZ. uz backend'da ishonch bayrog'i yo'q va u
    // xona shovqinidan ham bemalol "so'z" eshitadi, keyin o'sha so'z savol
    // bo'lib chatga ketardi.
    if (!speechSeen || blob.size < 1200) {
      fail('Ovoz eshitilmadi');
      return;
    }

    try {
      const result = await transcribe(blob, aborter ? aborter.signal : undefined);
      if (turn !== turnId) return;
      const text = (result.text || '').trim();
      if (!text) { fail('Ovoz eshitilmadi'); return; }

      addMsg('you', text);
      if (result.truncated) setNote('Yozuv chegaradan uzun bo\'ldi, oxiri kesildi', 'warn');

      // Router hujjati: ishonchi past transkriptda so'z xatosi ~60-70%.
      // Avtomatik harakat QILMAYMIZ - ko'rsatamiz va odam hal qiladi.
      if (result.lowConfidence) {
        pendingQuestion = text;
        setNote('Tanib olishga ishonch past: "' + text + '"', 'warn');
        setState('confirm');
        return;
      }
      ask(text, turn);
    } catch (err) {
      if (err && err.name === 'AbortError') return;
      if (turn !== turnId) return;
      if (err instanceof ApiError && err.status === 401) { sessionExpired(); return; }
      fail(errorText(err));
    }
  }

  // =========================================================================
  // 11. Savol -> javob -> ovoz
  // =========================================================================

  /** Oqimdagi `error` kadrining matni.
   *
   *  XIZMATNING O'Z MATNI YUTADI - HAR QANDAY kod uchun, `auth_missing`
   *  ham. Avval `auth_missing` uchun o'zimizning HRM haqidagi gapimiz
   *  qo'yilardi, va 2026-09-14 da CRM qo'shilganda bu NOTO'G'RI bo'lib
   *  qoldi: CRM savoliga xizmat "CRM tizimiga kiring" deb javob berardi,
   *  biz esa uni "HRM ulanmagan" ga almashtirib, odamni BOSHQA tizimga
   *  yo'naltirardik. Savol qaysi platformani talab qilganini xizmat
   *  biladi, biz bilmaymiz.
   *
   *  O'z matnimiz faqat hech qanday matn kelmaganda zaxira bo'lib qoladi. */
  function frameError(frame) {
    const own = (frame.text || '').trim();
    if (own) return own;
    if (frame.code === 'auth_missing' || frame.code === 'auth_expired') {
      return 'Bu savol uchun jonli ma\'lumot kerak, o\'sha tizim esa hisobingizga bu yerda hali ulanmagan. Qoidalar va hujjatlar bo\'yicha savollar ishlaydi.';
    }
    return 'Javob berilmadi';
  }

  //: JONLI SO'ROV bo'lgan manba turlari - hujjatdan farqli. `crm` `hrm` ga
  //: 2026-09-14 da qo'shildi; undan oldin CRM manbasi hujjatlar ro'yxatiga
  //: tushib, mavjud bo'lmagan fayl kabi ko'rsatilardi. Yangi platforma uchun
  //: shu yerga bitta qator qo'shiladi.
  const LOOKUP_KINDS = ['hrm', 'crm'];

  /** Manba qatorining ko'rinadigan nomi.
   *
   *  Ikki tur ATAYLAB har xil: hujjatda nom bor va u `[1]` bilan belgilanadi;
   *  jonli so'rovda esa ochiladigan narsa yo'q - u ma'lum bir paytda
   *  bo'lib o'tgan chaqiruv, shuning uchun nomi va nima qaytargani (digest)
   *  aytiladi. */
  function sourceLabel(s, index) {
    const lookup = LOOKUP_KINDS.indexOf(String(s.kind)) >= 0;
    const mark = s.marker || (lookup ? '[T' + (index + 1) + ']' : '[' + (s.citation_index || index + 1) + ']');
    if (lookup) {
      const what = s.tool || s.kind;
      return mark + ' ' + what + (s.digest ? ' - ' + s.digest : '');
    }
    const name = s.title || s.doc_id || 'hujjat';
    return mark + ' ' + name + (s.page ? ', ' + s.page + '-bet' : '');
  }

  async function ask(question, turn) {
    setState('thinking');
    const el = addMsg('venera', '');
    const body = document.createElement('span');
    const cursor = document.createElement('span');
    cursor.className = 'cursor';
    el.appendChild(body);
    el.appendChild(cursor);

    let answer = '';
    let failure = null;
    let failed = false;
    const onFrame = (frame) => {
      if (turn !== turnId) return;
      switch (frame.type) {
        case 'stage':
          if (frame.text) statusText.textContent = frame.text;
          break;
        case 'token':
          answer += frame.text || '';
          body.textContent = answer;
          log.scrollTop = log.scrollHeight;
          break;
        case 'sources': {
          // Jonli xizmat ro'yxatni `items` da, hujjat esa `sources` da
          // yuboradi. Faqat bittasini o'qish = ro'yxat JIMGINA doim bo'sh.
          const list = frame.sources || frame.items || [];
          if (!list.length) break;
          const docs = [], calls = [];
          for (const item of list) {
            (LOOKUP_KINDS.indexOf(String(item.kind)) >= 0 ? calls : docs).push(item);
          }
          const src = document.createElement('span');
          src.className = 'src';
          const parts = [];
          if (docs.length) parts.push('Manbalar: ' + docs.map(sourceLabel).join('  '));
          if (calls.length) parts.push('Tizim so\'rovlari: ' + calls.map(sourceLabel).join('  '));
          src.textContent = parts.join('\n');
          el.appendChild(src);
          break;
        }
        case 'artifact': {
          // Maydonlar YA kadrning o'zida, YA `artifact` ichida keladi -
          // faqat bittasini qarash havolalarni jimgina yo'qotardi.
          const art = frame.artifact || frame;
          // Faylni Telegram WebView ichida yuklab olish ishonchsiz (ayniqsa
          // iOS da `<a download>` + blob:), shuning uchun bu yerda faqat
          // nomi aytiladi - faylning o'zi veb ilovadan olinadi.
          addMsg('system', 'Hujjat tayyorlandi: ' + (art.filename || art.title || 'fayl') + '. Uni veb ilovadan yuklab oling.');
          break;
        }
        case 'error':
          // Javobni BOSIB O'TMAYMIZ: xato kadri tokenlardan KEYIN ham
          // kelishi mumkin, va kelgan qism baribir o'qishga arziydi.
          // Qarorni oqim tugagach qabul qilamiz.
          failure = frameError(frame);
          break;
      }
    };

    try {
      await streamAsk(question, onFrame, aborter ? aborter.signal : undefined);
    } catch (err) {
      if (err && err.name === 'AbortError') { cursor.remove(); return; }
      if (turn !== turnId) return;
      if (err instanceof ApiError && err.status === 401) { cursor.remove(); sessionExpired(); return; }
      failed = true;
      answer = errorText(err);
      body.textContent = answer;
    }
    cursor.remove();
    if (turn !== turnId) return;

    if (failure && !answer) {
      // Foydali hech narsa kelmadi - xatoning o'zi javob bo'ladi.
      failed = true;
      answer = failure;
      body.textContent = answer;
    } else if (failure) {
      // Qisman javobdan keyingi xato - IZOH, nosozlik emas.
      setNote(failure, 'warn');
    }

    if (!answer) { setState('idle'); return; }
    if (failed || !voiceOn) { setState('idle'); return; }
    await speak(answer, turn);
  }

  /**
   * Suhbat javobini o'qib beradi - ovozli turnning OXIRGI qadami.
   *
   * NEGA BUTUN JAVOB BITTA SO'ROVDA, gap-gapga bo'lib emas: yuqoridagi
   * xizmat tokenlarni ~15 s jimlikdan keyin 0.02 s ichida BIRDAN yuboradi,
   * ya'ni "kelgan gapni darhol o'qish" hech narsa tejamaydi - o'qish
   * boshlanadigan payt baribir javob to'liq kelgan payt bo'ladi.
   */
  async function speak(markdown, turn) {
    const prepared = forSpeech(markdown || '');
    // Javob kelmadi (xato yoki bo'sh): JIM qolamiz. Xato matni suhbatda
    // ko'rinadi, va uni ovoz bilan takrorlash hech kimga yordam bermaydi.
    if (!prepared.text) { setState('idle'); return; }
    if (prepared.shortened) setNote('Javobning boshi oʻqildi — toʻligʻi ekranda.', 'warn');
    stopSpeaking();
    speechAborter = new AbortController();
    setState('speaking');
    try {
      const playback = await speakStream(prepared.text, speechAborter.signal, (lvl) => { target = lvl; });
      if (turn !== turnId) { playback.stop(); return; }
      stopSpeech = playback.stop;
      await playback.done;
    } catch (err) {
      if (err && err.name === 'AbortError') return;
      // 501 = ovoz serverda hali yoqilmagan. Bu NOSOZLIK EMAS - javob
      // ekranda turibdi, shuning uchun xato ko'rsatilmaydi.
      if (!(err instanceof ApiError && err.status === 501)) {
        setNote('Javob keldi, lekin ovoz tayyorlanmadi.', 'warn');
      }
    } finally {
      stopSpeech = null;
      if (turn === turnId) { setState('idle'); }
    }
  }

  function stopSpeaking() {
    if (speechAborter) { speechAborter.abort(); speechAborter = null; }
    if (stopSpeech) { try { stopSpeech(); } catch (e) {} stopSpeech = null; }
    target = 0;
  }

  // =========================================================================
  // 12. Kirish / chiqish
  // =========================================================================

  function sessionExpired() {
    clearToken();
    user = null;
    teardown();
    releaseMic();
    stopSpeaking();
    log.textContent = '';
    logEmpty.hidden = false;
    show(authView);
    showAuthError('Sessiya tugadi. Qaytadan kiring.');
  }

  function showAuthError(text) {
    authError.textContent = text || '';
    authError.hidden = !text;
  }

  function enterApp(u) {
    user = u;
    whoName.textContent = u.fullName || u.email;
    whoMeta.textContent = [u.position, u.department, (u.roles || []).join(', ')]
      .filter(Boolean).join(' · ') || u.email;
    show(appView);
    setNote('');
    setState('idle');
    // Parol almashtirish talab qilinsa - menyuni o'zi ochib beramiz.
    if (u.passwordChangeRequired) {
      openMenu();
      pwBox.hidden = false;
      pwOpen.hidden = true;
      pwNote.textContent = 'Parolni almashtirish talab qilinadi.';
      pwNote.hidden = false;
    }
  }

  loginForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const email = emailInput.value.trim();
    const password = passwordInput.value;
    if (!email || !password) return;
    loginBtn.disabled = true;
    loginBtn.textContent = 'Kirilmoqda…';
    showAuthError('');
    try {
      const result = await api.login(email, password);
      setToken(result.token);
      passwordInput.value = '';
      enterApp(result.user);
    } catch (err) {
      showAuthError(errorText(err));
    } finally {
      loginBtn.disabled = false;
      loginBtn.textContent = 'Kirish';
    }
  });

  // Server hozircha 501 qaytaradi - uning O'Z xabarini ko'rsatamiz.
  signupLink.addEventListener('click', async () => {
    showAuthError('');
    const email = emailInput.value.trim();
    try {
      await api.signup({ email, fullName: email });
      showAuthError('Ro\'yxatdan o\'tish so\'rovi yuborildi.');
    } catch (err) {
      showAuthError(errorText(err));
    }
  });

  forgotLink.addEventListener('click', async () => {
    showAuthError('');
    try {
      await api.changePassword('', '');
      showAuthError('Parol o\'zgartirildi.');
    } catch (err) {
      showAuthError(errorText(err));
    }
  });

  function openMenu() { menuSheet.hidden = false; }
  function closeMenu() { menuSheet.hidden = true; }
  menuBtn.addEventListener('click', openMenu);
  menuClose.addEventListener('click', closeMenu);
  menuSheet.addEventListener('click', (e) => { if (e.target === menuSheet) closeMenu(); });

  pwOpen.addEventListener('click', () => { pwBox.hidden = false; pwOpen.hidden = true; });
  pwSubmit.addEventListener('click', async () => {
    pwNote.hidden = true;
    pwSubmit.disabled = true;
    try {
      await api.changePassword(curPw.value, newPw.value);
      pwNote.textContent = 'Parol o\'zgartirildi.';
      pwNote.className = 'note';
      curPw.value = ''; newPw.value = '';
    } catch (err) {
      pwNote.textContent = errorText(err);
      pwNote.className = 'note warn';
    } finally {
      pwNote.hidden = false;
      pwSubmit.disabled = false;
    }
  });

  logoutBtn.addEventListener('click', async () => {
    // Server tomonda bekor qilinadigan sessiya YO'Q (JWT holatsiz) - shuning
    // uchun tokenni FRONTEND o'chiradi va endpoint natijasi ahamiyatsiz.
    try { await api.logout(); } catch (e) { /* baribir chiqamiz */ }
    clearToken();
    drop(CHAT_KEY);
    user = null;
    teardown();
    releaseMic();
    stopSpeaking();
    log.textContent = '';
    logEmpty.hidden = false;
    closeMenu();
    show(authView);
    showAuthError('');
  });

  // =========================================================================
  // 13. Kiritishlar
  // =========================================================================
  orbWrap.addEventListener('click', () => {
    if (state === 'idle' || state === 'confirm') startListening();
    else if (state === 'listening') stopListening();
    else if (state === 'speaking') { stopSpeaking(); setState('idle'); }
    else if (state === 'thinking' || state === 'transcribing') {
      if (aborter) aborter.abort();
      turnId++;
      teardown();
      setState('idle');
    }
  });

  confirmYes.addEventListener('click', () => {
    if (state !== 'confirm' || !pendingQuestion) return;
    setNote('');
    ask(pendingQuestion, turnId);
    pendingQuestion = '';
  });
  confirmNo.addEventListener('click', () => {
    pendingQuestion = '';
    setNote('');
    setState('idle');
  });

  /** Ovozli javob yoqilganmi. Yagona manba `aria-pressed` EMAS, shu
   *  o'zgaruvchi; atribut undan kelib chiqadi va ko'rinishni CSS hal qiladi.
   *  Checkbox o'rniga tugma: u yuqori qatorda pill va menyu bilan bitta
   *  uslubda turishi kerak. */
  let voiceOn = store(VOICE_KEY) !== '0';
  function setVoice(on) {
    voiceOn = on;
    voiceToggle.setAttribute('aria-pressed', on ? 'true' : 'false');
    voiceToggle.title = on ? 'Ovozli javob yoqilgan' : 'Ovozli javob o\'chirilgan';
    keep(VOICE_KEY, on ? '1' : '0');
  }
  voiceToggle.addEventListener('click', () => {
    setVoice(!voiceOn);
    // O'chirilganda ayni paytda o'qilayotgan javob ham to'xtaydi - aks holda
    // kalit "keyingi safardan" ishlagandek tuyulardi.
    if (!voiceOn && state === 'speaking') { stopSpeaking(); setState('idle'); }
  });

  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) return;
    if (state === 'listening') { if (aborter) aborter.abort(); turnId++; teardown(); setState('idle'); }
    if (state === 'speaking') { stopSpeaking(); setState('idle'); }
    // Mikrofon fonda OCHIQ QOLMASIN. Turnlar orasida u ataylab tirik turadi
    // (`getMic`), lekin sahifa ko'rinmay qolishi - bu boshqa gap.
    releaseMic();
  });

  // =========================================================================
  // 14. Ishga tushish
  // =========================================================================
  setVoice(voiceOn);

  (async () => {
    if (!getToken()) { show(authView); return; }
    // Token saqlangan bo'lsa ham eskirgan bo'lishi mumkin - serverdan
    // so'raymiz. Bu ayni paytda foydalanuvchi ma'lumotini ham beradi.
    bootText.textContent = 'Sessiya tekshirilmoqda…';
    try {
      const u = await api.me();
      enterApp(u);
    } catch (err) {
      clearToken();
      show(authView);
      if (!(err instanceof ApiError && err.status === 401)) showAuthError(errorText(err));
    }
  })();
})();
