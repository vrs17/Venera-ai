import {
  buildImportPath,
  buildRecordPath,
  decideEntry,
  ENTRY_SOURCES,
  entrySignature,
  keysEqual,
  parseEntryParams,
  parseImportParams,
  sanitizeIncomingPath,
} from '@/features/entry/deepLink';
import { hrefFromAction, RECORD_ACTION_ID, recordShortcutHref, withEntryNonce } from '@/features/entry/quickActions';
import { __resetInstallKeyCache, ensureInstallKey, getCachedInstallKey } from '@/features/entry/trustedKey';
import { createTokenStore, memoryKV } from '@/features/auth/tokenStore';
import { redirectSystemPath } from '@/app/+native-intent';

const KEY = 'ab'.repeat(32);
const OTHER = 'cd'.repeat(32);

describe('deep link parsing and sanitising', () => {
  it('keeps only src, k and action', () => {
    expect(sanitizeIncomingPath(`venera-rec://record?src=tile&k=${KEY}&evil=1&action=stop`)).toBe(`/record?src=tile&k=${KEY}&action=stop`);
    expect(sanitizeIncomingPath('venera-rec://record')).toBe('/record?src=link');
    expect(sanitizeIncomingPath('venera-rec://record/?src=launcher&k=short')).toBe('/record?src=launcher');
    expect(sanitizeIncomingPath(`/record?src=bogus&k=${KEY}&action=delete`)).toBe(`/record?src=link&k=${KEY}`);
    expect(sanitizeIncomingPath('record?src=shortcut')).toBe('/record?src=shortcut');
  });

  it('passes known app paths, drops foreign schemes and unknown paths', () => {
    expect(sanitizeIncomingPath('venera-rec://meeting/abc123')).toBe('/meeting/abc123');
    expect(sanitizeIncomingPath('/settings')).toBe('/settings');
    // Asosiy ekran - Mini App (`/`), native yig'ilishlar ro'yxati - `/meetings`.
    expect(sanitizeIncomingPath('venera-rec://meetings')).toBe('/meetings');
    expect(sanitizeIncomingPath('venera-rec://')).toBe('/');
    expect(sanitizeIncomingPath('https://evil.example/record?src=tile')).toBe('/');
    expect(sanitizeIncomingPath('venera-rec://admin')).toBe('/');
    expect(sanitizeIncomingPath('')).toBe('/');
    expect(redirectSystemPath({ path: `venera-rec://record?src=tile&k=${KEY}`, initial: true })).toBe(`/record?src=tile&k=${KEY}`);
  });

  it('parses router params (arrays, junk)', () => {
    expect(parseEntryParams({ src: ['tile', 'app'], k: KEY, action: 'stop' })).toEqual({ src: 'tile', k: KEY, action: 'stop', n: null });
    expect(parseEntryParams({ src: 'x', k: 'zz', action: 'go', n: '12a' })).toEqual({ src: 'link', k: null, action: null, n: null });
    expect(parseEntryParams({ src: 'tile', n: '98765' }).n).toBe('98765');
    expect(buildRecordPath({ src: 'app', k: null, action: null })).toBe('/record?src=app');
  });

  it('keeps the per-press nonce through sanitising and in the signature', () => {
    expect(sanitizeIncomingPath(`venera-rec://record?src=launcher&k=${KEY}&n=123456&x=1`)).toBe(`/record?src=launcher&k=${KEY}&n=123456`);
    expect(sanitizeIncomingPath('venera-rec://record?src=tile&n=../../x')).toBe('/record?src=tile');
    const a = parseEntryParams({ src: 'launcher', k: KEY, n: '1' });
    const b = parseEntryParams({ src: 'launcher', k: KEY, n: '2' });
    expect(entrySignature(a)).toBe(entrySignature({ ...a }));
    expect(entrySignature(a)).not.toBe(entrySignature(b));
  });
});

