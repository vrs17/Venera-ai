/**
 * Gap boshlanishi/tugashini aniqlash (VAD) va Barno gapirayotganda bo'lib gapirish
 * ("barge-in") - expo-audio metering (dBFS cho'qqi, har 60 ms) asosida.
 *
 * NIMA UCHUN metering (xom PCM emas): expo-audio'ning xom oqimi (`AudioStream`) oddiy MIC
 * manbasidan yozadi - aks-sado bekor qilish (AEC) yo'q. `voice_communication` manbali
 * yozuvchi esa AEC beradi va har o'lchovda cho'qqini qaytaradi - bizga shu yetadi.
 *
 * Shovqin sathi (floor) moslashadi: jim xonada chegara -40, shovqinli ofisda -18 gacha.
 * Hysteresis (boshlash -6 dB pastroqda tugaydi) - gap ichidagi past bo'g'inlar uzib
 * yubormasin. 1 s jimlik - gap tugadi ("taxminan 1 soniya").
 *
 * Shovqinli ofis: qabul qilingan (STT tanigan) gaplardan odamning O'Z ovozi balandligi
 * o'rganiladi. Xona shovqinli bo'lsa, undan 12 dB pastdagi ovoz (yonidagi hamkasb) gap
 * deb olinmaydi - telefonga yaqin gapirgan egasining ovozi doim balandroq.
 */
import { FRAME_MS, MAX_UTTERANCE_MS } from './limits';
import type { MicFrame } from './ports';

export type VadMode = 'listen' | 'thinking' | 'thinking_hold' | 'speaking' | 'off';
export type VadEvent =
  | { type: 'speech_start'; atMs: number }
  | { type: 'speech_end'; fromMs: number; toMs: number; voicedMs: number; levelDb: number }
  | { type: 'max_reached'; fromMs: number; toMs: number; voicedMs: number; levelDb: number }
  | { type: 'speech_discard' }
  | { type: 'barge_in'; atMs: number };

export interface VadContext {
  mode: VadMode;
  /** Ijro etilayotgan klipning so'nggi ~160 ms dagi eng baland CHO'QQISI (dBFS); hech narsa o'ynamasa null. */
  outDbMax: number | null;
  clipAgeMs: number;
  earpiece: boolean;
  /** Klip tugaganidan keyingi qisqa oyna - xona aks-sadosi gap deb olinmasin. */
  guard: boolean;
}

export interface Vad {
  push(frame: MicFrame, ctx: VadContext): VadEvent | null;
  /** Yangi segment (vaqt o'qi noldan) - o'rganilgan shovqin va aks-sado saqlanadi. */
  reset(): void;
  /** Bo'lib gapirish shovqin bo'lib chiqdi (o'z ovozini eshitgan) - chegara ko'tariladi. */
  noteDiscardAfterBarge(): void;
  /** STT tanigan (ishonchli) gapning balandligi - egasining ovozi shu atrofda. */
  noteUserLevel(db: number): void;
  readonly floorDb: number;
  readonly startDb: number;
  readonly inSpeech: boolean;
  /** Bo'lib gapirish nomzodi yig'ilyapti - tuman Barno rangiga o'tmasin. */
  readonly bargeBuilding: boolean;
  readonly bargeExtraDb: number;
  readonly couplingDb: number | null;
  readonly userLevelDb: number | null;
}

