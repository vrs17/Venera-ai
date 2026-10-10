import { backoffMs, CAP_MS } from '@/features/upload/backoff';
import { chunkPlan, DEFAULT_CHUNK_BYTES, nextChunk } from '@/features/upload/chunker';

describe('chunker', () => {
  it('cuts 4 MiB chunks from receivedBytes', () => {
    const size = 10 * 1024 * 1024 + 5;
    expect(chunkPlan(size)).toEqual([
      { offset: 0, length: DEFAULT_CHUNK_BYTES },
      { offset: DEFAULT_CHUNK_BYTES, length: DEFAULT_CHUNK_BYTES },
      { offset: 2 * DEFAULT_CHUNK_BYTES, length: 2 * 1024 * 1024 + 5 },
    ]);
    expect(chunkPlan(size, DEFAULT_CHUNK_BYTES, 8 * 1024 * 1024)).toEqual([{ offset: 8 * 1024 * 1024, length: 2 * 1024 * 1024 + 5 }]);
  });

  it('returns null when everything is uploaded or the offset is invalid', () => {
    expect(nextChunk(100, 100)).toBeNull();
    expect(nextChunk(101, 100)).toBeNull();
    expect(nextChunk(-1, 100)).toBeNull();
    expect(nextChunk(0, 1, 0)).toEqual({ offset: 0, length: 1 });
  });
});

describe('backoff', () => {
  it('doubles from 5 s with +-20% jitter and caps at 15 min', () => {
    expect(backoffMs(1, () => 0.5)).toBe(5000);
    expect(backoffMs(2, () => 0.5)).toBe(10000);
    expect(backoffMs(1, () => 0)).toBe(4000);
    expect(backoffMs(1, () => 1)).toBe(6000);
    expect(backoffMs(30, () => 1)).toBe(CAP_MS);
    for (let i = 1; i < 12; i++) {
      const v = backoffMs(i);
      expect(v).toBeGreaterThan(0);
      expect(v).toBeLessThanOrEqual(CAP_MS);
    }
  });
});