describe('entry decision', () => {
  const p = (k: string | null, action: 'stop' | null = null) => ({ src: 'tile' as const, k, action });

  it('auto-starts only with the trusted key', () => {
    expect(decideEntry(p(KEY), KEY, 'idle')).toBe('start');
    expect(decideEntry(p(OTHER), KEY, 'idle')).toBe('ready');
    expect(decideEntry(p(null), KEY, 'idle')).toBe('ready');
    expect(decideEntry(p(KEY), null, 'idle')).toBe('ready');
    expect(decideEntry(p(KEY), KEY, 'stopped')).toBe('start');
    expect(decideEntry(p(KEY), KEY, 'permission_denied')).toBe('start');
  });

  it('is idempotent while recording', () => {
    expect(decideEntry(p(KEY), KEY, 'recording')).toBe('show');
    expect(decideEntry(p(KEY), KEY, 'paused')).toBe('show');
    expect(decideEntry(p(KEY), KEY, 'preparing')).toBe('show');
  });

  it('action=stop stops only with the trusted key and an active recording', () => {
    expect(decideEntry(p(KEY, 'stop'), KEY, 'recording')).toBe('stop');
    expect(decideEntry(p(KEY, 'stop'), KEY, 'paused')).toBe('stop');
    expect(decideEntry(p(OTHER, 'stop'), KEY, 'recording')).toBe('show');
    // Plitka/yon tugma - almashtirgich: eskirgan "to'xtat" (hech narsa yozilmayapti) = yangi yozuv.
    expect(decideEntry(p(KEY, 'stop'), KEY, 'idle')).toBe('start');
    expect(decideEntry({ src: 'launcher', k: KEY, action: 'stop' }, KEY, 'idle')).toBe('start');
    // Ovoz tugmasi xizmati olib tashlandi (Play Protect): `src=volume` endi kirish nuqtasi emas - oddiy havola.
    expect(ENTRY_SOURCES).not.toContain('volume');
    expect(parseEntryParams({ src: 'volume', k: KEY })).toMatchObject({ src: 'link', k: KEY });
    expect(decideEntry({ src: 'link', k: KEY, action: 'stop' }, KEY, 'idle')).toBe('ready');
    // Bildirishnomadagi Stop esa hech qachon yangi yozuv boshlamaydi.
    expect(decideEntry({ src: 'notification', k: KEY, action: 'stop' }, KEY, 'idle')).toBe('ready');
    expect(decideEntry(p(OTHER, 'stop'), KEY, 'idle')).toBe('ready');
  });

  it('compares keys strictly and builds stable signatures', () => {
    expect(keysEqual(KEY, KEY)).toBe(true);
    expect(keysEqual(KEY, OTHER)).toBe(false);
    expect(keysEqual(KEY, KEY.slice(1))).toBe(false);
    expect(keysEqual(null, KEY)).toBe(false);
    expect(entrySignature(p(KEY), 1)).not.toBe(entrySignature(p(KEY, 'stop'), 1));
  });
});

describe('install key and app shortcut', () => {
  beforeEach(() => __resetInstallKeyCache());

  it('generates a 64-hex key once, stores it in SecureStore and hands it to native', async () => {
    const kv = memoryKV();
    const store = createTokenStore(kv);
    const native = jest.fn();
    let n = 0;
    const randomBytes = (len: number) => new Uint8Array(len).map(() => n++ & 0xff);
    const k1 = await ensureInstallKey({ store, randomBytes, setNativeKey: native });
    expect(k1).toMatch(/^[0-9a-f]{64}$/);
    expect(kv.data.get('venera.installKey')).toBe(k1);
    const k2 = await ensureInstallKey({ store, randomBytes, setNativeKey: native });
    expect(k2).toBe(k1);
    expect(native).toHaveBeenCalledTimes(2);
    expect(getCachedInstallKey()).toBe(k1);
  });

  it('the shortcut carries the trusted key and only our action is routed', () => {
    const href = recordShortcutHref(KEY);
    expect(href).toBe(`/record?src=shortcut&k=${KEY}`);
    expect(hrefFromAction({ id: RECORD_ACTION_ID, title: 'x', params: { href } })).toBe(href);
    expect(hrefFromAction({ id: 'other', title: 'x', params: { href } })).toBeNull();
    expect(hrefFromAction({ id: RECORD_ACTION_ID, title: 'x', params: { href: '/settings' } })).toBeNull();
    expect(hrefFromAction(undefined)).toBeNull();
    // Har bosish yangi nonce oladi va u sanitizatsiyadan o'tadi.
    const pressed = withEntryNonce(href, 1760000000123);
    expect(pressed).toBe(`/record?src=shortcut&k=${KEY}&n=1760000000123`);
    expect(sanitizeIncomingPath(pressed)).toBe(pressed);
  });
});