export const VAD = {
  FLOOR_INIT_DB: -50,
  FLOOR_MIN_DB: -65,
  FLOOR_MAX_DB: -24,
  START_ABOVE_FLOOR: 14,
  START_MIN_DB: -40,
  START_MAX_DB: -18,
  HYSTERESIS_DB: 6,
  HANGOVER_MS: 1000,
  MIN_VOICED_MS: 300,
  MIN_UTTERANCE_MS: 500,
  /** Klip tugagach (guard) va hech narsa o'ynamayotganda bo'lib gapirish chegarasi = START + 4. */
  QUIET_BARGE_ABOVE_START: 4,
  BARGE_MARGIN_DB: 10,
  BARGE_FLOOR_SPEAKER_DB: -30,
  BARGE_FLOOR_EARPIECE_DB: -38,
  COUPLING_SPEAKER_DB: -6,
  COUPLING_EARPIECE_DB: -20,
  COUPLING_MIN_DB: -30,
  COUPLING_MAX_DB: 12,
  /** Klip boshida aks-sado bekor qiluvchi moslashguncha bo'lib gapirish hisoblanmaydi. */
  BARGE_GRACE_MS: 250,
  /**
   * Kalibrlash: sessiyadagi birinchi klip(lar)ning boshida aks-sado SENZURASIZ o'rganiladi.
   * NIMA UCHUN: avval bog'lanish faqat "odam gapirmayotgan" kadrlardan o'rganilardi. Haqiqiy
   * aks-sado chegaradan baland bo'lsa HAR kadr "odam" ko'rinadi va bog'lanish hech qachon
   * ko'tarilmaydi - Barno o'zini 0.5 s da bo'lib qo'yardi. Klip boshidagi ~0.5 s da odam
   * deyarli hech qachon gapirmaydi; o'sha oynada bo'lib gapirish ham hisoblanmaydi.
   */
  CALIBRATE_CLIPS: 4,
  CALIBRATE_FROM_MS: 150,
  CALIBRATE_TO_MS: 700,
  CALIBRATE_RATE: 0.3,
  COUPLING_RATE: 0.08,
  BARGE_EXTRA_STEP_DB: 6,
  BARGE_EXTRA_MAX_DB: 12,
  /** Egasining ovozidan shuncha past ovoz shovqinli xonada gap deb olinmaydi. */
  USER_GATE_BELOW_DB: 12,
  /** Darvoza bundan baland bo'lmaydi (bir marta baland gapirgan odam keyin sekin ham gapira olsin). */
  USER_GATE_MAX_DB: -20,
  /** Darvoza faqat shovqinli xonada (sath shundan baland) ishlaydi - jim xonada sekin gap ham o'tadi. */
  USER_GATE_FLOOR_DB: -45,
  /** Oxirgi 6 kadrdan shunchasi - bargeBuilding (tuman bir martalik yo'taldan rang almashtirmasin). */
  BUILDING_HITS: 3,
  /**
   * Sessiya boshidagi shuncha kadr (~0.6 s) faqat xona sathini o'rganadi. NIMA UCHUN: sath
   * -50 dan boshlanadi; shovqinli ofisda (-36) birinchi kadrlarning o'zi "gap" bo'lib
   * qolardi va 60 s shovqin serverga ketardi.
   */
  WARMUP_FRAMES: 10,
  /**
   * So'nggi ~3 s dagi eng past daraja ham baland bo'lsa - bu uzluksiz shovqin (gap emas,
   * gapda so'zlar orasida doim pauza bor): sath gap ichida ham sekin ko'tariladi.
   */
  MIN_WINDOW_FRAMES: 50,
  MIN_WINDOW_READY: 25,
} as const;

/** Mikrofon "jim" deb qaytargan qiymat (-160) yoki birinchi o'lchov - o'rganishga yaramaydi. */
const SILENT_DB = -100;
/** Gap balandligi uchun saqlanadigan ovozli kadrlar (60 s / 60 ms). */
const MAX_LEVEL_FRAMES = 1000;

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

function median(xs: number[]): number {
  if (!xs.length) return -160;
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.floor(s.length / 2)];
}

