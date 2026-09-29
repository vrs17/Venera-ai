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
// Ulanishlar ("+" menyusi, HRM/CRM) va taklif kartasi ham shunday:
// `useConnectors.ts`, `ConnectorList.vue`, `ConnectorDialog.vue`,
// `ActionCard.vue` ning nusxasi - bir xil so'rovlar, bir xil matnlar.
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

  // KLAVIATURA OCHILGANDA BALANDLIK. Matn maydoni qo'shilgach bu majburiy
  // bo'ldi: `100dvh` Telegram WebView'da klaviatura chiqqanda YANGILANMAYDI
  // (u brauzer oynasiniki, WebView'niki emas), natijada sahifaning pastki
  // qismi - ya'ni aynan kiritish paneli - klaviatura ostida qolardi.
  //
  // `viewportStableHeight`, `viewportHeight` EMAS: ikkinchisi ochilish
  // animatsiyasi davomida har kadrda o'zgarib, tebranish hosil qiladi.
  if (tg && typeof tg.onEvent === 'function') {
    const applyViewport = () => {
      const h = tg.viewportStableHeight || tg.viewportHeight;
      if (!h) return;
      document.body.style.height = h + 'px';
      document.body.style.minHeight = h + 'px';   // `min-height: 100dvh` ni bosib o'tadi
    };
    try { tg.onEvent('viewportChanged', applyViewport); } catch (e) {}
    applyViewport();
  }

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
    // `X-Venera-Client` - admin panel statistikasi uchun kanal: server web va
    // mini app so'rovini boshqacha ajrata olmaydi (`core/channels.py`).
    const headers = Object.assign({ Accept: 'application/json', 'Accept-Language': 'uz',
                                    'X-Venera-Client': 'miniapp' }, extra || {});
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
    // `username` - HRM/CRM (Keycloak) logini; kirgach ikkala ulanish o'zi ochiladi.
    login: (username, password) =>
      apiFetch('/api/v1/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) }),
    me: () => apiFetch('/api/v1/auth/me'),
    logout: () => apiFetch('/api/v1/auth/logout', { method: 'POST' }),
    // Bot chati (Telegram'ning o'zi) shu hisobga ulanadi - `api/v1/telegram.py`.
    linkTelegram: (initData) => apiFetch('/api/v1/telegram/link', {
      method: 'POST', body: JSON.stringify({ initData }),
    }),
    unlinkTelegram: (initData) => apiFetch('/api/v1/telegram/unlink', {
      method: 'POST', body: JSON.stringify({ initData }),
    }),
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

    // Ulanishlar (HRM / CRM) - `apps/web/src/api/connectors.api.ts` nusxasi.
    // Parol shu yerdan serverga ketadi va HECH QAYERDA saqlanmaydi (serverda
    // ham: u platformaga login uchun ishlatiladi va unutiladi). Javobda
    // token yo'q - faqat holat: sahifa HRM/CRM tokenini hech qachon ko'rmaydi.
    connectors: () => apiFetch('/api/v1/connectors'),
    connect: (id, username, password) =>
      apiFetch('/api/v1/connectors/' + id + '/connect', {
        method: 'POST',
        body: JSON.stringify({ username, password }),
      }),
    setConnector: (id, enabled) =>
      apiFetch('/api/v1/connectors/' + id, { method: 'PATCH', body: JSON.stringify({ enabled }) }),
    disconnect: (id) => apiFetch('/api/v1/connectors/' + id, { method: 'DELETE' }),

    // Yozuv amallari - `apps/web/src/api/actions.api.ts` nusxasi. Sahifa
    // FAQAT taklif kalitini yuboradi: kim tasdiqlayotgani (Venera
    // foydalanuvchisi) va amal uchun platforma tokenini server qo'shadi -
    // taklif qilingan paytdagi kimlik bilan, ya'ni birovning taklifini
    // tasdiqlab bo'lmaydi.
    confirmAction: (token) =>
      apiFetch('/api/v1/actions/' + encodeURIComponent(token) + '/confirm', { method: 'POST' }),
    cancelAction: (token) =>
      apiFetch('/api/v1/actions/' + encodeURIComponent(token) + '/cancel', { method: 'POST' }),
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
      try { reader.cancel().catch(() => {}); } catch (e) {}
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
  async function speakStream(text, signal, onLevel, after) {
    const response = await fetch('/api/v1/tts/speak', {
      method: 'POST',
      signal,
      headers: authHeaders({ 'Content-Type': 'application/json; charset=utf-8', Accept: 'audio/L16, */*' }),
      body: JSON.stringify({ text, language: 'uz' }),
    });
    if (!response.ok) throw await apiError(response);
    const rate = rateOf(response);
    // IJRO DARVOZASI. So'rov KUTMAYDI - u javob tayyor bo'lishi bilan ketadi
    // va tanasi shu yerda buferlanadi; faqat ijro `after` tugashini kutadi.
    // Shunda kutish ovozi kesilmaydi, javob esa u tugagan ZAHOTI boshlanadi
    // (o'lchangan TTS birinchi ovozgacha ~1.1 s - bu vaqt tejaladi).
    if (after) { try { await after; } catch (e) {} }
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
   * Javob matnini EKRANGA tayyorlaydi.
   *
   * Ikki ish qiladi va ikkalasi ham o'qishni yengillashtirish uchun:
   *
   * 1. AUDIT IZI OLIB TASHLANADI. Javob oxirida "Tekshirilgan HRM
   *    ma'lumotlari:" va `[T1] hrm_today_late - date=... -> count=9,
   *    data=9 rows, status=200` turadi. Bu xodim uchun emas, tizim uchun
   *    yozilgan matn: `status=200` va `9 rows` savol bergan odamga hech
   *    narsa aytmaydi, lekin javobdan uzunroq bo'lishi mumkin.
   *    (Veb ilova uni EKRANDA qoldiradi - u yerda alohida yig'iladigan
   *    bo'lim bor va bank auditi uni talab qiladi. Telegram'da esa bitta
   *    tor ustun, va iz javobni ko'mib yuboradi.)
   *
   * 2. MARKDOWN BELGILARI TOZALANADI. Sahifa matnni ODDIY matn sifatida
   *    ko'rsatadi (`white-space: pre-wrap`), ya'ni `**bo'lim:**` shundayligicha
   *    yulduzchalari bilan ko'rinardi. Ro'yxat belgisi `•` ga aylanadi -
   *    qatorlar saqlanadi, faqat belgi almashadi.
   *
   * Hujjat iqtiboslari (`[1]`, `[2]`) SAQLANADI: ular javob ostidagi
   * "Manbalar" ro'yxatiga ishora qiladi va o'sha ro'yxat ko'rinib turadi.
   */
  function forScreen(markdown) {
    return answerBody(markdown)
      // Iz olib tashlangach `[T1]` markerlari hech qayerga ishora qilmaydi.
      // ATAYLAB faqat `T` prefiksi: `[1]` hujjat iqtibosi, u qoladi.
      // Ortidagi probel ham yeyiladi: marker qator BOSHIDA turgan bo'lsa
      // ("[T1] hrm_today_late"), usiz qator bo'shliq bilan boshlanardi.
      .replace(/\[T\d{1,3}\][ \t]?/g, '')
      .replace(/```[a-zA-Z]*\n?/g, '')
      .replace(/`([^`]*)`/g, '$1')
      .replace(/!?\[([^\]]*)\]\([^)]*\)/g, '$1')
      .replace(/^#{1,6}[ \t]*/gm, '')
      // Ro'yxat belgisi -> nuqta. `*` ni olib tashlashdan OLDIN.
      .replace(/^([ \t]*)[-*+][ \t]+/gm, '$1• ')
      .replace(/\*\*|__|~~/g, '')
      .replace(/\*/g, '')
      // Marker olib tashlangach qolgan bo'shliq: "kech qoldi :" -> "kech qoldi:"
      // FAQAT probel va tab: `\s` bo'lsa qator uzilishlarini ham yeb qo'yardi.
      .replace(/[ \t]+([,.;:!?])/g, '$1')
      .replace(/[ \t]{2,}/g, ' ')
      .replace(/[ \t]+$/gm, '')
      .replace(/\n{3,}/g, '\n\n')
      .trim();
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

  /** Yangi suhbat kaliti. `crypto.randomUUID` faqat xavfsiz kontekstda
   *  (HTTPS) bor - boshqa joyda oddiy tasodifiy kalit. Ikkalasi ham
   *  manzilga xavfsiz: tarix yo'llari kalitni URL ga qo'yadi. */
  function freshChatId() {
    return (window.crypto && crypto.randomUUID)
      ? crypto.randomUUID()
      : 'tg-' + Math.random().toString(36).slice(2) + Date.now().toString(36);
  }

  /** Suhbat kaliti. Bir xil kalitli savollar bir-birini ESLAYDI, ya'ni
   *  "va o'tgan oyda?" degan savol ishlaydi. `user_id` ni server token'dan
   *  qo'yadi, shuning uchun bu kalit boshqa odamning suhbatiga tushirmaydi. */
  function chatId() {
    let id = store(CHAT_KEY);
    if (!id) {
      id = freshChatId();
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

  async function streamAsk(question, onFrame, signal, spoken) {
    const text = (question || '').trim().slice(0, MAX_QUESTION_CHARS);
    if (!text) throw new ApiError('Savol bo\'sh');
    const response = await fetch('/api/v1/chat/stream', {
      method: 'POST',
      signal,
      headers: authHeaders({ 'Content-Type': 'application/json; charset=utf-8', Accept: 'application/x-ndjson' }),
      // `voice` - OVOZLI rejimdami. Server buni o'zi bilmaydi, shuning
      // uchun klient aytadi: faqat shunda kutish gaplari (`hold` kadrlari)
      // yuboriladi. Matnli rejimda ular shovqin bo'lardi.
      // `input` - savol QANDAY kiritilgani (mikrofon yoki yozib), faqat
      // admin paneldagi savol izi uchun: ovozli rejim default yoqiq, ya'ni
      // `voice` yozilgan savolni ham "ovozli" qilib ko'rsatardi.
      body: JSON.stringify({
        question: text, chatId: chatId(), voice: voiceOn, locale: 'uz',
        input: spoken ? 'voice' : 'text',
      }),
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
      // assistant navbatida joyni band qilib turadi. `cancel()` VA'DA
      // qaytaradi va bekor qilingan (AbortError) oqimda u RAD ETILADI -
      // `try` buni ushlamaydi, ya'ni har "To'xtatish" konsolga ushlanmagan
      // xato chiqarardi. Shuning uchun `.catch`.
      try { reader.cancel().catch(() => {}); } catch (e) {}
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
  const loginForm = $('loginForm'), loginInput = $('login'), passwordInput = $('password'),
        loginBtn = $('loginBtn'), authError = $('authError'),
        signupLink = $('signupLink'), forgotLink = $('forgotLink');
  const orbWrap = $('orbWrap'), ripple = $('ripple'), logEmpty = $('logEmpty'),
        statusEl = $('status'), statusText = $('statusText'), note = $('note'), log = $('log'),
        modePill = $('modePill'), voiceToggle = $('voiceToggle'),
        input = $('input'), sendBtn = $('sendBtn'),
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

  /** Tarixdan ochilgan suhbatning nechta xabari olinadi
   *  (`/chats/{id}?limit=`). Avval 20 edi - tarixsiz ilovada eski xabarga
   *  qaytishning ma'nosi yo'q edi. */
  const LOG_LIMIT = 200;
  /** Ekranda saqlanadigan xabarlar soni - `LOG_LIMIT` dan 40 ta KO'P. Teng
   *  bo'lsa 200 xabarli suhbat ochilgach birinchi yangi savoldanoq eng eski
   *  xabarlar jimgina qirqila boshlardi. Chegara baribir qoladi: cheksiz
   *  ro'yxat eski telefonda sahifani sekinlashtiradi. */
  const LOG_KEEP = LOG_LIMIT + 40;

  /** `at` - xabar vaqti (ms). Berilmasa hozirgi payt; `null` bo'lsa vaqt
   *  KO'RSATILMAYDI (tizim eslatmalarida u ma'nosiz, javobga esa u oqim
   *  tugagach `stampMessage` bilan qo'yiladi). */
  function msgEl(who, text, at) {
    const el = document.createElement('div');
    el.className = 'msg ' + who;
    if (who !== 'system') {
      const w = document.createElement('span');
      w.className = 'who';
      w.textContent = who === 'you' ? 'Siz' : 'Venera';
      el.appendChild(w);
    }
    el.appendChild(document.createTextNode(text));
    if (who !== 'system' && at !== null) stampMessage(el, at);
    return el;
  }

  function trimLog() {
    while (log.children.length > LOG_KEEP) log.removeChild(log.firstChild);
  }

  function addMsg(who, text, at) {
    const el = msgEl(who, text, at);
    log.appendChild(el);
    logEmpty.hidden = true;
    log.scrollTop = log.scrollHeight;
    trimLog();
    return el;
  }

  /* --- Xabar vaqti: `apps/web/src/time.ts` ning qisqartmasi ---------------
     Veb ilovada vaqt sichqoncha ustida ko'rinadi; bu yerda DOIM - sensorli
     ekranda "ustiga olib borish" yo'q. O'zbek oy nomlari QO'LDA: brauzerning
     `Intl` ma'lumotida o'zbek uchun oy nomi yo'q va u "M09 18" deb chiqaradi
     (jonli ko'rilgan). Bugungi xabar uchun faqat soat ("11:39"), eskisi
     uchun kun ham ("18-sentabr, 11:39"), o'tgan yilniki uchun yil ham. */
  const UZ_MONTHS = ['yanvar', 'fevral', 'mart', 'aprel', 'may', 'iyun',
                     'iyul', 'avgust', 'sentabr', 'oktabr', 'noyabr', 'dekabr'];

  function clockText(d) {
    return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
  }

  function whenText(ms) {
    const d = new Date(ms), now = new Date();
    const sameDay = d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth()
      && d.getDate() === now.getDate();
    if (sameDay) return clockText(d);
    const day = d.getDate() + '-' + UZ_MONTHS[d.getMonth()];
    if (d.getFullYear() === now.getFullYear()) return day + ', ' + clockText(d);
    return day + ', ' + d.getFullYear() + '-yil, ' + clockText(d);
  }

  /** ISO (serverdan) -> ms, buzuq bo'lsa `null`. */
  function isoToMs(iso) {
    if (!iso) return null;
    const ms = Date.parse(iso);
    return isFinite(ms) ? ms : null;
  }

  /** Xabarning OXIRIGA vaqt qo'yadi. Javobda - oqim TUGAGANDAN keyin:
   *  darhol qo'yilgan vaqt kadrlar bilan keladigan matnning USTIDA qolardi. */
  function stampMessage(el, at) {
    const t = document.createElement('time');
    t.className = 'at';
    const ms = at || Date.now();
    t.dateTime = new Date(ms).toISOString();
    t.textContent = whenText(ms);
    el.appendChild(t);
    return t;
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
    // Yuborish tugmasi holatga BOG'LIQ (band bo'lsa "to'xtatish"), shuning
    // uchun u shu yerdan yangilanadi - har chaqiruv joyida takrorlanmaydi.
    syncSend();
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
      ask(text, turn, true);
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

  /** Javob ostidagi manbalar qatori. Ikki joyda kerak: javob kelganda va
   *  suhbat tarixdan qayta ochilganda (12b-bo'lim, manbalar xotirasi). */
  function renderSources(el, docs) {
    if (!docs || !docs.length) return;
    const src = document.createElement('span');
    src.className = 'src';
    src.textContent = 'Manbalar: ' + docs.map(sourceLabel).join('  ');
    el.appendChild(src);
  }

  /** `spoken` - savol mikrofondan kelgan (STT), yozilmagan. */
  async function ask(question, turn, spoken) {
    setState('thinking');
    // Kalit SHU YERDA olinadi: manbalar javob kelgan suhbat ostida eslab
    // qolinadi, javob kelguncha ekranda boshqa suhbat ochilgan bo'lsa ham.
    const chat = chatId();
    let answerDocs = null;
    // VAQTSIZ yaratiladi - vaqt javob tugagach, matnning ostiga qo'yiladi.
    const el = addMsg('venera', '', null);
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
        case 'hold':
          // KUTISH GAPI. Bu ekranga chiqmaydi va javobga qo'shilmaydi -
          // faqat aytiladi.
          //
          // Mini app uchun bu ayniqsa muhim: yuqoridagi xizmat tokenlarni
          // ~15 sekund jimlikdan keyin BIRDAN yuboradi (pastdagi `speak`
          // izohiga qara), ya'ni bu 15 sekund davomida telefon butunlay
          // jim turardi va odam ilovani tashlab ketardi.
          if (frame.clip) void speakHold(frame.clip, turn);
          break;
        case 'token':
          answer += frame.text || '';
          // Xom matn `answer` da saqlanadi (ovoz uchun kerak), ekranga esa
          // tozalangani chiqadi.
          body.textContent = forScreen(answer);
          log.scrollTop = log.scrollHeight;
          break;
        case 'sources': {
          // Jonli xizmat ro'yxatni `items` da, hujjat esa `sources` da
          // yuboradi. Faqat bittasini o'qish = ro'yxat JIMGINA doim bo'sh.
          const list = frame.sources || frame.items || [];
          if (!list.length) break;
          // JONLI SO'ROVLAR (`hrm`, `crm`) EKRANGA CHIQMAYDI. Ular javob
          // matnidagi audit izining AYNI O'ZI, boshqa shaklda:
          // "T1 hrm_today_late - count=9, data=9 rows, status=200". Izni
          // `forScreen` da olib tashlab, o'sha ma'lumotni pastda qayta
          // ko'rsatish ma'nosiz bo'lardi.
          //
          // HUJJATLAR esa QOLADI va bu farq ataylab: "[1] ichki mehnat
          // tartibi qoidalari, 22-bet" - bu texnik iz emas, javobning
          // qayerdan olingani. Bank muhitida xodim javobga ishonmasa,
          // aynan shu qatorga qaraydi.
          const docs = list.filter((item) => LOOKUP_KINDS.indexOf(String(item.kind)) < 0);
          if (!docs.length) break;
          answerDocs = docs;
          renderSources(el, docs);
          break;
        }
        case 'artifact': {
          // Maydonlar YA kadrning o'zida, YA `artifact` ichida keladi -
          // faqat bittasini qarash havolalarni jimgina yo'qotardi.
          const art = frame.artifact || frame;
          // Yuklab olish tugmalari bilan (12c-bo'lim): Telegram'ning o'z
          // yuklab olgichi, imzolangan havola orqali.
          showArtifact(art);
          break;
        }
        case 'proposal': {
          // Yordamchi yozuv amalini TAKLIF qildi (masalan CRM da vaqt
          // yozish). HECH NARSA O'ZGARMAGAN: javob ostidagi karta odamdan
          // tasdiq yoki rad so'raydi. Maydonlar YA `proposal` ichida, YA
          // kadrning o'zida - artifact kabi.
          const proposal = frame.proposal || frame;
          if (proposal && proposal.token) renderProposal(el, proposal);
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
      await streamAsk(question, onFrame, aborter ? aborter.signal : undefined, spoken);
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
    stampMessage(el);

    if (!answer) { setState('idle'); return; }
    if (!failed) {
      // Javob saqlandi, ya'ni suhbat endi serverda BOR. Manbalar SHU
      // qurilmada eslab qolinadi (xizmat tarixi ularni saqlamaydi), varaq
      // ochiq bo'lsa ro'yxat yangilanadi - yangi suhbat unda paydo bo'lsin.
      rememberSources(chat, answer, answerDocs);
      if (!historySheet.hidden) void loadChats();
    }
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
    // Joriy kutish ovozi KESILMAYDI. O'lchangan: HRM javobi 3-4 sekundda
    // kelardi, ovozning o'zi 2.5-3.3 sekund - ya'ni u yarmida uzilardi, yarim
    // gap esa jimlikdan yomonroq. Javob so'rovi DARHOL ketadi (ovozi
    // buferlanadi), ijro esa kutish ovozi tugashi bilan boshlanadi.
    const gate = holdPlaying;
    stopAnswerAudio();
    speechAborter = new AbortController();
    setState('speaking');
    try {
      const playback = await speakStream(prepared.text, speechAborter.signal, (lvl) => { target = lvl; }, gate);
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

  let holdPlaying = null;
  let stopHold = null;

  /** `decodeAudioData` ning ikki shakli: eski WebKit (Telegram iOS) faqat
   *  callback bilan ishlaydi, yangilari esa va'da qaytaradi. */
  function decodeClip(ctx, bytes) {
    return new Promise((resolve, reject) => {
      const p = ctx.decodeAudioData(bytes, resolve, reject);
      if (p && typeof p.then === 'function') p.then(resolve, reject);
    });
  }

  /**
   * TAYYOR kutish ovozini o'ynatadi - HRM/CRM javobi kelgunicha.
   *
   * Ovoz serverda OLDINDAN sintez qilingan va savolning mavzusi hamda ohangi
   * bo'yicha tanlangan (`hold` kadridagi `clip`). Ya'ni TTS kutilmaydi.
   *
   * NEGA `<audio>` EMAS, umumiy AudioContext. `<audio src>` Authorization
   * sarlavhasini yubora olmaydi, ustiga Telegram WebView jestdan tashqarida
   * boshlangan ijroni jimgina bloklaydi (yuqoridagi `audioContext` izohi).
   * Umumiy kontekst esa mikrofon bosilganda ochilgan - TTS aynan shu yerda
   * ishlaydi.
   *
   * QO'RIQCHILAR: faqat `thinking` holatida va o'z turni uchun (javobdan
   * keyin chiqqan ovoz uning ustiga chiqadi); bir vaqtda bittadan (kelgan
   * keyingisi tashlanadi, ustma-ust qo'yilmaydi); xato JIM.
   */
  async function speakHold(clip, turn) {
    if (!voiceOn || !clip || turn !== turnId || state !== 'thinking') return;
    if (holdPlaying) return;
    let playing = null;
    try {
      const response = await fetch('/api/v1/tts/hold/' + encodeURIComponent(clip) + '.wav',
                                   { headers: authHeaders({}) });
      if (!response.ok) return;
      const bytes = await response.arrayBuffer();
      if (turn !== turnId || state !== 'thinking') return;
      const ctx = audioContext();
      const buffer = await decodeClip(ctx, bytes);
      if (turn !== turnId || state !== 'thinking' || holdPlaying) return;
      const source = ctx.createBufferSource();
      source.buffer = buffer;
      source.connect(ctx.destination);
      playing = new Promise((resolve) => {
        source.onended = () => resolve();
        stopHold = () => { try { source.stop(); } catch (e) {} resolve(); };
      });
      holdPlaying = playing;
      source.start();
      await playing;
    } catch (e) {
      // Jim: kutish ovozi qulaylik, xato ko'rsatiladigan narsa emas.
    } finally {
      if (playing && holdPlaying === playing) { holdPlaying = null; stopHold = null; }
    }
  }

  /** Faqat JAVOB ovozini to'xtatadi - kutish ovoziga tegmaydi. */
  function stopAnswerAudio() {
    if (speechAborter) { speechAborter.abort(); speechAborter = null; }
    if (stopSpeech) { try { stopSpeech(); } catch (e) {} stopSpeech = null; }
  }

  function stopSpeaking() {
    stopAnswerAudio();
    // Panel yopilsa yoki yangi savol boshlansa - kutish ovozi ham to'xtaydi.
    if (stopHold) { try { stopHold(); } catch (e) {} stopHold = null; }
    target = 0;
  }

  // =========================================================================
  // 12. Kirish / chiqish
  // =========================================================================

  function sessionExpired() {
    resetHistory();
    clearToken();
    user = null;
    teardown();
    releaseMic();
    stopSpeaking();
    resetConnectors();
    log.textContent = '';
    logEmpty.hidden = false;
    input.value = '';
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
    input.value = '';
    resize();
    setState('idle');
    loadCurrentChat();
    linkBot();
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
    const username = loginInput.value.trim();
    const password = passwordInput.value;
    if (!username || !password) return;
    loginBtn.disabled = true;
    loginBtn.textContent = 'Kirilmoqda…';
    showAuthError('');
    try {
      const result = await api.login(username, password);
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
    const email = loginInput.value.trim();
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

  /** Bot chatini shu hisobga ulaydi: odam botga oddiy xabar yoki ovozli
   *  xabar yozsa, javob SHU hisob nomidan keladi. Har ochilganda chaqiriladi
   *  - ulanish muddati (30 kun) shu bilan yangilanadi.
   *
   *  Isbot - Telegram imzolagan `initData` (kim ochgani) va sessiya (kim
   *  kirgani); `user.id` ni o'zimiz yubormaymiz. Xato jim: bot o'chiq
   *  bo'lsa ham ilova to'liq ishlaydi. */
  function linkBot() {
    if (!tg || !tg.initData) return;
    api.linkTelegram(tg.initData).catch(() => { /* bot o'chiq yoki initData eskirgan */ });
  }

  logoutBtn.addEventListener('click', async () => {
    // Server tomonda bekor qilinadigan sessiya YO'Q (JWT holatsiz) - shuning
    // uchun tokenni FRONTEND o'chiradi va endpoint natijasi ahamiyatsiz.
    // Chiqish - bot chatidan ham: aks holda bot shu Telegram'da eski
    // hisob nomidan javob berishda davom etardi.
    if (tg && tg.initData) {
      try { await api.unlinkTelegram(tg.initData); } catch (e) { /* baribir chiqamiz */ }
    }
    try { await api.logout(); } catch (e) { /* baribir chiqamiz */ }
    clearToken();
    drop(CHAT_KEY);
    // Manbalar xotirasi ham: unda hujjat nomlari bor, va keyingi odam
    // (umumiy qurilma) oldingisining izini ko'rmasin. Sessiya TUGAGANDA
    // (`sessionExpired`) esa qoladi - odatda o'sha odam qayta kiradi.
    forgetSources();
    resetHistory();
    user = null;
    teardown();
    releaseMic();
    stopSpeaking();
    resetConnectors();
    log.textContent = '';
    logEmpty.hidden = false;
    input.value = '';
    closeMenu();
    show(authView);
    showAuthError('');
  });

  // =========================================================================
  // 12b. Suhbatlar tarixi - `composables/useChats.ts` + `ChatHistory.vue`
  //      ning nusxasi
  // =========================================================================
  // SUHBATLAR BU YERDA SAQLANMAYDI. Ular yuqoridagi xizmatda turadi - har
  // savol bilan ketadigan `chatId` bo'yicha; Venera backend'i proksi qiladi
  // (`/api/v1/chats`) va kimlikni TOKEN'DAN o'zi qo'yadi. Ya'ni:
  //   * veb ilova bilan BIR HISOB = BIR RO'YXAT: vebda boshlangan suhbat shu
  //     yerda ko'rinadi va davom ettiriladi, teskarisi ham;
  //   * boshqa odamning suhbatiga kalitini bilgan holda ham kirib bo'lmaydi
  //     (404).
  // Suhbat yaratadigan chaqiruv yo'q: yangi `chatId` bilan birinchi savol uni
  // yaratadi, ro'yxatga esa u birinchi javob saqlangach tushadi.

  function chatPath(id) { return '/api/v1/chats/' + encodeURIComponent(id); }

  const chatsApi = {
    list: () => apiFetch('/api/v1/chats?limit=50'),
    open: (id) => apiFetch(chatPath(id) + '?limit=' + LOG_LIMIT),
    rename: (id, title) => apiFetch(chatPath(id), { method: 'PATCH', body: JSON.stringify({ title: title }) }),
    remove: (id) => apiFetch(chatPath(id), { method: 'DELETE' }),
    restore: (id) => apiFetch(chatPath(id) + '/restore', { method: 'POST' }),
  };

  const historyBtn = $('historyBtn'), historySheet = $('historySheet'),
        historyClose = $('historyClose'), newChatBtn = $('newChatBtn'),
        histList = $('histList'), histUndo = $('histUndo'), histUndoBtn = $('histUndoBtn'),
        histNote = $('histNote');

  // Statik belgilar - foydalanuvchi matni EMAS, shuning uchun innerHTML xavfsiz.
  const PENCIL_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>';
  const TRASH_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/></svg>';

  /** "Bekor qilish" qancha turadi - vebdagi bilan bir xil. */
  const UNDO_MS = 8000;

  let chats = [];               // ro'yxat - serverdan, oxirgi faollik bo'yicha
  let chatsState = 'idle';      // idle | loading | ready | failed
  let listRequest = 0;          // eski ro'yxat javobi yangisini bosib ketmasin
  let openRequest = 0;          // eski suhbat javobi yangisini bosib ketmasin
  let editingId = null;         // nomi tahrirlanayotgan suhbat
  let lastDeleted = null, undoTimer = 0, noteTimer = 0;

  /** Ekrandagi suhbat kaliti. `chatId()` dan farqi - YANGISINI YARATMAYDI:
   *  ro'yxatda "qaysi biri ochiq" deb so'rash kalit yaratishga sabab emas. */
  function currentChatId() { return store(CHAT_KEY); }

  function stamp(iso) {
    const t = iso ? Date.parse(iso) : NaN;
    return isFinite(t) ? t : 0;
  }
  function byActivity(a, b) { return stamp(b.updated_at) - stamp(a.updated_at); }

  /** Kunlar bo'yicha guruh - vebdagi kabi. Ro'yxat allaqachon oxirgi faollik
   *  bo'yicha tartiblangan, guruh esa faqat ko'z uchun. */
  function groupOf(iso, startOfToday) {
    const at = stamp(iso), day = 86400000;
    if (!at) return 'Oldinroq';
    if (at >= startOfToday) return 'Bugun';
    if (at >= startOfToday - day) return 'Kecha';
    if (at >= startOfToday - 6 * day) return 'Oxirgi 7 kun';
    return 'Oldinroq';
  }

  function histMessage(text) {
    const p = document.createElement('p');
    p.className = 'hist-empty';
    p.textContent = text;
    return p;
  }

  function iconButton(label, svg, onClick) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'iconbtn';
    b.setAttribute('aria-label', label);
    b.title = label;
    b.innerHTML = svg;
    b.addEventListener('click', onClick);
    return b;
  }

  function renderHistory() {
    // Nom tahrirlanayotgan bo'lsa QAYTA CHIZILMAYDI. Fon yangilanishi
    // (`loadChats` - varaq ochilganda yoki javob kelganda) ro'yxatni qayta
    // qurib, ochiq kiritish maydonini yo'q qilardi - odam yozayotgan nom
    // jimgina yo'qolardi. Tahrir tugagach (`finish`) ro'yxat baribir
    // chiziladi, ya'ni yangi ma'lumot yo'qolmaydi.
    const field = histList.querySelector('.hist-input');
    if (editingId && field && field.dataset.chat === editingId) return;
    // Fokus qaysi qatorda edi - qayta qurilgach O'SHA suhbatning qatoriga
    // qaytadi. Aks holda u `<body>` ga tushardi (masalan nom Enter bilan
    // saqlangach) va klaviatura bilan yurgan odam ro'yxatning boshidan
    // qayta boshlardi.
    const had = document.activeElement;
    const hadRow = had && had !== histList && histList.contains(had) ? had.closest('.hist-row') : null;
    const focusId = hadRow ? hadRow.dataset.chat : null;
    histList.textContent = '';
    if (chatsState === 'loading' && !chats.length) {
      histList.appendChild(histMessage('Yuklanmoqda…'));
      return;
    }
    if (chatsState === 'failed' && !chats.length) {
      const p = histMessage('Ro\'yxat yuklanmadi. ');
      const retry = document.createElement('button');
      retry.type = 'button';
      retry.className = 'link';
      retry.textContent = 'Qayta urinish';
      retry.addEventListener('click', () => { void loadChats(); });
      p.appendChild(retry);
      histList.appendChild(p);
      return;
    }
    if (!chats.length) {
      histList.appendChild(histMessage('Hali suhbatlar yo\'q. Savol bering — suhbat shu yerda saqlanadi.'));
      return;
    }
    const now = new Date();
    const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    const active = currentChatId();
    let group = null;
    for (const chat of chats) {
      const label = groupOf(chat.updated_at, startOfToday);
      if (label !== group) {
        group = label;
        const h = document.createElement('div');
        h.className = 'hist-label';
        h.textContent = label;
        histList.appendChild(h);
      }
      histList.appendChild(historyRow(chat, chat.chat_id === active));
    }
    if (focusId && focusId !== editingId) {
      for (const row of histList.children) {
        if (row.dataset.chat !== focusId) continue;
        const open = row.querySelector('.hist-open');
        if (open) open.focus();
        break;
      }
    }
  }

  function historyRow(chat, active) {
    const row = document.createElement('div');
    row.className = 'hist-row' + (active ? ' active' : '');
    row.dataset.chat = chat.chat_id;
    if (editingId === chat.chat_id) {
      // Nomini o'zgartirish - qatorning o'zida. Enter va fokus ketishi
      // saqlaydi, Esc bekor qiladi. Enter'dan keyin blur ham keladi -
      // `done` ikkinchisini o'tkazib yuboradi.
      const field = document.createElement('input');
      field.className = 'hist-input';
      field.type = 'text';
      field.maxLength = 80;
      field.value = chat.title || '';
      field.setAttribute('aria-label', 'Suhbat nomi');
      field.dataset.chat = chat.chat_id;
      let done = false;
      const finish = (save) => {
        if (done) return;
        done = true;
        editingId = null;
        if (save) void renameChat(chat.chat_id, field.value);
        else renderHistory();
      };
      field.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); finish(true); }
        else if (e.key === 'Escape') { e.preventDefault(); finish(false); }
      });
      field.addEventListener('blur', () => finish(true));
      row.appendChild(field);
      setTimeout(() => { field.focus(); field.select(); }, 0);
      return row;
    }
    const open = document.createElement('button');
    open.type = 'button';
    open.className = 'hist-open';
    open.textContent = chat.title || 'Nomsiz suhbat';
    open.addEventListener('click', () => { void openChat(chat.chat_id); });
    row.appendChild(open);
    row.appendChild(iconButton('Nomini o\'zgartirish', PENCIL_SVG, () => {
      editingId = chat.chat_id;
      renderHistory();
    }));
    row.appendChild(iconButton('O\'chirish', TRASH_SVG, () => { void removeChat(chat.chat_id); }));
    return row;
  }

  function flashNote(text) {
    histNote.textContent = text;
    histNote.hidden = false;
    clearTimeout(noteTimer);
    noteTimer = setTimeout(() => { histNote.hidden = true; }, 5000);
  }

  /** Ro'yxat HAR OCHILISHDA serverdan olinadi: arzon so'rov, va boshqa
   *  qurilmadagi (vebdagi) o'zgarish ham, model keyinroq bergan nom ham
   *  shunda ko'rinadi. Eski ro'yxat esa yuklanish paytida turadi. */
  async function loadChats() {
    const request = ++listRequest;
    chatsState = 'loading';
    renderHistory();
    try {
      const result = await chatsApi.list();
      if (request !== listRequest) return;
      chats = ((result && result.items) || []).slice().sort(byActivity);
      chatsState = 'ready';
    } catch (err) {
      if (request !== listRequest) return;
      if (err instanceof ApiError && err.status === 401) { sessionExpired(); return; }
      chatsState = 'failed';
      if (chats.length) flashNote(errorText(err));
    }
    renderHistory();
  }

  function openHistory() {
    closeMenu();
    historySheet.hidden = false;
    renderHistory();
    void loadChats();
  }

  function closeHistory() {
    historySheet.hidden = true;
    editingId = null;
  }

  function clearLog() {
    log.textContent = '';
    logEmpty.hidden = false;
    setNote('');
  }

  /** Yangi suhbat - yangi kalit. Kalit ALMASHMASA oldingi suhbat xotirasi
   *  yangisiga oqib o'tardi ("va o'tgan oyda?" eski mavzuni davom ettirardi). */
  function startNewChat() {
    cancelTurn();
    openRequest++;              // yuklanayotgan eski suhbat endi kerak emas
    keep(CHAT_KEY, freshChatId());
    clearLog();
    closeHistory();
  }

  /** Ro'yxatdan suhbatni ochish. Keyingi savol O'SHA kalit bilan ketadi,
   *  ya'ni xizmat suhbatni to'xtagan joyidan davom ettiradi. */
  async function openChat(id) {
    closeHistory();
    if (id === currentChatId() && log.children.length) return;   // allaqachon ochiq
    cancelTurn();
    keep(CHAT_KEY, id);
    clearLog();
    await showChat(id, true);
  }

  /**
   * Suhbat xabarlarini serverdan olib, ekranga chiqaradi.
   *
   * Xabarlar "yuklanmoqda" qatorining O'RNIGA qo'yiladi, oxiriga emas: odam
   * yuklanish paytida savol berib ulgurgan bo'lsa, uning savoli pastda qoladi
   * va tarix undan yuqoriga tushadi.
   *
   * `loud` - xato ekranda aytilsinmi. Ro'yxatdan ochilganda - ha; ilova
   * ochilganda esa jim: odam hech narsa so'ramagan.
   */
  async function showChat(id, loud) {
    const request = ++openRequest;
    const marker = addMsg('system', 'Suhbat yuklanmoqda…');
    try {
      const detail = await chatsApi.open(id);
      if (request !== openRequest) return;
      const frag = document.createDocumentFragment();
      const remembered = srcLoad();
      for (const m of (detail && detail.messages) || []) {
        const content = String((m && m.content) || '');
        if (!content.trim()) continue;
        // Vaqt - SERVERNIKI. Yo'q yoki buzuq bo'lsa ko'rsatilmaydi: "hozir"
        // deb qo'yish eski xabarni yangi qilib ko'rsatardi.
        const at = isoToMs(m.created_at);
        if (m.role === 'user') { frag.appendChild(msgEl('you', content, at)); continue; }
        // Saqlangan javobda iz yo'q, lekin `[T1]` va markdown belgilari bor -
        // jonli javobdagi bilan AYNI tozalash. Tartib ham jonlidagidek:
        // matn, manbalar, vaqt.
        const el = msgEl('venera', forScreen(content), null);
        // Xizmat tarixi iqtiboslarni SAQLAMAYDI - ular shu qurilmada eslab
        // qolingan bo'lsa qaytariladi (pastda, "Manbalar xotirasi").
        renderSources(el, recallSources(id, content, remembered));
        if (at !== null) stampMessage(el, at);
        frag.appendChild(el);
      }
      log.insertBefore(frag, marker);
      marker.remove();
      trimLog();
      logEmpty.hidden = log.children.length > 0;
      log.scrollTop = log.scrollHeight;
    } catch (err) {
      if (request !== openRequest) return;
      marker.remove();
      logEmpty.hidden = log.children.length > 0;
      if (err instanceof ApiError && err.status === 401) { sessionExpired(); return; }
      if (err instanceof ApiError && err.status === 404) {
        // Hali saqlanmagan (javobsiz), boshqa qurilmada o'chirilgan yoki
        // boshqa odamniki. O'chirilgan suhbat kaliti bilan savol uni QAYTA
        // TIRILTIRARDI - shuning uchun yangi kalit.
        chats = chats.filter((c) => c.chat_id !== id);
        if (currentChatId() === id) keep(CHAT_KEY, freshChatId());
        if (loud) setNote('Suhbat topilmadi — yangi suhbat boshlandi', 'warn');
        return;
      }
      if (loud) setNote('Suhbat ochilmadi: ' + errorText(err), 'warn');
    }
  }

  /** Ilova ochilganda oxirgi suhbat ekranga QAYTADI. Kalit ilgari ham
   *  saqlanardi va xizmat suhbatni eslab turardi, lekin ekran bo'sh edi -
   *  odam davom etayotgan suhbatni ko'rmasdi. */
  function loadCurrentChat() {
    const id = currentChatId();
    if (id) void showChat(id, false);
  }

  /** O'chirish - darhol ro'yxatdan chiqadi, serverda YUMSHOQ o'chiriladi va
   *  "Bekor qilish" ochiladi. Server rad etsa qator qaytariladi. */
  async function removeChat(id) {
    const row = chats.find((c) => c.chat_id === id);
    if (!row) return;
    chats = chats.filter((c) => c.chat_id !== id);
    renderHistory();
    try {
      await chatsApi.remove(id);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) { sessionExpired(); return; }
      chats = chats.concat([row]).sort(byActivity);
      renderHistory();
      flashNote(errorText(err));
      return;
    }
    // Ochiq suhbat o'chirildi - ekran yangi suhbatga o'tadi (vebdagi kabi).
    // Eski kalit bilan savol berish o'chirilganni qayta tiriltirardi.
    if (currentChatId() === id) {
      cancelTurn();
      openRequest++;
      keep(CHAT_KEY, freshChatId());
      clearLog();
    }
    lastDeleted = row;
    histUndo.hidden = false;
    clearTimeout(undoTimer);
    undoTimer = setTimeout(hideUndo, UNDO_MS);
  }

  function hideUndo() {
    clearTimeout(undoTimer);
    undoTimer = 0;
    lastDeleted = null;
    histUndo.hidden = true;
  }

  /** "Bekor qilish": suhbat nomi va xabarlari bilan qaytadi. */
  async function undoDelete() {
    const row = lastDeleted;
    if (!row) return;
    hideUndo();
    try {
      const restored = await chatsApi.restore(row.chat_id);
      chats = chats.filter((c) => c.chat_id !== row.chat_id).concat([restored || row]).sort(byActivity);
      renderHistory();
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) { sessionExpired(); return; }
      // 404: hech qachon bo'lmagan - qaytaradigan narsa yo'q, jim.
      if (err instanceof ApiError && err.status === 404) return;
      flashNote(errorText(err));
    }
  }

  /** Nomini o'zgartirish - darhol ko'rinadi, server rad etsa qaytariladi.
   *  Shundan keyin model nomni qayta yozmaydi (`title_source: user`). */
  async function renameChat(id, raw) {
    const row = chats.find((c) => c.chat_id === id);
    const title = String(raw || '').replace(/\s+/g, ' ').trim().slice(0, 80);
    if (!row || !title || title === row.title) { renderHistory(); return; }
    const before = { title: row.title, title_source: row.title_source };
    row.title = title;
    row.title_source = 'user';
    renderHistory();
    try {
      const saved = await chatsApi.rename(id, title);
      if (saved && saved.title) Object.assign(row, saved);
      renderHistory();
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) { sessionExpired(); return; }
      Object.assign(row, before);
      renderHistory();
      flashNote(errorText(err));
    }
  }

  /** Chiqishda va sessiya tugaganda: keyingi odam eski ro'yxatni bir lahza
   *  ham ko'rmasin. */
  function resetHistory() {
    listRequest++;
    openRequest++;
    chats = [];
    chatsState = 'idle';
    editingId = null;
    hideUndo();
    histNote.hidden = true;
    historySheet.hidden = true;
  }

  historyBtn.addEventListener('click', openHistory);
  historyClose.addEventListener('click', closeHistory);
  historySheet.addEventListener('click', (e) => { if (e.target === historySheet) closeHistory(); });
  newChatBtn.addEventListener('click', startNewChat);
  histUndoBtn.addEventListener('click', () => { void undoDelete(); });

  /* --- Manbalar xotirasi (`apps/web/src/sourcesCache.ts` nusxasi) ---------
     Yordamchining tarixi har xabar uchun faqat rol, matn va vaqtni saqlaydi
     - iqtiboslar YO'Q. Server tuzatilguncha ular SHU qurilmada eslab
     qolinadi: suhbat kaliti + javob matnining boshi (120 belgi) bo'yicha.
     Boshqa qurilmada (yoki vebda) ochilgan suhbatda manbalar bo'lmaydi.
     Faqat hujjat nomi va beti - token yoki javob matni yozilmaydi. */
  const SRC_KEY = 'venera_tg_sources';
  /** Shuncha suhbatdan ortig'i - eng eskisi o'chiriladi (localStorage kichik). */
  const SRC_MAX_CHATS = 60;

  function srcLoad() {
    try {
      const raw = store(SRC_KEY);
      const parsed = raw ? JSON.parse(raw) : {};
      return (parsed && typeof parsed === 'object') ? parsed : {};
    } catch (e) { return {}; }
  }

  function srcSave(data) {
    try { keep(SRC_KEY, JSON.stringify(data)); } catch (e) { /* to'lgan - eslanmaydi */ }
  }

  function srcKey(answer) {
    return (answer || '').trim().slice(0, 120);
  }

  /** Javob keldi - manbalarini shu suhbat ostida eslab qol. */
  function rememberSources(id, answer, docs) {
    const key = srcKey(answer);
    if (!id || !key || !docs || !docs.length) return;
    const data = srcLoad();
    const entry = (data[id] && Array.isArray(data[id].turns)) ? data[id] : { at: 0, turns: [] };
    const i = entry.turns.findIndex((t) => t && t.key === key);
    const turn = { key: key, docs: docs };
    if (i >= 0) entry.turns[i] = turn; else entry.turns.push(turn);
    entry.at = Date.now();
    data[id] = entry;
    const ids = Object.keys(data);
    if (ids.length > SRC_MAX_CHATS) {
      ids.sort((a, b) => ((data[a] && data[a].at) || 0) - ((data[b] && data[b].at) || 0));
      for (const old of ids.slice(0, ids.length - SRC_MAX_CHATS)) delete data[old];
    }
    srcSave(data);
  }

  /** Qayta ochilgan javob uchun manbalar, bo'lsa. `data` - oldindan
   *  o'qilgan xotira: suhbat ochilganda u HAR JAVOB uchun qayta o'qilmasin. */
  function recallSources(id, answer, data) {
    const entry = (data || srcLoad())[id];
    if (!entry || !Array.isArray(entry.turns)) return null;
    const key = srcKey(answer);
    const turn = entry.turns.filter((t) => t && t.key === key)[0];
    return turn && Array.isArray(turn.docs) ? turn.docs : null;
  }

  /** Chiqishda - hammasi (`logout`). */
  function forgetSources() { drop(SRC_KEY); }

  // =========================================================================
  // 12c. Hujjatni yuklab olish - Telegram'ning o'z yuklab olgichi bilan
  // =========================================================================
  // NEGA `<a download>` EMAS (veb ilovadagi kabi). Telegram WebView ichida
  // `blob:` havola bilan yuklab olish ishonchsiz: iOS uni umuman bajarmaydi,
  // Android esa Telegram versiyasiga bog'liq. `WebApp.downloadFile` (Bot API
  // 8.0) faylni Telegram ilovasining O'ZI yuklaydi va saqlashni taklif
  // qiladi - lekin u bizning `Authorization` sarlavhamizni yubora olmaydi.
  // Shuning uchun server avval 10 daqiqalik imzolangan havola beradi
  // (`POST .../link`, sessiya bilan), Telegram esa faylni shu havoladan
  // tokensiz oladi. Havola faqat shu bitta fayl uchun va API'ga kira olmaydi.

  const FILE_KINDS = [['docx', 'DOCX'], ['pdf', 'PDF']];

  /** Hujjat nomi - veb ilovadagi kabi sarlavhadan. Server uni yana
   *  tozalaydi va kengaytmani fayl turiga qarab o'zi qo'yadi. */
  function artifactName(art) {
    return String(art.title || art.filename || 'ariza').trim() || 'ariza';
  }

  /** "Hujjat tayyorlandi" qatori va har fayl turi uchun tugma. Havolasi
   *  yo'q tur ko'rsatilmaydi: backend o'gira olmagan havolani olib
   *  tashlaydi, o'lik tugmadan esa yo'q tugma yaxshi. */
  function showArtifact(art) {
    const name = artifactName(art);
    const files = FILE_KINDS.filter((k) => typeof art[k[0] + '_url'] === 'string' && art[k[0] + '_url']);
    const el = addMsg('system', 'Hujjat tayyorlandi: ' + name);
    if (!files.length) {
      el.appendChild(document.createTextNode('. Uni veb ilovadan yuklab oling.'));
      return;
    }
    const row = document.createElement('span');
    row.className = 'files';
    for (const [kind, label] of files) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'btn sm ghost';
      b.textContent = label + ' yuklab olish';
      b.addEventListener('click', () => { void saveArtifact(art[kind + '_url'], name, b, label); });
      row.appendChild(b);
    }
    el.appendChild(row);
    log.scrollTop = log.scrollHeight;
  }

  /** Faylni saqlash: imzolangan havola -> Telegram yuklab olgichi.
   *  Eski Telegram'da (`downloadFile` yo'q) havola tashqi brauzerda ochiladi
   *  va u faylni `Content-Disposition: attachment` bo'yicha o'zi saqlaydi. */
  async function saveArtifact(path, name, button, label) {
    if (button.disabled) return;
    button.disabled = true;
    button.textContent = 'Tayyorlanmoqda…';
    try {
      const link = await apiFetch(path + '/link', { method: 'POST', body: JSON.stringify({ filename: name }) });
      const url = location.origin + link.url;
      if (!openDownload(url, link.filename)) {
        setNote('Faylni saqlab bo\'lmadi - uni veb ilovadan yuklab oling', 'warn');
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) { sessionExpired(); return; }
      setNote('Fayl tayyorlanmadi: ' + errorText(err), 'warn');
    } finally {
      button.disabled = false;
      button.textContent = label + ' yuklab olish';
    }
  }

  /** `true` - yuklab olish boshlandi (yoki Telegram oynasi ochildi). */
  function openDownload(url, filename) {
    if (tg && typeof tg.downloadFile === 'function' &&
        typeof tg.isVersionAtLeast === 'function' && tg.isVersionAtLeast('8.0')) {
      try {
        tg.downloadFile({ url: url, file_name: filename });
        return true;
      } catch (e) { /* pastdagi zaxiraga */ }
    }
    if (tg && typeof tg.openLink === 'function') {
      try {
        tg.openLink(url);
        return true;
      } catch (e) { /* pastdagi zaxiraga */ }
    }
    if (tg) return false;
    // Telegram'dan tashqarida (oddiy brauzerda sinash) - oddiy havola.
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.rel = 'noopener';
    document.body.appendChild(a);
    a.click();
    a.remove();
    return true;
  }

  // =========================================================================
  // 13. Kiritishlar
  // =========================================================================
  /** Turn ketyaptimi - ya'ni yuborish tugmasi "to'xtatish" bo'lishi kerakmi. */
  function busy() {
    return state === 'listening' || state === 'transcribing' ||
           state === 'thinking' || state === 'speaking';
  }

  /** Ketayotgan turnni bekor qiladi. `turnId++` MUHIM: oqim javobi keyin
   *  kelsa ham, u eski turn deb tashlanadi. */
  function cancelTurn() {
    if (aborter) aborter.abort();
    stopSpeaking();
    turnId++;
    teardown();
    setState('idle');
  }

  /** Qo'lda yozilgan savolni yuboradi.
   *
   *  Ovozli yo'ldan farqi faqat boshida: STT yo'q, ya'ni matn tayyor.
   *  Qolgani AYNI O'SHA yo'l (`ask`), shuning uchun turn raqami, bekor
   *  qilgich va holat mashinasi bitta joyda qoladi. */
  function sendText(raw) {
    const text = (raw || '').trim();
    if (!text) return false;
    // Band bo'lsa yubormaymiz: xizmat bir vaqtda 4 ta so'rov ko'taradi va
    // navbatni o'zimiz uzaytirishning ma'nosi yo'q. Tugma bunday paytda
    // allaqachon "to'xtatish" bo'lib turadi.
    if (busy()) return false;
    setNote('');
    pendingQuestion = '';
    if (aborter) aborter.abort();
    aborter = new AbortController();
    const turn = ++turnId;
    addMsg('you', text);
    ask(text, turn, false);
    return true;
  }

  /** Matn maydoni mazmuniga qarab o'sadi, `max-height` gacha. */
  function resize() {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 110) + 'px';
  }

  /** Tugmaning ko'rinishi UCH holatdan kelib chiqadi: band / matn bor /
   *  bo'sh. Bitta joyda hisoblanadi - aks holda holatlar ajralib ketardi. */
  function syncSend() {
    const on = busy();
    sendBtn.classList.toggle('busy', on);
    sendBtn.classList.toggle('ready', !on && input.value.trim().length > 0);
    sendBtn.setAttribute('aria-label', on ? 'To\'xtatish' : 'Yuborish');
    sendBtn.title = on ? 'To\'xtatish' : 'Yuborish';
  }

  input.addEventListener('input', () => { resize(); syncSend(); });
  // Klaviatura sahifani qisqartiradi - oxirgi xabar ko'rinmay qolmasin.
  // Kechikish ATAYLAB: o'lcham fokus paytida emas, klaviatura ochilib
  // bo'lgandan keyin o'zgaradi.
  input.addEventListener('focus', () => {
    setTimeout(() => { log.scrollTop = log.scrollHeight; }, 300);
  });
  input.addEventListener('keydown', (e) => {
    // Enter yuboradi, Shift+Enter yangi qator. `isComposing` - IME
    // (masalan kirill yoki emoji tanlagich) so'z terayotganda Enter
    // TANLASH uchun bosiladi, yuborish uchun emas.
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      if (sendText(input.value)) { input.value = ''; resize(); syncSend(); }
    }
  });

  sendBtn.addEventListener('click', () => {
    if (busy()) { cancelTurn(); syncSend(); return; }
    if (sendText(input.value)) { input.value = ''; resize(); syncSend(); }
  });

  orbWrap.addEventListener('click', () => {
    if (state === 'idle' || state === 'confirm') startListening();
    else if (state === 'listening') stopListening();
    else cancelTurn();
  });

  confirmYes.addEventListener('click', () => {
    if (state !== 'confirm' || !pendingQuestion) return;
    setNote('');
    ask(pendingQuestion, turnId, true);
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
  // 15. Ulanishlar (HRM, CRM) - `composables/useConnectors.ts`,
  //     `ComposerMenu.vue`, `ConnectorList.vue`, `ConnectorDialog.vue` nusxasi
  // =========================================================================
  // MANBA - SERVER (`/api/v1/connectors`): tokenlar u yerda turadi, sahifa
  // faqat holatni ko'radi (ulanmagan / ulangan / muddati tugagan) va uchta
  // amalni so'raydi: ulanish (login + parol), kalit, uzish.
  //
  // Veb ilovadan farqi FAQAT shaklda: u yerda Vue komponentlari va reaktiv
  // holat, bu yerda oddiy massiv va `render*()` funksiyalari - holat
  // o'zgarganda ro'yxat va oyna qaytadan chiziladi. Matnlar veb ilovaning
  // `i18n.ts` dagi o'zbekcha (lotin) satrlari.
  const plusBtn = $('plusBtn'), cmenu = $('cmenu'), cmenuConnectors = $('cmenuConnectors'), clist = $('clist');
  const cdlg = $('cdlg'), cdlgForm = $('cdlgForm'), cdlgClose = $('cdlgClose'), cdlgBadge = $('cdlgBadge'),
        cdlgTitle = $('cdlgTitle'), cdlgSub = $('cdlgSub'), cdlgError = $('cdlgError'),
        cdlgFields = $('cdlgFields'), cLogin = $('cLogin'), cPassword = $('cPassword'),
        cdlgActions = $('cdlgActions');

  // Ikonkalar `apps/web/src/icons.ts` dan, aynan o'sha chizmalar - ikkala
  // ilova bir xil ko'rinsin. STATIK satrlar, foydalanuvchi matni yo'q,
  // shuning uchun innerHTML xavfsiz (CSP ham ruxsat beradi: bu skript emas).
  const ICONS = {
    users: '<svg viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="7" cy="6" r="2.6"/><path d="M2.5 15a4.5 4.5 0 0 1 9 0"/><path d="M11.5 3.6a2.6 2.6 0 0 1 0 4.8M13.2 11a4.5 4.5 0 0 1 2.8 4"/></svg>',
    board: '<svg viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="2.5" y="3" width="13" height="12" rx="2"/><path d="M6.5 6v5.5M9 6v3M11.5 6v4.5"/></svg>',
    plug: '<svg viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M6.5 2.5V6M11.5 2.5V6"/><path d="M4.5 6h9v2.5a4.5 4.5 0 0 1-9 0V6z"/><path d="M9 13v2.5"/></svg>',
    gear: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>',
    plus: '<svg viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M9 3.5v11M3.5 9h11"/></svg>',
    check: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 8.5l3.2 3L13 5"/></svg>',
    pencil: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"><path d="M11.5 2.5l2 2L5.8 12.2l-2.5 0.5 0.5-2.5 7.7-7.7z"/></svg>',
  };
  function icon(name) {
    const tpl = document.createElement('template');
    tpl.innerHTML = ICONS[name] || ICONS.plug;
    return tpl.content.firstElementChild;
  }
  function make(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  const CONNECTOR_ICONS = { hrm: 'users', crm: 'board' };
  const CONNECTOR_HINTS = { hrm: 'Davomat, xodimlar', crm: 'Vazifalar, loyihalar, sprintlar' };

  // Server javobi kelguncha ko'rinadigan qatorlar: nomlar ma'lum, holat esa
  // "ulanmagan" - menyu bo'sh ochilmasin.
  function placeholder(id, label) {
    return { id, label, configured: true, state: 'disconnected', login: null, enabled: false, expiresAt: null };
  }
  let connectors = [placeholder('hrm', 'HRM'), placeholder('crm', 'CRM')];
  let connectorsFailed = false;
  let connectorsInflight = null;

  function applyStatus(status) {
    const i = connectors.findIndex((c) => c.id === status.id);
    if (i >= 0) connectors[i] = status; else connectors.push(status);
  }
  const findConnector = (id) => connectors.find((c) => c.id === id) || null;

  /** Holatni serverdan oladi. Bir vaqtda ikki chaqiruv bitta so'rovni
   *  bo'lishadi. Xato bo'lsa ro'yxat baribir ko'rinadi (eski/placeholder
   *  holat bilan), qatorlar ostida "holat yuklanmadi" chiqadi. */
  function loadConnectors() {
    if (connectorsInflight) return connectorsInflight;
    connectorsInflight = (async () => {
      try {
        const result = await api.connectors();
        (result && result.connectors || []).forEach(applyStatus);
        connectorsFailed = false;
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) { sessionExpired(); return; }
        connectorsFailed = true;
      } finally {
        connectorsInflight = null;
        renderConnectors();
        if (dialogId) renderDialog();
      }
    })();
    return connectorsInflight;
  }

  /** Chiqishda: holat unutiladi, menyu va oyna yopiladi - keyingi odam
   *  oldingisining hisoblarini ko'rmasin. */
  function resetConnectors() {
    connectors = [placeholder('hrm', 'HRM'), placeholder('crm', 'CRM')];
    connectorsFailed = false;
    closeDialog();
    closeComposer();
  }

  function connectorHint(c) {
    if (!c.configured) return 'Serverda sozlanmagan';
    if (c.state === 'connected') return c.login || 'Ulangan';
    if (c.state === 'expired') return 'Muddati tugagan';
    return CONNECTOR_HINTS[c.id] || '';
  }
  function connectorTitle(c) {
    if (c.state === 'connected') return (c.login || '') + ' sifatida ulangan';
    if (c.state === 'expired') return 'Qayta ulanish';
    return c.label + ' ga ulanish';
  }

  /** HRM / CRM qatorlari. Ulanmagan yoki muddati tugagan qatorda "+"
   *  (ulanish oynasini ochadi), ulanganida kalit (chatda ishlatish /
   *  ishlatmaslik) va tishli g'ildirak (hisob oynasi: uzish). */
  function renderConnectors() {
    clist.textContent = '';
    for (const c of connectors) {
      const row = make('div', 'crow' +
        (c.state === 'connected' && c.enabled ? ' is-on' : '') +
        (c.configured ? '' : ' is-unavailable'));

      // Nom + izoh: bosilsa ulanish (ulangan bo'lsa - hisob) oynasi ochiladi.
      const main = make('button', 'crow-main');
      main.type = 'button';
      main.title = connectorTitle(c);
      main.disabled = !c.configured;
      main.appendChild(icon(CONNECTOR_ICONS[c.id]));
      const text = make('span', 'crow-text');
      text.appendChild(make('span', 'crow-name', c.label));
      const hint = make('span', 'crow-hint');
      if (c.configured && c.state !== 'disconnected') {
        const dot = make('span', 'crow-dot' + (c.state === 'expired' ? ' is-expired' : ''));
        dot.setAttribute('aria-hidden', 'true');
        hint.appendChild(dot);
      }
      hint.appendChild(document.createTextNode(connectorHint(c)));
      text.appendChild(hint);
      main.appendChild(text);
      main.addEventListener('click', () => openDialog(c.id));
      row.appendChild(main);

      // Tishli g'ildirak: hisob oynasi (uzish, qayta kirish). Ulanmagan
      // qatorda yo'q - u yerda "+" ning o'zi oynani ochadi.
      if (c.configured && c.state !== 'disconnected') {
        const gear = make('button', 'crow-gear');
        gear.type = 'button';
        gear.title = 'Sozlamalar';
        gear.setAttribute('aria-label', c.label + ': Sozlamalar');
        gear.appendChild(icon('gear'));
        gear.addEventListener('click', () => openDialog(c.id));
        row.appendChild(gear);
      }

      // Ulangan: kalit. Aks holda "+" - ulanish yoki qayta ulanish.
      if (c.state === 'connected') {
        const sw = make('button', 'switch');
        sw.type = 'button';
        sw.setAttribute('role', 'switch');
        sw.setAttribute('aria-checked', c.enabled ? 'true' : 'false');
        sw.setAttribute('aria-label', c.label);
        const knob = make('span', 'switch-knob');
        knob.setAttribute('aria-hidden', 'true');
        sw.appendChild(knob);
        sw.addEventListener('click', () => toggleConnector(c.id));
        row.appendChild(sw);
      } else {
        const add = make('button', 'crow-connect');
        add.type = 'button';
        add.title = c.state === 'expired' ? 'Qayta ulanish' : 'Ulanish';
        add.setAttribute('aria-label', connectorTitle(c));
        add.disabled = !c.configured;
        add.appendChild(icon('plus'));
        add.addEventListener('click', () => openDialog(c.id));
        row.appendChild(add);
      }
      clist.appendChild(row);
    }
    if (connectorsFailed) {
      const p = make('p', 'clist-note', 'Ulanishlar holati yuklanmadi');
      p.setAttribute('role', 'status');
      clist.appendChild(p);
    }
  }

  /** Kalit: darhol ko'rinadi (optimistik), server rad etsa qaytariladi. */
  async function toggleConnector(id) {
    const c = findConnector(id);
    if (!c || c.state !== 'connected') return;
    const wanted = !c.enabled;
    c.enabled = wanted;
    renderConnectors();
    haptic('light');
    try {
      applyStatus(await api.setConnector(id, wanted));
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) { sessionExpired(); return; }
      c.enabled = !wanted;
    }
    renderConnectors();
  }

  // --- "+" menyusi -------------------------------------------------------
  let composerOpen = false, connectorsOpen = false;

  function openComposer() {
    if (composerOpen) return;
    composerOpen = true;
    cmenu.hidden = false;
    plusBtn.setAttribute('aria-expanded', 'true');
    // Har ochilishda holat serverdan yangilanadi: HRM sessiyasi 10 soatda
    // tugaydi, CRM refresh rad etilishi mumkin - ro'yxat buni ko'rsatishi kerak.
    renderConnectors();
    loadConnectors();
  }
  function closeComposer() {
    if (!composerOpen) return;
    composerOpen = false;
    setConnectorsOpen(false);
    cmenu.hidden = true;
    plusBtn.setAttribute('aria-expanded', 'false');
  }
  /** "Ulanishlar" qatori ostidagi ro'yxat - veb ilovadagi mobil ko'rinish. */
  function setConnectorsOpen(on) {
    connectorsOpen = on;
    clist.hidden = !on;
    cmenuConnectors.classList.toggle('is-active', on);
    cmenuConnectors.setAttribute('aria-expanded', on ? 'true' : 'false');
  }

  plusBtn.addEventListener('click', () => {
    haptic('light');
    if (composerOpen) closeComposer(); else openComposer();
  });
  cmenuConnectors.addEventListener('click', () => setConnectorsOpen(!connectorsOpen));

  // Tashqariga bosilsa yopiladi. "+" tugmasi menyuning bir qismi deb
  // hisoblanadi - aks holda u menyuni yopib, keyin darhol qayta ochardi.
  // Oyna ochiqligida tekshiruv o'chiq: oyna menyuning ustida, DOM'da esa
  // tashqarida.
  document.addEventListener('pointerdown', (e) => {
    if (!composerOpen || dialogId) return;
    if (cmenu.contains(e.target) || plusBtn.contains(e.target)) return;
    closeComposer();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape' || e.isComposing) return;
    if (dialogId) closeDialog();
    else if (composerOpen) closeComposer();
  });

  // --- ulanish oynasi ----------------------------------------------------
  // Login + parol, saytning o'zida (tashqi sahifaga yubormaydi). Ulangan
  // tizim uchun hisob ko'rsatiladi va "Uzish" bor; muddati tugagan bo'lsa
  // yana kirish shakli, login to'ldirilgan holda. Uzish IKKI bosqichli:
  // "Uzish" -> "Haqiqatan ham?" - uzilgan hisobni qaytarish uchun yana
  // login va parol kerak, tasodifiy bosish qimmat.
  let dialogId = null, dialogBusy = false, dialogConfirming = false, dialogOpener = null;

  function openDialog(id) {
    const c = findConnector(id);
    if (!c || !c.configured) return;
    dialogId = id;
    dialogBusy = false;
    dialogConfirming = false;
    dialogOpener = document.activeElement;
    // Qayta kirishda login oldindan to'ldirilgan - odam faqat parol yozadi.
    cLogin.value = c.login || '';
    cPassword.value = '';
    showDialogError('');
    renderDialog();
    cdlg.hidden = false;
    haptic('light');
    if (c.state !== 'connected') (cLogin.value ? cPassword : cLogin).focus();
  }
  function closeDialog() {
    if (!dialogId) return;
    dialogId = null;
    dialogConfirming = false;
    cdlg.hidden = true;
    cPassword.value = '';
    // Fokus oynani ochgan tugmaga qaytadi.
    if (dialogOpener && dialogOpener.isConnected && typeof dialogOpener.focus === 'function') dialogOpener.focus();
    dialogOpener = null;
  }
  function showDialogError(text) {
    cdlgError.textContent = text || '';
    cdlgError.hidden = !text;
  }
  function dialogButton(label, cls, onClick) {
    const b = make('button', 'btn sm' + (cls ? ' ' + cls : ''), label);
    b.type = 'button';
    b.disabled = dialogBusy;
    b.addEventListener('click', onClick);
    return b;
  }

  function renderDialog() {
    const c = findConnector(dialogId);
    if (!c) { closeDialog(); return; }
    const connected = c.state === 'connected';
    const expired = c.state === 'expired';

    cdlgBadge.textContent = '';
    cdlgBadge.appendChild(icon(CONNECTOR_ICONS[c.id]));
    if (dialogConfirming) {
      cdlgTitle.textContent = c.label + ' dan uzilasizmi?';
      cdlgSub.textContent = 'Venera ' + c.label + ' dan javob bermay qo\'yadi. Qayta ulash uchun login va parol kerak bo\'ladi.';
    } else if (connected) {
      cdlgTitle.textContent = c.label;
      cdlgSub.textContent = (c.login || '') + ' sifatida ulangan';
    } else {
      cdlgTitle.textContent = c.label + ' ga ulanish';
      cdlgSub.textContent = expired
        ? c.label + ' sessiyasining muddati tugagan. Qayta kiring.'
        : c.label + ' hisobingiz bilan kiring.';
    }

    cdlgFields.hidden = connected;
    cLogin.disabled = cPassword.disabled = dialogBusy;
    cdlgActions.textContent = '';
    if (!connected) {
      cdlgActions.appendChild(dialogButton('Bekor qilish', 'ghost', closeDialog));
      const submit = make('button', 'btn sm', dialogBusy ? 'Ulanmoqda…' : expired ? 'Qayta ulanish' : 'Ulanish');
      submit.type = 'submit';
      submit.disabled = dialogBusy;
      cdlgActions.appendChild(submit);
    } else if (dialogConfirming) {
      cdlgActions.appendChild(dialogButton('Yo\'q', 'ghost', () => { dialogConfirming = false; renderDialog(); }));
      cdlgActions.appendChild(dialogButton(dialogBusy ? 'Uzilmoqda…' : 'Ha, uzish', 'danger filled', onDisconnect));
    } else {
      cdlgActions.appendChild(dialogButton('Yopish', 'ghost', closeDialog));
      cdlgActions.appendChild(dialogButton('Uzish', 'danger', () => {
        dialogConfirming = true;
        showDialogError('');
        renderDialog();
      }));
    }
  }

  /** Xato matni: server xabari bo'lsa - o'sha; tarmoq/noma'lum xato bo'lsa
   *  umumiy "ulanib bo'lmadi". 401 bu yerda VENERA sessiyasi (platforma
   *  paroli xato bo'lsa server 400 qaytaradi), ya'ni qayta kirish kerak. */
  function dialogFail(err) {
    if (err instanceof ApiError && err.status === 401) { sessionExpired(); return; }
    showDialogError(err instanceof ApiError ? errorText(err) : 'Ulanib bo\'lmadi. Login va parolni tekshiring.');
  }

  cdlgForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const c = findConnector(dialogId);
    if (!c || c.state === 'connected' || dialogBusy) return;
    const login = cLogin.value.trim();
    const password = cPassword.value;
    if (!login || !password) { showDialogError('Login va parolni kiriting'); return; }
    dialogBusy = true;
    showDialogError('');
    renderDialog();
    try {
      applyStatus(await api.connect(c.id, login, password));
      cPassword.value = '';
      haptic('medium');
      closeDialog();
    } catch (err) {
      dialogFail(err);
    } finally {
      dialogBusy = false;
      if (dialogId) renderDialog();
      renderConnectors();
    }
  });

  async function onDisconnect() {
    const c = findConnector(dialogId);
    if (!c || dialogBusy) return;
    dialogBusy = true;
    showDialogError('');
    renderDialog();
    try {
      applyStatus(await api.disconnect(c.id));
      haptic('medium');
      closeDialog();
    } catch (err) {
      dialogConfirming = false;
      dialogFail(err);
    } finally {
      dialogBusy = false;
      if (dialogId) renderDialog();
      renderConnectors();
    }
  }

  cdlgClose.addEventListener('click', closeDialog);
  // Fon: faqat o'ziga bosilganda yopadi (kartada boshlangan sudrash
  // tashqarida tugasa - yopilmaydi, shuning uchun pointerdown, click emas).
  cdlg.addEventListener('pointerdown', (e) => { if (e.target === cdlg) closeDialog(); });

  // =========================================================================
  // 16. Taklif kartasi (yozuv amali) - `components/ActionCard.vue` nusxasi
  // =========================================================================
  // Yordamchi TAKLIF qilgan yozuv amali (masalan CRM da vaqt yozish).
  // HECH NARSA O'ZGARMAGAN: chat turi faqat taklif qiladi, o'zgarish faqat
  // shu yerda "Tasdiqlash" bosilganda bo'ladi. Karta nima o'zgarishini
  // ko'rsatadi (xulosa, obyekt, maydonlar: eski -> yangi, ogohlantirishlar)
  // va ikki tugma beradi. Rad etish tasdiqsiz: u xavfsiz, hech narsa qilmaydi.
  // Holat kartaning o'zida (yopilma ichida) - har taklif o'z natijasini saqlaydi.

  /** Qiymatning ko'rinadigan matni: obyekt bo'lsa nomi/kaliti. */
  function actionText(value) {
    if (value == null || value === '') return '—';
    if (typeof value === 'object') {
      const name = value.title != null ? value.title
        : value.name != null ? value.name
        : value.key != null ? value.key
        : value.id;
      return name != null ? String(name) : JSON.stringify(value);
    }
    return String(value);
  }

  /** Yakuniy holat: tugmalar yo'qoladi, natija qoladi. */
  function actionOutcome(r) {
    if (r.status === 'executed' && r.ok !== false) return { tone: 'ok', label: 'Bajarildi' };
    if (r.status === 'cancelled') return { tone: 'muted', label: 'Rad etildi' };
    if (r.status === 'expired') return { tone: 'warn', label: 'Muddati tugagan' };
    if (r.status === 'pending') return null;
    return { tone: 'bad', label: 'Bajarilmadi' };
  }

  function renderProposal(host, proposal) {
    const card = make('section', 'act');
    card.setAttribute('aria-label', 'Taklif qilingan o\'zgarish');
    const platform = String(proposal.connector || '').toLowerCase();

    const head = make('header', 'act-head');
    head.appendChild(icon(CONNECTOR_ICONS[platform] || 'pencil'));
    head.appendChild(make('span', 'act-title', 'Taklif qilingan o\'zgarish'));
    if (platform) head.appendChild(make('span', 'act-platform', platform.toUpperCase()));
    const status = make('span', 'act-status');
    status.hidden = true;
    head.appendChild(status);
    card.appendChild(head);

    if (proposal.summary) card.appendChild(make('p', 'act-summary', String(proposal.summary)));

    const target = proposal.target ? actionText(proposal.target) : '';
    const changes = (proposal.changes || []).filter((c) => c && (c.field || c.to !== undefined));
    if (target || changes.length) {
      const dl = make('dl', 'act-details');
      const row = (label, fill) => {
        dl.appendChild(make('dt', null, label));
        const dd = make('dd');
        fill(dd);
        dl.appendChild(dd);
      };
      if (target) row('Obyekt', (dd) => { dd.textContent = target; });
      for (const c of changes) {
        row(c.field || 'O\'zgarish', (dd) => {
          if (c.from !== undefined && c.from !== null && c.from !== '') {
            dd.appendChild(make('s', 'act-from', actionText(c.from)));
            const arrow = make('span', 'act-arrow', '→');
            arrow.setAttribute('aria-hidden', 'true');
            dd.appendChild(arrow);
          }
          dd.appendChild(make('span', 'act-to', actionText(c.to)));
        });
      }
      card.appendChild(dl);
    }

    if (proposal.warnings && proposal.warnings.length) {
      const ul = make('ul', 'act-warnings');
      for (const w of proposal.warnings) ul.appendChild(make('li', null, String(w)));
      card.appendChild(ul);
    }

    // Natija: bajarilgan bo'lsa platforma nima qaytargani, yiqilgan bo'lsa sababi.
    const bad = make('p', 'act-bad');
    bad.setAttribute('role', 'alert');
    bad.hidden = true;
    card.appendChild(bad);
    const resultEl = make('p', 'act-result');
    resultEl.hidden = true;
    card.appendChild(resultEl);

    const foot = make('footer', 'act-foot');
    foot.appendChild(make('span', 'act-hint', 'Tasdiqlamaguningizcha hech narsa o\'zgarmaydi. Taklif 15 daqiqada kuchini yo\'qotadi.'));
    const buttons = make('div', 'act-buttons');
    const reject = make('button', 'btn sm ghost', 'Rad etish');
    reject.type = 'button';
    // Tasdiqlash - to'ldirilgan: bu javobning yagona haqiqiy "qil" tugmasi.
    const confirm = make('button', 'btn sm', 'Tasdiqlash');
    confirm.type = 'button';
    buttons.appendChild(reject);
    buttons.appendChild(confirm);
    foot.appendChild(buttons);
    card.appendChild(foot);

    let busy = null, settled = false;
    async function run(kind) {
      if (busy || settled) return;
      busy = kind;
      bad.hidden = true;
      reject.disabled = confirm.disabled = true;
      if (kind === 'confirm') confirm.textContent = 'Bajarilmoqda…'; else reject.textContent = 'Rad etilmoqda…';
      try {
        const r = await (kind === 'confirm' ? api.confirmAction : api.cancelAction)(proposal.token);
        const o = actionOutcome(r);
        settled = r.status === 'executed' || r.status === 'cancelled' || r.status === 'expired' || r.status === 'failed';
        if (o) {
          status.hidden = false;
          status.className = 'act-status is-' + o.tone;
          status.textContent = '';
          if (o.tone === 'ok') status.appendChild(icon('check'));
          status.appendChild(document.createTextNode(o.label));
          card.classList.add('is-' + o.tone);
          if (o.tone === 'ok' && r.result) {
            // Platforma qaytargan ko'rsatkich, masalan yaratilgan vazifa kaliti.
            const key = r.result.key != null ? r.result.key : r.result.id != null ? r.result.id : r.result.number;
            if (key != null) { resultEl.textContent = String(key); resultEl.hidden = false; }
          }
          if (o.tone === 'bad') { bad.textContent = r.error || 'Amalni bajarib bo\'lmadi.'; bad.hidden = false; }
        }
        if (settled) foot.remove();
        haptic(o && o.tone === 'ok' ? 'medium' : 'light');
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) { sessionExpired(); return; }
        bad.textContent = errorText(err);
        bad.hidden = false;
      } finally {
        busy = null;
        if (!settled) {
          reject.disabled = confirm.disabled = false;
          reject.textContent = 'Rad etish';
          confirm.textContent = 'Tasdiqlash';
        }
        log.scrollTop = log.scrollHeight;
      }
    }
    reject.addEventListener('click', () => run('cancel'));
    confirm.addEventListener('click', () => run('confirm'));

    host.appendChild(card);
    log.scrollTop = log.scrollHeight;
    return card;
  }

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