describe('import deep link ("Ulashish -> Barno")', () => {
  const A = 'share_1728560000000_0_Call_recording_Alisher_241010_143012.m4a';
  const B = 'share_1728560000000_1_voice.aac';

  it('keeps only validated file names, skipped and nonce (the install key is dropped)', () => {
    // `k` (o'rnatish kaliti) import havolasida kerak emas - tashlanadi.
    expect(sanitizeIncomingPath(`venera-rec://import?files=${A},${B}&skipped=2&n=17285&k=${KEY}&evil=1`)).toBe(
      `/import?files=${A},${B}&skipped=2&n=17285`,
    );
    // URL-kodlangan vergul ham (boshqa ilova `%2C` bilan yuborsa) bir xil natija.
    expect(sanitizeIncomingPath(`venera-rec://import?files=${A}%2C${B}&n=1`)).toBe(`/import?files=${A},${B}&n=1`);
    expect(redirectSystemPath({ path: `venera-rec://import?files=${B}&n=5`, initial: true })).toBe(`/import?files=${B}&n=5`);
  });

  it('drops path traversal, foreign extensions, junk params; nothing left -> recordings list', () => {
    expect(sanitizeIncomingPath(`venera-rec://import?files=../../databases/venera-queue.db,${B}`)).toBe(`/import?files=${B}`);
    expect(sanitizeIncomingPath('venera-rec://import?files=a.flac,b.json,..%2Fx.m4a,c.mp3.part')).toBe('/meetings');
    expect(sanitizeIncomingPath('venera-rec://import')).toBe('/meetings');
    expect(sanitizeIncomingPath(`venera-rec://import?files=${B}&skipped=9999&n=x1&k=short`)).toBe(`/import?files=${B}`);
    expect(sanitizeIncomingPath(`https://evil.example/import?files=${B}`)).toBe('/');
  });

  it('"Audio yuklash" names (.mp3, .wav, .ogg) pass the same strict check as native m4a/aac names', () => {
    const files = ['share_1731130000000_0_Kengash.mp3', 'share_1731130000000_1_diktofon.wav', 'share_1731130000000_2_voice.ogg'];
    expect(parseImportParams({ files: files.join(','), n: '3' })).toEqual({ files, skipped: 0, n: '3' });
    expect(sanitizeIncomingPath(`venera-rec://import?files=${files[0]},../${files[1]},x.MP3&n=4`)).toBe(`/import?files=${files[0]},x.MP3&n=4`);
    expect(parseImportParams({ files: 'a b.mp3,.mp3,ж.ogg,x.wav.json' }).files).toEqual([]);
  });

  it('caps the number of files and removes duplicates', () => {
    const many = Array.from({ length: 30 }, (_, i) => `f${i}.m4a`);
    const out = parseImportParams({ files: [...many, 'f0.m4a'].join(',') });
    expect(out.files).toHaveLength(20);
    expect(new Set(out.files).size).toBe(20);
    expect(buildImportPath({ files: [], skipped: 3, n: '1' })).toBe('/meetings');
    expect(parseImportParams({ files: [A, B], skipped: ['4'], n: '77', k: 'a'.repeat(64) })).toEqual({ files: [A, B], skipped: 4, n: '77' });
  });

  it('call/share are not recording entry sources', () => {
    expect(ENTRY_SOURCES).not.toContain('call');
    expect(ENTRY_SOURCES).not.toContain('share');
    expect(parseEntryParams({ src: 'call' }).src).toBe('link');
    expect(sanitizeIncomingPath('venera-rec://record?src=share')).toBe('/record?src=link');
  });
});
