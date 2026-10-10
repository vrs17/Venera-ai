/**
 * Chunk chegaralari (spec 7.5 qadam 2): `receivedBytes` dan boshlab
 * `maxChunkBytes` (4 MiB) gacha. Server 1..maxChunkBytes bayt qabul qiladi.
 */
export const DEFAULT_CHUNK_BYTES = 4 * 1024 * 1024;

export interface ChunkRange {
  offset: number;
  length: number;
}

export function nextChunk(receivedBytes: number, totalBytes: number, maxChunkBytes = DEFAULT_CHUNK_BYTES): ChunkRange | null {
  const max = Math.max(1, Math.floor(maxChunkBytes));
  if (receivedBytes < 0 || receivedBytes >= totalBytes) return null;
  return { offset: receivedBytes, length: Math.min(max, totalBytes - receivedBytes) };
}

/** Butun fayl rejasi (progress ko'rsatish va testlar uchun). */
export function chunkPlan(totalBytes: number, maxChunkBytes = DEFAULT_CHUNK_BYTES, from = 0): ChunkRange[] {
  const out: ChunkRange[] = [];
  let pos = from;
  for (let c = nextChunk(pos, totalBytes, maxChunkBytes); c; c = nextChunk(pos, totalBytes, maxChunkBytes)) {
    out.push(c);
    pos = c.offset + c.length;
  }
  return out;
}
