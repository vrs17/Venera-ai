/**
 * WAV (PCM 16-bit mono) o'qish va ovoz balandligi egri chizig'i (envelope).
 *
 * NIMA UCHUN: expo-audio pleeridan namunalarni olish (`setAudioSamplingEnabled`)
 * Visualizer va RECORD_AUDIO talab qiladi. Klip baytlari baribir qo'limizda - egri
 * chiziqni o'zimiz hisoblaymiz. U ikki joyda kerak: tuman (Barno ovozi bilan ko'tariladi)
 * va bo'lib gapirish (mikrofondagi aks-sado darajasini taxmin qilish).
 */

export interface Pcm {
  samples: Int16Array;
  sampleRate: number;
  durationMs: number;
}

export interface Envelope {
  hopMs: number;
  durationMs: number;
  /** Har bo'lakning RMS darajasi, dBFS. */
  db: Float32Array;
  /**
   * Har bo'lakning CHO'QQI darajasi, dBFS. NIMA UCHUN alohida: mikrofon o'lchovi
   * (expo-audio metering) - oxirgi o'lchovdan beri eng baland NAMUNA (cho'qqi). Aks-sado
   * chegarasi chiqishni RMS bilan, mikrofonni cho'qqi bilan solishtirsa nutqda 6-12 dB
   * farq chiqadi va Barno o'zini o'zi "bo'lib" qo'yadi. Solishtirish bir xil o'lchovda.
   */
  peakDb: Float32Array;
  /** 0..1, tekislangan (tuman uchun). */
  level: Float32Array;
}

function ascii(bytes: Uint8Array, at: number, len: number): string {
  let s = '';
  for (let i = 0; i < len && at + i < bytes.length; i++) s += String.fromCharCode(bytes[at + i]);
  return s;
}

/** RIFF bo'laklari bo'ylab yuradi (44 baytli sarlavhaga tayanmaydi). Boshqa format - xato. */
export function parseWav(bytes: Uint8Array): Pcm {
  if (bytes.length < 12 || ascii(bytes, 0, 4) !== 'RIFF' || ascii(bytes, 8, 4) !== 'WAVE') throw new Error('not a wav');
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let off = 12;
  let rate = 0;
  let fmtOk = false;
  let dataAt = -1;
  let dataLen = 0;
  while (off + 8 <= bytes.length) {
    const id = ascii(bytes, off, 4);
    const size = view.getUint32(off + 4, true);
    const body = off + 8;
    if (id === 'fmt ') {
      if (size < 16 || body + 16 > bytes.length) throw new Error('bad fmt');
      const format = view.getUint16(body, true);
      const channels = view.getUint16(body + 2, true);
      rate = view.getUint32(body + 4, true);
      const bits = view.getUint16(body + 14, true);
      if (format !== 1 || channels !== 1 || bits !== 16 || rate <= 0) throw new Error('unsupported wav');
      fmtOk = true;
    } else if (id === 'data') {
      dataAt = body;
      // Oqimli WAV sarlavhasida o'lcham 0xFFFFFFFF bo'lishi mumkin - borini olamiz.
      dataLen = Math.min(size, bytes.length - body);
      break;
    }
    off = body + size + (size & 1);
  }
  if (!fmtOk || dataAt < 0) throw new Error('bad wav');
  const count = Math.floor(dataLen / 2);
  const samples = new Int16Array(count);
  // Nusxa (ko'rinish emas): bayt manzili toq bo'lsa Int16Array ko'rinishi yiqiladi.
  for (let i = 0; i < count; i++) samples[i] = view.getInt16(dataAt + i * 2, true);
  return { samples, sampleRate: rate, durationMs: (count / rate) * 1000 };
}

const MIN_DB = -100;

export function envelopeOf(pcm: Pcm, hopMs = 20): Envelope {
  const hop = Math.max(1, Math.round((pcm.sampleRate * hopMs) / 1000));
  const n = Math.ceil(pcm.samples.length / hop);
  const db = new Float32Array(n);
  const peakDb = new Float32Array(n);
  const level = new Float32Array(n);
  let smooth = 0;
  for (let h = 0; h < n; h++) {
    const from = h * hop;
    const to = Math.min(pcm.samples.length, from + hop);
    let sum = 0;
    let peak = 0;
    for (let i = from; i < to; i++) {
      const v = pcm.samples[i] / 32768;
      sum += v * v;
      const a = v < 0 ? -v : v;
      if (a > peak) peak = a;
    }
    const rms = Math.sqrt(sum / Math.max(1, to - from));
    const d = Math.max(MIN_DB, 20 * Math.log10(Math.max(rms, 1e-5)));
    db[h] = d;
    peakDb[h] = Math.max(MIN_DB, 20 * Math.log10(Math.max(peak, 1e-5)));
    const target = Math.min(1, Math.max(0, (d + 50) / 40));
    // Tez ko'tariladi, sekin tushadi - tuman "titramasin".
    smooth += (target - smooth) * (target > smooth ? 0.6 : 0.15);
    level[h] = smooth;
  }
  return { hopMs, durationMs: pcm.durationMs, db, peakDb, level };
}

export function envelopeAt(env: Envelope, ms: number): { level: number; db: number } {
  if (!env.db.length) return { level: 0, db: MIN_DB };
  const i = Math.min(env.db.length - 1, Math.max(0, Math.floor(ms / env.hopMs)));
  return { level: env.level[i], db: env.db[i] };
}

/**
 * `[fromMs, toMs]` dagi eng baland bo'lak (dBFS); oraliq klipdan tashqarida bo'lsa null.
 * `track`: 'rms' (tuman) yoki 'peak' (aks-sado chegarasi - mikrofon cho'qqisi bilan bir xil o'lchov).
 */
export function envelopeMaxDb(env: Envelope, fromMs: number, toMs: number, track: 'rms' | 'peak' = 'rms'): number | null {
  const arr = track === 'peak' ? env.peakDb : env.db;
  if (!arr.length || toMs < 0) return null;
  const a = Math.max(0, Math.floor(fromMs / env.hopMs));
  const b = Math.min(arr.length - 1, Math.floor(toMs / env.hopMs));
  if (a > b) return null;
  let max = MIN_DB;
  for (let i = a; i <= b; i++) if (arr[i] > max) max = arr[i];
  return max;
}