export function createVad(): Vad {
  let floor: number = VAD.FLOOR_INIT_DB;
  let coupling: number | null = null;
  let couplingEarpiece: boolean | null = null;
  let extra = 0;
  let discards = 0;
  let userLevel: number | null = null;

  // --- kalibrlash ---
  let clipsCalibrated = 0;
  let lastClipAge = -1;
  let clipLearned = 0;
  let clipCounted = false;

  let warmLeft: number = VAD.WARMUP_FRAMES;
  let recent: number[] = [];

  let inSpeech = false;
  let onsetAt = 0;
  let lastVoicedAt = 0;
  let voicedMs = 0;
  let voicedDbs: number[] = [];
  let onsetRing: { t: number; hit: boolean; db: number }[] = [];
  let bargeRing: { t: number; hit: boolean; db: number }[] = [];
  /** Bo'lib gapirish aniqlandi - sessiya tinglashga o'tguncha keyingi kadrlar kutiladi. */
  let bargeHold = false;
  let lastMode: VadMode = 'off';

  const baseStart = () => clamp(floor + VAD.START_ABOVE_FLOOR, VAD.START_MIN_DB, VAD.START_MAX_DB);
  /** Shovqinli xonada egasining ovozi darvozasi (o'rganilmagan bo'lsa - oddiy chegara). */
  const startDb = () => {
    const base = baseStart();
    if (userLevel === null || floor < VAD.USER_GATE_FLOOR_DB) return base;
    return Math.max(base, Math.min(userLevel - VAD.USER_GATE_BELOW_DB, VAD.USER_GATE_MAX_DB));
  };

  function learn(db: number) {
    // Pastga tez (0.3), yuqoriga sekin (0.05, ~1.2 s) - bir zumlik shovqin sathni ko'tarmaydi.
    floor += (db < floor ? 0.3 : 0.05) * (db - floor);
    floor = clamp(floor, VAD.FLOOR_MIN_DB, VAD.FLOOR_MAX_DB);
  }

  function resetSpeech() {
    inSpeech = false;
    onsetAt = 0;
    lastVoicedAt = 0;
    voicedMs = 0;
    voicedDbs = [];
    onsetRing = [];
    bargeRing = [];
  }

  function voiced(db: number) {
    voicedMs += FRAME_MS;
    if (db > SILENT_DB && voicedDbs.length < MAX_LEVEL_FRAMES) voicedDbs.push(db);
  }

  function begin(atMs: number, lastMs: number, hits: { db: number }[]) {
    inSpeech = true;
    onsetAt = atMs;
    lastVoicedAt = lastMs;
    voicedMs = 0;
    voicedDbs = [];
    for (const h of hits) voiced(h.db);
  }

  function finish(kind: 'speech_end' | 'max_reached', t: number): VadEvent {
    const fromMs = onsetAt;
    const toMs = kind === 'max_reached' ? t : lastVoicedAt;
    const v = voicedMs;
    const levelDb = median(voicedDbs);
    resetSpeech();
    if (kind === 'max_reached') return { type: 'max_reached', fromMs, toMs, voicedMs: v, levelDb };
    // Qisqa "chirt" (yo'tal, eshik) serverga ketmaydi: uz STT shovqindan ham so'z "eshitadi".
    if (v >= VAD.MIN_VOICED_MS && toMs - fromMs >= VAD.MIN_UTTERANCE_MS) return { type: 'speech_end', fromMs, toMs, voicedMs: v, levelDb };
    return { type: 'speech_discard' };
  }

  /** Uzluksiz shovqin: so'nggi oynaning eng past darajasi sathdan baland - sath unga ko'tariladi. */
  function trackMinimum(db: number) {
    recent.push(db);
    if (recent.length > VAD.MIN_WINDOW_FRAMES) recent.shift();
    // Gap ichida faqat to'liq oyna (~3 s) bo'yicha: so'zlar orasidagi pauza albatta tushadi.
    if (recent.length < (inSpeech ? VAD.MIN_WINDOW_FRAMES : VAD.MIN_WINDOW_READY)) return;
    let m = recent[0];
    for (const x of recent) if (x < m) m = x;
    if (m > floor) floor = clamp(floor + 0.05 * (m - floor), VAD.FLOOR_MIN_DB, VAD.FLOOR_MAX_DB);
  }

  function listen(t: number, db: number, learnable: boolean, guard: boolean): VadEvent | null {
    if (learnable && warmLeft > 0) {
      // Boshlanish: avval xonani eshitamiz (gap emas).
      warmLeft--;
      floor = clamp(floor + 0.3 * (db - floor), VAD.FLOOR_MIN_DB, VAD.FLOOR_MAX_DB);
      return null;
    }
    if (learnable) trackMinimum(db);
    const start = startDb();
    const stop = start - VAD.HYSTERESIS_DB;
    if (!inSpeech) {
      if (learnable && db < baseStart()) learn(db);
      const thr = guard ? start + VAD.QUIET_BARGE_ABOVE_START : start;
      onsetRing.push({ t, hit: db >= thr, db });
      if (onsetRing.length > 4) onsetRing.shift();
      const hits = onsetRing.filter((h) => h.hit);
      if (hits.length >= 3) {
        begin(hits[0].t, hits[hits.length - 1].t, hits);
        onsetRing = [];
        return { type: 'speech_start', atMs: onsetAt };
      }
      return null;
    }
    if (db >= stop) {
      voiced(db);
      lastVoicedAt = t;
    }
    if (t - onsetAt >= MAX_UTTERANCE_MS) return finish('max_reached', t);
    if (t - lastVoicedAt >= VAD.HANGOVER_MS) return finish('speech_end', t);
    return null;
  }

  function barge(frame: MicFrame, db: number, learnable: boolean, ctx: VadContext): VadEvent | null {
    if (coupling === null || couplingEarpiece !== ctx.earpiece) {
      // Quloq <-> karnay: aks-sado butunlay boshqa - qaytadan kalibrlaymiz.
      coupling = ctx.earpiece ? VAD.COUPLING_EARPIECE_DB : VAD.COUPLING_SPEAKER_DB;
      couplingEarpiece = ctx.earpiece;
      clipsCalibrated = 0;
    }
    const playing = ctx.outDbMax !== null;
    let calibrating = false;
    if (playing) {
      if (lastClipAge < 0 || ctx.clipAgeMs < lastClipAge) {
        // Yangi klip boshlandi.
        clipLearned = 0;
        clipCounted = false;
      }
      lastClipAge = ctx.clipAgeMs;
      calibrating = clipsCalibrated < VAD.CALIBRATE_CLIPS && ctx.clipAgeMs < VAD.CALIBRATE_TO_MS;
    } else {
      lastClipAge = -1;
    }
    const out = ctx.outDbMax as number;
    let thr: number;
    if (playing) {
      // Aks-sadoni hisobga olgan chegara: chiqish cho'qqisi + o'rganilgan bog'lanish + zaxira.
      const bottom = ctx.earpiece ? VAD.BARGE_FLOOR_EARPIECE_DB : VAD.BARGE_FLOOR_SPEAKER_DB;
      thr = Math.max(bottom, out + coupling + VAD.BARGE_MARGIN_DB + extra);
    } else {
      thr = startDb() + VAD.QUIET_BARGE_ABOVE_START;
      if (learnable && db < baseStart()) learn(db);
    }
    const grace = playing && (calibrating || ctx.clipAgeMs < VAD.BARGE_GRACE_MS);
    const hit = !grace && learnable && db >= thr;
    if (playing && learnable && out > -45) {
      if (calibrating) {
        if (ctx.clipAgeMs >= VAD.CALIBRATE_FROM_MS) {
          // Senzurasiz: shu oynada har kadr aks-sado deb olinadi (chiqish mikrofonga ~100 ms da yetadi).
          coupling += VAD.CALIBRATE_RATE * (db - out - coupling);
          clipLearned++;
          if (!clipCounted && clipLearned >= 3) {
            clipCounted = true;
            clipsCalibrated++;
          }
        }
      } else if (!hit && !grace) {
        // Kalibrlashdan keyin: faqat odam gapirmayotgan kadrlardan (aks-sado pasaysa ham kuzatamiz).
        coupling += VAD.COUPLING_RATE * (db - out - coupling);
      }
      coupling = clamp(coupling, VAD.COUPLING_MIN_DB, VAD.COUPLING_MAX_DB);
    }
    bargeRing.push({ t: frame.tMs, hit, db });
    if (bargeRing.length > 12) bargeRing.shift();
    // Gapirayotganda 300 ms yetadi; o'ylayotganda 600 ms - 12 s kutishni yo'talga almashtirmaylik.
    const [need, win] = ctx.mode === 'speaking' ? [5, 6] : [10, 12];
    const hits = bargeRing.slice(-win).filter((h) => h.hit);
    if (hits.length >= need) {
      begin(hits[0].t, frame.tMs, hits);
      bargeRing = [];
      onsetRing = [];
      bargeHold = true;
      return { type: 'barge_in', atMs: onsetAt };
    }
    return null;
  }

  return {
    push(frame, ctx) {
      const learnable = frame.db > SILENT_DB;
      const db = learnable ? frame.db : -160;
      if (ctx.mode !== lastMode) {
        // Rejim almashdi: yarim yig'ilgan nomzodlar eskirdi. Bo'lib gapirishdan keyingi gap
        // (bargeHold) esa tinglash rejimida davom etadi - u allaqachon boshlangan.
        onsetRing = [];
        bargeRing = [];
        if (ctx.mode !== 'listen' && inSpeech && !bargeHold) resetSpeech();
        lastMode = ctx.mode;
      }
      if (ctx.mode === 'off') {
        if (inSpeech) resetSpeech();
        bargeHold = false;
        return null;
      }
      if (ctx.mode === 'listen') {
        bargeHold = false;
        lastClipAge = -1;
        return listen(frame.tMs, db, learnable, ctx.guard);
      }
      if (bargeHold) return null;
      return barge(frame, db, learnable, ctx);
    },
    reset() {
      resetSpeech();
      bargeHold = false;
    },
    noteDiscardAfterBarge() {
      discards++;
      if (discards >= 2) {
        // Ikki marta o'z ovozini "eshitdi" - bu qurilma/xonada aks-sado o'tyapti.
        extra = Math.min(VAD.BARGE_EXTRA_MAX_DB, extra + VAD.BARGE_EXTRA_STEP_DB);
        discards = 0;
      }
    },
    noteUserLevel(db) {
      if (!Number.isFinite(db) || db <= SILENT_DB) return;
      // Sekin o'rganamiz: bitta baland gap darvozani keskin ko'tarmasin.
      userLevel = userLevel === null ? db : userLevel + 0.3 * (db - userLevel);
    },
    get floorDb() {
      return floor;
    },
    get startDb() {
      return startDb();
    },
    get inSpeech() {
      return inSpeech;
    },
    get bargeBuilding() {
      return bargeRing.slice(-6).filter((h) => h.hit).length >= VAD.BUILDING_HITS;
    },
    get bargeExtraDb() {
      return extra;
    },
    get couplingDb() {
      return coupling;
    },
    get userLevelDb() {
      return userLevel;
    },
  };
}
