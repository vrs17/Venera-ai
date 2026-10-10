/**
 * AAC ADTS faylini kadrlar bo'yicha kesish - mikrofon segmentidan bitta gapni ajratish.
 *
 * NIMA UCHUN: mikrofon tinglash, o'ylash va gapirish davomida UZLUKSIZ yozadi (birinchi
 * bo'g'in kesilmasin, Barno gapirayotganda ham bo'lib bo'lsin). Serverga faqat gapning
 * o'zi (+300 ms oldidan) ketadi: Barno ovozining aks-sadosi va jimlik STT'ga tushmaydi.
 * ADTS'da har kadrning o'z sarlavhasi bor - JS'da dekodersiz kesish mumkin.
 */
const SAMPLE_RATES = [96000, 88200, 64000, 48000, 44100, 32000, 24000, 22050, 16000, 12000, 11025, 8000, 7350];

export interface AdtsFrame {
  offset: number;
  length: number;
  startMs: number;
  durMs: number;
}

/** Kadrlar ro'yxati; birinchi buzuq sarlavhada to'xtaydi (yozuv uzilib qolgan dum). */
export function parseAdts(bytes: Uint8Array): AdtsFrame[] {
  const frames: AdtsFrame[] = [];
  let off = 0;
  let t = 0;
  while (off + 7 <= bytes.length) {
    const b0 = bytes[off];
    const b1 = bytes[off + 1];
    if (b0 !== 0xff || (b1 & 0xf0) !== 0xf0 || (b1 & 0x06) !== 0) break;
    const sf = (bytes[off + 2] >> 2) & 0x0f;
    const rate = SAMPLE_RATES[sf];
    if (!rate) break;
    const len = ((bytes[off + 3] & 0x03) << 11) | (bytes[off + 4] << 3) | ((bytes[off + 5] & 0xe0) >> 5);
    if (len < 7 || off + len > bytes.length) break;
    const blocks = (bytes[off + 6] & 0x03) + 1;
    const dur = (1024 * blocks * 1000) / rate;
    frames.push({ offset: off, length: len, startMs: t, durMs: dur });
    t += dur;
    off += len;
  }
  return frames;
}

/** Davomiylik (ms) - kadrlar yig'indisi. */
export function adtsDurationMs(bytes: Uint8Array): number {
  const frames = parseAdts(bytes);
  const last = frames[frames.length - 1];
  return last ? last.startMs + last.durMs : 0;
}

/**
 * `[fromMs, toMs)` oralig'iga tegadigan kadrlar ketma-ket qo'shiladi. Hech narsa
 * qolmasa null. Birinchi kadr ~64 ms MDCT shovqini berishi mumkin - STT'ga farqi yo'q.
 */
export function trimAdts(bytes: Uint8Array, fromMs: number, toMs?: number): Uint8Array | null {
  const end = toMs ?? Number.POSITIVE_INFINITY;
  const keep = parseAdts(bytes).filter((f) => f.startMs < end && f.startMs + f.durMs > fromMs);
  if (!keep.length) return null;
  const first = keep[0];
  const last = keep[keep.length - 1];
  // Kadrlar faylda ketma-ket - bitta bo'lak nusxa yetadi.
  return bytes.slice(first.offset, last.offset + last.length);
}
